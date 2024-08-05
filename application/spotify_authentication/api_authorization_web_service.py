"""This module contains the code for acquiring tokens to use the Spotify API."""
from pathlib import Path
from urllib.parse import urlencode
from wsgiref.simple_server import make_server

import falcon
import requests

BASE_DIR = Path(__file__).parent.parent.parent
SPOTIFY_CLIENT_ID_FILE = BASE_DIR / "secrets" / "spotify_client_id.secret"
SPOTIFY_CLIENT_SECRET_FILE = BASE_DIR / "secrets" / "spotify_client_secret.secret"
SPOTIFY_AUTHORIZATION_CODE_FILE = BASE_DIR / "secrets" / "spotify_authorization_code.secret"
SPOTIFY_API_TOKEN_FILE = BASE_DIR / "secrets" / "spotify_api_token.secret"
SPOTIFY_REFRESH_TOKEN_FILE = BASE_DIR / "secrets" / "spotify_refresh_token.secret"

with open(SPOTIFY_CLIENT_ID_FILE, "r") as f:
    SPOTIFY_CLIENT_ID = f.read()

with open(SPOTIFY_CLIENT_SECRET_FILE, "r") as f:
    SPOTIFY_CLIENT_SECRET = f.read()


class SpotifyLoginResource:

    def on_get(self, req, resp):
        scopes = "playlist-read-private user-library-read user-follow-read"
        callback_uri = "http://localhost:8000/callback"

        query_params = urlencode({"response_type": 'code',
                                  "client_id": SPOTIFY_CLIENT_ID,
                                  "scope": scopes,
                                  "redirect_uri": callback_uri})

        authorization_code_uri = f'https://accounts.spotify.com/authorize?{query_params}'
        raise falcon.HTTPMovedPermanently(authorization_code_uri)


class SpotifyAuthCodeResource:

    def on_get(self, req, resp):
        error = req.get_param("error")
        if error is not None:
            print(f'Error in Spotify callback request: {error}')
            resp.status = falcon.HTTP_400

        authorization_code = req.get_param("code", required=True)

        with open(SPOTIFY_AUTHORIZATION_CODE_FILE, "w") as f:
            f.write(authorization_code)

        print("Requesting API Token from Spotify...")

        r = requests.post(
            'https://accounts.spotify.com/api/token',
            data={
                "code": authorization_code,
                "redirect_uri": "http://localhost:8000/callback",
                "grant_type": 'authorization_code'
            },
            auth=(SPOTIFY_CLIENT_ID, SPOTIFY_CLIENT_SECRET),
            headers={
              "Content-Type": "application/x-www-form-urlencoded"
            }
        )

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

        resp.status = falcon.HTTP_200
        resp.content_type = 'text/html'
        resp.text = f'''
        <!DOCTYPE html>
        <html>
        <head>
        <style>
            body {{
                font-family: sans-serif;
            }}

        </style>
        </head>
        <body>
            <h1>Success!</h1>
            <ul>
            <li>Access Token: {access_token}</li>
            <li>Token Type: {token_type}</li>
            <li>Scope: {scope}</li>
            <li>Expires in: {expires_in}</li>
            <li>Refresh Token: {refresh_token}</li>
            </ul>
        </body>
        </html>'''


def serve_the_app():
    app = falcon.App()
    app.add_route('/login', SpotifyLoginResource())
    app.add_route('/callback', SpotifyAuthCodeResource())

    with make_server('', 8000, app) as httpd:
        print('Starting to serve at http://localhost:8000/login')
        # Serve until process is killed
        httpd.serve_forever()


if __name__ == '__main__':
    serve_the_app()

