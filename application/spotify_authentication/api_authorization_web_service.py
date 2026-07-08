"""This module contains the code for acquiring tokens to use the Spotify API.

Multiplayer (plan 06 T4): the login page is an "add a user" flow — hit it once
per friend. Each authorization round-trip carries a single-use OAuth `state`
nonce (minted into Redis with a TTL, validated + consumed by the callback),
which both closes the CSRF gap and guarantees the callback only files tokens
for logins this service started. The callback derives the user's identity from
GET /v1/me with the fresh token (never assumed), and files tokens under
secrets/users/<spotify_user_id>/.

PRIMARY-USER SEMANTICS: the first account to authorize becomes the primary
user (see token_store) — its tokens are ALSO written to the legacy
secrets/spotify_*.secret files, which the docker compose auth-gate healthcheck
and all user_id=None code paths depend on.
"""
import html
import secrets as py_secrets
from urllib.parse import urlencode
from wsgiref.simple_server import make_server

import falcon
import requests

from application.config import SECRETS_DIR, SPOTIFY_ACCOUNTS_BASE_URL, SPOTIFY_API_BASE_URL
from application.cache.redis_client import consume_oauth_state, store_oauth_state
from application.spotify_authentication import token_store

SPOTIFY_CLIENT_ID_FILE = SECRETS_DIR / "spotify_client_id.secret"
SPOTIFY_CLIENT_SECRET_FILE = SECRETS_DIR / "spotify_client_secret.secret"
SPOTIFY_AUTHORIZATION_CODE_FILE = SECRETS_DIR / "spotify_authorization_code.secret"

# Spotify rejects http://localhost as an "insecure" redirect URI; the explicit
# loopback IP http://127.0.0.1 is required for local development. This exact
# value must also be registered in the Spotify app's Redirect URI settings, and
# is used in both the authorize request and the token exchange (they must match).
SPOTIFY_REDIRECT_URI = "http://127.0.0.1:8000/callback"

with open(SPOTIFY_CLIENT_ID_FILE, "r") as f:
    SPOTIFY_CLIENT_ID = f.read()

with open(SPOTIFY_CLIENT_SECRET_FILE, "r") as f:
    SPOTIFY_CLIENT_SECRET = f.read()


def _page(title, body):
    return f'''
    <!DOCTYPE html>
    <html>
    <head>
    <style>
        body {{ font-family: sans-serif; max-width: 40em; margin: 3em auto; }}
        a.button {{ display: inline-block; padding: 0.6em 1.2em; background: #1db954;
                    color: white; text-decoration: none; border-radius: 2em; }}
        li {{ margin: 0.3em 0; }}
    </style>
    </head>
    <body>
        <h1>{title}</h1>
        {body}
    </body>
    </html>'''


def _user_list_html():
    users = token_store.list_user_ids()
    primary = token_store.get_primary_user_id()
    if not users:
        return "<p>No Spotify accounts have authorized this app yet.</p>"
    items = "".join(
        f"<li><code>{html.escape(user)}</code>"
        + (" &mdash; primary (drives the legacy single-user pipeline)"
           if user == primary else "")
        + "</li>"
        for user in users
    )
    return f"<p>Authorized users (from <code>secrets/users/</code>):</p><ul>{items}</ul>"


class SpotifyLoginResource:
    """GET /login — the "add a user" page: lists already-authorized users and
    links to /login/start, which begins a fresh OAuth dance."""

    def on_get(self, req, resp):
        resp.content_type = "text/html"
        resp.text = _page(
            "Spotify Power Browser — users",
            _user_list_html()
            + '<p><a class="button" href="/login/start">Add a user &rarr;</a></p>'
            + "<p>Each friend logs in once here; their listening data is then "
              "crawled into the shared graph. Dev-mode apps must allowlist the "
              "account's email in the Spotify dashboard first "
              "(see docs/multiplayer-runbook.md).</p>",
        )


class SpotifyLoginStartResource:
    """GET /login/start — mint the single-use state nonce and redirect to
    Spotify's authorize endpoint."""

    def on_get(self, req, resp):
        # Bundled scope expansion for plans 02 (listening history: recently-played
        # + top items), 04 (playback-state polling), and 08 (playlist write-back).
        # One re-auth unlocks all three (docs/plans/README.md "Do these first" #2).
        scopes = (
            "playlist-read-private user-library-read user-follow-read "
            "user-read-recently-played user-top-read user-read-playback-state "
            "playlist-modify-private"
        )

        state = py_secrets.token_urlsafe(32)
        store_oauth_state(state)

        query_params = urlencode({"response_type": 'code',
                                  "client_id": SPOTIFY_CLIENT_ID,
                                  "scope": scopes,
                                  "state": state,
                                  "redirect_uri": SPOTIFY_REDIRECT_URI})

        authorization_code_uri = f'{SPOTIFY_ACCOUNTS_BASE_URL}/authorize?{query_params}'
        # 303 + no-store, NEVER a cacheable 301: the Location embeds a
        # single-use nonce, and a cached redirect would replay it on the next
        # login attempt (docs/auth.md).
        raise falcon.HTTPSeeOther(authorization_code_uri,
                                  headers={"Cache-Control": "no-store"})


class SpotifyAuthCodeResource:

    def on_get(self, req, resp):
        error = req.get_param("error")
        if error is not None:
            print(f'Error in Spotify callback request: {error}')
            resp.status = falcon.HTTP_400
            resp.content_type = "text/html"
            resp.text = _page("Authorization failed", f"<p>{html.escape(error)}</p>")
            return

        # CSRF gate: the state must be one WE minted, unexpired, and never
        # seen before (consume_oauth_state is single-use). A callback without
        # a valid state is rejected before any token exchange happens.
        state = req.get_param("state")
        if not consume_oauth_state(state):
            print("Rejecting /callback with a missing, unknown, or replayed state param.")
            resp.status = falcon.HTTP_400
            resp.content_type = "text/html"
            resp.text = _page(
                "Invalid or expired login attempt",
                '<p>The OAuth state was missing, already used, or timed out. '
                'Start again from <a href="/login">the login page</a>.</p>',
            )
            return

        authorization_code = req.get_param("code", required=True)

        with open(SPOTIFY_AUTHORIZATION_CODE_FILE, "w") as f:
            f.write(authorization_code)

        print("Requesting API Token from Spotify...")

        r = requests.post(
            f'{SPOTIFY_ACCOUNTS_BASE_URL}/api/token',
            data={
                "code": authorization_code,
                "redirect_uri": SPOTIFY_REDIRECT_URI,
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
        scope = r["scope"]
        expires_in = r["expires_in"]
        refresh_token = r["refresh_token"]

        # Identity is DERIVED, not assumed: ask the API whose token this is,
        # then file it under that user id (plan 06 T4).
        me = None
        try:
            me = requests.get(
                f'{SPOTIFY_API_BASE_URL}/v1/me',
                headers={"Authorization": f"Bearer {access_token}"},
            )
            me.raise_for_status()
        except requests.RequestException:
            # The primary onboarding failure (dev-mode allowlist not yet
            # propagated -> 403, or a transient 5xx). The auth code is burned
            # and the state consumed, so the whole login must be redone — tell
            # the human that, like the responder's other two failure paths,
            # instead of dropping an unhandled traceback as a bare 500.
            # DELIBERATELY nothing is persisted: without /v1/me we don't know
            # WHOSE tokens these are, and filing them under a guess is worse
            # than one more login round-trip.
            detail = (f"HTTP {me.status_code}" if me is not None
                      else "a connection error")
            print(f'GET /v1/me failed after the token exchange ({detail}); '
                  f'discarding the issued tokens and asking the user to retry.')
            resp.status = falcon.HTTP_502
            resp.content_type = "text/html"
            resp.text = _page(
                "Login almost worked",
                f'<p>Spotify accepted the login, but asking who you are '
                f'(<code>GET /v1/me</code>) failed with {html.escape(detail)}. '
                f'<strong>No tokens were saved.</strong></p>'
                f'<p>If this app is in development mode, check that this '
                f"account's email is allowlisted in the Spotify dashboard "
                f'(docs/multiplayer-runbook.md &sect;1), then retry from '
                f'<a href="/login">the login page</a>.</p>',
            )
            return
        me = me.json()
        user_id = me["id"]
        display_name = me.get("display_name") or user_id

        # Files under secrets/users/<id>/; the FIRST user to LOG IN becomes
        # primary and is mirrored to the legacy files (the compose auth gate's
        # healthcheck watches secrets/spotify_api_token.secret). This callback
        # is the ONLY caller allowed to claim the primary slot — background
        # refresh saves never do (token_store.save_tokens docstring).
        token_store.save_tokens(user_id, access_token, refresh_token, claim_primary=True)
        primary = token_store.get_primary_user_id()

        resp.status = falcon.HTTP_200
        resp.content_type = 'text/html'
        # Deliberately does NOT echo the tokens (they're on disk; a browser
        # history entry full of bearer tokens helps nobody).
        resp.text = _page(
            "Success!",
            f'''
            <p>Authorized <strong>{html.escape(display_name)}</strong>
               (<code>{html.escape(user_id)}</code>)
               {"&mdash; the primary user" if primary == user_id else ""}.</p>
            <ul>
                <li>Scope: {html.escape(scope)}</li>
                <li>Access token expires in: {expires_in}s (auto-refreshed)</li>
                <li>Tokens filed under: <code>secrets/users/{html.escape(user_id)}/</code></li>
            </ul>
            {_user_list_html()}
            <p><a class="button" href="/login">Add another user</a></p>''',
        )


def create_app():
    app = falcon.App()
    app.add_route('/login', SpotifyLoginResource())
    app.add_route('/login/start', SpotifyLoginStartResource())
    app.add_route('/callback', SpotifyAuthCodeResource())
    return app


def serve_the_app():
    app = create_app()

    with make_server('', 8000, app) as httpd:
        print('Starting to serve at http://127.0.0.1:8000/login')
        # Serve until process is killed
        httpd.serve_forever()


if __name__ == '__main__':
    serve_the_app()
