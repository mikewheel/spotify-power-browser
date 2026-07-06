"""Sync-module tests (plan 08 T2) — fully offline: pure diff/param logic plus
end-to-end sync flows against the mock Spotify app served in-process on an
ephemeral localhost port (no compose network, no Neo4j — the store is the
in-memory protocol double from application/playlists/model.py).
"""
import json
import logging
import threading
from wsgiref.simple_server import make_server

import pytest
import requests

from application.playlists.model import (
    InMemoryManagedPlaylistStore, build_record_sync_params, params_hash,
)
from application.playlists.sync import (
    PlaylistDiff, SpotifyPlaylistClient, UnmanagedPlaylistError,
    apply_diff, compute_diff, description_stamp, sync_playlist,
)
from mock_spotify import catalog
from mock_spotify.app import create_app, _ThreadingWSGIServer


@pytest.fixture
def mock_url():
    """The mock served in-process; N_TRACKS bumped so >100-target chunking
    tests can use catalog-generated ids that actually resolve."""
    server = make_server("127.0.0.1", 0, create_app(), server_class=_ThreadingWSGIServer)
    base = f"http://127.0.0.1:{server.server_port}"
    original_base, original_n = catalog.PUBLIC_BASE_URL, catalog.N_TRACKS
    catalog.PUBLIC_BASE_URL = base
    catalog.N_TRACKS = 250
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    requests.post(f"{base}/_control/reset", timeout=3).raise_for_status()
    yield base
    requests.post(f"{base}/_control/reset", timeout=3)
    server.shutdown()
    catalog.PUBLIC_BASE_URL, catalog.N_TRACKS = original_base, original_n


@pytest.fixture
def client(mock_url):
    return SpotifyPlaylistClient(base_url=mock_url, token="mock-token")


@pytest.fixture
def sync_log(caplog):
    """Capture the sync module's log records: its logger sets propagate=False
    (application/loggers.py), so caplog's root-logger handler never sees them
    unless attached to the module logger directly."""
    sync_logger = logging.getLogger("application.playlists.sync")
    caplog.set_level(logging.INFO)
    sync_logger.addHandler(caplog.handler)
    yield caplog
    sync_logger.removeHandler(caplog.handler)


def _ids(*numbers):
    return [f"trk{n:06d}" for n in numbers]


def _sync(client, store, target, apply=True, order_significant=True):
    return sync_playlist(
        client, store,
        generator="test-generator",
        identity_params={},
        playlist_name="[SPB] Test Generator",
        display_name="test-generator",
        target_track_ids=target,
        order_significant=order_significant,
        apply=apply,
    )


###
# Pure logic
###

def test_compute_diff_adds_removes_and_order():
    diff = compute_diff(_ids(1, 2, 3), _ids(2, 3, 4), order_significant=True)
    assert diff.adds == _ids(4)
    assert diff.removes == _ids(1)
    assert diff.rewrite is False  # kept(2,3) + adds(4) == target
    assert diff.target == _ids(2, 3, 4)


def test_compute_diff_empty_when_in_sync():
    diff = compute_diff(_ids(1, 2), _ids(1, 2), order_significant=True)
    assert diff.is_empty
    assert diff.describe() == ["in sync - no changes"]


def test_compute_diff_dedupes_target():
    diff = compute_diff([], _ids(1, 1, 2), order_significant=True)
    assert diff.target == _ids(1, 2)
    assert diff.adds == _ids(1, 2)


def test_compute_diff_reorder_requires_order_significance():
    same_set_new_order = compute_diff(_ids(1, 2, 3), _ids(3, 1, 2), order_significant=False)
    assert same_set_new_order.is_empty  # queues that don't care about order stay put

    reordered = compute_diff(_ids(1, 2, 3), _ids(3, 1, 2), order_significant=True)
    assert reordered.rewrite is True
    assert reordered.adds == [] and reordered.removes == []


def test_compute_diff_forces_rewrite_when_current_duplicates_a_kept_id():
    # Remove-by-URI removes ALL occurrences of an id, so a duplicate of a
    # target-kept id can only be corrected by the full-rewrite path. The
    # description stamp promises manual edits are overwritten, so these must
    # never be reported as "in sync". Three traced scenarios:

    # [A,A,B] -> [A,B]: adds/removes are empty; only rewrite can fix the dup.
    dup_in_sync = compute_diff(_ids(1, 1, 2), _ids(1, 2), order_significant=True)
    assert dup_in_sync.rewrite is True
    assert not dup_in_sync.is_empty

    # [A,A,B] -> [A,B,C]: append-only would leave [A,A,B,C] behind.
    dup_with_add = compute_diff(_ids(1, 1, 2), _ids(1, 2, 3), order_significant=True)
    assert dup_with_add.rewrite is True

    # [A,B,A] -> [A]: removing B alone would leave [A,A].
    dup_with_remove = compute_diff(_ids(1, 2, 1), _ids(1), order_significant=True)
    assert dup_with_remove.rewrite is True

    # Order-insignificant generators still promise deduped contents, so the
    # duplicate forces the rewrite there too.
    dup_unordered = compute_diff(_ids(1, 1, 2), _ids(1, 2), order_significant=False)
    assert dup_unordered.rewrite is True

    # Duplicates only of ids being REMOVED don't need a rewrite: remove-by-URI
    # already drops every occurrence.
    dup_removed = compute_diff(_ids(9, 9, 1), _ids(1), order_significant=True)
    assert dup_removed.rewrite is False
    assert dup_removed.removes == _ids(9)


def test_params_hash_is_stable_and_order_insensitive():
    assert params_hash({"a": 1, "b": 2}) == params_hash({"b": 2, "a": 1})
    assert params_hash({"a": 1}) != params_hash({"a": 2})


def test_record_sync_params_shape_matches_cypher_contract():
    params = build_record_sync_params("pl000001", _ids(1, 2))
    assert set(params) == {"sync"}
    assert set(params["sync"]) == {"spotify_id", "last_synced", "snapshot"}
    snapshot = json.loads(params["sync"]["snapshot"])
    assert snapshot["track_ids"] == _ids(1, 2)
    assert snapshot["at"] == params["sync"]["last_synced"]


def test_snapshot_window_keeps_last_three_newest_first():
    store = InMemoryManagedPlaylistStore()
    store.record_created("pl000001", "g", params_hash({}), "[SPB] G", "mockuser")
    for n in range(4):
        store.record_sync("pl000001", _ids(n))
    snapshots = store.get_by_spotify_id("pl000001")["target_snapshots"]
    assert len(snapshots) == 3
    assert [json.loads(s)["track_ids"] for s in snapshots] == [_ids(3), _ids(2), _ids(1)]


def test_description_stamp_is_bounded_and_labeled():
    stamp = description_stamp("x" * 400, on_date="2026-07-06")
    assert len(stamp) <= 300
    short = description_stamp("adjacent-discoveries", on_date="2026-07-06")
    assert "Generated by spotify-power-browser" in short
    assert "do not edit" in short and "2026-07-06" in short


###
# End-to-end against the mock
###

def test_first_sync_creates_playlist_and_fills_it(client, mock_url):
    store = InMemoryManagedPlaylistStore()
    result = _sync(client, store, _ids(1, 2, 3))

    assert result["created"] is True and result["applied"] is True
    playlist_id = result["playlist_id"]
    assert client.get_playlist_track_ids(playlist_id) == _ids(1, 2, 3)

    record = store.get_by_spotify_id(playlist_id)
    assert record["generator"] == "test-generator"
    assert record["last_synced"] is not None
    assert json.loads(record["target_snapshots"][0])["track_ids"] == _ids(1, 2, 3)

    obj = client.get_playlist(playlist_id)
    assert obj["name"] == "[SPB] Test Generator"
    assert "Generated by spotify-power-browser" in obj["description"]
    assert "do not edit" in obj["description"]


def test_second_sync_is_an_empty_diff(client, mock_url):
    store = InMemoryManagedPlaylistStore()
    first = _sync(client, store, _ids(1, 2, 3))
    second = _sync(client, store, _ids(1, 2, 3))

    assert second["created"] is False
    assert second["playlist_id"] == first["playlist_id"]
    assert second["diff"].is_empty  # idempotent: second run = empty diff
    assert client.get_playlist_track_ids(first["playlist_id"]) == _ids(1, 2, 3)


def test_sync_applies_adds_and_removes_as_a_diff(client, mock_url):
    store = InMemoryManagedPlaylistStore()
    _sync(client, store, _ids(1, 2, 3))
    result = _sync(client, store, _ids(2, 3, 4))

    assert result["diff"].adds == _ids(4)
    assert result["diff"].removes == _ids(1)
    assert client.get_playlist_track_ids(result["playlist_id"]) == _ids(2, 3, 4)


def test_guard_refuses_playlists_not_recorded_as_managed(client, mock_url):
    # A playlist that exists on Spotify but was NOT created by the sync system
    # (i.e. any hand-made playlist) must be refused before any write.
    foreign = client.create_playlist("mockuser", "my precious hand-made mix")
    client.add_tracks(foreign["id"], _ids(1, 2))

    store = InMemoryManagedPlaylistStore()  # knows nothing about `foreign`
    diff = compute_diff(_ids(1, 2), _ids(9), order_significant=True)
    with pytest.raises(UnmanagedPlaylistError):
        apply_diff(client, store, foreign["id"], diff)

    # ...and nothing was modified.
    assert client.get_playlist_track_ids(foreign["id"]) == _ids(1, 2)


def test_guard_checks_before_even_an_empty_diff(client, mock_url):
    foreign = client.create_playlist("mockuser", "another hand-made one")
    store = InMemoryManagedPlaylistStore()
    with pytest.raises(UnmanagedPlaylistError):
        apply_diff(client, store, foreign["id"], PlaylistDiff())


def test_chunking_handles_more_than_100_targets(client, mock_url):
    # The mock 400s any add/remove call with >100 ids (like Spotify), so a
    # passing 150-track sync proves the client chunked its calls.
    store = InMemoryManagedPlaylistStore()
    target = _ids(*range(150))
    result = _sync(client, store, target)
    assert client.get_playlist_track_ids(result["playlist_id"]) == target

    # And chunked removals on the way back down.
    shrunk = _sync(client, store, _ids(0, 1))
    assert len(shrunk["diff"].removes) == 148
    assert client.get_playlist_track_ids(result["playlist_id"]) == _ids(0, 1)


def test_dry_run_makes_no_writes_anywhere(client, mock_url):
    store = InMemoryManagedPlaylistStore()

    # Dry-run against a missing playlist: nothing created, anywhere.
    result = _sync(client, store, _ids(1, 2), apply=False)
    assert result["applied"] is False and result["playlist_id"] is None
    assert result["diff"].adds == _ids(1, 2)  # the diff is still reported
    assert store.playlists == {}

    # Dry-run against an existing playlist: diff reported, nothing changes.
    applied = _sync(client, store, _ids(1, 2))
    snapshots_before = store.get_by_spotify_id(applied["playlist_id"])["target_snapshots"]
    dry = _sync(client, store, _ids(3, 4), apply=False)
    assert dry["applied"] is False
    assert dry["diff"].adds == _ids(3, 4) and dry["diff"].removes == _ids(1, 2)
    assert client.get_playlist_track_ids(applied["playlist_id"]) == _ids(1, 2)
    assert store.get_by_spotify_id(applied["playlist_id"])["target_snapshots"] == snapshots_before


def test_reorder_rewrites_only_for_order_significant_generators(client, mock_url):
    store = InMemoryManagedPlaylistStore()
    first = _sync(client, store, _ids(1, 2, 3))

    # Same set, new order, order-insignificant: nothing happens.
    unordered = _sync(client, store, _ids(3, 1, 2), order_significant=False)
    assert unordered["diff"].is_empty
    assert client.get_playlist_track_ids(first["playlist_id"]) == _ids(1, 2, 3)

    # Order-significant: full rewrite realizes the generator's order.
    reordered = _sync(client, store, _ids(3, 1, 2), order_significant=True)
    assert reordered["diff"].rewrite is True
    assert client.get_playlist_track_ids(first["playlist_id"]) == _ids(3, 1, 2)


def test_sync_overwrites_manual_duplicates_of_kept_tracks(client, mock_url, sync_log):
    # The stamp promises "changes are overwritten": a duplicate added by hand
    # in the Spotify app must be corrected on the next applied sync, not
    # reported as in-sync forever.
    store = InMemoryManagedPlaylistStore()
    first = _sync(client, store, _ids(1, 2))
    playlist_id = first["playlist_id"]
    client.add_tracks(playlist_id, _ids(1))  # manual edit -> [1, 2, 1]
    assert client.get_playlist_track_ids(playlist_id) == _ids(1, 2, 1)

    result = _sync(client, store, _ids(1, 2))
    assert not result["diff"].is_empty
    assert client.get_playlist_track_ids(playlist_id) == _ids(1, 2)

    # ...and stays in sync afterwards.
    assert _sync(client, store, _ids(1, 2))["diff"].is_empty


def test_sync_with_adds_also_corrects_duplicates_without_false_warning(client, mock_url, sync_log):
    # current [1, 2, 1] -> target [1, 2, 3]: pre-fix this appended 3 only,
    # left the duplicate in place, and logged a false "unplayable ids"
    # warning because len(final) != len(target).
    store = InMemoryManagedPlaylistStore()
    first = _sync(client, store, _ids(1, 2))
    playlist_id = first["playlist_id"]
    client.add_tracks(playlist_id, _ids(1))  # manual edit -> [1, 2, 1]

    sync_log.clear()
    _sync(client, store, _ids(1, 2, 3))
    assert client.get_playlist_track_ids(playlist_id) == _ids(1, 2, 3)
    assert not any("unplayable" in record.message for record in sync_log.records)


def test_401_refreshes_and_retries_once(mock_url):
    refreshed = []
    client = SpotifyPlaylistClient(
        base_url=mock_url, token="expired-token",
        refresh=lambda: refreshed.append(True), reload=lambda: "fresh-token",
    )
    requests.post(f"{mock_url}/_control/config", json={"fail_next_n": 1, "fail_status": 401})
    me = client.get_current_user()  # 401 once -> refresh + reload -> 200
    assert me["id"] == "mockuser"
    assert refreshed == [True]
    assert client._token == "fresh-token"


def test_owner_env_wins_over_me_lookup(client, mock_url, monkeypatch):
    monkeypatch.setenv("PLAYLIST_SYNC_OWNER", "env-owner")
    store = InMemoryManagedPlaylistStore()
    result = _sync(client, store, _ids(1))
    assert client.get_playlist(result["playlist_id"])["owner"]["id"] == "env-owner"
    assert store.get_by_spotify_id(result["playlist_id"])["owner_spotify_user_id"] == "env-owner"
