from application.config import APPLICATION_DIR, DATA_DIR, SECRETS_DIR
from application.loggers import get_logger
from application.requests_factory import SpotifyRequestFactory
from application.graph_database.connect import execute_query_against_neo4j
from application.response_handlers.base_handler import BaseResponseHandler

logger = get_logger(__name__)

GRAPH_DATABASE_QUERIES_DIR = APPLICATION_DIR / "graph_database" / "queries"


class GetSingleAlbumResponseHandler(BaseResponseHandler):
    """
    Parses responses from the Albums endpoint: https://api.spotify.com/v1/albums/{id}
    Docs: https://developer.spotify.com/documentation/web-api/reference/get-an-album
    """

    URL_PATTERN = "https://api.spotify.com/v1/albums"
    DISK_LOCATION = DATA_DIR / "responses" / "albums"

    with open(GRAPH_DATABASE_QUERIES_DIR / "insert_single_album.cypher", "r") as f:
        CYPHER_QUERY = f.read()

    def __init__(self, request_url, depth_of_search, response):
        super().__init__(request_url, depth_of_search, response)

    def check_url_match(self, url):
        return False  # TODO

    def write_to_disk(self):
        output_file = self.DISK_LOCATION / f"album_{self.clean_name}.json"
        super()._write_to_disk(output_path=output_file)

    def write_to_neo4j(self, driver, database="neo4j"):
        execute_query_against_neo4j(
            query=self.__class__.CYPHER_QUERY,
            driver=driver,
            database=database,
            album=self.response
        )

    def follow_links(self):
        if self.depth_of_search <= 0:
            logger.debug(f'Ending recursion at {self.request_url}; depth of search equals zero.')
            return

        logger.info(f'Following tracks from album {self.response["name"]}')
        SpotifyRequestFactory.request_url(
            url=self.response["tracks"]["href"],
            depth_of_search=(self.depth_of_search - 1)
        )

        for artist in self.response["artists"]:
            logger.info(f'Following artist from album {self.response["name"]}: {artist["name"]}')
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

    NEO4J_CREDENTIALS_FILE = SECRETS_DIR / "neo4j_credentials.yaml"

    neo4j_driver = connect_to_neo4j(NEO4J_CREDENTIALS_FILE)
    initialize_neo4j_environment(driver=neo4j_driver)

    with open(DATA_DIR / "responses" / "albums" / "album_2HEARTs.json", "r") as f:
        response = loads(f.read())

    parser = GetSingleAlbumResponseHandler(
        request_url=None,
        depth_of_search=None,
        response=response
    )

    parser.write_to_neo4j(driver=neo4j_driver)
