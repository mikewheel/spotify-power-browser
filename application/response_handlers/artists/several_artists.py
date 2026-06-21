from application.config import DATA_DIR
from application.response_handlers.batch_handler import (
    SeveralResourcesResponseHandler,
    GRAPH_DATABASE_QUERIES_DIR,
)


class GetSeveralArtistsResponseHandler(SeveralResourcesResponseHandler):
    """Get Several Artists: https://api.spotify.com/v1/artists?ids=...
    Docs: https://developer.spotify.com/documentation/web-api/reference/get-multiple-artists

    Terminal: artists have no neighbors to follow (inherits the no-op
    follow_links from the base handler).
    """

    RESPONSE_KEY = "artists"
    FILE_PREFIX = "artist"
    NEO4J_PARAM = "artists"
    DISK_LOCATION = DATA_DIR / "responses" / "artists"

    with open(GRAPH_DATABASE_QUERIES_DIR / "insert_batch_of_artists.cypher", "r") as f:
        CYPHER_QUERY = f.read()
