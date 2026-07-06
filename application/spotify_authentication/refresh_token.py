import requests

from application.config import SECRETS_DIR, SPOTIFY_ACCOUNTS_BASE_URL
from application.spotify_authentication import token_store

SPOTIFY_CLIENT_ID_FILE = SECRETS_DIR / "spotify_client_id.secret"
SPOTIFY_CLIENT_SECRET_FILE = SECRETS_DIR / "spotify_client_secret.secret"
# Legacy single-user token paths, kept as module attributes because existing
# tests monkeypatch them; they are the user_id=None storage location.
SPOTIFY_API_TOKEN_FILE = SECRETS_DIR / "spotify_api_token.secret"
SPOTIFY_REFRESH_TOKEN_FILE = SECRETS_DIR / "spotify_refresh_token.secret"


def refresh_spotify_auth(user_id=None):
    """Exchange the (per-user) refresh token for a fresh access token.

    user_id=None preserves the legacy single-user behavior byte-for-byte:
    read/write the fixed secrets/spotify_*.secret files. A user id reads and
    writes secrets/users/<id>/ instead (plan 06 T3); when that user is the
    primary, token_store.save_tokens also mirrors to the legacy files so the
    compose auth gate and legacy consumers never go stale.
    """
    if user_id is None:
        with open(SPOTIFY_REFRESH_TOKEN_FILE, "r") as f:
            refresh_token = f.read()
    else:
        refresh_token = token_store.read_refresh_token(user_id)

    with open(SPOTIFY_CLIENT_ID_FILE, "r") as f:
        client_id = f.read()

    with open(SPOTIFY_CLIENT_SECRET_FILE, "r") as f:
        client_secret = f.read()

    # Spotify's token endpoint requires client authentication on the refresh
    # grant — the same HTTP Basic scheme the initial authorization-code
    # exchange uses (api_authorization_web_service.py). Without it the request
    # is rejected with HTTP 400, which used to kill every crawl at the ~1h
    # access-token expiry wall.
    r = requests.post(f'{SPOTIFY_ACCOUNTS_BASE_URL}/api/token',
                      data={
                          "grant_type": 'refresh_token',
                          "refresh_token": refresh_token
                      },
                      auth=(client_id, client_secret),
                      headers={
                          "Content-Type": "application/x-www-form-urlencoded"
                      })

    r.raise_for_status()
    r = r.json()

    access_token = r["access_token"]
    # Spotify commonly omits refresh_token in refresh responses; keep using
    # the current one then (per RFC 6749 §6 the old token stays valid).
    refresh_token = r.get("refresh_token", refresh_token)

    if user_id is None:
        # Write through the module-level paths (not token_store) so the
        # existing tests' monkeypatched tmp files keep working.
        with open(SPOTIFY_API_TOKEN_FILE, "w") as f:
            f.write(access_token)

        with open(SPOTIFY_REFRESH_TOKEN_FILE, "w") as f:
            f.write(refresh_token)

        # TWO-WAY mirror (the runbook documents primary <-> legacy as kept in
        # sync "on every save/refresh"): the legacy refresh token IS the
        # primary's, so when a legacy-path refresh rotates it, the primary's
        # namespaced copies must follow — or a later per-user 401 for the
        # primary replays the stale token and 400s (invalid_grant), wedging
        # their crawl until a manual re-auth.
        primary = token_store.get_primary_user_id()
        if primary is not None:
            token_store.save_tokens(primary, access_token, refresh_token)
    else:
        token_store.save_tokens(user_id, access_token, refresh_token)
