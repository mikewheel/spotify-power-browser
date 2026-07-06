from urllib.parse import urlparse

from application.config import APPLICATION_DIR, DATA_DIR, SPOTIFY_API_BASE_URL
from application.graph_database.connect import execute_query_against_neo4j
from application.loggers import get_logger
from application.requests_factory import SpotifyRequestFactory
from application.response_handlers.base_handler import BaseResponseHandler

logger = get_logger(__name__)

GRAPH_DATABASE_QUERIES_DIR = APPLICATION_DIR / "graph_database" / "queries"


class GetTracksOfAlbumResponseHandler(BaseResponseHandler):
    """Get Album Tracks: GET /v1/albums/{id}/tracks (plan 01 T6).
    Docs: https://developer.spotify.com/documentation/web-api/reference/get-an-albums-tracks

    Only reached for albums whose track list paginates past the 50 tracks a
    batch-album response embeds: GetSeveralAlbumsResponseHandler follows the
    nested album.tracks.next when present (rare -- long compilations and
    deluxe boxes), and the api_call_engine keeps following this page's own
    "next" at the same depth until pagination ends.

    Depth semantics: pages arrive at the depth of the batch-album response
    that spawned them (1 in a discography crawl -- pagination is a
    continuation, not a hop), so follow_links can still batch this page's
    track credits at depth 0 for frontier enrichment, where the terminal
    artists handler ends the crawl.
    """

    URL_PATTERN = f"{SPOTIFY_API_BASE_URL}/v1/albums/{{album_id}}/tracks"
    DISK_LOCATION = DATA_DIR / "responses" / "tracks_of_album"

    with open(GRAPH_DATABASE_QUERIES_DIR / "discovery" / "insert_tracks_of_album_page.cypher", "r") as f:
        CYPHER_QUERY = f.read()

    def __init__(self, request_url, depth_of_search, response):
        super().__init__(request_url, depth_of_search, response)

    @property
    def album_id(self):
        """The {id} segment of /v1/albums/{id}/tracks."""
        return urlparse(self.request_url).path.rstrip("/").split("/")[-2]

    @property
    def name(self):
        return f"tracks_of_album_{self.album_id}_{self.response.get('offset', 0)}"

    def check_url_match(self, url):
        return False  # sub-resource routing is by path segments in the dispatcher

    def write_to_disk(self):
        output_file = self.DISK_LOCATION / f"{self.clean_name}.json"
        super()._write_to_disk(output_path=output_file)

    def write_to_neo4j(self, driver, database="neo4j"):
        execute_query_against_neo4j(
            query=self.__class__.CYPHER_QUERY,
            driver=driver,
            database=database,
            album_uri=f"spotify:album:{self.album_id}",
            album_id=self.album_id,
            tracks=self.response["items"],
        )

    def follow_links(self):
        if self.depth_of_search <= 0:
            logger.debug(f'Ending recursion at {self.request_url}; depth of search equals zero.')
            return

        # Frontier enrichment for the paginated tail: these simplified tracks
        # never appear in the embedded first-50, so their credits would
        # otherwise miss the popularity sweep.
        SpotifyRequestFactory.request_batch(
            "artists",
            [artist["id"] for track in self.response["items"] for artist in track["artists"]],
            depth_of_search=(self.depth_of_search - 1),
        )

    def write_to_sqlite(self):
        raise NotImplementedError()
