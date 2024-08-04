from pathlib import Path
from json import dump

from application.loggers import get_logger
from application.requests_factory import SpotifyRequestFactory
from application.graph_database.connect import execute_query_against_neo4j

logger = get_logger(__name__)

PROJECT_ROOT_DIR = Path(__file__).parent.parent.parent
DATA_DIR = PROJECT_ROOT_DIR / "data"
GRAPH_DATABASE_QUERIES_DIR = PROJECT_ROOT_DIR / "application" / "graph_database" / "queries"


class TracksParser:
    """
    Parses responses from the Tracks endpoint: https://api.spotify.com/v1/tracks
    Docs: https://developer.spotify.com/documentation/web-api/reference/get-track
    """

    URL_PATTERN = "https://api.spotify.com/v1/tracks"
    DISK_LOCATION = DATA_DIR / "responses" / "tracks"

    with open(GRAPH_DATABASE_QUERIES_DIR / "insert_new_track.cypher", "r") as f:
        CYPHER_QUERY = f.read()

    def __init__(self, request_url, depth_of_search, response):
        self.request_url = request_url
        self.depth_of_search = depth_of_search
        self.response = response

    def write_to_disk(self):
        clean_name = self.response['name'].replace("/", "_slash_").replace("\\", "_back_slash_")
        output_file = self.DISK_LOCATION / f"track_{clean_name}.json"
        output_file.parent.mkdir(parents=True, exist_ok=True)

        with open(output_file, "w") as f:
            dump(self.response, f, indent=4)

        logger.info(f'SUCCESS: {output_file.name}')

    def write_to_neo4j(self, driver, database="neo4j"):
        execute_query_against_neo4j(
            query=self.__class__.CYPHER_QUERY,
            driver=driver,
            database=database,
            track=self.response
        )

    def follow_links(self):
        if self.depth_of_search <= 0:
            logger.debug(f'Ending recursion at {self.request_url}; depth of search equals zero.')
            return

        logger.info(f'Following album from track {self.response["name"]}: {self.response["album"]["name"]}')
        SpotifyRequestFactory.request_url(
            url=self.response["album"]["href"],
            depth_of_search=(self.depth_of_search - 1)
        )

        for artist in self.response["artists"]:
            logger.info(f'Following artist from track {self.response["name"]}: {artist["name"]}')
            SpotifyRequestFactory.request_url(
                url=artist["href"],
                depth_of_search=(self.depth_of_search - 1)
            )

    def write_to_sqlite(self):
        raise NotImplementedError()


if __name__ == "__main__":
    from json import loads

    from application.graph_database.connect import connect_to_neo4j
    from application.graph_database.initialize_database_environment import (
        initialize_database_environment as initialize_neo4j_environment
    )

    NEO4J_CREDENTIALS_FILE = PROJECT_ROOT_DIR / "secrets" / "neo4j_credentials.yaml"

    neo4j_driver = connect_to_neo4j(NEO4J_CREDENTIALS_FILE)
    initialize_neo4j_environment(driver=neo4j_driver)

    with open(DATA_DIR / "responses" / "tracks" / "track_8-bit.json", "r") as f:
        response = loads(f.read())

    parser = TracksParser(
        request_url=None,
        depth_of_search=None,
        response=response
    )

    parser.write_to_neo4j(driver=neo4j_driver)
