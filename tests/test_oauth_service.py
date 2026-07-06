"""OAuth web service (plan 06 T4): the add-a-user flow, the CSRF state param,
and identity-derived token filing.

The module reads client id/secret from secrets/ at import; tests skip if those
aren't present (e.g. running outside the Docker test service). State storage
is faked in-memory here (the Redis round-trip is covered by
tests/test_redis_dedup.py); the token exchange + /v1/me identity flow runs
against the mock service and skips without it.
"""
import pytest


@pytest.fixture
def svc(monkeypatch, tmp_path):
    try:
        import application.spotify_authentication.api_authorization_web_service as svc
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"OAuth service unavailable (secrets missing?): {exc}")

    from application.spotify_authentication import token_store

    # In-memory single-use state store (the Redis behavior, without Redis).
    states = set()

    def consume(state):
        if state in states:
            states.remove(state)
            return True
        return False

    monkeypatch.setattr(svc, "store_oauth_state", states.add)
    monkeypatch.setattr(svc, "consume_oauth_state", consume)
    svc._test_states = states

    # Sandbox every file the flow writes.
    monkeypatch.setattr(svc, "SPOTIFY_AUTHORIZATION_CODE_FILE", tmp_path / "code.secret")
    monkeypatch.setattr(token_store, "USERS_DIR", tmp_path / "users")
    monkeypatch.setattr(token_store, "PRIMARY_USER_FILE", tmp_path / "users" / ".primary_user")
    monkeypatch.setattr(token_store, "LEGACY_API_TOKEN_FILE", tmp_path / "spotify_api_token.secret")
    monkeypatch.setattr(token_store, "LEGACY_REFRESH_TOKEN_FILE",
                        tmp_path / "spotify_refresh_token.secret")
    svc._test_tmp = tmp_path
    return svc


@pytest.fixture
def client(svc):
    from falcon import testing
    return testing.TestClient(svc.create_app())


def test_login_page_is_the_add_a_user_flow(client):
    resp = client.simulate_get("/login")
    assert resp.status_code == 200
    assert "Add a user" in resp.text
    assert "/login/start" in resp.text
    assert "No Spotify accounts have authorized" in resp.text  # empty users dir


def test_login_page_lists_authorized_users(svc, client):
    from application.spotify_authentication import token_store
    token_store.save_tokens("alice", "t", "r", claim_primary=True)
    resp = client.simulate_get("/login")
    assert "alice" in resp.text
    assert "primary" in resp.text


def test_login_start_redirects_to_spotify_authorize_with_state(svc, client):
    # Guards the Falcon app wiring (and a Falcon major bump).
    resp = client.simulate_get("/login/start")
    assert resp.status_code == 303
    location = resp.headers["location"]
    assert location.startswith(f"{svc.SPOTIFY_ACCOUNTS_BASE_URL}/authorize")
    assert "state=" in location
    # ...and the nonce it carries was actually stored for the callback.
    minted = location.split("state=")[1].split("&")[0]
    assert minted in svc._test_states


def test_login_start_redirect_is_not_browser_cacheable(svc, client):
    # The redirect's Location embeds a SINGLE-USE state nonce. A 301 is
    # heuristically cacheable with no Cache-Control header, so the second
    # "Add a user" click in the same browser (the runbook's friends-at-your-
    # machine onboarding) would replay the already-consumed nonce and the
    # callback would 400 on every retry until a hard cache clear. The
    # redirect must be a 303 See Other AND explicitly non-storable.
    resp = client.simulate_get("/login/start")
    assert resp.status_code == 303
    assert resp.headers.get("Cache-Control") == "no-store"


def test_login_start_mints_a_fresh_nonce_per_click(svc, client):
    # Two friends clicking "Add a user" back-to-back must each get their own
    # single-use state (the cached-301 failure mode collapsed them into one).
    loc1 = client.simulate_get("/login/start").headers["location"]
    loc2 = client.simulate_get("/login/start").headers["location"]
    nonce1 = loc1.split("state=")[1].split("&")[0]
    nonce2 = loc2.split("state=")[1].split("&")[0]
    assert nonce1 != nonce2
    assert {nonce1, nonce2} <= svc._test_states


def test_login_start_uses_loopback_ip_not_localhost(svc, client):
    # Spotify rejects http://localhost; the redirect_uri must be 127.0.0.1.
    location = client.simulate_get("/login/start").headers["location"]
    assert "redirect_uri=http%3A%2F%2F127.0.0.1%3A8000%2Fcallback" in location
    assert "localhost" not in location


def test_callback_without_state_is_rejected(client):
    resp = client.simulate_get("/callback", params={"code": "whatever"})
    assert resp.status_code == 400


def test_callback_with_unknown_state_is_rejected(client):
    resp = client.simulate_get("/callback", params={"code": "x", "state": "forged"})
    assert resp.status_code == 400


def test_state_is_single_use(svc, client, monkeypatch):
    # Unroutable accounts endpoint: the first use consumes the state and then
    # fails fast at the token exchange (the state is the subject here, and no
    # request may leave the machine); the replay must be rejected up front.
    monkeypatch.setattr(svc, "SPOTIFY_ACCOUNTS_BASE_URL", "http://127.0.0.1:1")
    svc._test_states.add("nonce-1")
    try:
        client.simulate_get("/callback", params={"code": "x", "state": "nonce-1"})
    except Exception:  # noqa: BLE001  (connection refused inside the handler)
        pass
    resp = client.simulate_get("/callback", params={"code": "x", "state": "nonce-1"})
    assert resp.status_code == 400


###
# Full round-trip against the mock accounts + API facades (skips w/o mock).
###

def _authorize(svc, client, state="nonce-flow"):
    svc._test_states.add(state)
    return client.simulate_get("/callback", params={"code": "mock-auth-code", "state": state})


def test_callback_files_tokens_under_the_derived_user_id(svc, client, mock_base, monkeypatch):
    monkeypatch.setattr(svc, "SPOTIFY_ACCOUNTS_BASE_URL", mock_base)
    monkeypatch.setattr(svc, "SPOTIFY_API_BASE_URL", mock_base)

    resp = _authorize(svc, client)
    assert resp.status_code == 200
    assert "mockuser" in resp.text
    assert "mock-access-token" not in resp.text  # tokens are not echoed to the browser

    tmp = svc._test_tmp
    assert (tmp / "users" / "mockuser" / "spotify_api_token.secret").read_text() == "mock-access-token"
    assert (tmp / "users" / "mockuser" / "spotify_refresh_token.secret").read_text() == "mock-refresh-token"
    # First user became primary -> the legacy (compose-gate) files are live.
    assert (tmp / "spotify_api_token.secret").read_text() == "mock-access-token"


def test_callback_renders_a_handled_page_when_the_identity_call_fails(svc, client,
                                                                      mock_base, monkeypatch):
    # The onboarding failure mode: the token exchange succeeds but GET /v1/me
    # fails (dev-mode allowlist not propagated -> 403, or a transient 5xx).
    # The auth code is burned and the state consumed, so the human MUST be
    # told to retry from /login — a handled 4xx/5xx page, never a bare 500
    # traceback — and no tokens may be persisted anywhere (without /v1/me we
    # don't know whose they are).
    import requests

    monkeypatch.setattr(svc, "SPOTIFY_ACCOUNTS_BASE_URL", mock_base)
    monkeypatch.setattr(svc, "SPOTIFY_API_BASE_URL", mock_base)
    requests.post(f"{mock_base}/_control/config",
                  json={"fail_url_substring": "/v1/me", "fail_status": 500})

    resp = _authorize(svc, client, state="nonce-me-fails")

    assert 400 <= resp.status_code < 600           # an error, but a HANDLED one
    assert "No tokens were saved" in resp.text     # our page, not a traceback
    assert 'href="/login"' in resp.text            # the retry pointer

    tmp = svc._test_tmp
    users_dir = tmp / "users"
    assert not users_dir.exists() or not any(p.is_dir() for p in users_dir.iterdir())
    assert not (tmp / "spotify_api_token.secret").exists()
    assert not (tmp / "spotify_refresh_token.secret").exists()


def test_second_user_files_separately_and_primary_is_kept(svc, client, mock_base, monkeypatch):
    import requests

    monkeypatch.setattr(svc, "SPOTIFY_ACCOUNTS_BASE_URL", mock_base)
    monkeypatch.setattr(svc, "SPOTIFY_API_BASE_URL", mock_base)

    _authorize(svc, client, state="nonce-u1")
    requests.post(f"{mock_base}/_control/config", json={"token_user": "mockuser2"})
    resp = _authorize(svc, client, state="nonce-u2")

    assert resp.status_code == 200
    tmp = svc._test_tmp
    assert (tmp / "users" / "mockuser2" / "spotify_api_token.secret").read_text() \
        == "mock-access-token-mockuser2"
    # Primary (first user) unchanged; legacy files still the primary's.
    assert (tmp / "users" / ".primary_user").read_text() == "mockuser"
    assert (tmp / "spotify_api_token.secret").read_text() == "mock-access-token"
