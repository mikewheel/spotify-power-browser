import requests

from application.config import SECRETS_DIR, SPOTIFY_ACCOUNTS_BASE_URL

SPOTIFY_CLIENT_ID_FILE = SECRETS_DIR / "spotify_client_id.secret"
SPOTIFY_CLIENT_SECRET_FILE = SECRETS_DIR / "spotify_client_secret.secret"
SPOTIFY_API_TOKEN_FILE = SECRETS_DIR / "spotify_api_token.secret"
SPOTIFY_REFRESH_TOKEN_FILE = SECRETS_DIR / "spotify_refresh_token.secret"


def refresh_spotify_auth():

    with open(SPOTIFY_REFRESH_TOKEN_FILE, "r") as f:
        refresh_token = f.read()

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

    with open(SPOTIFY_API_TOKEN_FILE, "w") as f:
        f.write(access_token)

    with open(SPOTIFY_REFRESH_TOKEN_FILE, "w") as f:
        f.write(refresh_token)
