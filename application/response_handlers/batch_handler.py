"""Base handler for Spotify's multi-id "Get Several X" batch endpoints.

Their responses are shaped {"<resource_key>": [<full object>, ...]} (e.g.
{"tracks": [...]}), and Spotify returns null entries for ids that don't resolve.
Subclasses set RESPONSE_KEY / FILE_PREFIX / DISK_LOCATION / CYPHER_QUERY /
NEO4J_PARAM, and override follow_links where the resource has neighbors.
"""
from json import dump

from application.config import APPLICATION_DIR
from application.graph_database.connect import execute_query_against_neo4j
from application.loggers import get_logger
from application.response_handlers.base_handler import BaseResponseHandler

logger = get_logger(__name__)

GRAPH_DATABASE_QUERIES_DIR = APPLICATION_DIR / "graph_database" / "queries"


class SeveralResourcesResponseHandler(BaseResponseHandler):

    RESPONSE_KEY = None   # e.g. "tracks"
    FILE_PREFIX = None    # e.g. "track"
    DISK_LOCATION = None
    CYPHER_QUERY = None
    NEO4J_PARAM = None    # cypher parameter name, e.g. "tracks"

    @property
    def items(self):
        """The resolved (non-null) objects from the batch response."""
        return [item for item in self.response[self.RESPONSE_KEY] if item is not None]

    def write_to_disk(self):
        for item in self.items:
            try:
                name = item.get("name") or item.get("id") or item.get("uri") or "unknown"
                clean = name.replace("/", "_slash_").replace("\\", "_back_slash_")
                # Include the unique Spotify id so two resources that share a name
                # don't overwrite each other's on-disk snapshot.
                output_file = self.DISK_LOCATION / f"{self.FILE_PREFIX}_{item['id']}_{clean}.json"
                output_file.parent.mkdir(parents=True, exist_ok=True)
                with open(output_file, "w") as f:
                    dump(item, f, indent=4)
                logger.info(f'SUCCESS: {output_file.name}')
            except Exception as e:
                # One malformed item shouldn't abort the rest of the batch write
                # (auto_ack means an aborted batch write is lost, not retried).
                logger.warning(f'Skipping unwritable batch item: {e}')

    def write_to_neo4j(self, driver, database="neo4j"):
        execute_query_against_neo4j(
            query=self.__class__.CYPHER_QUERY,
            driver=driver,
            database=database,
            **{self.NEO4J_PARAM: self.items},
        )

    def follow_links(self):
        logger.debug(f'Ending recursion at {self.request_url}; depth {self.depth_of_search}.')
        return

    def write_to_sqlite(self):
        raise NotImplementedError()
