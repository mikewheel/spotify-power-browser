"""A mock Spotify Web API: a controllable facade of the endpoints the crawler
uses, with a failure-injection control plane.

Endpoints (api.spotify.com facade):
  GET  /v1/me/tracks?offset=&limit=     paginated saved tracks (self-referential next)
  GET  /v1/{tracks,albums,artists}/{id} single resource (404 if unknown)
  GET  /v1/{tracks,albums,artists}?ids= batch (null for unknown ids)
  GET  /v1/me/player                    playback state (204 if none; see catalog player_*)
Auth (accounts.spotify.com facade):
  POST /api/token                       fake token (authorization_code / refresh_token)
  GET  /authorize                       redirect to the callback with a fake code
Control plane:
  POST /_control/config                 inject failures (see FailureInjectionMiddleware)
  POST /_control/reset                  clear injection
  GET  /_control/health                 200 (compose healthcheck)
"""
import json
from socketserver import ThreadingMixIn
from wsgiref.simple_server import make_server, WSGIServer

import falcon

from mock_spotify import catalog

# Mutable injection state, driven by POST /_control/config.
INJECTION = {
    "fail_next_n": 0,            # next N (non-control) requests fail, then resume
    "fail_url_substring": None,  # any request whose path contains this always fails
    "fail_status": 429,          # 429 | 401 | 500
    "retry_after": 0,            # Retry-After seconds for 429s
}


def _default_injection():
    return {"fail_next_n": 0, "fail_url_substring": None, "fail_status": 429, "retry_after": 0}


def _raise(status, retry_after):
    if status == 429:
        raise falcon.HTTPTooManyRequests(retry_after=int(retry_after))
    if status == 401:
        raise falcon.HTTPUnauthorized(title="The access token expired")
    raise falcon.HTTPInternalServerError(title="mock injected 500")


class FailureInjectionMiddleware:
    def process_request(self, req, resp):
        if req.path.startswith("/_control"):
            return
        sub = INJECTION["fail_url_substring"]
        if sub and sub in req.path:
            _raise(INJECTION["fail_status"], INJECTION["retry_after"])
        if INJECTION["fail_next_n"] > 0:
            INJECTION["fail_next_n"] -= 1
            _raise(INJECTION["fail_status"], INJECTION["retry_after"])


class LikedSongsResource:
    def on_get(self, req, resp):
        offset = req.get_param_as_int("offset", default=0)
        limit = req.get_param_as_int("limit", default=20)
        resp.media = catalog.liked_songs_page(offset, limit)


class SingleResource:
    def __init__(self, resource_type):
        self.resource_type = resource_type

    def on_get(self, req, resp, resource_id):
        obj = catalog.get_by_id(self.resource_type, resource_id)
        if obj is None:
            raise falcon.HTTPNotFound()
        resp.media = obj


class BatchResource:
    def __init__(self, resource_type):
        self.resource_type = resource_type

    def on_get(self, req, resp):
        ids = (req.get_param("ids") or "").split(",")
        resp.media = {self.resource_type: [catalog.get_by_id(self.resource_type, i) for i in ids if i]}


class TokenResource:
    def on_post(self, req, resp):
        # Fidelity: Spotify's token endpoint rejects clients that don't
        # authenticate (HTTP Basic). The permissive version of this mock let a
        # missing-client-auth bug in refresh_spotify_auth() ship undetected.
        if not (req.auth or "").startswith("Basic "):
            resp.status = falcon.HTTP_400
            resp.media = {
                "error": "invalid_client",
                "error_description": "client authentication required",
            }
            return

        form = req.get_media() if req.content_length else {}
        resp.media = {
            "access_token": "mock-access-token",
            "token_type": "Bearer",
            "scope": "user-library-read",
            "expires_in": 3600,
        }
        # Spotify includes a refresh_token on the initial code exchange but
        # commonly omits it when the grant is itself a refresh.
        if form.get("grant_type") != "refresh_token":
            resp.media["refresh_token"] = "mock-refresh-token"


class AuthorizeResource:
    def on_get(self, req, resp):
        redirect_uri = req.get_param("redirect_uri", default="http://127.0.0.1:8000/callback")
        raise falcon.HTTPSeeOther(f"{redirect_uri}?code=mock-auth-code")


class ControlConfigResource:
    def on_post(self, req, resp):
        cfg = req.media or {}
        for key in INJECTION:
            if key in cfg:
                INJECTION[key] = cfg[key]
        player = catalog.configure_player(cfg)  # player_* keys (plan 04 phase B)
        resp.media = {**INJECTION, **player}


class ControlResetResource:
    def on_post(self, req, resp):
        INJECTION.update(_default_injection())
        catalog.reset_player()
        resp.media = dict(INJECTION)


class HealthResource:
    def on_get(self, req, resp):
        resp.media = {"status": "ok"}


class PlayerResource:
    """GET /v1/me/player (plan 04 phase B): currently-playing state, scripted
    via /_control/config player_* keys. 204 like the real API when there's no
    active device (player_track_id: null)."""

    def on_get(self, req, resp):
        state = catalog.player_state()
        if state is None:
            resp.status = falcon.HTTP_204
            return
        resp.media = state


class ArtistAlbumsResource:
    """GET /v1/artists/{resource_id}/albums (plan 01): the artist's
    discography, paginated with a self-referential next link. Honors
    include_groups (album/single/compilation filtering) like the real API."""

    def on_get(self, req, resp, resource_id):
        offset = req.get_param_as_int("offset", default=0)
        limit = req.get_param_as_int("limit", default=20)
        page = catalog.artist_albums_page(
            resource_id, offset, limit, include_groups=req.get_param("include_groups")
        )
        if page is None:
            raise falcon.HTTPNotFound()
        resp.media = page


class AlbumTracksResource:
    """GET /v1/albums/{resource_id}/tracks (plan 01): an album's track list,
    paginated with a self-referential next link — the route the crawler needs
    for albums whose track list exceeds the 50 embedded in a batch response."""

    def on_get(self, req, resp, resource_id):
        offset = req.get_param_as_int("offset", default=0)
        limit = req.get_param_as_int("limit", default=50)
        page = catalog.album_tracks_page(resource_id, offset, limit)
        if page is None:
            raise falcon.HTTPNotFound()
        resp.media = page


def create_app():
    app = falcon.App(middleware=[FailureInjectionMiddleware()])
    app.add_route("/v1/me/tracks", LikedSongsResource())
    for rtype in ("tracks", "albums", "artists"):
        app.add_route(f"/v1/{rtype}/{{resource_id}}", SingleResource(rtype))
        app.add_route(f"/v1/{rtype}", BatchResource(rtype))
    app.add_route("/api/token", TokenResource())
    app.add_route("/authorize", AuthorizeResource())
    app.add_route("/_control/config", ControlConfigResource())
    app.add_route("/_control/reset", ControlResetResource())
    app.add_route("/_control/health", HealthResource())
    app.add_route("/v1/me/player", PlayerResource())
    # Plan 01 adjacent-artist discovery: discography sub-resources.
    app.add_route("/v1/artists/{resource_id}/albums", ArtistAlbumsResource())
    app.add_route("/v1/albums/{resource_id}/tracks", AlbumTracksResource())
    return app


class _ThreadingWSGIServer(ThreadingMixIn, WSGIServer):
    daemon_threads = True


def serve(port=80):
    with make_server("", port, create_app(), server_class=_ThreadingWSGIServer) as httpd:
        print(f"Mock Spotify serving on :{port}")
        httpd.serve_forever()


if __name__ == "__main__":
    import os
    serve(int(os.environ.get("MOCK_PORT", "80")))
