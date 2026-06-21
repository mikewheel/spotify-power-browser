import pytest


@pytest.fixture
def client():
    # The OAuth module reads client id/secret from secrets/ at import; skip if
    # those aren't present (e.g. running outside the Docker test service).
    try:
        from application.spotify_authentication.api_authorization_web_service import create_app
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"OAuth service unavailable (secrets missing?): {exc}")
    from falcon import testing
    return testing.TestClient(create_app())


def test_login_redirects_to_spotify_authorize(client):
    # Guards the Falcon app wiring (and a Falcon major bump).
    resp = client.simulate_get("/login")
    assert resp.status_code in (301, 302)
    assert resp.headers["location"].startswith("https://accounts.spotify.com/authorize")


def test_login_uses_loopback_ip_not_localhost(client):
    # Spotify rejects http://localhost; the redirect_uri must be 127.0.0.1.
    location = client.simulate_get("/login").headers["location"]
    assert "redirect_uri=http%3A%2F%2F127.0.0.1%3A8000%2Fcallback" in location
    assert "localhost" not in location
