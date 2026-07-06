"""Guarded, idempotent playlist sync (plan 08 T2) + the CLI entrypoint.

    python3 -m application.playlists.sync <generator> [args] [--dry-run|--apply]

DRY-RUN IS THE DEFAULT: without --apply the diff is printed and nothing is
written anywhere (no Spotify mutations, no ManagedPlaylist writes). Pass
--apply to actually create/modify the playlist and stamp the graph.

Safety model (the managed-only hard rule):
  - Every playlist this system touches was created by it and recorded as a
    (:ManagedPlaylist) node. Every mutation path goes through
    assert_managed(); an id the store can't resolve raises
    UnmanagedPlaylistError before any request is sent. Hand-made playlists
    are constitutionally untouchable.
  - Each applied sync pushes the target list onto the node's rolling
    last-three snapshots (p.target_snapshots, JSON strings, newest first).
    Restore path: json-decode the snapshot you want back —

        MATCH (p:ManagedPlaylist {spotify_id: $id}) RETURN p.target_snapshots

    — then re-apply it as the target:

        sync_playlist(client, store, generator=..., identity_params=...,
                      playlist_name=..., target_track_ids=snapshot["track_ids"],
                      order_significant=True, apply=True)

Sync algorithm (diff, not recreate): GET current items -> compute adds /
removes -> apply in <=100-id chunks (Spotify's cap). Reorder happens only for
order-significant generators, and — because the API can only append or
remove-by-URI — is realized as a full rewrite (remove everything, re-add the
target in order) when the post-diff order would not match the target.

Spotify calls go through `requests` with the token file + SPOTIFY_API_BASE_URL
exactly like api_call_engine does, including the 401 -> refresh_spotify_auth()
-> retry-once path.

Config: PLAYLIST_SYNC_OWNER env selects the Spotify user id for create calls;
default is read from GET /v1/me at runtime.
"""
import argparse
import os
from dataclasses import dataclass, field
from datetime import date

import requests

from application.api_call_engine import get_api_token, load_api_token
from application.config import SECRETS_DIR, SPOTIFY_API_BASE_URL
from application.loggers import get_logger
from application.playlists.model import params_hash
from application.spotify_authentication.refresh_token import refresh_spotify_auth

logger = get_logger(__name__)

NEO4J_CREDENTIALS_FILE = SECRETS_DIR / "neo4j_credentials.yaml"

MAX_IDS_PER_CALL = 100          # Spotify's cap on add/remove items per request
MAX_DESCRIPTION_LENGTH = 300    # Spotify's cap on playlist descriptions


class UnmanagedPlaylistError(RuntimeError):
    """Raised before any write when a playlist id is not a ManagedPlaylist."""


def _chunked(items, size=MAX_IDS_PER_CALL):
    """Split a list into consecutive chunks of at most `size`."""
    return [items[i:i + size] for i in range(0, len(items), size)]


def _dedupe(items):
    """Drop repeated ids, keeping first occurrence order."""
    seen = set()
    return [i for i in items if not (i in seen or seen.add(i))]


def _uri(track_id):
    return f"spotify:track:{track_id}"


class SpotifyPlaylistClient:
    """Synchronous Spotify Web API client for the playlist write-back paths.

    base_url / token / refresh / reload are injectable for offline tests
    against the mock; the defaults read the token file and refresh exactly
    like api_call_engine (401 -> refresh_spotify_auth() -> retry once).
    """

    def __init__(self, base_url=None, token=None, refresh=None, reload=None):
        self.base_url = base_url or SPOTIFY_API_BASE_URL
        self._token = token
        self._refresh = refresh if refresh is not None else refresh_spotify_auth
        self._reload = reload if reload is not None else load_api_token

    def _get_token(self):
        if self._token is None:
            self._token = get_api_token()
        return self._token

    def _request(self, method, path_or_url, **kwargs):
        url = (
            path_or_url if path_or_url.startswith("http")
            else f"{self.base_url}{path_or_url}"
        )
        response = requests.request(
            method, url,
            headers={"Authorization": f"Bearer {self._get_token()}"},
            **kwargs,
        )
        if response.status_code == 401:
            logger.warning("HTTP 401: access token expired. Refreshing and retrying once...")
            self._refresh()
            self._token = self._reload()
            response = requests.request(
                method, url,
                headers={"Authorization": f"Bearer {self._token}"},
                **kwargs,
            )
        response.raise_for_status()
        return response

    def get_current_user(self):
        return self._request("GET", "/v1/me").json()

    def get_playlist(self, playlist_id):
        return self._request("GET", f"/v1/playlists/{playlist_id}").json()

    def create_playlist(self, user_id, name, description="", public=False):
        return self._request(
            "POST", f"/v1/users/{user_id}/playlists",
            json={"name": name, "public": public, "description": description},
        ).json()

    def get_playlist_track_ids(self, playlist_id):
        """All current track ids, in playlist order, following pagination."""
        track_ids, url = [], f"/v1/playlists/{playlist_id}/tracks"
        while url:
            page = self._request("GET", url).json()
            track_ids += [
                item["track"]["id"] for item in page["items"] if item.get("track")
            ]
            url = page.get("next")
        return track_ids

    def add_tracks(self, playlist_id, track_ids):
        for chunk in _chunked(track_ids):
            self._request(
                "POST", f"/v1/playlists/{playlist_id}/tracks",
                json={"uris": [_uri(i) for i in chunk]},
            )

    def remove_tracks(self, playlist_id, track_ids):
        for chunk in _chunked(track_ids):
            self._request(
                "DELETE", f"/v1/playlists/{playlist_id}/tracks",
                json={"tracks": [{"uri": _uri(i)} for i in chunk]},
            )

    def update_details(self, playlist_id, name=None, description=None):
        body = {}
        if name is not None:
            body["name"] = name
        if description is not None:
            body["description"] = description
        if body:
            self._request("PUT", f"/v1/playlists/{playlist_id}", json=body)


@dataclass
class PlaylistDiff:
    """What a sync would change. `rewrite` means the target ORDER cannot be
    reached by removes + appends alone, so apply removes everything and
    re-adds the target in order (order-significant generators only)."""
    adds: list = field(default_factory=list)
    removes: list = field(default_factory=list)
    rewrite: bool = False
    target: list = field(default_factory=list)
    current: list = field(default_factory=list)

    @property
    def is_empty(self):
        return not self.adds and not self.removes and not self.rewrite

    def describe(self):
        """Human-readable diff lines (what --dry-run prints)."""
        if self.is_empty:
            return ["in sync - no changes"]
        lines = []
        if self.adds:
            lines.append(f"add {len(self.adds)} track(s): {', '.join(self.adds[:10])}"
                         + (" ..." if len(self.adds) > 10 else ""))
        if self.removes:
            lines.append(f"remove {len(self.removes)} track(s): {', '.join(self.removes[:10])}"
                         + (" ..." if len(self.removes) > 10 else ""))
        if self.rewrite:
            lines.append(f"reorder: full rewrite of {len(self.target)} track(s) to match the generator order")
        return lines


def compute_diff(current_ids, target_ids, order_significant):
    """Idempotent diff between the playlist's current ids and the generator's
    target list. Duplicate ids collapse (managed playlists are only ever
    written by this module with deduped targets)."""
    target = _dedupe(target_ids)
    current = list(current_ids)
    current_set, target_set = set(current), set(target)

    removes = _dedupe([i for i in current if i not in target_set])
    adds = [i for i in target if i not in current_set]
    kept = [i for i in _dedupe(current) if i in target_set]

    # After removes + appends the playlist would read kept + adds; if the
    # generator is order-significant and that isn't the target order, only a
    # full rewrite realizes it (the API appends or removes-by-URI, nothing else).
    rewrite = order_significant and (kept + adds) != target

    return PlaylistDiff(adds=adds, removes=removes, rewrite=rewrite,
                        target=target, current=current)


def assert_managed(store, playlist_id):
    """The hard guard: refuse to touch any playlist id the graph does not
    record as a ManagedPlaylist. Raises; never proceeds."""
    if playlist_id is None or store.get_by_spotify_id(playlist_id) is None:
        raise UnmanagedPlaylistError(
            f"Refusing to modify playlist {playlist_id!r}: it is not recorded as a "
            f"ManagedPlaylist. This system only touches playlists it created; "
            f"hand-made playlists are untouchable."
        )


def apply_diff(client, store, playlist_id, diff):
    """Apply a computed diff to a MANAGED playlist, in <=100-id chunks."""
    assert_managed(store, playlist_id)
    if diff.is_empty:
        return
    if diff.rewrite:
        client.remove_tracks(playlist_id, _dedupe(diff.current))
        client.add_tracks(playlist_id, diff.target)
    else:
        if diff.removes:
            client.remove_tracks(playlist_id, diff.removes)
        if diff.adds:
            client.add_tracks(playlist_id, diff.adds)


def description_stamp(display_name, on_date=None):
    """The auto-stamped description (<=300 chars, Spotify's cap)."""
    on_date = on_date or date.today().isoformat()
    stamp = (
        f"Generated by spotify-power-browser · {display_name} · {on_date}"
        f" · do not edit (changes are overwritten)"
    )
    return stamp[:MAX_DESCRIPTION_LENGTH]


def resolve_owner(client):
    """The Spotify user id used for create calls: PLAYLIST_SYNC_OWNER env,
    or GET /v1/me at runtime."""
    return os.environ.get("PLAYLIST_SYNC_OWNER") or client.get_current_user()["id"]


def sync_playlist(client, store, *, generator, identity_params, playlist_name,
                  target_track_ids, order_significant, apply=False,
                  display_name=None, owner_id=None):
    """Create-if-missing by generator identity, then idempotent diff-sync.

    Dry-run (apply=False — the default everywhere) performs NO writes of any
    kind. Returns {"playlist_id", "created", "applied", "diff"}.
    """
    display_name = display_name or generator
    hash_value = params_hash(identity_params)
    record = store.get_by_generator(generator, hash_value)
    created = False

    if record is None:
        if not apply:
            diff = compute_diff([], target_track_ids, order_significant)
            logger.info(
                f"[dry-run] would create playlist {playlist_name!r} for generator "
                f"{generator!r} and add {len(diff.target)} track(s)."
            )
            return {"playlist_id": None, "created": False, "applied": False, "diff": diff}

        owner = owner_id or resolve_owner(client)
        playlist = client.create_playlist(
            owner, playlist_name, description=description_stamp(display_name)
        )
        store.record_created(playlist["id"], generator, hash_value, playlist_name, owner)
        record = store.get_by_generator(generator, hash_value)
        created = True
        logger.info(f"Created managed playlist {playlist['id']} ({playlist_name!r}).")

    playlist_id = record["spotify_id"]
    current = client.get_playlist_track_ids(playlist_id)
    diff = compute_diff(current, target_track_ids, order_significant)

    if not apply:
        logger.info(f"[dry-run] {playlist_name!r}: " + "; ".join(diff.describe()))
        return {"playlist_id": playlist_id, "created": created, "applied": False, "diff": diff}

    apply_diff(client, store, playlist_id, diff)
    client.update_details(playlist_id, description=description_stamp(display_name))
    store.record_sync(playlist_id, diff.target)

    # The API silently skips unplayable ids (market availability): log count
    # mismatches, don't fail.
    final = client.get_playlist_track_ids(playlist_id)
    if len(final) != len(diff.target):
        logger.warning(
            f"{playlist_name!r}: playlist holds {len(final)} of {len(diff.target)} "
            f"target track(s) after sync (unplayable ids are skipped by Spotify)."
        )

    logger.info(
        f"Synced {playlist_name!r} ({playlist_id}): +{len(diff.adds)} -{len(diff.removes)}"
        f"{' [rewrite]' if diff.rewrite else ''} -> {len(final)} track(s)."
    )
    return {"playlist_id": playlist_id, "created": created, "applied": True, "diff": diff}


def main(argv=None):
    # Imported lazily so the sync core stays usable without the generators
    # module's Cypher files (and vice versa in tests).
    from application.graph_database.connect import connect_to_neo4j
    from application.playlists.generators import (
        DEFAULT_MAX_POPULARITY, DEFAULT_MIN_BRIDGES, GENERATOR_NAMES,
        build_generator, run_generator,
    )
    from application.playlists.model import Neo4jManagedPlaylistStore

    parser = argparse.ArgumentParser(
        prog="python3 -m application.playlists.sync",
        description="Materialize a graph insight as a managed Spotify playlist (plan 08). "
                    "DRY-RUN BY DEFAULT: pass --apply to write.",
    )
    parser.add_argument("generator", choices=GENERATOR_NAMES, help="which generator to sync")
    parser.add_argument("generator_args", nargs="*",
                        help="generator arguments (exploration-queue: the artist name)")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true",
                      help="print the diff without writing anything (the default)")
    mode.add_argument("--apply", action="store_true",
                      help="actually write to Spotify and stamp the graph")
    parser.add_argument("--max-popularity", type=int, default=DEFAULT_MAX_POPULARITY,
                        help="adjacent-discoveries: popularity cap on candidates")
    parser.add_argument("--min-bridges", type=int, default=DEFAULT_MIN_BRIDGES,
                        help="adjacent-discoveries: minimum independent collaborator paths")
    args = parser.parse_args(argv)

    spec = build_generator(
        args.generator, args.generator_args,
        max_popularity=args.max_popularity, min_bridges=args.min_bridges,
    )

    driver = connect_to_neo4j(NEO4J_CREDENTIALS_FILE)
    try:
        target_track_ids, unknown_popularity = run_generator(driver, spec)
        if unknown_popularity:
            logger.warning(
                f"{unknown_popularity} artist(s) in the result have no popularity value "
                f"(not yet backfilled?) - treated as unknown and included."
            )
        if not target_track_ids:
            print(f"{spec.display_name}: the generator returned no tracks - nothing to sync.")
            return

        result = sync_playlist(
            SpotifyPlaylistClient(), Neo4jManagedPlaylistStore(driver),
            generator=spec.key,
            identity_params=spec.identity_params,
            playlist_name=spec.playlist_name,
            display_name=spec.display_name,
            target_track_ids=target_track_ids,
            order_significant=spec.order_significant,
            apply=args.apply,
        )

        mode_label = "APPLIED" if result["applied"] else "DRY-RUN (pass --apply to write)"
        print(f"{spec.playlist_name} [{mode_label}]")
        for line in result["diff"].describe():
            print(f"  {line}")
    finally:
        driver.close()


if __name__ == "__main__":
    main()
