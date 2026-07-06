"""ManagedPlaylist model layer (plan 08).

Split like application/annotations/model.py so the interesting parts test
offline:
  - params_hash / build_*_params are pure and define the exact param shapes
    the Cypher under application/graph_database/queries/playlists/ consumes;
  - Neo4jManagedPlaylistStore is the thin execution layer over the bolt
    driver;
  - InMemoryManagedPlaylistStore implements the same protocol without a
    database, for offline tests and throwaway dry-run experiments.

The store protocol (what sync.py depends on):
  get_by_generator(generator, params_hash) -> record dict | None
  get_by_spotify_id(spotify_id)            -> record dict | None   (the guard)
  record_created(spotify_id, generator, params_hash, name, owner_spotify_user_id)
  record_sync(spotify_id, target_track_ids)
"""
import hashlib
import json
from datetime import datetime, timezone

from application.config import APPLICATION_DIR
from application.graph_database.connect import execute_query_against_neo4j
from application.loggers import get_logger

logger = get_logger(__name__)

PLAYLIST_QUERIES_DIR = APPLICATION_DIR / "graph_database" / "queries" / "playlists"

# How many target snapshots the graph keeps per playlist (newest first). Must
# match the slice in record_sync.cypher.
SNAPSHOTS_KEPT = 3


def _load_query(name):
    with open(PLAYLIST_QUERIES_DIR / f"{name}.cypher", "r") as f:
        return f.read()


INSERT_MANAGED_PLAYLIST_QUERY = _load_query("insert_managed_playlist")
FETCH_BY_GENERATOR_QUERY = _load_query("fetch_managed_playlist_by_generator")
FETCH_BY_SPOTIFY_ID_QUERY = _load_query("fetch_managed_playlist_by_spotify_id")
RECORD_SYNC_QUERY = _load_query("record_sync")


def _now_iso():
    return datetime.now(timezone.utc).isoformat()


def params_hash(identity_params):
    """Stable hash of a generator's identity params (e.g. the artist name for
    exploration-queue). Same params -> same managed playlist across runs."""
    canonical = json.dumps(identity_params, sort_keys=True, separators=(",", ":"))
    return hashlib.sha1(canonical.encode("utf-8")).hexdigest()


def build_snapshot(target_track_ids, at=None):
    """One target snapshot as the JSON string record_sync.cypher stores
    (Neo4j properties cannot hold nested lists)."""
    return json.dumps(
        {"at": at or _now_iso(), "track_ids": list(target_track_ids)},
        separators=(",", ":"),
    )


def build_managed_playlist_params(spotify_id, generator, params_hash_value,
                                  name, owner_spotify_user_id):
    """Param shape for insert_managed_playlist.cypher."""
    return {
        "playlist": {
            "spotify_id": spotify_id,
            "generator": generator,
            "params_hash": params_hash_value,
            "name": name,
            "owner_spotify_user_id": owner_spotify_user_id,
            "created_at": _now_iso(),
        }
    }


def build_record_sync_params(spotify_id, target_track_ids, at=None):
    """Param shape for record_sync.cypher."""
    at = at or _now_iso()
    return {
        "sync": {
            "spotify_id": spotify_id,
            "last_synced": at,
            "snapshot": build_snapshot(target_track_ids, at=at),
        }
    }


class Neo4jManagedPlaylistStore:
    """ManagedPlaylist reads/writes through the bolt driver."""

    def __init__(self, driver, database="neo4j"):
        self.driver = driver
        self.database = database

    def _fetch_one(self, query, **params):
        records, _, _ = self.driver.execute_query(query, database_=self.database, **params)
        return dict(records[0]) if records else None

    def get_by_generator(self, generator, params_hash_value):
        return self._fetch_one(
            FETCH_BY_GENERATOR_QUERY, generator=generator, params_hash=params_hash_value
        )

    def get_by_spotify_id(self, spotify_id):
        return self._fetch_one(FETCH_BY_SPOTIFY_ID_QUERY, spotify_id=spotify_id)

    def record_created(self, spotify_id, generator, params_hash_value, name,
                       owner_spotify_user_id):
        params = build_managed_playlist_params(
            spotify_id, generator, params_hash_value, name, owner_spotify_user_id
        )
        execute_query_against_neo4j(
            query=INSERT_MANAGED_PLAYLIST_QUERY, driver=self.driver,
            database=self.database, **params,
        )
        logger.info(f"Recorded ManagedPlaylist {spotify_id} for generator {generator!r}.")
        return params["playlist"]

    def record_sync(self, spotify_id, target_track_ids):
        params = build_record_sync_params(spotify_id, target_track_ids)
        execute_query_against_neo4j(
            query=RECORD_SYNC_QUERY, driver=self.driver,
            database=self.database, **params,
        )
        return params["sync"]


class InMemoryManagedPlaylistStore:
    """The same protocol backed by a dict — offline tests + experiments."""

    def __init__(self):
        self.playlists = {}

    def get_by_generator(self, generator, params_hash_value):
        for record in self.playlists.values():
            if record["generator"] == generator and record["params_hash"] == params_hash_value:
                return dict(record)
        return None

    def get_by_spotify_id(self, spotify_id):
        record = self.playlists.get(spotify_id)
        return dict(record) if record else None

    def record_created(self, spotify_id, generator, params_hash_value, name,
                       owner_spotify_user_id):
        params = build_managed_playlist_params(
            spotify_id, generator, params_hash_value, name, owner_spotify_user_id
        )
        record = {**params["playlist"], "last_synced": None, "target_snapshots": []}
        self.playlists[spotify_id] = record
        return params["playlist"]

    def record_sync(self, spotify_id, target_track_ids):
        params = build_record_sync_params(spotify_id, target_track_ids)
        record = self.playlists[spotify_id]
        record["last_synced"] = params["sync"]["last_synced"]
        record["target_snapshots"] = (
            [params["sync"]["snapshot"]] + record["target_snapshots"]
        )[:SNAPSHOTS_KEPT]
        return params["sync"]
