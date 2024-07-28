from enum import Enum


class RequestsExchange(Enum):
    EXCHANGE_NAME = "spotify_api_requests"
    EXCHANGE_TYPE = "direct"
    ROUTING_KEY_MAKE_API_CALL = "make_api_call"


class ResponsesExchange(Enum):
    EXCHANGE_NAME = "spotify_api_responses"
    EXCHANGE_TYPE = "direct"
    ROUTING_KEY_WRITE_TO_DISK = "write_to_disk"
    ROUTING_KEY_WRITE_TO_SQLITE = "write_to_sqlite"
    ROUTING_KEY_WRITE_TO_NEO4J = "write_to_neo4j"
    ROUTING_KEY_FOLLOW_LINKS = "follow_links"
