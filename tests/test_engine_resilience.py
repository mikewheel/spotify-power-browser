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
    # Seed the (legacy, user_id=None) slot of the per-user token cache.
    monkeypatch.setitem(engine.TOKEN_CACHE, None, "mock-token")
    monkeypatch.setattr(engine, "connect_to_rabbitmq_exchange", lambda **kw: (MagicMock(), MagicMock()))
    monkeypatch.setattr(engine, "publish_message_to_exchange", lambda **kw: published.append(kw))
    monkeypatch.setattr(engine, "sleep", lambda *_: None)
    monkeypatch.setattr(engine.SpotifyRequestFactory, "request_url",
                        staticmethod(lambda url, depth_of_search=0, user_id=None: None))
    return published


def _call(url, depth=0):
    # Deliberately NO user_id key: pins the pre-multiplayer envelope shape
    # (plan 06 back-compat with in-flight messages).
    #
    # Drive _consume_request directly: make_spotify_api_call is now a thin pika
    # wrapper that SWALLOWS give-up exceptions to keep the channel alive, so the
    # give-up-and-roll-back behavior under test lives in _consume_request. The
    # wrapper's swallowing is covered by tests/test_engine_consumer_resilience.py.
    engine._consume_request(json.dumps({"request_url": url, "depth_of_search": depth}))


def test_429_is_retried_with_capped_backoff_then_succeeds(engine_env, mock_base):
    requests.post(f"{mock_base}/_control/config",
                  json={"fail_next_n": 1, "fail_status": 429, "retry_after": 0})
    _call(f"{mock_base}/v1/tracks/trk000000")     # 429 once -> retry -> 200
    assert len(engine_env) >= 1                    # the successful response was published


def test_401_triggers_refresh_then_retries(engine_env, mock_base, monkeypatch):
    refreshed = []
    monkeypatch.setattr(engine, "refresh_spotify_auth",
                        lambda user_id=None: refreshed.append(user_id))
    monkeypatch.setattr(engine, "load_api_token", lambda user_id=None: "refreshed-token")
    requests.post(f"{mock_base}/_control/config", json={"fail_next_n": 1, "fail_status": 401})
    _call(f"{mock_base}/v1/tracks/trk000000")     # 401 once -> refresh + reload -> 200
    assert refreshed == [None]                    # legacy identity refreshed
    assert engine.TOKEN_CACHE[None] == "refreshed-token"
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


def test_401_refresh_failure_rolls_back_dedup_before_raising(engine_env, mock_base,
                                                             redis_client, monkeypatch):
    # A 401 whose refresh FAILS (revoked grant -> Spotify 400 invalid_grant,
    # or a deleted token file) is a give-up for this message: with auto_ack
    # there's no redelivery, so — exactly like the 429/500 give-up paths —
    # the dedup mark must be rolled back before the exception propagates, or
    # the URL (and its whole pagination chain) is unreachable forever even
    # after the user re-authorizes.
    from application.cache.redis_client import url_is_new, reset_crawled_set
    reset_crawled_set()

    def broken_refresh(user_id=None):
        raise requests.exceptions.HTTPError("400 invalid_grant (refresh token revoked)")
    monkeypatch.setattr(engine, "refresh_spotify_auth", broken_refresh)

    url = f"{mock_base}/v1/tracks/trk000007"
    requests.post(f"{mock_base}/_control/config",
                  json={"fail_url_substring": "trk000007", "fail_status": 401})

    assert url_is_new(url, 0) is True              # mark it crawled (as request_url would)
    with pytest.raises(requests.exceptions.HTTPError):
        _call(url)                                  # 401 -> refresh raises -> give up
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
