"""Artist completeness — DEGRADED MODE until plan 02 lands.

Real completeness ("how much of this artist have I actually heard?") needs the
listening-history model from docs/plans/02-listening-completeness.md
((:User)-[:LISTENED_TO]->(:Track)). Until that exists, this tool degrades to
liked-vs-catalog: "heard" means liked, and "catalog" means tracks known to the
graph — which is itself only liked-crawl deep until plan 01's discography
crawl runs. Both numbers are lower bounds; the mode is stated in the payload
so an AI consumer doesn't over-claim.
"""
from mcp_server.readonly import run_readonly_query

COMPLETENESS_MODE = 'degraded:liked-vs-catalog'
COMPLETENESS_EXPLANATION = (
    'Listening history (plan 02) is not ingested yet, so "heard" degrades to '
    '"liked": liked_ratio = liked tracks / tracks known to the graph for this '
    'artist. The graph only holds tracks reached by the liked-songs crawl until '
    "plan 01's discography crawl runs, so catalog_in_graph is a lower bound on "
    'the real catalog.'
)

ARTIST_COMPLETENESS_QUERY = '''\
MATCH (a:Artist)
WHERE toLower(a.name) CONTAINS toLower($name)
MATCH (a)-[:CREATED]->(t:Track)
WITH a, count(DISTINCT t) AS catalog_in_graph,
     count(DISTINCT CASE WHEN t.liked_songs THEN t END) AS liked
RETURN a.name AS artist, a.uri AS uri,
       catalog_in_graph, liked,
       round(toFloat(liked) / catalog_in_graph, 3) AS liked_ratio
ORDER BY catalog_in_graph DESC, a.name ASC
LIMIT $limit
'''


def artist_completeness(driver, artist_name, limit=10):
    """Liked-vs-catalog ratio for artists matching the name (see module docstring for caveats)."""
    result = run_readonly_query(
        driver, ARTIST_COMPLETENESS_QUERY, params={'name': artist_name, 'limit': limit}, row_cap=limit
    )
    return {
        'mode': COMPLETENESS_MODE,
        'explanation': COMPLETENESS_EXPLANATION,
        'artists': result['rows'],
    }
