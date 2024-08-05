from pathlib import Path

from application.loggers import get_logger
from application.graph_database.connect import execute_query_against_neo4j
from response_handlers.base_handler import BaseResponseHandler

logger = get_logger(__name__)

PROJECT_ROOT_DIR = Path(__file__).parent.parent.parent
DATA_DIR = PROJECT_ROOT_DIR / "data"
GRAPH_DATABASE_QUERIES_DIR = PROJECT_ROOT_DIR / "application" / "graph_database" / "queries"


class GetSingleArtistResponseHandler(BaseResponseHandler):
    """
    Parses responses from the Artists endpoint: https://api.spotify.com/v1/artists/{id}
    Docs: https://developer.spotify.com/documentation/web-api/reference/get-an-artist
    """

    URL_PATTERN = "https://api.spotify.com/v1/artists"
    DISK_LOCATION = DATA_DIR / "responses" / "artists"

    with open(GRAPH_DATABASE_QUERIES_DIR / "insert_new_artist.cypher", "r") as f:
        CYPHER_QUERY = f.read()

    def __init__(self, request_url, depth_of_search, response):
        super().__init__(request_url, depth_of_search, response)

    def check_url_match(self, url):
        return False  # TODO

    def write_to_disk(self):
        output_file = self.DISK_LOCATION / f"artist_{self.clean_name}.json"
        super()._write_to_disk(output_path=output_file)

    def write_to_neo4j(self, driver, database="neo4j"):
        execute_query_against_neo4j(
            query=self.__class__.CYPHER_QUERY,
            driver=driver,
            database=database,
            artist=self.response
        )

    def follow_links(self):
        logger.debug(f'Ending recursion at {self.request_url}; artists have no neighbors.')
        return

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

    with open(DATA_DIR / "responses" / "artists" / "artist_20syl.json", "r") as f:
        response = loads(f.read())

    parser = GetSingleArtistResponseHandler(
        request_url=None,
        depth_of_search=None,
        response=response
    )

    parser.write_to_neo4j(driver=neo4j_driver)
