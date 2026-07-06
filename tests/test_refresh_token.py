"""refresh_spotify_auth() against the mock token endpoint.

The live-run bug this guards: the refresh POST went out with no client
authentication and Spotify 400'd it, so every crawl died at the ~1h access
token expiry. The mock now rejects unauthenticated token requests (like
Spotify) and omits refresh_token from refresh responses (like Spotify often
does), so both regressions are pinned here end-to-end.
"""
import requests

import application.spotify_authentication.refresh_token as rt


def _wire_secrets(monkeypatch, tmp_path, mock_base):
    (tmp_path / "spotify_client_id.secret").write_text("mock-client-id")
    (tmp_path / "spotify_client_secret.secret").write_text("mock-client-secret")
    (tmp_path / "spotify_api_token.secret").write_text("expired-token")
    (tmp_path / "spotify_refresh_token.secret").write_text("mock-refresh-token")
    monkeypatch.setattr(rt, "SPOTIFY_CLIENT_ID_FILE", tmp_path / "spotify_client_id.secret")
    monkeypatch.setattr(rt, "SPOTIFY_CLIENT_SECRET_FILE", tmp_path / "spotify_client_secret.secret")
    monkeypatch.setattr(rt, "SPOTIFY_API_TOKEN_FILE", tmp_path / "spotify_api_token.secret")
    monkeypatch.setattr(rt, "SPOTIFY_REFRESH_TOKEN_FILE", tmp_path / "spotify_refresh_token.secret")
    monkeypatch.setattr(rt, "SPOTIFY_ACCOUNTS_BASE_URL", mock_base)


def test_refresh_authenticates_and_rewrites_access_token(monkeypatch, tmp_path, mock_base):
    _wire_secrets(monkeypatch, tmp_path, mock_base)

    rt.refresh_spotify_auth()

    assert (tmp_path / "spotify_api_token.secret").read_text() == "mock-access-token"
    # The mock (like Spotify) omits refresh_token on a refresh grant; the old
    # one must be kept, not clobbered or KeyError'd.
    assert (tmp_path / "spotify_refresh_token.secret").read_text() == "mock-refresh-token"


def test_mock_token_endpoint_rejects_missing_client_auth(mock_base):
    r = requests.post(
        f"{mock_base}/api/token",
        data={"grant_type": "refresh_token", "refresh_token": "mock-refresh-token"},
        timeout=5,
    )
    assert r.status_code == 400
    assert r.json()["error"] == "invalid_client"
