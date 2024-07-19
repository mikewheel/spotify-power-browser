import requests
from pathlib import Path

BASE_DIR = Path(__file__).parent
SPOTIFY_CLIENT_ID_FILE = BASE_DIR / "secrets" / "spotify_client_id.secret"
SPOTIFY_API_TOKEN_FILE = BASE_DIR / "secrets" / "spotify_api_token.secret"
SPOTIFY_REFRESH_TOKEN_FILE = BASE_DIR / "secrets" / "spotify_refresh_token.secret"


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


