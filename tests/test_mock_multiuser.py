"""Mock second user (plan 06 T7): per-user token minting, per-bearer /v1/me
and /v1/me/tracks, and the overlap invariants the multiplayer E2E relies on.
Needs the mock service (skips otherwise)."""
import requests

from mock_spotify.catalog import (
    MOCK_USER_2_ID,
    N_TRACKS,
    USER2_EXCLUSIVE_TRACK_IDS,
    user2_liked_track_ids,
)

USER2_BEARER = {"Authorization": f"Bearer mock-access-token-{MOCK_USER_2_ID}"}


def _all_liked_ids(mock_base, headers=None):
    ids, url = [], f"{mock_base}/v1/me/tracks?offset=0&limit=7"
    while url:
        page = requests.get(url, headers=headers or {}, timeout=5).json()
        ids += [item["track"]["id"] for item in page["items"]]
        url = page["next"]
    return ids


def test_token_knob_selects_the_user_for_code_exchanges(mock_base):
    # Default: the primary user's original literal tokens (back-compat).
    r = requests.post(f"{mock_base}/api/token", auth=("id", "secret"),
                      data={"grant_type": "authorization_code", "code": "mock-auth-code"})
    assert r.json()["access_token"] == "mock-access-token"
    assert r.json()["refresh_token"] == "mock-refresh-token"

    # Knob flips the NEXT exchange to user 2, deterministically.
    requests.post(f"{mock_base}/_control/config", json={"token_user": MOCK_USER_2_ID})
    r = requests.post(f"{mock_base}/api/token", auth=("id", "secret"),
                      data={"grant_type": "authorization_code", "code": "mock-auth-code"})
    assert r.json()["access_token"] == f"mock-access-token-{MOCK_USER_2_ID}"
    assert r.json()["refresh_token"] == f"mock-refresh-token-{MOCK_USER_2_ID}"

    # Reset is clean: back to the primary user.
    requests.post(f"{mock_base}/_control/reset")
    r = requests.post(f"{mock_base}/api/token", auth=("id", "secret"),
                      data={"grant_type": "authorization_code", "code": "mock-auth-code"})
    assert r.json()["access_token"] == "mock-access-token"


def test_refresh_grant_derives_user_from_the_refresh_token(mock_base):
    r = requests.post(f"{mock_base}/api/token", auth=("id", "secret"),
                      data={"grant_type": "refresh_token",
                            "refresh_token": f"mock-refresh-token-{MOCK_USER_2_ID}"})
    body = r.json()
    assert body["access_token"] == f"mock-access-token-{MOCK_USER_2_ID}"
    assert "refresh_token" not in body  # refresh grants omit it, like Spotify


def test_me_profile_answers_per_bearer(mock_base):
    assert requests.get(f"{mock_base}/v1/me").json()["id"] == "mockuser"
    assert requests.get(f"{mock_base}/v1/me",
                        headers=USER2_BEARER).json()["id"] == MOCK_USER_2_ID


def test_liked_songs_answer_per_bearer_with_partial_overlap(mock_base):
    user1_ids = set(_all_liked_ids(mock_base))                 # no auth -> primary
    user2_ids = _all_liked_ids(mock_base, headers=USER2_BEARER)

    assert len(user1_ids) == N_TRACKS
    assert user2_ids == user2_liked_track_ids()  # deterministic, page-order stable

    shared = user1_ids & set(user2_ids)
    user2_only = set(user2_ids) - user1_ids
    # Real intersection AND real difference — overlap queries need both.
    assert len(shared) == 20
    assert user2_only == set(USER2_EXCLUSIVE_TRACK_IDS)
    # user 2's exclusives resolve in the shared catalog (full track objects
    # with album + artists), so the same insert Cypher can persist them.
    page = requests.get(f"{mock_base}/v1/me/tracks?offset=20&limit=2",
                        headers=USER2_BEARER).json()
    for item in page["items"]:
        assert item["track"]["album"]["id"]
        assert item["track"]["artists"]


def test_authorize_reflects_the_state_param(mock_base):
    r = requests.get(
        f"{mock_base}/authorize",
        params={"redirect_uri": "http://127.0.0.1:8000/callback", "state": "nonce-xyz",
                "response_type": "code", "client_id": "x"},
        allow_redirects=False, timeout=5,
    )
    assert r.status_code == 303
    assert "code=mock-auth-code" in r.headers["location"]
    assert "state=nonce-xyz" in r.headers["location"]


def test_unknown_bearer_falls_back_to_primary_user(mock_base):
    # Pre-multiplayer callers (and legacy tokens) must keep working.
    page = requests.get(f"{mock_base}/v1/me/tracks?offset=0&limit=1",
                        headers={"Authorization": "Bearer something-else"}).json()
    assert page["total"] == N_TRACKS
