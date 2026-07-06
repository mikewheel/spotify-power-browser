"""Fuzzy name lookup for Artist and Track nodes.

Case-insensitive CONTAINS matching, shortest names first (the closest match to
'Four Tet' is 'Four Tet', not 'Four Tet & Champion'). Use these to resolve the
exact node names/uris the other tools take as input.
"""
from mcp_server.readonly import run_readonly_query

FIND_ARTIST_QUERY = '''\
MATCH (a:Artist)
WHERE toLower(a.name) CONTAINS toLower($name)
RETURN a.name AS name, a.id AS id, a.uri AS uri,
       a.popularity AS popularity,
       coalesce(a.liked_songs, false) AS in_liked_songs
ORDER BY size(a.name) ASC, a.name ASC
LIMIT $limit
'''

FIND_TRACK_QUERY = '''\
MATCH (t:Track)
WHERE toLower(t.name) CONTAINS toLower($name)
OPTIONAL MATCH (t)<-[:CONTAINS]-(al:Album)
OPTIONAL MATCH (t)<-[:CREATED]-(ar:Artist)
WITH t, al, collect(DISTINCT ar.name) AS artists
RETURN t.name AS name, t.id AS id, t.uri AS uri,
       coalesce(t.liked_songs, false) AS in_liked_songs,
       al.name AS album, artists
ORDER BY size(t.name) ASC, t.name ASC
LIMIT $limit
'''


def find_artist(driver, name, limit=25):
    result = run_readonly_query(
        driver, FIND_ARTIST_QUERY, params={'name': name, 'limit': limit}, row_cap=limit
    )
    return {'matches': result['rows'], 'match_count': result['row_count']}


def find_track(driver, name, limit=25):
    result = run_readonly_query(
        driver, FIND_TRACK_QUERY, params={'name': name, 'limit': limit}, row_cap=limit
    )
    return {'matches': result['rows'], 'match_count': result['row_count']}
