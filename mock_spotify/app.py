"""A mock Spotify Web API: a controllable facade of the endpoints the crawler
uses, with a failure-injection control plane.

Endpoints (api.spotify.com facade):
  GET  /v1/me/tracks?offset=&limit=     paginated saved tracks (self-referential next;
                                        answered per Authorization bearer — plan 06)
  GET  /v1/me                           current user profile (per bearer — plan 06)
  GET  /v1/{tracks,albums,artists}/{id} single resource (404 if unknown)
  GET  /v1/{tracks,albums,artists}?ids= batch (null for unknown ids)
  GET  /v1/me/player                    playback state (204 if none; see catalog player_*)
Auth (accounts.spotify.com facade):
  POST /api/token                       fake token (authorization_code / refresh_token);
                                        mints PER-USER tokens (plan 06): the _control
                                        token_user knob selects the user for code
                                        exchanges, refresh grants derive the user from
                                        the submitted refresh token
  GET  /authorize                       redirect to the callback with a fake code
                                        (reflects the OAuth state param)
Control plane:
  POST /_control/config                 inject failures (see FailureInjectionMiddleware),
                                        player_* keys, token_user knob
  POST /_control/reset                  clear injection + player/playlist/token state
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
        # Plan 06: /v1/me/* answers per the Authorization bearer (absent or
        # unknown bearer -> the primary user, the pre-multiplayer behavior).
        user_id = catalog.user_from_bearer(req.auth)
        resp.media = catalog.liked_songs_page(offset, limit, user_id=user_id)


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
        # Plan 06 T7: mint PER-USER tokens. An authorization_code exchange
        # mints for the user selected by the /_control token_user knob
        # (default: the primary user -> the original literal token strings);
        # a refresh grant derives the user from the submitted refresh token,
        # like the real endpoint (a refresh token is user-bound).
        if form.get("grant_type") == "refresh_token":
            user_id = catalog.user_from_token(form.get("refresh_token"))
        else:
            user_id = catalog.token_exchange_user()
        resp.media = {
            "access_token": catalog.access_token_for(user_id),
            "token_type": "Bearer",
            "scope": "user-library-read",
            "expires_in": 3600,
        }
        # Spotify includes a refresh_token on the initial code exchange but
        # commonly omits it when the grant is itself a refresh.
        if form.get("grant_type") != "refresh_token":
            resp.media["refresh_token"] = catalog.refresh_token_for(user_id)


class AuthorizeResource:
    def on_get(self, req, resp):
        redirect_uri = req.get_param("redirect_uri", default="http://127.0.0.1:8000/callback")
        # Reflect the OAuth state param like the real authorize endpoint —
        # plan 06 T4's CSRF round-trip depends on it coming back verbatim.
        state = req.get_param("state")
        suffix = f"&state={state}" if state else ""
        raise falcon.HTTPSeeOther(f"{redirect_uri}?code=mock-auth-code{suffix}")


class ControlConfigResource:
    def on_post(self, req, resp):
        cfg = req.media or {}
        for key in INJECTION:
            if key in cfg:
                INJECTION[key] = cfg[key]
        player = catalog.configure_player(cfg)  # player_* keys (plan 04 phase B)
        token = catalog.configure_token_exchange(cfg)  # token_user knob (plan 06)
        resp.media = {**INJECTION, **player, **token}


class ControlResetResource:
    def on_post(self, req, resp):
        INJECTION.update(_default_injection())
        catalog.reset_player()
        catalog.reset_playlists()  # plan 08: playlist CRUD state
        catalog.reset_token_exchange()  # plan 06: back to the primary user
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


# --- plan 08 playlist write-back (appended) -------------------------------

# Spotify's cap on items per add/remove call — enforced for fidelity so the
# sync module's chunking is actually load-bearing in tests.
MAX_PLAYLIST_ITEMS_PER_CALL = 100


class UserProfileResource:
    """GET /v1/me (plan 08): the fake current user for playlist-create calls.
    Answered per the Authorization bearer since plan 06 (no/unknown bearer ->
    the primary user)."""

    def on_get(self, req, resp):
        resp.media = catalog.current_user(catalog.user_from_bearer(req.auth))


def _playlist_or_404(playlist_id):
    obj = catalog.playlist_object(playlist_id)
    if obj is None:
        raise falcon.HTTPNotFound()
    return obj


def _validated_track_ids(uris):
    """Enforce the 100-cap and resolve URIs to catalog track ids (400 on
    malformed/unknown, like Spotify)."""
    if len(uris) > MAX_PLAYLIST_ITEMS_PER_CALL:
        raise falcon.HTTPBadRequest(
            description=f"You can add a maximum of {MAX_PLAYLIST_ITEMS_PER_CALL} tracks per request."
        )
    track_ids = []
    for uri in uris:
        track_id = catalog.track_id_from_uri(uri)
        if track_id is None:
            raise falcon.HTTPBadRequest(description=f"Unsupported URL / URI: {uri}")
        track_ids.append(track_id)
    return track_ids


class PlaylistCreationResource:
    """POST /v1/users/{user_id}/playlists (plan 08): create an empty playlist."""

    def on_post(self, req, resp, user_id):
        body = req.get_media() if req.content_length else {}
        name = body.get("name")
        if not name:
            raise falcon.HTTPBadRequest(description="Missing required field: name")
        resp.status = falcon.HTTP_201
        resp.media = catalog.create_playlist(
            owner_id=user_id,
            name=name,
            description=body.get("description", ""),
            public=body.get("public", False),
        )


class PlaylistResource:
    """GET /v1/playlists/{playlist_id} + PUT to change details (plan 08 —
    the sync module re-stamps the description on every applied sync)."""

    def on_get(self, req, resp, playlist_id):
        resp.media = _playlist_or_404(playlist_id)

    def on_put(self, req, resp, playlist_id):
        _playlist_or_404(playlist_id)
        body = req.get_media() if req.content_length else {}
        catalog.change_playlist_details(
            playlist_id, name=body.get("name"), description=body.get("description")
        )


class PlaylistTracksResource:
    """GET (paginated) / POST (add) / DELETE (remove) /v1/playlists/{id}/tracks
    with Spotify's 100-items-per-call cap (plan 08)."""

    def on_get(self, req, resp, playlist_id):
        _playlist_or_404(playlist_id)
        offset = req.get_param_as_int("offset", default=0)
        limit = req.get_param_as_int("limit", default=100)
        resp.media = catalog.playlist_tracks_page(playlist_id, offset, limit)

    def on_post(self, req, resp, playlist_id):
        _playlist_or_404(playlist_id)
        body = req.get_media() if req.content_length else {}
        track_ids = _validated_track_ids(body.get("uris") or [])
        snapshot_id = catalog.add_playlist_tracks(
            playlist_id, track_ids, position=body.get("position")
        )
        resp.status = falcon.HTTP_201
        resp.media = {"snapshot_id": snapshot_id}

    def on_delete(self, req, resp, playlist_id):
        _playlist_or_404(playlist_id)
        body = req.get_media() if req.content_length else {}
        uris = [t.get("uri") for t in (body.get("tracks") or [])]
        track_ids = _validated_track_ids(uris)
        snapshot_id = catalog.remove_playlist_tracks(playlist_id, track_ids)
        resp.media = {"snapshot_id": snapshot_id}



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
    # --- plan 08 playlist write-back (appended) ---
    app.add_route("/v1/me", UserProfileResource())
    app.add_route("/v1/users/{user_id}/playlists", PlaylistCreationResource())
    app.add_route("/v1/playlists/{playlist_id}", PlaylistResource())
    app.add_route("/v1/playlists/{playlist_id}/tracks", PlaylistTracksResource())
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
