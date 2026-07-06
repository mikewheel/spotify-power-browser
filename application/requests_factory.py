from json import dumps

from application.config import (
    APPLICATION_DIR,
    ARTIST_AFFINITY_MIN,
    CRAWL_ARTIST_DISCOGRAPHIES,
    CRAWL_LIKED_SONGS,
    CRAWL_FOLLOWED_ARTISTS,
    CRAWL_FOLLOWED_PLAYLISTS,
    CRAWLED_URL_DEDUP,
    DEPTH_OF_SEARCH,
    RESET_CRAWL,
    SPOTIFY_API_BASE_URL,
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
                url=f"{SPOTIFY_API_BASE_URL}/v1/{resource_type}?ids={','.join(chunk)}",
                depth_of_search=depth_of_search,
            )

    @classmethod
    def request_liked_songs_first_page(cls, depth_of_search):
        logger.info(f'STARTING FETCH OF LIKED SONGS')
        return cls.request_url(
            url=f"{SPOTIFY_API_BASE_URL}/v1/me/tracks",
            depth_of_search=depth_of_search
        )

    @classmethod
    def request_followed_playlists_first_page(cls, depth_of_search):
        logger.info(f'STARTING FETCH OF FOLLOWED_PLAYLISTS')
        return cls.request_url(
            url=f"{SPOTIFY_API_BASE_URL}/v1/me/playlists",
            depth_of_search=depth_of_search
        )

    @classmethod
    def request_followed_artists_first_page(cls, depth_of_search):
        logger.info(f'STARTING FETCH OF FOLLOWED_ARTISTS')
        return cls.request_url(
            url=f"{SPOTIFY_API_BASE_URL}/v1/me/following?type=artist",
            depth_of_search=depth_of_search
        )

    # Depth for discography seeds (plan 01). The chain is exactly two resource
    # hops deep, decrementing at each follow like every other handler:
    #   seed  GET /v1/artists/{id}/albums            depth 2  (album-id harvest)
    #   ->    GET /v1/albums?ids=...                 depth 1  (full albums; the
    #         handler batches the albums' track credits -- the collab frontier)
    #   ->    GET /v1/artists?ids=...                depth 0  (frontier
    #         enrichment; the artists handler is terminal, so the crawl ends)
    # Pagination ("next" links, including an album's nested tracks.next) is
    # re-queued at the SAME depth -- it continues a resource, it isn't a hop.
    # Frontier artists' own discographies are never crawled: only this seeder
    # publishes /v1/artists/{id}/albums URLs, and it only selects artists with
    # liked tracks (depth 3 territory is a separate, deliberate decision).
    DISCOGRAPHY_SEED_DEPTH = 2

    @classmethod
    def request_artist_discographies(cls, driver, depth_of_search=DISCOGRAPHY_SEED_DEPTH):
        """Seed the discography crawl (plan 01): one albums-list request per
        artist with >= ARTIST_AFFINITY_MIN liked tracks (read from Neo4j).
        include_groups excludes compilations/appears_on deliberately (that's
        where third-party compilation noise lives). Returns the per-seed
        published/skipped booleans, like the other seed entrypoints."""
        with open(
            APPLICATION_DIR / "graph_database" / "queries" / "discovery"
            / "fetch_discography_seed_artist_ids.cypher", "r"
        ) as f:
            query = f.read()

        records, _, _ = driver.execute_query(query, affinity_min=ARTIST_AFFINITY_MIN)
        logger.info(
            f'STARTING DISCOGRAPHY CRAWL: {len(records)} artists have >= '
            f'{ARTIST_AFFINITY_MIN} liked tracks'
        )

        return [
            cls.request_url(
                url=(
                    f"{SPOTIFY_API_BASE_URL}/v1/artists/{record['id']}/albums"
                    f"?include_groups=album,single&limit=50"
                ),
                depth_of_search=depth_of_search,
            )
            for record in records
        ]


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

    if CRAWL_ARTIST_DISCOGRAPHIES:
        # Import here: only the discography seeder needs a Neo4j connection
        # (the other seeds are static /v1/me URLs), so the default crawl path
        # stays free of the graph-database dependency.
        from application.config import SECRETS_DIR
        from application.graph_database.connect import connect_to_neo4j

        neo4j_driver = connect_to_neo4j(SECRETS_DIR / "neo4j_credentials.yaml")
        try:
            seeded.extend(SpotifyRequestFactory.request_artist_discographies(
                driver=neo4j_driver
            ))
        finally:
            neo4j_driver.close()

    if seeded and not any(seeded):
        logger.warning(
            'No seed URLs were published - all are already in the crawled-URL set. '
            'Set RESET_CRAWL=true for a fresh crawl.'
        )
