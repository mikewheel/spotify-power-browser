"""Collaboration-graph tools: shared collaborators and adjacent-artist discovery.

`related-artists` / `recommendations` are removed from the API for this app
(verified 2026-07-06), so track-level co-credits (features, remixes, split
EPs) ARE the discovery mechanism — see docs/plans/01-adjacent-artist-discovery.md.

Popularity caveat: Artist.popularity is not yet populated (plan 01's backfill
adds it), so most artists have popularity NULL today. NULL is treated as
UNKNOWN — such artists are included regardless of $max_popularity and flagged
with popularity_unknown=true, sorted after known-popularity peers.
"""
from mcp_server.readonly import run_readonly_query

POPULARITY_CAVEAT = (
    'Artist.popularity is not yet populated for most nodes (plan 01 backfills it). '
    'Rows with popularity_unknown=true have no popularity data: they are included '
    'regardless of max_popularity and sorted after known-popularity artists.'
)

# Which of the input names match no Artist node (exact, case-insensitive)?
RESOLVE_ARTIST_NAMES_QUERY = '''\
UNWIND $names AS input_name
OPTIONAL MATCH (a:Artist)
WHERE toLower(a.name) = toLower(input_name)
RETURN input_name, count(a) AS matches
'''

COLLABORATORS_OF_QUERY = '''\
UNWIND $names AS input_name
MATCH (seed:Artist)
WHERE toLower(seed.name) = toLower(input_name)
MATCH (seed)-[:CREATED]->(t:Track)<-[:CREATED]-(collab:Artist)
WHERE collab <> seed AND NOT toLower(collab.name) IN $lower_names
WITH collab,
     count(DISTINCT seed) AS seeds_bridged,
     count(DISTINCT t) AS shared_tracks,
     collect(DISTINCT seed.name) AS via
RETURN collab.name AS name, collab.uri AS uri,
       collab.popularity AS popularity,
       collab.popularity IS NULL AS popularity_unknown,
       seeds_bridged, shared_tracks, via
ORDER BY seeds_bridged DESC, shared_tracks DESC, coalesce(collab.popularity, 101) ASC
LIMIT $limit
'''

# Plan 01 §Design discovery query, adapted for null popularity (see caveat above).
# "My" artists = anyone credited on a liked track; candidates bridge to them
# through co-credits on any track and must not themselves be one of mine.
DISCOVER_ADJACENT_QUERY = '''\
MATCH (mine:Artist)-[:CREATED]->(:Track {liked_songs: true})
WITH collect(DISTINCT mine) AS my_artists
UNWIND my_artists AS m
MATCH (m)-[:CREATED]->(t:Track)<-[:CREATED]-(cand:Artist)
WHERE NOT cand IN my_artists
  AND (cand.popularity IS NULL OR cand.popularity <= $max_popularity)
WITH cand, count(DISTINCT m) AS bridges,
     collect(DISTINCT m.name)[..5] AS via
WHERE bridges >= $min_bridges
RETURN cand.name AS name, cand.uri AS uri,
       cand.popularity AS popularity,
       cand.popularity IS NULL AS popularity_unknown,
       cand.followers AS followers, bridges, via
ORDER BY bridges DESC, coalesce(cand.popularity, 101) ASC
LIMIT $limit
'''

# Seeded variant: bridge only from the named artists, and additionally exclude
# candidates already in the liked-songs graph (they aren't discoveries).
DISCOVER_ADJACENT_SEEDED_QUERY = '''\
UNWIND $seed_names AS seed_name
MATCH (m:Artist)
WHERE toLower(m.name) = toLower(seed_name)
WITH collect(DISTINCT m) AS my_artists
UNWIND my_artists AS m
MATCH (m)-[:CREATED]->(t:Track)<-[:CREATED]-(cand:Artist)
WHERE NOT cand IN my_artists
  AND NOT EXISTS { MATCH (cand)-[:CREATED]->(:Track {liked_songs: true}) }
  AND (cand.popularity IS NULL OR cand.popularity <= $max_popularity)
WITH cand, count(DISTINCT m) AS bridges,
     collect(DISTINCT m.name)[..5] AS via
WHERE bridges >= $min_bridges
RETURN cand.name AS name, cand.uri AS uri,
       cand.popularity AS popularity,
       cand.popularity IS NULL AS popularity_unknown,
       cand.followers AS followers, bridges, via
ORDER BY bridges DESC, coalesce(cand.popularity, 101) ASC
LIMIT $limit
'''


def _unmatched_names(driver, names):
    result = run_readonly_query(driver, RESOLVE_ARTIST_NAMES_QUERY, params={'names': names})
    return [row['input_name'] for row in result['rows'] if row['matches'] == 0]


def collaborators_of(driver, artist_names, limit=25):
    """Artists who share track credits with the named artists, ranked by how many seeds they bridge."""
    params = {
        'names': artist_names,
        'lower_names': [name.lower() for name in artist_names],
        'limit': limit,
    }
    result = run_readonly_query(driver, COLLABORATORS_OF_QUERY, params=params)
    return {
        'collaborators': result['rows'],
        'unmatched_names': _unmatched_names(driver, artist_names),
        'caveat': POPULARITY_CAVEAT,
    }


def discover_adjacent(driver, seed_artist_names=None, max_popularity=40, min_bridges=2, limit=50):
    """Unknown-but-adjacent artists: co-credited with your taste, weighted toward the obscure."""
    if seed_artist_names:
        result = run_readonly_query(driver, DISCOVER_ADJACENT_SEEDED_QUERY, params={
            'seed_names': seed_artist_names,
            'max_popularity': max_popularity,
            'min_bridges': min_bridges,
            'limit': limit,
        })
        unmatched = _unmatched_names(driver, seed_artist_names)
    else:
        result = run_readonly_query(driver, DISCOVER_ADJACENT_QUERY, params={
            'max_popularity': max_popularity,
            'min_bridges': min_bridges,
            'limit': limit,
        })
        unmatched = []
    return {
        'discoveries': result['rows'],
        'unmatched_names': unmatched,
        'caveat': POPULARITY_CAVEAT,
    }
