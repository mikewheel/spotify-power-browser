"""Engine envelope user_id (plan 06 T5), driven against the mock: the bearer
follows the envelope, 401-refresh is per user, pagination re-queues conserve
the user, and absent/unknown user ids fall back to the legacy identity."""
import json
from unittest.mock import MagicMock

import pytest
import requests

import application.api_call_engine as engine
from application.spotify_authentication import token_store


@pytest.fixture
def env(mock_base, monkeypatch, tmp_path):
    """Real token files in a tmp store: primary 'mockuser' (mirrored to the
    legacy file the engine's None-identity reads) + 'mockuser2'."""
    monkeypatch.setattr(token_store, "USERS_DIR", tmp_path / "users")
    monkeypatch.setattr(token_store, "PRIMARY_USER_FILE", tmp_path / "users" / ".primary_user")
    monkeypatch.setattr(token_store, "LEGACY_API_TOKEN_FILE", tmp_path / "spotify_api_token.secret")
    monkeypatch.setattr(token_store, "LEGACY_REFRESH_TOKEN_FILE",
                        tmp_path / "spotify_refresh_token.secret")
    monkeypatch.setattr(engine, "SPOTIFY_API_TOKEN_FILE", tmp_path / "spotify_api_token.secret")

    token_store.save_tokens("mockuser", "mock-access-token", "mock-refresh-token",
                            claim_primary=True)  # first login -> primary + legacy mirror
    token_store.save_tokens("mockuser2", "mock-access-token-mockuser2",
                            "mock-refresh-token-mockuser2")

    published, requested = [], []
    monkeypatch.setattr(engine, "TOKEN_CACHE", {})
    monkeypatch.setattr(engine, "connect_to_rabbitmq_exchange",
                        lambda **kw: (MagicMock(), MagicMock()))
    monkeypatch.setattr(engine, "publish_message_to_exchange",
                        lambda **kw: published.append(json.loads(kw["body"])))
    monkeypatch.setattr(engine, "sleep", lambda *_: None)
    monkeypatch.setattr(
        engine.SpotifyRequestFactory, "request_url",
        staticmethod(lambda url, depth_of_search=0, user_id=None:
                     requested.append((url, depth_of_search, user_id))),
    )

    class Env:
        pass
    e = Env()
    e.published, e.requested = published, requested
    return e


def _call(url, depth=0, **envelope_extra):
    body = {"request_url": url, "depth_of_search": depth, **envelope_extra}
    engine.make_spotify_api_call(None, None, None, json.dumps(body))


def test_envelope_user_selects_that_users_bearer(env, mock_base):
    _call(f"{mock_base}/v1/me", user_id="mockuser2")
    # /v1/me answers per bearer -> proof the right token went out.
    assert env.published[0]["response"]["id"] == "mockuser2"
    # ...and the published response envelope carries the user forward.
    assert all(msg["user_id"] == "mockuser2" for msg in env.published)


def test_message_without_user_id_falls_back_to_legacy_token(env, mock_base):
    # Back-compat: an in-flight pre-multiplayer message has NO user_id key.
    _call(f"{mock_base}/v1/me")
    assert env.published[0]["response"]["id"] == "mockuser"  # legacy = primary's mirror
    assert all(msg["user_id"] is None for msg in env.published)


def test_unknown_user_id_falls_back_to_legacy_token(env, mock_base):
    # A user whose token dir vanished (deleted mid-crawl) must not wedge the
    # worker: the engine acts as the legacy identity instead of crashing.
    _call(f"{mock_base}/v1/me", user_id="ghost-user")
    assert env.published[0]["response"]["id"] == "mockuser"
    # OWNERSHIP FOLLOWS THE BEARER THAT FETCHED: the ghost id must NOT ride
    # the response envelope, or handlers would record a nonexistent user as
    # owning data the legacy identity fetched.
    assert all(msg["user_id"] is None for msg in env.published)


def test_unknown_user_pagination_requeues_as_the_resolved_identity(env, mock_base):
    _call(f"{mock_base}/v1/me/tracks?offset=0&limit=7", depth=1, user_id="ghost-user")
    # legacy identity fetched (primary's full 60-track set -> a next page)...
    assert env.requested, "expected a pagination re-queue"
    next_url, _, user_id = env.requested[0]
    assert "offset=7" in next_url
    assert user_id is None  # ...and the continuation belongs to it too


def test_factory_rejects_a_user_with_no_tokens(env, monkeypatch):
    from application.requests_factory import resolve_seed_users
    with pytest.raises(SystemExit):
        resolve_seed_users(user="nobody-here")
    assert resolve_seed_users(user="mockuser2") == ["mockuser2"]
    assert resolve_seed_users() == ["mockuser"]  # the recorded primary


def test_pagination_requeue_conserves_the_envelope_user(env, mock_base):
    _call(f"{mock_base}/v1/me/tracks?offset=0&limit=7", depth=1, user_id="mockuser2")
    # user 2 has 22 liked tracks -> limit=7 leaves a next page to re-queue.
    assert len(env.requested) == 1
    next_url, depth, user_id = env.requested[0]
    assert "offset=7" in next_url
    assert depth == 1                 # pagination continues, not a hop
    assert user_id == "mockuser2"     # CRITICAL: page 2 is per-bearer


def test_401_refreshes_the_envelopes_user(env, mock_base, monkeypatch):
    refreshed = []
    monkeypatch.setattr(engine, "refresh_spotify_auth",
                        lambda user_id=None: refreshed.append(user_id))
    requests.post(f"{mock_base}/_control/config", json={"fail_next_n": 1, "fail_status": 401})
    _call(f"{mock_base}/v1/me", user_id="mockuser2")
    assert refreshed == ["mockuser2"]
    # the reloaded token really is user 2's (from their namespaced file)
    assert engine.TOKEN_CACHE["mockuser2"] == "mock-access-token-mockuser2"
    assert env.published[0]["response"]["id"] == "mockuser2"


def test_two_users_crawled_sequentially_get_distinct_pages(env, mock_base):
    _call(f"{mock_base}/v1/me/tracks?offset=0&limit=50", depth=0, user_id="mockuser")
    _call(f"{mock_base}/v1/me/tracks?offset=0&limit=50", depth=0, user_id="mockuser2")

    pages = [msg for msg in env.published if msg["request_url"].startswith(f"{mock_base}/v1/me/tracks")]
    by_user = {}
    for msg in pages:
        by_user.setdefault(msg["user_id"], set()).update(
            item["track"]["id"] for item in msg["response"]["items"]
        )
    assert by_user["mockuser"] != by_user["mockuser2"]
    assert by_user["mockuser"] & by_user["mockuser2"]  # ...but they overlap
