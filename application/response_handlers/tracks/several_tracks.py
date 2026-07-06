from application.config import DATA_DIR
from application.requests_factory import SpotifyRequestFactory
from application.response_handlers.batch_handler import (
    SeveralResourcesResponseHandler,
    GRAPH_DATABASE_QUERIES_DIR,
)


class GetSeveralTracksResponseHandler(SeveralResourcesResponseHandler):
    """Get Several Tracks: https://api.spotify.com/v1/tracks?ids=...
    Docs: https://developer.spotify.com/documentation/web-api/reference/get-several-tracks
    """

    RESPONSE_KEY = "tracks"
    FILE_PREFIX = "track"
    NEO4J_PARAM = "tracks"
    DISK_LOCATION = DATA_DIR / "responses" / "tracks"

    with open(GRAPH_DATABASE_QUERIES_DIR / "insert_batch_of_tracks.cypher", "r") as f:
        CYPHER_QUERY = f.read()

    def follow_links(self):
        if self.depth_of_search <= 0:
            return
        SpotifyRequestFactory.request_batch(
            "albums",
            [track["album"]["id"] for track in self.items],
            depth_of_search=(self.depth_of_search - 1),
            user_id=self.user_id,
        )
        SpotifyRequestFactory.request_batch(
            "artists",
            [artist["id"] for track in self.items for artist in track["artists"]],
            depth_of_search=(self.depth_of_search - 1),
            user_id=self.user_id,
        )
