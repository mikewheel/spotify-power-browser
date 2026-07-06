"""Namespaced per-user token store (plan 06 T3) — pure filesystem unit tests
(tmp_path), plus per-user refresh against the mock token endpoint.

The load-bearing invariant under test: the PRIMARY user's tokens are mirrored
to the legacy secrets/spotify_*.secret files, because the docker compose
auth-gate healthcheck (`test -s /src/secrets/spotify_api_token.secret`) and
every user_id=None code path read them.
"""
import pytest

import application.spotify_authentication.refresh_token as rt
from application.spotify_authentication import token_store
from application.spotify_authentication.token_store import InvalidUserIdError


@pytest.fixture
def store(monkeypatch, tmp_path):
    """Point every token-store path at a tmp secrets dir."""
    monkeypatch.setattr(token_store, "USERS_DIR", tmp_path / "users")
    monkeypatch.setattr(token_store, "PRIMARY_USER_FILE", tmp_path / "users" / ".primary_user")
    monkeypatch.setattr(token_store, "LEGACY_API_TOKEN_FILE", tmp_path / "spotify_api_token.secret")
    monkeypatch.setattr(token_store, "LEGACY_REFRESH_TOKEN_FILE",
                        tmp_path / "spotify_refresh_token.secret")
    return tmp_path


def test_two_token_dirs_coexist(store):
    token_store.save_tokens("alice", "token-a", "refresh-a")
    token_store.save_tokens("bob", "token-b", "refresh-b")

    assert (store / "users" / "alice" / "spotify_api_token.secret").read_text() == "token-a"
    assert (store / "users" / "bob" / "spotify_api_token.secret").read_text() == "token-b"
    assert token_store.list_user_ids() == ["alice", "bob"]
    assert token_store.read_api_token("bob") == "token-b"
    assert token_store.read_refresh_token("alice") == "refresh-a"


def test_first_user_becomes_primary_and_mirrors_to_legacy_files(store):
    token_store.save_tokens("alice", "token-a", "refresh-a")

    assert token_store.get_primary_user_id() == "alice"
    # the compose auth-gate healthcheck's file:
    assert (store / "spotify_api_token.secret").read_text() == "token-a"
    assert (store / "spotify_refresh_token.secret").read_text() == "refresh-a"


def test_second_user_does_not_steal_primary_or_clobber_legacy_files(store):
    token_store.save_tokens("alice", "token-a", "refresh-a")
    token_store.save_tokens("bob", "token-b", "refresh-b")

    assert token_store.get_primary_user_id() == "alice"
    assert (store / "spotify_api_token.secret").read_text() == "token-a"  # untouched
    assert (store / "spotify_refresh_token.secret").read_text() == "refresh-a"


def test_primary_refresh_keeps_legacy_files_in_sync(store):
    token_store.save_tokens("alice", "token-a-1", "refresh-a-1")
    token_store.save_tokens("alice", "token-a-2", "refresh-a-2")

    assert token_store.read_api_token("alice") == "token-a-2"
    assert (store / "spotify_api_token.secret").read_text() == "token-a-2"


def test_save_without_refresh_token_keeps_existing_refresh(store):
    token_store.save_tokens("alice", "token-1", "refresh-1")
    token_store.save_tokens("alice", "token-2")  # e.g. refresh grant omitted it

    assert token_store.read_api_token("alice") == "token-2"
    assert token_store.read_refresh_token("alice") == "refresh-1"


def test_user_id_none_targets_legacy_files_only(store):
    token_store.save_tokens(None, "legacy-token", "legacy-refresh")

    assert (store / "spotify_api_token.secret").read_text() == "legacy-token"
    assert token_store.list_user_ids() == []
    assert token_store.get_primary_user_id() is None
    assert token_store.read_api_token() == "legacy-token"


def test_unsafe_user_ids_are_rejected(store):
    # (user_id=None is NOT in this list: it legitimately targets the legacy files)
    for bad in ("../evil", "a/b", "", ".hidden", "a\x00b", 42):
        with pytest.raises(InvalidUserIdError):
            token_store.save_tokens(bad, "t")
    assert not token_store.has_user("../evil")


def test_has_user_and_listing_ignore_non_user_entries(store):
    token_store.save_tokens("alice", "token-a", "refresh-a")
    (store / "users" / "empty_dir").mkdir()  # no token file inside

    assert token_store.has_user("alice") is True
    assert token_store.has_user("empty_dir") is False
    assert token_store.has_user("nobody") is False
    assert token_store.list_user_ids() == ["alice"]  # .primary_user + empty_dir excluded


###
# Per-user refresh against the mock accounts facade (skips w/o the mock).
###

def _wire(monkeypatch, tmp_path, mock_base):
    (tmp_path / "spotify_client_id.secret").write_text("mock-client-id")
    (tmp_path / "spotify_client_secret.secret").write_text("mock-client-secret")
    monkeypatch.setattr(rt, "SPOTIFY_CLIENT_ID_FILE", tmp_path / "spotify_client_id.secret")
    monkeypatch.setattr(rt, "SPOTIFY_CLIENT_SECRET_FILE", tmp_path / "spotify_client_secret.secret")
    monkeypatch.setattr(rt, "SPOTIFY_ACCOUNTS_BASE_URL", mock_base)
    monkeypatch.setattr(token_store, "USERS_DIR", tmp_path / "users")
    monkeypatch.setattr(token_store, "PRIMARY_USER_FILE", tmp_path / "users" / ".primary_user")
    monkeypatch.setattr(token_store, "LEGACY_API_TOKEN_FILE", tmp_path / "spotify_api_token.secret")
    monkeypatch.setattr(token_store, "LEGACY_REFRESH_TOKEN_FILE",
                        tmp_path / "spotify_refresh_token.secret")


def test_refresh_with_user_id_rewrites_that_users_files(monkeypatch, tmp_path, mock_base):
    _wire(monkeypatch, tmp_path, mock_base)
    # Two authorized users; alice is primary (first in).
    token_store.save_tokens("mockuser", "expired-1", "mock-refresh-token")
    token_store.save_tokens("mockuser2", "expired-2", "mock-refresh-token-mockuser2")

    rt.refresh_spotify_auth(user_id="mockuser2")

    # user 2's namespaced token was refreshed with a PER-USER token...
    assert token_store.read_api_token("mockuser2") == "mock-access-token-mockuser2"
    # ...and the primary's legacy mirror was NOT clobbered.
    assert (tmp_path / "spotify_api_token.secret").read_text() == "expired-1"
    assert token_store.read_api_token("mockuser") == "expired-1"


def test_refresh_of_primary_user_keeps_legacy_mirror_fresh(monkeypatch, tmp_path, mock_base):
    _wire(monkeypatch, tmp_path, mock_base)
    token_store.save_tokens("mockuser", "expired-1", "mock-refresh-token")

    rt.refresh_spotify_auth(user_id="mockuser")

    assert token_store.read_api_token("mockuser") == "mock-access-token"
    assert (tmp_path / "spotify_api_token.secret").read_text() == "mock-access-token"
