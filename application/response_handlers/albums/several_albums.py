from application.config import DATA_DIR
from application.requests_factory import SpotifyRequestFactory
from application.response_handlers.batch_handler import (
    SeveralResourcesResponseHandler,
    GRAPH_DATABASE_QUERIES_DIR,
)


class GetSeveralAlbumsResponseHandler(SeveralResourcesResponseHandler):
    """Get Several Albums: https://api.spotify.com/v1/albums?ids=...
    Docs: https://developer.spotify.com/documentation/web-api/reference/get-multiple-albums
    """

    RESPONSE_KEY = "albums"
    FILE_PREFIX = "album"
    NEO4J_PARAM = "albums"
    DISK_LOCATION = DATA_DIR / "responses" / "albums"

    with open(GRAPH_DATABASE_QUERIES_DIR / "insert_batch_of_albums.cypher", "r") as f:
        CYPHER_QUERY = f.read()

    def follow_links(self):
        if self.depth_of_search <= 0:
            return
        # Batch-follow artists. Album tracks are a paginated sub-resource (not an
        # ?ids= batch endpoint) and their handler is unimplemented, so they're
        # not followed here.
        SpotifyRequestFactory.request_batch(
            "artists",
            [artist["id"] for album in self.items for artist in album["artists"]],
            depth_of_search=(self.depth_of_search - 1),
        )
