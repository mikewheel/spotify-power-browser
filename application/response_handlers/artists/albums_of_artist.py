from urllib.parse import urlparse

from application.config import DATA_DIR, SPOTIFY_API_BASE_URL
from application.loggers import get_logger
from application.requests_factory import SpotifyRequestFactory
from application.response_handlers.base_handler import BaseResponseHandler

logger = get_logger(__name__)


class GetAlbumsOfArtistResponseHandler(BaseResponseHandler):
    """Get Artist's Albums: GET /v1/artists/{id}/albums (plan 01 T5).
    Docs: https://developer.spotify.com/documentation/web-api/reference/get-an-artists-albums

    An album-id harvest: follow_links batches the ids through /v1/albums?ids=
    and the full objects are written by GetSeveralAlbumsResponseHandler.
    Invariant: only the discography seeder publishes this URL shape, so a
    frontier artist's own discography is never crawled — depth chain and
    rationale in application/response_handlers/README.md.
    """

    URL_PATTERN = f"{SPOTIFY_API_BASE_URL}/v1/artists/{{artist_id}}/albums"
    DISK_LOCATION = DATA_DIR / "responses" / "albums_of_artist"

    def __init__(self, request_url, depth_of_search, response, user_id=None):
        super().__init__(request_url, depth_of_search, response, user_id=user_id)

    @property
    def artist_id(self):
        """The {id} segment of /v1/artists/{id}/albums."""
        return urlparse(self.request_url).path.rstrip("/").split("/")[-2]

    @property
    def name(self):
        return f"albums_of_artist_{self.artist_id}_{self.response.get('offset', 0)}"

    def write_to_disk(self):
        output_file = self.DISK_LOCATION / f"{self.clean_name}.json"
        super()._write_to_disk(output_path=output_file)

    def write_to_neo4j(self, driver, database="neo4j"):
        # Deliberate no-op: the simplified album objects on this page are a
        # strict subset of the full objects the follow-up /v1/albums?ids=
        # batch returns, and those flow through the existing batch-album
        # insert (plus the embedded-tracks insert). Writing here would only
        # duplicate that work with poorer data.
        logger.debug(
            f'Skipping Neo4j write for album-id harvest page {self.request_url}; '
            f'full albums arrive via the batch follow.'
        )

    def follow_links(self):
        if self.depth_of_search <= 0:
            logger.debug(f'Ending recursion at {self.request_url}; depth of search equals zero.')
            return

        album_ids = [album["id"] for album in self.response["items"]]
        logger.info(
            f'Following {len(album_ids)} albums from the discography of artist {self.artist_id}'
        )
        SpotifyRequestFactory.request_batch(
            "albums",
            album_ids,
            depth_of_search=(self.depth_of_search - 1),
            user_id=self.user_id,
        )

    def write_to_sqlite(self):
        raise NotImplementedError()
