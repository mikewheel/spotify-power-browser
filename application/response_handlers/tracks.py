from pathlib import Path
from json import dump

from application.loggers import get_logger
from application.requests_factory import SpotifyRequestFactory

logger = get_logger(__name__)

BASE_DIR = Path(__file__).parent.parent.parent
DATA_DIR = BASE_DIR / "data"


class TracksParser:
    """
    Parses responses from the Tracks endpoint: https://api.spotify.com/v1/tracks
    Docs: https://developer.spotify.com/documentation/web-api/reference/get-track
    """

    URL_PATTERN = "https://api.spotify.com/v1/tracks"
    DISK_LOCATION = DATA_DIR / "responses" / "tracks"

    def __init__(self, request_url, depth_of_search, response):
        self.request_url = request_url
        self.depth_of_search = depth_of_search
        self.response = response

    def write_to_disk(self):
        output_file = self.DISK_LOCATION / f"track_{self.response['name']}.json"
        output_file.parent.mkdir(parents=True, exist_ok=True)

        with open(output_file, "w") as f:
            dump(self.response, f, indent=4)

        logger.info(f'SUCCESS: {output_file.name}')

    def write_to_sqlite(self):
        raise NotImplementedError()

    def write_to_neo4j(self, driver):
        # TODO: When you have the Neo4J query here, this is where the MERGE clause will need to have an ON UPDATE
        #       section, because it's gonna probably have data that the Liked Songs or other respones don't have
        raise NotImplementedError()

    def follow_links(self):
        if self.depth_of_search <= 0:
            logger.debug(f'Ending recursion at {self.request_url}; depth of search equals zero.')
            return

        # TODO: get artists
        # TODO: get album
        raise NotImplementedError()
