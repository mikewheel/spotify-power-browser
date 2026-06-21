from json import dumps

from application.config import (
    CRAWL_LIKED_SONGS,
    CRAWL_FOLLOWED_ARTISTS,
    CRAWL_FOLLOWED_PLAYLISTS,
    CRAWLED_URL_DEDUP,
    DEPTH_OF_SEARCH,
    RESET_CRAWL,
)
from application.cache.redis_client import url_is_new, unmark_url, reset_crawled_set
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
        """Publish a request for `url`. Returns True if it was newly published,
        or False if it was skipped (negative depth, or already crawled)."""
        if depth_of_search < 0:
            return False

        # Dedup at the single choke point all requests flow through (seeds,
        # pagination "next", follow-links re-queues, batch chunks). SADD returns
        # 0 if the URL was already requested at this depth -> skip. Marked at
        # publish time, so this also collapses duplicate in-flight requests.
        if CRAWLED_URL_DEDUP and not url_is_new(url, depth_of_search):
            logger.debug(f'Skipping already-requested URL at depth {depth_of_search}: {url}')
            return False

        try:
            connection, channel = connect_to_rabbitmq_exchange(
                exchange_name=RequestsExchange.EXCHANGE_NAME.value,
                exchange_type=RequestsExchange.EXCHANGE_TYPE.value
            )

            logger.info(f'Requesting {url} with search depth {depth_of_search}')
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
        except Exception:
            # Roll back the dedup mark so a failed enqueue isn't left permanently
            # marked crawled (which would silently drop it forever).
            if CRAWLED_URL_DEDUP:
                unmark_url(url, depth_of_search)
            raise

        return True

    # Spotify's multi-id batch endpoints cap the number of ids per call.
    BATCH_ID_LIMITS = {"tracks": 50, "albums": 20, "artists": 50}

    @classmethod
    def request_batch(cls, resource_type, ids, depth_of_search=0):
        """Request a batch of resources via Spotify's multi-id endpoint
        (GET /v1/{resource_type}?ids=...), chunked to the per-type id cap.

        Each chunk is routed through request_url so dedup and publishing stay
        centralized at the single choke point.
        """
        limit = cls.BATCH_ID_LIMITS[resource_type]
        # De-dup ids within the call and drop falsy ones, preserving order.
        unique_ids = list(dict.fromkeys(i for i in ids if i))
        for start in range(0, len(unique_ids), limit):
            chunk = unique_ids[start:start + limit]
            cls.request_url(
                url=f"https://api.spotify.com/v1/{resource_type}?ids={','.join(chunk)}",
                depth_of_search=depth_of_search,
            )

    @classmethod
    def request_liked_songs_first_page(cls, depth_of_search):
        logger.info(f'STARTING FETCH OF LIKED SONGS')
        return cls.request_url(
            url="https://api.spotify.com/v1/me/tracks",
            depth_of_search=depth_of_search
        )

    @classmethod
    def request_followed_playlists_first_page(cls, depth_of_search):
        logger.info(f'STARTING FETCH OF FOLLOWED_PLAYLISTS')
        return cls.request_url(
            url="https://api.spotify.com/v1/me/playlists",
            depth_of_search=depth_of_search
        )

    @classmethod
    def request_followed_artists_first_page(cls, depth_of_search):
        logger.info(f'STARTING FETCH OF FOLLOWED_ARTISTS')
        return cls.request_url(
            url="https://api.spotify.com/v1/me/following?type=artist",
            depth_of_search=depth_of_search
        )


if __name__ == "__main__":
    if RESET_CRAWL:
        logger.info('RESET_CRAWL set: clearing the crawled-URL dedup set for a fresh crawl.')
        reset_crawled_set()

    seeded = []
    if CRAWL_LIKED_SONGS:
        seeded.append(SpotifyRequestFactory.request_liked_songs_first_page(
            depth_of_search=DEPTH_OF_SEARCH
        ))

    if CRAWL_FOLLOWED_PLAYLISTS:
        seeded.append(SpotifyRequestFactory.request_followed_playlists_first_page(
            depth_of_search=DEPTH_OF_SEARCH
        ))

    if CRAWL_FOLLOWED_ARTISTS:
        seeded.append(SpotifyRequestFactory.request_followed_artists_first_page(
            depth_of_search=DEPTH_OF_SEARCH
        ))

    if seeded and not any(seeded):
        logger.warning(
            'No seed URLs were published - all are already in the crawled-URL set. '
            'Set RESET_CRAWL=true for a fresh crawl.'
        )
