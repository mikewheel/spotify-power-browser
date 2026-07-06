"""Multiplayer E2E (plan 06): two users' likes crawled sequentially through
the REAL handler + Cypher into one graph, then the overlap pack returns the
constructed intersection. Plus the 0001 migration against a throwaway Neo4j.

Needs the mock service and Neo4j (skips otherwise). The migration tests
additionally skip on a non-empty (shared) graph: migration 0001/0002 touch
EVERY legacy-flagged track by design, which is only safe on a throwaway DB.
"""
from pathlib import Path

import pytest
import requests

from application.config import APPLICATION_DIR
from application.graph_database.migrations.run import (
    build_standard_params, load_migration_statements, run_migration,
)
from application.response_handlers.me.my_liked_songs import LikedSongsPlaylistResponseHandler
from mock_spotify.catalog import (
    MOCK_USER_2_ID,
    N_TRACKS,
    USER2_EXCLUSIVE_TRACK_IDS,
    user2_liked_track_ids,
)

OVERLAP_DIR = APPLICATION_DIR / "graph_database" / "queries" / "overlap"

USER_1 = "mockuser"
USER_2 = MOCK_USER_2_ID

# Purge exactly what the mock can produce + the two mock users (safe on a
# shared graph -- distinctive 6-digit functional ids, same as the plan-01 E2E).
PURGE_MOCK_NODES = (
    "MATCH (n) WHERE n.uri =~ "
    "'spotify:(track:(trk|dtk)|album:(alb|dal)|artist:(art|fra))[0-9]{6}' "
    "DETACH DELETE n"
)
PURGE_MOCK_GENRES = "MATCH (g:Genre) WHERE g.name =~ 'genre-[0-9]' DETACH DELETE g"
PURGE_MOCK_USERS = f"MATCH (u:User) WHERE u.id IN ['{USER_1}', '{USER_2}'] DETACH DELETE u"


def _overlap_query(name):
    return (OVERLAP_DIR / f"{name}.cypher").read_text().strip().rstrip(";")


def _crawl_likes(mock_base, graph, user_id, bearer_token):
    """Page through /v1/me/tracks as one user and persist every page through
    the real handler + Cypher (sequentially — like the real pipeline)."""
    url = f"{mock_base}/v1/me/tracks?offset=0&limit=7"
    while url:
        page = requests.get(url, headers={"Authorization": f"Bearer {bearer_token}"},
                            timeout=5).json()
        LikedSongsPlaylistResponseHandler(url, 0, page, user_id=user_id) \
            .write_to_neo4j(driver=graph)
        url = page["next"]


@pytest.fixture
def two_user_graph(mock_base, neo4j_driver):
    def purge():
        neo4j_driver.execute_query(PURGE_MOCK_NODES)
        neo4j_driver.execute_query(PURGE_MOCK_GENRES)
        neo4j_driver.execute_query(PURGE_MOCK_USERS)
    purge()
    _crawl_likes(mock_base, neo4j_driver, USER_1, "mock-access-token")
    _crawl_likes(mock_base, neo4j_driver, USER_2, f"mock-access-token-{USER_2}")
    yield neo4j_driver
    purge()


def test_shared_catalog_nodes_are_not_duplicated(two_user_graph):
    overlap_ids = [t for t in user2_liked_track_ids() if t.startswith("trk")]
    records, _, _ = two_user_graph.execute_query(
        "MATCH (t:Track) WHERE t.id IN $ids "
        "RETURN t.id AS id, count(t) AS copies ORDER BY id",
        ids=overlap_ids)
    assert len(records) == len(overlap_ids)          # every shared track exists
    assert all(r["copies"] == 1 for r in records)    # exactly once — MERGE joined them


def test_per_user_liked_rels_are_distinct(two_user_graph):
    records, _, _ = two_user_graph.execute_query(
        "MATCH (u:User)-[l:LIKED]->(:Track) WHERE u.id IN [$a, $b] "
        "RETURN u.id AS user, count(l) AS likes, "
        "collect(DISTINCT l.added_at)[0] AS added_at ORDER BY user",
        a=USER_1, b=USER_2)
    by_user = {r["user"]: r for r in records}
    assert by_user[USER_1]["likes"] == N_TRACKS
    assert by_user[USER_2]["likes"] == len(user2_liked_track_ids())
    # per-user provenance: each user's own library timestamp, not a shared one
    assert by_user[USER_1]["added_at"] == "2021-01-01T00:00:00Z"
    assert by_user[USER_2]["added_at"] == "2023-05-05T00:00:00Z"

    # a shared track carries exactly one LIKED per user
    records, _, _ = two_user_graph.execute_query(
        "MATCH (u:User)-[l:LIKED]->(t:Track {id: 'trk000025'}) "
        "RETURN u.id AS user, count(l) AS c ORDER BY user")
    assert [(r["user"], r["c"]) for r in records] == [(USER_1, 1), (USER_2, 1)]


def test_user2_exclusives_are_theirs_alone(two_user_graph):
    records, _, _ = two_user_graph.execute_query(
        "MATCH (u:User)-[:LIKED]->(t:Track) WHERE t.id IN $ids "
        "RETURN DISTINCT u.id AS user", ids=list(USER2_EXCLUSIVE_TRACK_IDS))
    assert [r["user"] for r in records] == [USER_2]


def test_shared_artists_query_returns_the_constructed_intersection(two_user_graph):
    records, _, _ = two_user_graph.execute_query(
        _overlap_query("shared_artists_weighted"), a=USER_1, b=USER_2)
    shared = {r["artist_id"]: r for r in records}
    assert shared  # tracks 20..39 credit artists both users share
    # trk000025's performing artist (art000010: 25 % 15) is definitionally shared
    assert "art000010" in shared
    row = shared["art000010"]
    assert row["a_likes"] >= row["b_likes"] >= 1          # user 1 likes strictly more
    assert row["mutual_depth"] == row["b_likes"]          # min() of the two


def test_jaccard_reflects_partial_overlap(two_user_graph):
    records, _, _ = two_user_graph.execute_query(
        _overlap_query("liked_artist_jaccard"), a=USER_1, b=USER_2)
    row = records[0]
    assert row["intersection_size"] > 0                    # real overlap...
    assert row["intersection_size"] < row["union_size"]    # ...but not identity
    assert 0.0 < row["jaccard"] < 1.0


def test_a_loves_b_never_heard_finds_user2_exclusive_artist(two_user_graph):
    # dtk010001 credits frontier artist fra000001 — liked by user 2 only.
    records, _, _ = two_user_graph.execute_query(
        _overlap_query("a_loves_b_never_heard"), a=USER_2, b=USER_1, min_likes=1)
    artists = {r["artist_id"] for r in records}
    assert "fra000001" in artists
    # ...and nothing user 1 likes can appear on user 2's exclusive list.
    records, _, _ = two_user_graph.execute_query(
        "MATCH (:User {id: $a})-[:LIKED]->(:Track)<-[:CREATED]-(ar:Artist) "
        "RETURN collect(DISTINCT ar.id) AS ids", a=USER_1)
    assert not artists & set(records[0]["ids"])


def test_bridge_playlist_returns_only_tracks_neither_user_liked(two_user_graph):
    records, _, _ = two_user_graph.execute_query(
        _overlap_query("bridge_playlist"), a=USER_1, b=USER_2, min_bridges=1)
    track_ids = [r["track_id"] for r in records]
    if not track_ids:
        pytest.skip("liked-songs-only crawl has no unliked frontier tracks "
                    "(a discography crawl enriches this) — nothing to assert")
    liked, _, _ = two_user_graph.execute_query(
        "MATCH (u:User)-[:LIKED]->(t:Track) WHERE u.id IN [$a, $b] "
        "RETURN collect(DISTINCT t.id) AS ids", a=USER_1, b=USER_2)
    assert not set(track_ids) & set(liked[0]["ids"])


###
# Migration 0001/0002 (throwaway-DB only: they touch every legacy-flagged node)
###

MIGRATION_MARK = "MIGTEST"


@pytest.fixture
def throwaway_graph(neo4j_driver):
    records, _, _ = neo4j_driver.execute_query(
        "MATCH (t:Track) WHERE t.liked_songs = true "
        f"AND NOT t.uri CONTAINS '{MIGRATION_MARK}' RETURN count(t) AS c")
    if records[0]["c"] > 0:
        pytest.skip("graph holds real legacy-flagged tracks; migration tests "
                    "only run against a throwaway Neo4j")
    purge = (f"MATCH (n) WHERE (n.uri IS NOT NULL AND n.uri CONTAINS '{MIGRATION_MARK}') "
             f"OR (n:User AND n.id CONTAINS '{MIGRATION_MARK}') "
             f"OR (n:ManagedPlaylist AND n.spotify_id CONTAINS '{MIGRATION_MARK}') "
             "DETACH DELETE n")
    neo4j_driver.execute_query(purge)
    yield neo4j_driver
    neo4j_driver.execute_query(purge)


def test_migration_0001_lifts_flags_into_user_liked_rels(throwaway_graph):
    me = f"{MIGRATION_MARK}-user"
    throwaway_graph.execute_query(
        f"CREATE (:Track {{uri: 'spotify:track:{MIGRATION_MARK}1', id: '{MIGRATION_MARK}1', "
        f"liked_songs: true, date_added_to_liked_songs: '2020-02-02T00:00:00Z'}}), "
        f"(:Track {{uri: 'spotify:track:{MIGRATION_MARK}2', id: '{MIGRATION_MARK}2'}}), "
        f"(:ManagedPlaylist {{spotify_id: '{MIGRATION_MARK}-pl', "
        f"owner_spotify_user_id: '{me}'}})")

    params = build_standard_params(me=me, display_name="Mig Test")
    run_migration(throwaway_graph, "0001_multiplayer_ownership", params)

    records, _, _ = throwaway_graph.execute_query(
        "MATCH (u:User {id: $me})-[l:LIKED]->(t:Track) "
        "RETURN t.id AS id, l.added_at AS added_at", me=me)
    assert [(r["id"], r["added_at"]) for r in records] \
        == [(f"{MIGRATION_MARK}1", "2020-02-02T00:00:00Z")]

    # plan 08's ManagedPlaylist got re-linked to its owner
    records, _, _ = throwaway_graph.execute_query(
        "MATCH (:User {id: $me})-[:HAS_MANAGED]->(p:ManagedPlaylist) "
        "RETURN p.spotify_id AS s", me=me)
    assert records and records[0]["s"] == f"{MIGRATION_MARK}-pl"

    # legacy props KEPT (one-release rollback window)
    records, _, _ = throwaway_graph.execute_query(
        "MATCH (t:Track {id: $id}) RETURN t.liked_songs AS flag", id=f"{MIGRATION_MARK}1")
    assert records[0]["flag"] is True

    # idempotent: run again, still exactly one LIKED rel
    run_migration(throwaway_graph, "0001_multiplayer_ownership", params)
    records, _, _ = throwaway_graph.execute_query(
        "MATCH (:User {id: $me})-[l:LIKED]->() RETURN count(l) AS c", me=me)
    assert records[0]["c"] == 1


def test_migration_runner_refuses_the_0002_stub_without_force(throwaway_graph):
    with pytest.raises(RuntimeError, match="DO NOT RUN"):
        run_migration(throwaway_graph, "0002_drop_legacy_liked_props",
                      build_standard_params(me=f"{MIGRATION_MARK}-user"))


def test_migration_loader_rejects_unknown_names():
    with pytest.raises(FileNotFoundError):
        load_migration_statements("0999_does_not_exist")


def test_migration_loader_splits_0001_into_three_statements():
    _, _, statements = load_migration_statements("0001_multiplayer_ownership")
    assert len(statements) == 3
    assert statements[0].lstrip("/ \n").startswith("Migration 0001")  # comments intact
    joined = " ".join(statements)
    assert ":LIKED" in joined and ":HAS_MANAGED" in joined
