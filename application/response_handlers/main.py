import argparse
from json import loads
from pathlib import Path
from urllib.parse import urlparse

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
    AlbumsParser,
    ArtistsParser,
    LikedSongsPlaylistParser,
    TracksParser
)

logger = get_logger(__name__)

PROJECT_ROOT_DIR = Path(__file__).parent.parent.parent
NEO4J_CREDENTIALS_FILE = PROJECT_ROOT_DIR / "secrets" / "neo4j_credentials.yaml"


class SpotifyResponseController:
    """
    Pull Spotify API responses off the queue and dynamically dispatch them to the appropriate response parser.
    """

    RESPONSE_HANDLER_CLASSES = [
        AlbumsParser,
        ArtistsParser,
        LikedSongsPlaylistParser,
        TracksParser

    ]

    RESPONSE_HANDLER_URL_MAPPING = {
        cls.URL_PATTERN: cls
        for cls in RESPONSE_HANDLER_CLASSES
    }

    @staticmethod
    def dispatch_to_response_parser(ch, method, properties, body):
        global RESPONSE_HANDLER_ACTION

        msg = loads(body)

        request_url = msg["request_url"]
        depth_of_search = msg["depth_of_search"]
        response = msg["response"]

        # Make the request URL look uniform so that we can use it to search for the response handler
        parsed_request_url = urlparse(request_url)
        parsed_request_url = parsed_request_url._replace(
            netloc=parsed_request_url.netloc.split(":")[0]
        )
        parsed_request_url = parsed_request_url._replace(query="")
        parsed_request_url = parsed_request_url._replace(fragment="")

        if not request_url.startswith("https://api.spotify.com/v1/me"):
            parsed_request_url = parsed_request_url._replace(
                path=parsed_request_url.path.rsplit("/", maxsplit=1)[0]
            )

        parsed_request_url = parsed_request_url.geturl()

        try:
            response_handler = SpotifyResponseController.RESPONSE_HANDLER_URL_MAPPING[parsed_request_url]
        except KeyError:
            raise ValueError(f'No response handler maps to the following URL: {request_url}')

        if RESPONSE_HANDLER_ACTION == ResponsesExchange.ROUTING_KEY_WRITE_TO_DISK.value:
            response_handler(request_url, depth_of_search, response).write_to_disk()
        elif RESPONSE_HANDLER_ACTION == ResponsesExchange.ROUTING_KEY_WRITE_TO_SQLITE.value:
            response_handler(request_url, depth_of_search, response).write_to_sqlite()
        elif RESPONSE_HANDLER_ACTION == ResponsesExchange.ROUTING_KEY_WRITE_TO_NEO4J.value:
            global neo4j_driver
            response_handler(request_url, depth_of_search, response).write_to_neo4j(driver=neo4j_driver)
        elif RESPONSE_HANDLER_ACTION == ResponsesExchange.ROUTING_KEY_FOLLOW_LINKS.value:
            response_handler(request_url, depth_of_search, response).follow_links()
        else:
            raise ValueError(f'Unrecognized response handler action: {RESPONSE_HANDLER_ACTION}')


def entrypoint(response_handler_action):
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

    while True:
        try:
            logger.info(f'Starting to consume from queue {queue_name}')
            channel.start_consuming()
        except Exception as e:
            logger.error(e)
            logger.info(f'Restarting...')


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
