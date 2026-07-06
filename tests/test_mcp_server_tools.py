"""MCP tool implementations against a real Neo4j (skips when unreachable).

Seeds a tiny self-contained collab graph (distinctive MCPTEST uris, purged
around each test):

  Seed One --CREATED--> Liked A (liked_songs)          [in my taste]
  Seed Two --CREATED--> Liked B (liked_songs)          [in my taste]
  Seed One + Candidate --CREATED--> Collab A (not liked)
  Seed Two + Candidate --CREATED--> Collab B (not liked)

So "Candidate" bridges to my taste through TWO of my artists without being
one of them — the exact shape discover_adjacent exists to find — and has no
popularity property, exercising the popularity_unknown degraded path.
"""
import pytest
from neo4j.exceptions import Neo4jError

from mcp_server.readonly import WriteQueryError, run_readonly_query
from mcp_server.tools.collaboration import collaborators_of, discover_adjacent
from mcp_server.tools.completeness import artist_completeness
from mcp_server.tools.schema import graph_schema
from mcp_server.tools.search import find_artist, find_track

SEED_ONE = 'MCPTEST Seed One'
SEED_TWO = 'MCPTEST Seed Two'
CANDIDATE = 'MCPTEST Candidate'

SEED_GRAPH = '''
CREATE (m1:Artist {uri: 'spotify:artist:MCPTEST-m1', id: 'MCPTESTm1', name: $seed_one, liked_songs: true}),
       (m2:Artist {uri: 'spotify:artist:MCPTEST-m2', id: 'MCPTESTm2', name: $seed_two, liked_songs: true}),
       (c:Artist  {uri: 'spotify:artist:MCPTEST-c',  id: 'MCPTESTc',  name: $candidate}),
       (l1:Track {uri: 'spotify:track:MCPTEST-l1', name: 'MCPTEST Liked A', liked_songs: true}),
       (l2:Track {uri: 'spotify:track:MCPTEST-l2', name: 'MCPTEST Liked B', liked_songs: true}),
       (x1:Track {uri: 'spotify:track:MCPTEST-x1', name: 'MCPTEST Collab A'}),
       (x2:Track {uri: 'spotify:track:MCPTEST-x2', name: 'MCPTEST Collab B'}),
       (al:Album {uri: 'spotify:album:MCPTEST-al', name: 'MCPTEST Album'}),
       (m1)-[:CREATED]->(l1),
       (m2)-[:CREATED]->(l2),
       (m1)-[:CREATED]->(x1), (c)-[:CREATED]->(x1),
       (m2)-[:CREATED]->(x2), (c)-[:CREATED]->(x2),
       (al)-[:CONTAINS]->(l1), (al)-[:CONTAINS]->(x1)
'''


@pytest.fixture(autouse=True)
def _seed_graph(neo4j_driver):
    purge = "MATCH (n) WHERE n.uri CONTAINS 'MCPTEST' DETACH DELETE n"
    neo4j_driver.execute_query(purge)
    neo4j_driver.execute_query(
        SEED_GRAPH, seed_one=SEED_ONE, seed_two=SEED_TWO, candidate=CANDIDATE
    )
    yield
    neo4j_driver.execute_query(purge)


def test_run_readonly_query_returns_rows(neo4j_driver):
    result = run_readonly_query(
        neo4j_driver,
        "MATCH (a:Artist) WHERE a.uri CONTAINS 'MCPTEST' RETURN count(a) AS artists",
    )
    assert result['rows'] == [{'artists': 3}]
    assert result['row_count'] == 1
    assert result['truncated'] is False


def test_run_readonly_query_row_cap_truncates(neo4j_driver):
    result = run_readonly_query(
        neo4j_driver, 'UNWIND range(1, 500) AS i RETURN i', row_cap=200
    )
    assert result['row_count'] == 200
    assert result['truncated'] is True


def test_run_readonly_query_rejects_writes(neo4j_driver):
    with pytest.raises(WriteQueryError):
        run_readonly_query(neo4j_driver, "CREATE (n:Evil {uri: 'MCPTEST-evil'})")


def test_neo4j_itself_rejects_writes_that_dodge_the_keyword_guard(neo4j_driver):
    # db.createLabel contains no standalone write keyword, so it sails past the
    # regex — the READ_ACCESS session (the real enforcement point) must stop it.
    with pytest.raises(Neo4jError):
        run_readonly_query(neo4j_driver, "CALL db.createLabel('MCPTESTEvil')")


def test_graph_schema_reports_seeded_labels_and_patterns(neo4j_driver):
    result = graph_schema(neo4j_driver)
    labels = {row['label'] for row in result['node_counts']}
    assert {'Artist', 'Track', 'Album'} <= labels
    patterns = {
        (tuple(row['from_labels']), row['relationship'], tuple(row['to_labels']))
        for row in result['relationship_patterns']
    }
    assert (('Artist',), 'CREATED', ('Track',)) in patterns
    assert (('Album',), 'CONTAINS', ('Track',)) in patterns
    artist_properties = {
        row['label']: row['properties'] for row in result['properties_by_label']
    }['Artist']
    assert 'name' in artist_properties


def test_find_artist_matches_case_insensitive_substring(neo4j_driver):
    result = find_artist(neo4j_driver, 'mcptest seed')
    names = [m['name'] for m in result['matches']]
    assert SEED_ONE in names and SEED_TWO in names
    assert all(m['in_liked_songs'] for m in result['matches'])


def test_find_track_includes_album_and_artists(neo4j_driver):
    result = find_track(neo4j_driver, 'MCPTEST Liked A')
    assert result['match_count'] == 1
    match = result['matches'][0]
    assert match['album'] == 'MCPTEST Album'
    assert match['artists'] == [SEED_ONE]
    assert match['in_liked_songs'] is True


def test_collaborators_of_single_seed(neo4j_driver):
    result = collaborators_of(neo4j_driver, [SEED_ONE])
    assert result['unmatched_names'] == []
    names = [c['name'] for c in result['collaborators']]
    assert CANDIDATE in names
    candidate = next(c for c in result['collaborators'] if c['name'] == CANDIDATE)
    assert candidate['seeds_bridged'] == 1
    assert candidate['shared_tracks'] == 1
    assert candidate['via'] == [SEED_ONE]


def test_collaborators_of_ranks_by_seeds_bridged_and_reports_unmatched(neo4j_driver):
    result = collaborators_of(
        neo4j_driver, [SEED_ONE, SEED_TWO, 'MCPTEST Nobody By This Name']
    )
    assert result['unmatched_names'] == ['MCPTEST Nobody By This Name']
    candidate = next(c for c in result['collaborators'] if c['name'] == CANDIDATE)
    assert candidate['seeds_bridged'] == 2
    assert candidate['popularity_unknown'] is True
    assert sorted(candidate['via']) == [SEED_ONE, SEED_TWO]
    # Seeds are excluded from the collaborator list by name, and no real-graph
    # artist shares an MCPTEST track, so the candidate is the only (top) row.
    assert result['collaborators'][0]['name'] == CANDIDATE


def test_discover_adjacent_seeded_finds_the_candidate_with_null_popularity(neo4j_driver):
    result = discover_adjacent(
        neo4j_driver, seed_artist_names=[SEED_ONE, SEED_TWO], min_bridges=2
    )
    assert result['unmatched_names'] == []
    names = [d['name'] for d in result['discoveries']]
    assert names == [CANDIDATE]
    discovery = result['discoveries'][0]
    assert discovery['bridges'] == 2
    assert discovery['popularity'] is None
    assert discovery['popularity_unknown'] is True
    assert sorted(discovery['via']) == [SEED_ONE, SEED_TWO]
    assert 'popularity' in result['caveat']


def test_discover_adjacent_seeded_respects_min_bridges(neo4j_driver):
    result = discover_adjacent(
        neo4j_driver, seed_artist_names=[SEED_ONE], min_bridges=2
    )
    # Only one bridge to the candidate from a single seed: below the bar.
    assert result['discoveries'] == []


def test_discover_adjacent_unseeded_bridges_from_all_liked_artists(neo4j_driver):
    # Unseeded mode bridges from EVERY artist on a liked track, so the shared
    # graph may contribute rows beyond the fixture's; assert on the candidate.
    result = discover_adjacent(neo4j_driver, min_bridges=2, limit=10000)
    candidate = next(
        (d for d in result['discoveries'] if d['name'] == CANDIDATE), None
    )
    assert candidate is not None
    assert candidate['bridges'] == 2
    assert candidate['popularity_unknown'] is True


def test_artist_completeness_degraded_liked_vs_catalog(neo4j_driver):
    result = artist_completeness(neo4j_driver, SEED_ONE)
    assert result['mode'] == 'degraded:liked-vs-catalog'
    assert 'liked' in result['explanation']
    assert len(result['artists']) == 1
    row = result['artists'][0]
    # Seed One created two tracks in the graph, one of them liked.
    assert row['catalog_in_graph'] == 2
    assert row['liked'] == 1
    assert row['liked_ratio'] == 0.5
