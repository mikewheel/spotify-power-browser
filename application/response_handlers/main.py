import argparse
from json import loads
from time import sleep
from urllib.parse import urlparse, parse_qs

from application.config import SECRETS_DIR, SPOTIFY_API_BASE_URL
from application.graph_database.connect import connect_to_neo4j
from application.graph_database.initialize_database_environment import (
    initialize_database_environment as initialize_neo4j_environment
)
from application.loggers import get_logger
from application.message_queue.connect import (
    connect_to_rabbitmq_exchange,
    bind_queue_to_exchange
)
from application.message_queue.constants import ResponsesExchange
from application.response_handlers import (
    GetSingleAlbumResponseHandler,
    GetSingleArtistResponseHandler,
    LikedSongsPlaylistResponseHandler,
    GetSingleTrackResponseHandler,
    GetSeveralTracksResponseHandler,
    GetSeveralAlbumsResponseHandler,
    GetSeveralArtistsResponseHandler,
    GetAlbumsOfArtistResponseHandler,
    GetTracksOfAlbumResponseHandler,
)

logger = get_logger(__name__)

NEO4J_CREDENTIALS_FILE = SECRETS_DIR / "neo4j_credentials.yaml"


class SpotifyResponseController:
    """
    Pull Spotify API responses off the queue and dynamically dispatch them to the appropriate response parser.
    """

    RESPONSE_HANDLER_CLASSES = [
        GetSingleAlbumResponseHandler,
        GetSingleArtistResponseHandler,
        LikedSongsPlaylistResponseHandler,
        GetSingleTrackResponseHandler

    ]

    RESPONSE_HANDLER_URL_MAPPING = {
        cls.URL_PATTERN: cls
        for cls in RESPONSE_HANDLER_CLASSES
    }

    # Batch endpoints (GET /v1/{type}?ids=...) route by resource type, since the
    # path-strip below collapses /v1/tracks to /v1 once the query is removed.
    BATCH_RESPONSE_HANDLER_MAPPING = {
        "tracks": GetSeveralTracksResponseHandler,
        "albums": GetSeveralAlbumsResponseHandler,
        "artists": GetSeveralArtistsResponseHandler,
    }

    # Paginated sub-resource endpoints (GET /v1/{type}/{id}/{sub}) route by
    # their (parent type, sub-resource) segment pair: the id segment varies per
    # request, so they can't live in the exact URL_PATTERN mapping above.
    SUBRESOURCE_RESPONSE_HANDLER_MAPPING = {
        ("artists", "albums"): GetAlbumsOfArtistResponseHandler,
        ("albums", "tracks"): GetTracksOfAlbumResponseHandler,
    }

    @classmethod
    def resolve_handler(cls, request_url):
        """Return the response handler class for a request URL.

        Batch endpoints (GET /v1/{type}?ids=...) route by resource type;
        sub-resources (GET /v1/{type}/{id}/{sub}) route by their (type, sub)
        segment pair; every other URL is normalized (strip port/query/fragment,
        and the trailing id segment for non-/me URLs) and looked up by path.
        Raises ValueError if no handler matches.
        """
        parsed = urlparse(request_url)

        if "ids" in parse_qs(parsed.query):
            resource_type = parsed.path.rstrip("/").rsplit("/", maxsplit=1)[-1]
            try:
                return cls.BATCH_RESPONSE_HANDLER_MAPPING[resource_type]
            except KeyError:
                raise ValueError(
                    f'No batch response handler for resource type "{resource_type}": {request_url}'
                )

        segments = [segment for segment in parsed.path.split("/") if segment]
        if len(segments) == 4 and segments[0] == "v1" and segments[1] != "me":
            try:
                return cls.SUBRESOURCE_RESPONSE_HANDLER_MAPPING[(segments[1], segments[3])]
            except KeyError:
                raise ValueError(
                    f'No sub-resource response handler maps to the following URL: {request_url}'
                )

        normalized = parsed._replace(
            netloc=parsed.netloc.split(":")[0], query="", fragment=""
        )
        if not request_url.startswith(f"{SPOTIFY_API_BASE_URL}/v1/me"):
            normalized = normalized._replace(path=normalized.path.rsplit("/", maxsplit=1)[0])
        try:
            return cls.RESPONSE_HANDLER_URL_MAPPING[normalized.geturl()]
        except KeyError:
            raise ValueError(f'No response handler maps to the following URL: {request_url}')

    @staticmethod
    def dispatch_to_response_parser(ch, method, properties, body):
        """Consumer callback wrapper: a single bad message (a handler error or a
        transient Neo4j write blip) must NOT propagate into pika and close the
        channel — under auto_ack that stalls the whole worker (the write_to_neo4j
        backlog freeze). Log and skip; entrypoint()'s reconnect loop handles
        connection-level failures."""
        try:
            SpotifyResponseController._dispatch(ch, method, properties, body)
        except Exception:
            logger.exception(
                'Error handling a response message; skipping it to keep the consumer alive.'
            )

    @staticmethod
    def _dispatch(ch, method, properties, body):
        global RESPONSE_HANDLER_ACTION

        msg = loads(body)

        request_url = msg["request_url"]
        depth_of_search = msg["depth_of_search"]
        response = msg["response"]
        # Plan 06 T5: thread the envelope's user through to the handler.
        # .get(): pre-multiplayer in-flight messages carry no user_id -> None,
        # which every handler treats as the legacy single-user behavior.
        user_id = msg.get("user_id")

        response_handler = SpotifyResponseController.resolve_handler(request_url)
        handler = response_handler(request_url, depth_of_search, response, user_id=user_id)

        if RESPONSE_HANDLER_ACTION == ResponsesExchange.ROUTING_KEY_WRITE_TO_DISK.value:
            handler.write_to_disk()
        elif RESPONSE_HANDLER_ACTION == ResponsesExchange.ROUTING_KEY_WRITE_TO_SQLITE.value:
            handler.write_to_sqlite()
        elif RESPONSE_HANDLER_ACTION == ResponsesExchange.ROUTING_KEY_WRITE_TO_NEO4J.value:
            global neo4j_driver
            handler.write_to_neo4j(driver=neo4j_driver)
        elif RESPONSE_HANDLER_ACTION == ResponsesExchange.ROUTING_KEY_FOLLOW_LINKS.value:
            handler.follow_links()
        else:
            raise ValueError(f'Unrecognized response handler action: {RESPONSE_HANDLER_ACTION}')


def entrypoint(response_handler_action):
    # Full setup INSIDE the loop so a closed channel/connection (a broker
    # restart, a heartbeat timeout, a connection reset under load) is recovered
    # by RECONNECTING. The old version set up once outside the loop and
    # re-called start_consuming() on the already-closed channel, hot-spinning
    # "Channel is closed." forever while the durable queue's messages piled up
    # unconsumed (the write_to_neo4j backlog freeze). Bounded sleep on retry.
    while True:
        try:
            connection, channel = connect_to_rabbitmq_exchange(
                exchange_name=ResponsesExchange.EXCHANGE_NAME.value,
                exchange_type=ResponsesExchange.EXCHANGE_TYPE.value
            )
            queue_name = bind_queue_to_exchange(
                channel=channel,
                exchange_name=ResponsesExchange.EXCHANGE_NAME.value,
                exchange_type=ResponsesExchange.EXCHANGE_TYPE.value,
                routing_key=response_handler_action,
                queue_name=response_handler_action  # Mimics the behavior of the default exchange
            )
            channel.basic_consume(
                queue=queue_name,
                on_message_callback=SpotifyResponseController.dispatch_to_response_parser,
                auto_ack=True
            )
            logger.info(f'Starting to consume from queue {queue_name}')
            channel.start_consuming()
        except Exception as e:
            logger.error(f'Consumer connection failed ({e!r}); reconnecting in 5s...')
            sleep(5)


if __name__ == '__main__':
    arg_parser = argparse.ArgumentParser()
    arg_parser.add_argument("response_handler_action")
    args = arg_parser.parse_args()

    RESPONSE_HANDLER_ACTION = args.response_handler_action

    if RESPONSE_HANDLER_ACTION not in [
        ResponsesExchange.ROUTING_KEY_WRITE_TO_DISK.value,
        ResponsesExchange.ROUTING_KEY_WRITE_TO_SQLITE.value,
        ResponsesExchange.ROUTING_KEY_WRITE_TO_NEO4J.value,
        ResponsesExchange.ROUTING_KEY_FOLLOW_LINKS.value
    ]:
        raise ValueError(f'Unrecognized response handler action: {RESPONSE_HANDLER_ACTION}')

    # Set up database drivers and environment
    if RESPONSE_HANDLER_ACTION == ResponsesExchange.ROUTING_KEY_WRITE_TO_NEO4J.value:
        neo4j_driver = connect_to_neo4j(NEO4J_CREDENTIALS_FILE)
        initialize_neo4j_environment(driver=neo4j_driver)

    logger.info(f'Handling responses with action: {RESPONSE_HANDLER_ACTION}')

    entrypoint(response_handler_action=RESPONSE_HANDLER_ACTION)
