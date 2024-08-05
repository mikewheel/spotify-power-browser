import requests

from application.config import SECRETS_DIR

SPOTIFY_CLIENT_ID_FILE = SECRETS_DIR / "spotify_client_id.secret"
SPOTIFY_API_TOKEN_FILE = SECRETS_DIR / "spotify_api_token.secret"
SPOTIFY_REFRESH_TOKEN_FILE = SECRETS_DIR / "spotify_refresh_token.secret"


def refresh_spotify_auth():

    with open(SPOTIFY_REFRESH_TOKEN_FILE, "r") as f:
        refresh_token = f.read()

    r = requests.post('https://accounts.spotify.com/api/token',
                      data={
                          "grant_type": 'refresh_token',
                          "refresh_token": refresh_token
                      },
                      headers={
                          "Content-Type": "application/x-www-form-urlencoded"
                      })

    r.raise_for_status()
    r = r.json()

    access_token = r["access_token"]
    token_type = r["token_type"]
    scope = r["scope"]
    expires_in = r["expires_in"]
    refresh_token = r["refresh_token"]

    with open(SPOTIFY_API_TOKEN_FILE, "w") as f:
        f.write(access_token)

    with open(SPOTIFY_REFRESH_TOKEN_FILE, "w") as f:
        f.write(refresh_token)


