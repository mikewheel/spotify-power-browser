"""Generator tests (plan 08 T4).

Param-shape tests are pure and run everywhere; query-execution and
ManagedPlaylist round-trip tests use the neo4j_driver fixture and skip when
Neo4j isn't reachable. Distinctive CYTESTPL ids keep cleanup surgical, and
graph-global membership assertions self-skip on a non-empty (shared) graph.
"""
import json
from types import SimpleNamespace

import pytest

from application.playlists import generators
from application.playlists.generators import (
    GeneratorSpec, build_generator, run_generator,
)
from application.playlists.model import Neo4jManagedPlaylistStore, params_hash

MARK = "CYTESTPL"


###
# Param shapes (pure)
###

def test_adjacent_discoveries_spec_shape():
    spec = build_generator("adjacent-discoveries")
    assert spec.key == "adjacent-discoveries"
    assert spec.playlist_name == "[SPB] Adjacent Discoveries"
    assert spec.identity_params == {}  # tuning knobs don't fork playlists
    assert spec.order_significant is True
    assert set(spec.params) == {"max_popularity", "min_bridges"}
    assert "$max_popularity" in spec.query and "$min_bridges" in spec.query
    assert "track_id" in spec.query and "popularity_unknown" in spec.query


def test_adjacent_discoveries_tuning_knobs_flow_into_params():
    spec = build_generator("adjacent-discoveries", max_popularity=25, min_bridges=3)
    assert spec.params == {"max_popularity": 25, "min_bridges": 3}


def test_adjacent_discoveries_rejects_positional_args():
    with pytest.raises(ValueError):
        build_generator("adjacent-discoveries", ["stray"])


def test_exploration_queue_spec_shape():
    spec = build_generator("exploration-queue", ["Four", "Tet"])
    assert spec.key == "exploration-queue"
    assert spec.playlist_name == "[SPB] Exploration Queue - Four Tet"
    assert spec.identity_params == {"artist_name": "four tet"}  # one playlist per artist
    assert spec.params == {"artist_name": "Four Tet"}
    assert spec.order_significant is True
    assert "$artist_name" in spec.query


def test_exploration_queue_identity_is_case_insensitive():
    a = build_generator("exploration-queue", ["Four", "Tet"])
    b = build_generator("exploration-queue", ["four", "tet"])
    assert params_hash(a.identity_params) == params_hash(b.identity_params)


def test_exploration_queue_requires_an_artist():
    with pytest.raises(ValueError):
        build_generator("exploration-queue", [])


def test_unknown_generator_raises():
    with pytest.raises(ValueError):
        build_generator("time-capsule", ["2019"])


def test_candidates_query_is_kept_verbatim_from_plan_01():
    # The reference file must keep plan 01 §Design's exact shape (the tracks
    # projection derives from it; plan 01's implementation will unify here).
    with open(generators.PLAYLIST_QUERIES_DIR / "adjacent_discoveries_candidates.cypher") as f:
        text = f.read()
    assert "RETURN cand.name, cand.popularity, cand.followers, bridges, via" in text
    assert "ORDER BY bridges DESC, cand.popularity ASC LIMIT 50" in text


def test_run_generator_dedupes_and_counts_unknown_popularity():
    rows = [
        {"track_id": "trk1", "artist_name": "A", "popularity_unknown": True},
        {"track_id": "trk2", "artist_name": "B", "popularity_unknown": False},
        {"track_id": "trk1", "artist_name": "A", "popularity_unknown": True},  # dupe
        {"track_id": None, "artist_name": "C", "popularity_unknown": False},   # unresolved
    ]
    driver = SimpleNamespace(execute_query=lambda q, database_=None, **params: (rows, None, None))
    spec = GeneratorSpec(key="stub", display_name="stub", playlist_name="[SPB] Stub",
                         query="RETURN 1", params={})
    track_ids, unknown = run_generator(driver, spec)
    assert track_ids == ["trk1", "trk2"]
    assert unknown == 1  # distinct artists, not rows


###
# Against a real Neo4j (skips when unreachable)
###

@pytest.fixture
def seeded_graph(neo4j_driver):
    purge = f"MATCH (n) WHERE n.uri CONTAINS '{MARK}' OR n.spotify_id CONTAINS '{MARK}' DETACH DELETE n"
    neo4j_driver.execute_query(purge)

    def _node(label, ident, **props):
        assignments = ", ".join(f"n.{key} = ${key}" for key in props)
        neo4j_driver.execute_query(
            f"MERGE (n:{label} {{uri: $uri}}) SET n.id = $id" + (f", {assignments}" if assignments else ""),
            uri=f"spotify:{label.lower()}:{ident}", id=ident, **props,
        )

    def _rel(from_label, from_id, rel, to_label, to_id):
        neo4j_driver.execute_query(
            f"MATCH (a:{from_label} {{id: $from_id}}), (b:{to_label} {{id: $to_id}}) "
            f"MERGE (a)-[:{rel}]->(b)",
            from_id=from_id, to_id=to_id,
        )

    # --- adjacent-discoveries scenario ---
    # Liked artists M1/M2 with liked tracks; candidates who co-created tracks
    # with them: CAND-NULL (2 bridges, null popularity), CAND-POP10 (2 bridges,
    # popularity 10), CAND-POP90 (2 bridges but too popular), CAND-1BRIDGE.
    for m in (f"{MARK}-M1", f"{MARK}-M2"):
        _node("Artist", m, name=m)
        liked = f"{m}-LIKED"
        _node("Track", liked, name=liked, liked_songs=True)
        _rel("Artist", m, "CREATED", "Track", liked)

    def _candidate(cand_id, bridges, popularity=None):
        props = {"name": cand_id}
        if popularity is not None:
            props["popularity"] = popularity
        _node("Artist", cand_id, **props)
        for i in range(bridges):
            collab = f"{cand_id}-COLLAB-{i}"
            _node("Track", collab, name=collab)
            _rel("Artist", cand_id, "CREATED", "Track", collab)
            _rel("Artist", f"{MARK}-M{i + 1}", "CREATED", "Track", collab)
        # A non-liked solo track that sorts first -> the representative pick.
        solo = f"{cand_id}-A-SOLO"
        _node("Track", solo, name=solo)
        _rel("Artist", cand_id, "CREATED", "Track", solo)

    _candidate(f"{MARK}-CAND-NULL", bridges=2)                 # unknown popularity
    _candidate(f"{MARK}-CAND-POP10", bridges=2, popularity=10)
    _candidate(f"{MARK}-CAND-POP90", bridges=2, popularity=90)  # over the cap
    _candidate(f"{MARK}-CAND-1BRIDGE", bridges=1)               # under min_bridges

    # --- exploration-queue scenario ---
    # Queue artist with one fully-unliked album (2020), an older unliked album
    # (2018), and an album that contains a liked track (excluded).
    queue_artist = f"{MARK} Queue Artist"
    _node("Artist", f"{MARK}-QA", name=queue_artist)
    albums = [
        (f"{MARK}-AL-2020", "2020-05-01", [f"{MARK}-Q-2020-A", f"{MARK}-Q-2020-B"], False),
        (f"{MARK}-AL-2018", "2018-01-01", [f"{MARK}-Q-2018-A"], False),
        (f"{MARK}-AL-LIKED", "2019-06-01", [f"{MARK}-Q-LIKED-A"], True),
    ]
    for album_id, release_date, track_ids, liked in albums:
        _node("Album", album_id, name=album_id, release_date=release_date)
        _rel("Artist", f"{MARK}-QA", "CREATED", "Album", album_id)
        for track_id in track_ids:
            _node("Track", track_id, name=track_id, **({"liked_songs": True} if liked else {}))
            _rel("Album", album_id, "CONTAINS", "Track", track_id)
            _rel("Artist", f"{MARK}-QA", "CREATED", "Track", track_id)

    yield neo4j_driver
    neo4j_driver.execute_query(purge)


def _graph_is_shared(driver, expected_artists=8):
    """True when the graph holds more than this module's seed (a real library);
    graph-global membership assertions only hold on a throwaway DB."""
    records, _, _ = driver.execute_query("MATCH (a:Artist) RETURN count(a) AS n")
    return records[0]["n"] > expected_artists


def test_adjacent_discoveries_executes_and_respects_params(seeded_graph):
    spec = build_generator("adjacent-discoveries")
    track_ids, _ = run_generator(seeded_graph, spec)
    assert len(track_ids) <= 50
    assert len(track_ids) == len(set(track_ids))  # deduped

    impossible = build_generator("adjacent-discoveries", min_bridges=10 ** 6)
    track_ids, unknown = run_generator(seeded_graph, impossible)
    assert track_ids == [] and unknown == 0  # params actually bind


def test_adjacent_discoveries_ranking_and_null_popularity_flag(seeded_graph):
    if _graph_is_shared(seeded_graph):
        pytest.skip("shared graph: membership assertions only hold on a throwaway DB")

    spec = build_generator("adjacent-discoveries")  # max_popularity=40, min_bridges=2
    track_ids, unknown = run_generator(seeded_graph, spec)

    # Both 2-bridge candidates under the cap contribute their non-liked solo
    # track; known popularity outranks unknown at equal bridges (nulls last);
    # the popularity-90 and 1-bridge candidates are out.
    assert track_ids == [f"{MARK}-CAND-POP10-A-SOLO", f"{MARK}-CAND-NULL-A-SOLO"]
    assert unknown == 1  # CAND-NULL was included but flagged


def test_exploration_queue_flattens_unliked_albums_in_release_order(seeded_graph):
    # Safe on a shared graph: scoped to the distinctive seeded artist name.
    spec = build_generator("exploration-queue", [MARK, "Queue", "Artist"])
    track_ids, unknown = run_generator(seeded_graph, spec)
    assert track_ids == [
        f"{MARK}-Q-2018-A",          # 2018 album first (release-date order)
        f"{MARK}-Q-2020-A",          # then the 2020 album, tracks in id order
        f"{MARK}-Q-2020-B",
    ]  # the album containing a liked track is excluded entirely
    assert unknown == 1  # seeded queue artist has no popularity -> flagged


def test_exploration_queue_matches_artist_case_insensitively(seeded_graph):
    spec = build_generator("exploration-queue", [MARK.lower(), "queue", "artist"])
    track_ids, _ = run_generator(seeded_graph, spec)
    assert track_ids and all(MARK in track_id for track_id in track_ids)


def test_managed_playlist_constraint_applies(neo4j_driver):
    from application.graph_database.initialize_database_environment import (
        apply_uniqueness_constraints,
    )
    apply_uniqueness_constraints(neo4j_driver)
    records, _, _ = neo4j_driver.execute_query("SHOW CONSTRAINTS YIELD name RETURN name")
    assert "managed_playlist_spotify_id_uniqueness" in {r["name"] for r in records}


def test_managed_playlist_round_trip_and_snapshot_window(neo4j_driver):
    purge = f"MATCH (p:ManagedPlaylist) WHERE p.spotify_id CONTAINS '{MARK}' DETACH DELETE p"
    neo4j_driver.execute_query(purge)
    store = Neo4jManagedPlaylistStore(neo4j_driver)
    playlist_id = f"{MARK}-PL1"
    hash_value = params_hash({"artist_name": "four tet"})

    try:
        store.record_created(playlist_id, "exploration-queue", hash_value,
                             "[SPB] Exploration Queue - Four Tet", "mbw")

        by_generator = store.get_by_generator("exploration-queue", hash_value)
        assert by_generator["spotify_id"] == playlist_id
        assert by_generator["owner_spotify_user_id"] == "mbw"
        assert by_generator["last_synced"] is None

        assert store.get_by_spotify_id(playlist_id)["name"] == "[SPB] Exploration Queue - Four Tet"
        assert store.get_by_spotify_id(f"{MARK}-UNKNOWN") is None  # the guard's source of truth

        for n in range(4):
            store.record_sync(playlist_id, [f"trk{n}"])
        records, _, _ = neo4j_driver.execute_query(
            "MATCH (p:ManagedPlaylist {spotify_id: $spotify_id}) "
            "RETURN p.last_synced AS last_synced, p.target_snapshots AS snapshots",
            spotify_id=playlist_id,
        )
        assert records[0]["last_synced"] is not None
        snapshots = [json.loads(s) for s in records[0]["snapshots"]]
        assert [s["track_ids"] for s in snapshots] == [["trk3"], ["trk2"], ["trk1"]]
    finally:
        neo4j_driver.execute_query(purge)
