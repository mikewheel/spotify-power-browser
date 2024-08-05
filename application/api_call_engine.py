from json import dumps, loads
from pprint import pformat
from time import sleep

import requests

from application import config
from application.spotify_authentication.refresh_token import refresh_spotify_auth
from application.loggers import get_logger
from application.message_queue.connect import (
    connect_to_rabbitmq_exchange,
    bind_queue_to_exchange,
    publish_message_to_exchange,
)
from application.message_queue.constants import (
    RequestsExchange, ResponsesExchange
)
from application.requests_factory import SpotifyRequestFactory

logger = get_logger(logger_name=__name__)

SPOTIFY_API_TOKEN_FILE = config.SECRETS_DIR / "spotify_api_token.secret"
MAX_HTTP_500_ERROR_RETRIES_PER_REQUEST = 5

logger.info(f'Reading in Spotify API Token from {SPOTIFY_API_TOKEN_FILE}')
with open(SPOTIFY_API_TOKEN_FILE, "r") as f:
    SPOTIFY_API_TOKEN = f.read()


def make_spotify_api_call(ch, method, properties, body):
    msg = loads(body)
    logger.info(f'Received message from queue:\n{pformat(msg)}')

    request_url = msg["request_url"]
    depth_of_search = msg["depth_of_search"]
    http_500_error_count = 0

    while True:
        logger.info(f'GET: {request_url} ...')
        try:
            r = requests.get(
                request_url,
                headers={"Authorization": f'Bearer {SPOTIFY_API_TOKEN}'}
            )
        except requests.exceptions.ConnectionError:  # Connection reset by peer
            logger.warning("Connection reset by peer. Retrying...")
            sleep(5)
            continue

        try:
            r.raise_for_status()
        except requests.exceptions.HTTPError as e:
            if r.status_code == 500:
                http_500_error_count += 1

                if http_500_error_count >= MAX_HTTP_500_ERROR_RETRIES_PER_REQUEST:
                    raise requests.exceptions.HTTPError(
                        f'HTTP 500 errors for {request_url} have exceeded max retry count of '
                        f'{MAX_HTTP_500_ERROR_RETRIES_PER_REQUEST}'
                    )
                else:
                    logger.warning(
                        f'HTTP 500 #{http_500_error_count} on request to {request_url}. Waiting 5 seconds to retry...'
                    )
                    sleep(5)
                    continue

            elif r.status_code == 429:
                seconds_to_wait = r.headers.get("Retry-After") if r.headers.get("Retry-After") else 60
                logger.warning(f'HTTP 429: Rate limit exceeded! Waiting {seconds_to_wait} seconds to retry...')
                sleep(max(int(seconds_to_wait), 600))
                continue

            elif r.status_code == 401:
                logger.warning(f'HTTP 401: Access token expired. Requesting new token...')
                refresh_spotify_auth()
                logger.info(f'Success: new access token received.')
                continue

            else:
                raise e
        else:
            if r.status_code != 200:
                raise requests.exceptions.HTTPError(f'HTTP {r.status_code} received for {request_url}.')

            response = r.json()

            if response.get("next") is not None:
                next_request_url = response["next"]
                # Send a request for the next URL
                SpotifyRequestFactory.request_url(next_request_url, depth_of_search=depth_of_search)
            else:
                logger.debug(f'Reached the end of pagination for URL {request_url}')
            
            response_data_with_request = {
                "request_url": request_url,
                "depth_of_search": depth_of_search,
                "response": response
            }

            connection, channel = connect_to_rabbitmq_exchange(
                exchange_name=ResponsesExchange.EXCHANGE_NAME.value,
                exchange_type=ResponsesExchange.EXCHANGE_TYPE.value,
            )

            if config.WRITE_RESPONSES_TO_DISK:
                publish_message_to_exchange(
                    channel=channel,
                    exchange=ResponsesExchange.EXCHANGE_NAME.value,
                    routing_key=ResponsesExchange.ROUTING_KEY_WRITE_TO_DISK.value,
                    body=dumps(response_data_with_request)
                )

            if config.WRITE_RESPONSES_TO_SQLITE:
                publish_message_to_exchange(
                    channel=channel,
                    exchange=ResponsesExchange.EXCHANGE_NAME.value,
                    routing_key=ResponsesExchange.ROUTING_KEY_WRITE_TO_SQLITE.value,
                    body=dumps(response_data_with_request)
                )

            if config.WRITE_RESPONSES_TO_NEO4J:
                publish_message_to_exchange(
                    channel=channel,
                    exchange=ResponsesExchange.EXCHANGE_NAME.value,
                    routing_key=ResponsesExchange.ROUTING_KEY_WRITE_TO_NEO4J.value,
                    body=dumps(response_data_with_request)
                )

            if config.FOLLOW_LINKS_IN_RESPONSES:
                publish_message_to_exchange(
                    channel=channel,
                    exchange=ResponsesExchange.EXCHANGE_NAME.value,
                    routing_key=ResponsesExchange.ROUTING_KEY_FOLLOW_LINKS.value,
                    body=dumps(response_data_with_request)
                )

            logger.info(f'Successfully published response from {request_url} to all exchanges.')

            connection.close()
            return


def entrypoint():
    connection, channel = connect_to_rabbitmq_exchange(
        exchange_name=RequestsExchange.EXCHANGE_NAME.value,
        exchange_type=RequestsExchange.EXCHANGE_TYPE.value
    )

    queue_name = bind_queue_to_exchange(
        channel=channel,
        exchange_name=RequestsExchange.EXCHANGE_NAME.value,
        exchange_type=RequestsExchange.EXCHANGE_TYPE.value,
        routing_key=RequestsExchange.ROUTING_KEY_MAKE_API_CALL.value,
        queue_name=RequestsExchange.ROUTING_KEY_MAKE_API_CALL.value  # Mimics the behavior of the default exchange
    )

    channel.basic_consume(
        queue=queue_name,
        on_message_callback=make_spotify_api_call,
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
    entrypoint()
