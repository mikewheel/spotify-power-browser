"""Resilience tests: drive api_call_engine.make_spotify_api_call against the mock
with failure injection, so the 429-cap, 401-refresh, and the high-severity
dedup-rollback-on-500 paths are exercised end-to-end (previously untestable).

RabbitMQ publishing, real sleeps, and the token read are isolated so the retry
loops run instantly without external services beyond the mock (+ Redis).
"""
import json
from unittest.mock import MagicMock

import pytest
import requests

import application.api_call_engine as engine


@pytest.fixture
def engine_env(mock_base, monkeypatch):
    published = []
    monkeypatch.setattr(engine, "SPOTIFY_API_TOKEN", "mock-token")
    monkeypatch.setattr(engine, "connect_to_rabbitmq_exchange", lambda **kw: (MagicMock(), MagicMock()))
    monkeypatch.setattr(engine, "publish_message_to_exchange", lambda **kw: published.append(kw))
    monkeypatch.setattr(engine, "sleep", lambda *_: None)
    monkeypatch.setattr(engine.SpotifyRequestFactory, "request_url",
                        staticmethod(lambda url, depth_of_search=0: None))
    return published


def _call(url, depth=0):
    engine.make_spotify_api_call(None, None, None, json.dumps({"request_url": url, "depth_of_search": depth}))


def test_429_is_retried_with_capped_backoff_then_succeeds(engine_env, mock_base):
    requests.post(f"{mock_base}/_control/config",
                  json={"fail_next_n": 1, "fail_status": 429, "retry_after": 0})
    _call(f"{mock_base}/v1/tracks/trk000000")     # 429 once -> retry -> 200
    assert len(engine_env) >= 1                    # the successful response was published


def test_401_triggers_refresh_then_retries(engine_env, mock_base, monkeypatch):
    refreshed = []
    monkeypatch.setattr(engine, "refresh_spotify_auth", lambda: refreshed.append(True))
    monkeypatch.setattr(engine, "load_api_token", lambda: "refreshed-token")
    requests.post(f"{mock_base}/_control/config", json={"fail_next_n": 1, "fail_status": 401})
    _call(f"{mock_base}/v1/tracks/trk000000")     # 401 once -> refresh + reload -> 200
    assert refreshed == [True]
    assert engine.SPOTIFY_API_TOKEN == "refreshed-token"
    assert len(engine_env) >= 1


def test_500_exhaustion_gives_up_and_rolls_back_dedup(engine_env, mock_base, redis_client):
    # The high-severity review #1 fix, end-to-end: a URL that 500s out of retries
    # must be un-marked so it's re-requestable, not silently dropped.
    from application.cache.redis_client import url_is_new, reset_crawled_set
    reset_crawled_set()
    url = f"{mock_base}/v1/tracks/trk000005"
    requests.post(f"{mock_base}/_control/config",
                  json={"fail_url_substring": "trk000005", "fail_status": 500})

    assert url_is_new(url, 0) is True              # mark it crawled (as request_url would)
    with pytest.raises(requests.exceptions.HTTPError):
        _call(url)                                  # 5x 500 -> give up + unmark + raise
    assert url_is_new(url, 0) is True              # True again => it was rolled back


def test_persistent_429_gives_up_instead_of_looping_forever(engine_env, mock_base, redis_client):
    # A persistent ban must not loop forever: bounded retries -> give up, and
    # (like 500 exhaustion) the URL is rolled back so it stays re-requestable.
    from application.cache.redis_client import url_is_new, reset_crawled_set
    reset_crawled_set()
    url = f"{mock_base}/v1/tracks/trk000006"
    requests.post(f"{mock_base}/_control/config",
                  json={"fail_url_substring": "trk000006", "fail_status": 429, "retry_after": 0})

    assert url_is_new(url, 0) is True
    with pytest.raises(requests.exceptions.HTTPError):
        _call(url)                                  # always 429 -> bounded retries -> give up
    assert url_is_new(url, 0) is True              # rolled back
