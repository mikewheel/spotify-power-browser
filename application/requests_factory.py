from json import dumps

from application.message_queue.connect import connect_to_rabbitmq_exchange, publish_message_to_exchange
from application.message_queue.constants import RequestsExchange

from application.loggers import get_logger

logger = get_logger(__name__)


class SpotifyRequestFactory:
    """
    Template music metadata into the Spotify API URIs, and push them to a queue for pending API requests.
    """

    @staticmethod
    def request_url(url, depth_of_search=0):
        if depth_of_search < 0:
            return

        connection, channel = connect_to_rabbitmq_exchange(
            exchange_name=RequestsExchange.EXCHANGE_NAME.value,
            exchange_type=RequestsExchange.EXCHANGE_TYPE.value
        )

        publish_message_to_exchange(
            channel=channel,
            exchange=RequestsExchange.EXCHANGE_NAME.value,
            routing_key=RequestsExchange.ROUTING_KEY_MAKE_API_CALL.value,
            body=dumps(
                {
                    "request_url": url,
                    "depth_of_search": depth_of_search
                }
            )
        )

    @classmethod
    def request_liked_songs_first_page(cls, depth_of_search):
        logger.info(f'STARTING FETCH OF LIKED SONGS')
        cls.request_url(
            url="https://api.spotify.com/v1/me/tracks",
            depth_of_search=depth_of_search
        )

    @classmethod
    def request_followed_playlists_first_page(cls, depth_of_search):
        logger.info(f'STARTING FETCH OF FOLLOWED_PLAYLISTS')
        cls.request_url(
            url="https://api.spotify.com/v1/me/playlists",
            depth_of_search=depth_of_search
        )


if __name__ == "__main__":
    SpotifyRequestFactory.request_liked_songs_first_page(
        depth_of_search=0
    )
