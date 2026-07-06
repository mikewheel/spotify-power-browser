"""E2E-ish tests for entity mastering (plan 03 T7).

Three layers, each degrading gracefully:
  - mock-service tests fetch the crafted variant twins over HTTP (skip when
    the spotify_mock compose service isn't reachable) and feed them to the
    pure clustering logic;
  - direct catalog checks import mock_spotify.catalog when it's importable
    (host runs; the tests container doesn't mount mock_spotify/, so they skip
    there — the HTTP tests cover the same ground in compose);
  - graph-write tests run behind the neo4j_driver skip fixture.
"""
import pytest
import requests

from application.mastering.cluster import cluster_tracks, track_record_from_api
from application.mastering.overrides import Overrides
from application.mastering.run import write_mastering_result

# Mirrors mock_spotify/catalog.py VARIANTS (kept literal on purpose: the tests
# container doesn't mount mock_spotify/, and drift would fail loudly below).
DELUXE_PAIR_IDS = ("trk000052", "trk000053")
CLEAN_EXPLICIT_TWIN_IDS = ("trk000054", "trk000055")
REMASTER_PAIR_IDS = ("trk000056", "trk000057")
REMIX_TRACK_ID = "trk000058"
ALL_VARIANT_IDS = (
    *DELUXE_PAIR_IDS, *CLEAN_EXPLICIT_TWIN_IDS, *REMASTER_PAIR_IDS, REMIX_TRACK_ID,
)


def _fetch_tracks(mock_base, ids):
    tracks = requests.get(f"{mock_base}/v1/tracks?ids={','.join(ids)}").json()["tracks"]
    assert all(tracks), f"every variant id must resolve in the mock catalog: {ids}"
    return tracks


def _cluster_containing(result, track_id):
    for cluster in result.clusters:
        if any(m.track_id == track_id for m in cluster.members):
            return cluster
    raise AssertionError(f"No cluster contains {track_id}")


# ---------------------------------------------------------------------------
# Mock catalog over HTTP (the shape the crawler actually sees)
# ---------------------------------------------------------------------------

def test_catalog_emits_deterministic_isrcs(mock_base):
    first = _fetch_tracks(mock_base, ("trk000000", "trk000001"))
    second = _fetch_tracks(mock_base, ("trk000000", "trk000001"))
    for a, b in zip(first, second):
        assert a["external_ids"]["isrc"] == b["external_ids"]["isrc"]
    assert first[0]["external_ids"]["isrc"] != first[1]["external_ids"]["isrc"]


def test_liked_songs_pages_carry_isrcs(mock_base):
    page = requests.get(f"{mock_base}/v1/me/tracks?offset=52&limit=7").json()
    for item in page["items"]:
        assert item["track"]["external_ids"]["isrc"]


def test_deluxe_pair_shares_one_isrc(mock_base):
    a, b = _fetch_tracks(mock_base, DELUXE_PAIR_IDS)
    assert a["external_ids"]["isrc"] == b["external_ids"]["isrc"]
    assert a["id"] != b["id"]


def test_clean_explicit_twins_differ_in_isrc_not_title(mock_base):
    a, b = _fetch_tracks(mock_base, CLEAN_EXPLICIT_TWIN_IDS)
    assert a["external_ids"]["isrc"] != b["external_ids"]["isrc"]
    assert a["name"] == b["name"]
    assert a["explicit"] != b["explicit"]
    assert a["artists"][0]["id"] == b["artists"][0]["id"]
    assert abs(a["duration_ms"] - b["duration_ms"]) <= 3000


def test_mock_twins_flow_through_the_identity_ladder(mock_base):
    """The T7 deliverable: crafted variants -> track records -> clusters."""
    tracks = _fetch_tracks(mock_base, ALL_VARIANT_IDS)
    records = [track_record_from_api(t) for t in tracks]
    result = cluster_tracks(records)

    # (a) deluxe re-release pair: ISRC tier, Song id IS the shared ISRC
    deluxe = _cluster_containing(result, DELUXE_PAIR_IDS[0])
    assert {m.track_id for m in deluxe.members} == set(DELUXE_PAIR_IDS)
    assert deluxe.song_id == "USMCK2600052"
    assert all(m.method == "isrc" and m.confidence == 1.0 for m in deluxe.members)

    # (b) clean/explicit twins: heuristic tier, kinds assigned from the flag
    twins = _cluster_containing(result, CLEAN_EXPLICIT_TWIN_IDS[0])
    assert {m.track_id for m in twins.members} == set(CLEAN_EXPLICIT_TWIN_IDS)
    assert {m.kind for m in twins.members} == {"explicit", "clean"}
    assert all(m.method == "heuristic" for m in twins.members)
    assert twins.song_id.startswith("song:")  # two ISRCs -> hash, never a Spotify id

    # (c) remaster folds into the original; the strip is recorded as the kind
    remaster = _cluster_containing(result, REMASTER_PAIR_IDS[0])
    assert {m.track_id for m in remaster.members} == set(REMASTER_PAIR_IDS)
    kinds = {m.track_id: m.kind for m in remaster.members}
    assert kinds[REMASTER_PAIR_IDS[0]] == "remaster"
    assert kinds[REMASTER_PAIR_IDS[1]] == "canonical"

    # (d) the remix stands alone... and points at its parent Song
    remix = _cluster_containing(result, REMIX_TRACK_ID)
    assert {m.track_id for m in remix.members} == {REMIX_TRACK_ID}
    assert remix.members[0].kind == "remix"
    assert [
        (e.remix_song_id, e.parent_song_id) for e in result.remix_edges
    ] == [(remix.song_id, remaster.song_id)]

    # every variant landed in exactly one cluster
    assigned = sorted(m.track_id for c in result.clusters for m in c.members)
    assert assigned == sorted(ALL_VARIANT_IDS)


# ---------------------------------------------------------------------------
# Direct catalog checks (host runs only — skips where mock_spotify isn't
# importable; the HTTP tests above cover compose)
# ---------------------------------------------------------------------------

def test_catalog_module_variants_match_this_files_ids():
    catalog = pytest.importorskip("mock_spotify.catalog")
    assert catalog.DELUXE_PAIR_IDS == DELUXE_PAIR_IDS
    assert catalog.CLEAN_EXPLICIT_TWIN_IDS == CLEAN_EXPLICIT_TWIN_IDS
    assert catalog.REMASTER_PAIR_IDS == REMASTER_PAIR_IDS
    assert catalog.REMIX_TRACK_ID == REMIX_TRACK_ID
    # Variants live inside the default catalog so liked-songs crawls reach them.
    assert max(catalog.VARIANTS) < catalog.N_TRACKS


def test_catalog_module_twins_cluster_without_http():
    catalog = pytest.importorskip("mock_spotify.catalog")
    records = [
        track_record_from_api(catalog.get_by_id("tracks", tid))
        for tid in ALL_VARIANT_IDS
    ]
    result = cluster_tracks(records)
    assert _cluster_containing(result, DELUXE_PAIR_IDS[0]).song_id == "USMCK2600052"
    assert len(result.remix_edges) == 1


# ---------------------------------------------------------------------------
# Neo4j write layer (skips when Neo4j isn't reachable)
# ---------------------------------------------------------------------------

MARKER = "MSTTEST"


@pytest.fixture
def graph(neo4j_driver):
    """Purge this module's distinctively-marked nodes before and after."""
    def purge():
        neo4j_driver.execute_query(
            f"MATCH (n) WHERE n.uri CONTAINS '{MARKER}' DETACH DELETE n")
        neo4j_driver.execute_query(
            f"MATCH (s:Song) WHERE s.id CONTAINS '{MARKER}' DETACH DELETE s")
    purge()
    yield neo4j_driver
    purge()


def _delete_songs(driver, result):
    ids = [c.song_id for c in result.clusters]
    driver.execute_query("MATCH (s:Song) WHERE s.id IN $ids DETACH DELETE s", ids=ids)


def _seed_graph_tracks(driver, tracks):
    """Seed Track/Artist nodes directly (mastering-layer tests exercise the
    mastering Cyphers, not the crawl insert path — that's covered above)."""
    records = [track_record_from_api(t) | {"uri": t["uri"]} for t in tracks]
    driver.execute_query(
        "UNWIND $records AS record "
        "MERGE (t:Track {uri: record.uri}) "
        "SET t.id = record.id, t.name = record.name, t.isrc = record.isrc, "
        "    t.linked_from_id = record.linked_from_id, "
        "    t.duration_ms = record.duration_ms, t.explicit = record.explicit, "
        "    t.is_local = false "
        "WITH record, t UNWIND range(0, size(record.artist_ids) - 1) AS idx "
        "MERGE (ar:Artist {uri: 'spotify:artist:' + record.artist_ids[idx] + 'MSTTEST'}) "
        "SET ar.id = record.artist_ids[idx], ar.name = record.artist_names[idx] "
        "MERGE (t)<-[:CREATED]-(ar)",
        records=records,
    )


def test_track_insert_persists_and_refreshes_enrichment_fields(graph, make):
    from application.response_handlers.tracks.several_tracks import GetSeveralTracksResponseHandler

    def stored():
        recs, _, _ = graph.execute_query(
            "MATCH (t:Track {id: 'trkMSTTEST1'}) "
            "RETURN t.isrc AS isrc, t.album_type AS album_type, t.linked_from_id AS lnk, "
            "t.artist_ids AS artist_ids")
        return recs[0]["isrc"], recs[0]["album_type"], recs[0]["lnk"], recs[0]["artist_ids"]

    track = make.track("MSTTEST1", isrc=f"{MARKER}ISRC1", linked_from_id=f"{MARKER}LNK1")
    GetSeveralTracksResponseHandler(None, 0, {"tracks": [track]}).write_to_neo4j(driver=graph)
    assert stored() == (f"{MARKER}ISRC1", "album", f"{MARKER}LNK1", ["artMSTTEST1"])

    # A payload WITHOUT the enrichment fields must not erase them (coalesce).
    bare = make.track("MSTTEST1", isrc="")
    bare["album"]["album_type"] = None
    GetSeveralTracksResponseHandler(None, 0, {"tracks": [bare]}).write_to_neo4j(driver=graph)
    assert stored() == (f"{MARKER}ISRC1", "album", f"{MARKER}LNK1", ["artMSTTEST1"])

    # A payload WITH a fresh isrc refreshes it (the backfill path: ON MATCH SET).
    refreshed = make.track("MSTTEST1", isrc=f"{MARKER}ISRC1B")
    GetSeveralTracksResponseHandler(None, 0, {"tracks": [refreshed]}).write_to_neo4j(driver=graph)
    assert stored()[0] == f"{MARKER}ISRC1B"


def test_liked_songs_insert_persists_enrichment_fields(graph, make):
    from application.response_handlers.me.my_liked_songs import LikedSongsPlaylistResponseHandler

    def stored():
        recs, _, _ = graph.execute_query(
            "MATCH (t:Track {id: 'trkMSTTEST2'}) RETURN t.isrc AS isrc, t.album_type AS album_type")
        return recs[0]["isrc"], recs[0]["album_type"]

    track = make.track("MSTTEST2", isrc=f"{MARKER}ISRC2")
    LikedSongsPlaylistResponseHandler(None, 0, make.liked_page([track])).write_to_neo4j(driver=graph)
    assert stored() == (f"{MARKER}ISRC2", "album")

    # ON MATCH: a payload without external_ids must not erase the isrc...
    bare = make.track("MSTTEST2", isrc="")
    LikedSongsPlaylistResponseHandler(None, 0, make.liked_page([bare])).write_to_neo4j(driver=graph)
    assert stored() == (f"{MARKER}ISRC2", "album")

    # ...while a payload with a fresh one refreshes it (the backfill path).
    refreshed = make.track("MSTTEST2", isrc=f"{MARKER}ISRC2B")
    LikedSongsPlaylistResponseHandler(None, 0, make.liked_page([refreshed])).write_to_neo4j(driver=graph)
    assert stored()[0] == f"{MARKER}ISRC2B"


def test_fetch_query_prefers_stored_artist_ids_with_edge_fallback(graph, make):
    from application.mastering.run import fetch_track_records

    artists = [make.artist("MSTTESTzz"), make.artist("MSTTESTaa")]
    track = make.track("MSTTEST3", artists=artists, isrc=f"{MARKER}ISRC3")
    _seed_graph_tracks(graph, [track])

    def fetch_one():
        records = [r for r in fetch_track_records(graph) if r["id"] == "trkMSTTEST3"]
        assert len(records) == 1
        return records[0]

    # Legacy node (no t.artist_ids): sorted CREATED-edge ids as the fallback.
    record = fetch_one()
    assert record["isrc"] == f"{MARKER}ISRC3"
    assert record["artist_ids"] == ["artMSTTESTaa", "artMSTTESTzz"]  # sorted

    # Once the insert/backfill stored the credit-ordered list, it wins.
    graph.execute_query(
        "MATCH (t:Track {id: 'trkMSTTEST3'}) SET t.artist_ids = $ids",
        ids=["artMSTTESTzz", "artMSTTESTaa"])
    assert fetch_one()["artist_ids"] == ["artMSTTESTzz", "artMSTTESTaa"]


def test_write_mastering_result_is_idempotent_and_repoints(graph, make):
    artist = make.artist("MSTTEST4")
    tracks = [
        make.track("MSTTEST4a", artists=[artist], isrc=f"{MARKER}ISRC4A"),
        make.track("MSTTEST4b", artists=[artist], isrc=f"{MARKER}ISRC4B"),
    ]
    tracks[0]["name"] = tracks[1]["name"] = "Gutter Anthem MSTTEST"
    tracks[0]["explicit"] = True
    _seed_graph_tracks(graph, tracks)

    records = [track_record_from_api(t) for t in tracks]
    merged = cluster_tracks(records)
    split = cluster_tracks(records, overrides=Overrides(splits=[["trkMSTTEST4b"]]))
    try:
        write_mastering_result(merged, graph)
        write_mastering_result(merged, graph)  # idempotent re-run

        recs, _, _ = graph.execute_query(
            "MATCH (t:Track)-[v:VERSION_OF]->(s:Song) WHERE t.id STARTS WITH 'trkMSTTEST4' "
            "RETURN t.id AS tid, s.id AS sid, v.kind AS kind, v.method AS method, "
            "v.confidence AS confidence ORDER BY tid")
        assert len(recs) == 2  # exactly ONE VERSION_OF each, even after a re-run
        assert recs[0]["sid"] == recs[1]["sid"]
        assert {r["kind"] for r in recs} == {"explicit", "clean"}
        assert all(r["method"] == "heuristic" and r["confidence"] == 0.85 for r in recs)

        # An override lands: the next run RE-POINTS the edges (no accumulation,
        # and the now-empty Song is left alone — never deleted).
        write_mastering_result(split, graph)
        recs, _, _ = graph.execute_query(
            "MATCH (t:Track)-[v:VERSION_OF]->(s:Song) WHERE t.id STARTS WITH 'trkMSTTEST4' "
            "RETURN t.id AS tid, s.id AS sid ORDER BY tid")
        assert len(recs) == 2
        assert recs[0]["sid"] != recs[1]["sid"]

        old_song = [c.song_id for c in merged.clusters]
        recs, _, _ = graph.execute_query(
            "MATCH (s:Song) WHERE s.id IN $ids RETURN count(s) AS c", ids=old_song)
        assert recs[0]["c"] == len(old_song)  # orphaned, not deleted
    finally:
        _delete_songs(graph, merged)
        _delete_songs(graph, split)


def test_remix_of_edge_written(graph, make):
    artist = make.artist("MSTTEST5")
    parent = make.track("MSTTEST5a", artists=[artist], isrc=f"{MARKER}ISRC5A")
    remix = make.track("MSTTEST5b", artists=[artist], isrc=f"{MARKER}ISRC5B")
    parent["name"] = "Cathedral MSTTEST"
    remix["name"] = "Cathedral MSTTEST (Nightcrawler Remix)"
    _seed_graph_tracks(graph, [parent, remix])

    result = cluster_tracks([track_record_from_api(t) for t in (parent, remix)])
    assert result.remix_edges
    try:
        write_mastering_result(result, graph)
        recs, _, _ = graph.execute_query(
            "MATCH (remix:Song)-[r:REMIX_OF]->(parent:Song) "
            "WHERE remix.id = $rid AND parent.id = $pid RETURN r.confidence AS confidence",
            rid=result.remix_edges[0].remix_song_id,
            pid=result.remix_edges[0].parent_song_id)
        assert recs and recs[0]["confidence"] == 0.9
    finally:
        _delete_songs(graph, result)


def test_song_uniqueness_constraint_applies(neo4j_driver):
    from application.graph_database.initialize_database_environment import (
        apply_uniqueness_constraints,
    )
    apply_uniqueness_constraints(neo4j_driver)
    recs, _, _ = neo4j_driver.execute_query(
        "SHOW CONSTRAINTS YIELD name WHERE name = 'song_id_uniqueness' RETURN name")
    assert recs
