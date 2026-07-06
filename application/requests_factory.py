from json import dumps

from application.config import (
    APPLICATION_DIR,
    ARTIST_AFFINITY_MIN,
    CRAWL_ALL_USERS,
    CRAWL_ARTIST_DISCOGRAPHIES,
    CRAWL_LIKED_SONGS,
    CRAWL_FOLLOWED_ARTISTS,
    CRAWL_FOLLOWED_PLAYLISTS,
    CRAWL_USER,
    CRAWLED_URL_DEDUP,
    DEPTH_OF_SEARCH,
    RESET_CRAWL,
    RESET_CRAWL_CATALOG,
    SPOTIFY_API_BASE_URL,
)
from application.cache.redis_client import (
    url_is_new, unmark_url, reset_crawled_set, reset_user_crawled_set,
)
from application.message_queue.connect import connect_to_rabbitmq_exchange, publish_message_to_exchange
from application.message_queue.constants import RequestsExchange

from application.loggers import get_logger

logger = get_logger(__name__)


class SpotifyRequestFactory:
    """
    Template music metadata into the Spotify API URIs, and push them to a queue for pending API requests.
    """

    @staticmethod
    def request_url(url, depth_of_search=0, user_id=None):
        """Publish a request for `url` on behalf of `user_id` (None = the
        legacy single-user identity). Returns True if it was newly published,
        or False if it was skipped (negative depth, or already crawled).

        Every published message carries user_id (plan 06 T5) so the engine can
        pick the right bearer token and handlers can write per-user ownership;
        null keeps the exact legacy behavior end-to-end."""
        if depth_of_search < 0:
            return False

        # Dedup at the single choke point all requests flow through (seeds,
        # pagination "next", follow-links re-queues, batch chunks). SADD returns
        # 0 if the URL was already requested at this depth -> skip. Marked at
        # publish time, so this also collapses duplicate in-flight requests.
        # /v1/me/* URLs dedup per user; catalog URLs share one set (plan 06 T6).
        if CRAWLED_URL_DEDUP and not url_is_new(url, depth_of_search, user_id=user_id):
            logger.debug(f'Skipping already-requested URL at depth {depth_of_search}: {url}')
            return False

        try:
            connection, channel = connect_to_rabbitmq_exchange(
                exchange_name=RequestsExchange.EXCHANGE_NAME.value,
                exchange_type=RequestsExchange.EXCHANGE_TYPE.value
            )

            logger.info(
                f'Requesting {url} with search depth {depth_of_search}'
                + (f' for user {user_id}' if user_id else '')
            )
            publish_message_to_exchange(
                channel=channel,
                exchange=RequestsExchange.EXCHANGE_NAME.value,
                routing_key=RequestsExchange.ROUTING_KEY_MAKE_API_CALL.value,
                body=dumps(
                    {
                        "request_url": url,
                        "depth_of_search": depth_of_search,
                        "user_id": user_id
                    }
                )
            )
        except Exception:
            # Roll back the dedup mark so a failed enqueue isn't left permanently
            # marked crawled (which would silently drop it forever).
            if CRAWLED_URL_DEDUP:
                unmark_url(url, depth_of_search, user_id=user_id)
            raise

        return True

    # Spotify's multi-id batch endpoints cap the number of ids per call.
    BATCH_ID_LIMITS = {"tracks": 50, "albums": 20, "artists": 50}

    @classmethod
    def request_batch(cls, resource_type, ids, depth_of_search=0, user_id=None):
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
                user_id=user_id,
            )

    @classmethod
    def request_liked_songs_first_page(cls, depth_of_search, user_id=None):
        logger.info(f'STARTING FETCH OF LIKED SONGS' + (f' for {user_id}' if user_id else ''))
        return cls.request_url(
            url=f"{SPOTIFY_API_BASE_URL}/v1/me/tracks",
            depth_of_search=depth_of_search,
            user_id=user_id
        )

    @classmethod
    def request_followed_playlists_first_page(cls, depth_of_search, user_id=None):
        logger.info(f'STARTING FETCH OF FOLLOWED_PLAYLISTS' + (f' for {user_id}' if user_id else ''))
        return cls.request_url(
            url=f"{SPOTIFY_API_BASE_URL}/v1/me/playlists",
            depth_of_search=depth_of_search,
            user_id=user_id
        )

    @classmethod
    def request_followed_artists_first_page(cls, depth_of_search, user_id=None):
        logger.info(f'STARTING FETCH OF FOLLOWED_ARTISTS' + (f' for {user_id}' if user_id else ''))
        return cls.request_url(
            url=f"{SPOTIFY_API_BASE_URL}/v1/me/following?type=artist",
            depth_of_search=depth_of_search,
            user_id=user_id
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
    def request_artist_discographies(cls, driver, depth_of_search=DISCOGRAPHY_SEED_DEPTH,
                                     user_id=None):
        """Seed the discography crawl (plan 01): one albums-list request per
        artist with >= ARTIST_AFFINITY_MIN liked tracks (read from Neo4j).
        include_groups excludes compilations/appears_on deliberately (that's
        where third-party compilation noise lives). Returns the per-seed
        published/skipped booleans, like the other seed entrypoints.

        user_id (plan 06) scopes the seed worklist to one user's taste via
        (:User)-[:LIKED] (None = any user, the legacy single-user behavior)
        and rides the published envelopes."""
        with open(
            APPLICATION_DIR / "graph_database" / "queries" / "discovery"
            / "fetch_discography_seed_artist_ids.cypher", "r"
        ) as f:
            query = f.read()

        records, _, _ = driver.execute_query(
            query, affinity_min=ARTIST_AFFINITY_MIN, user_id=user_id
        )
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
                user_id=user_id,
            )
            for record in records
        ]


def resolve_seed_users(user=None, all_users=False):
    """Which user identities to seed crawls for, in order.

    - explicit --user wins;
    - --all-users iterates every authorized user in secrets/users/ (sorted),
      SEQUENTIALLY — rate limits are per-app, parallel crawls fight each other;
    - default: the recorded primary user, or the legacy no-user identity
      ([None]) when nobody has authorized through the multi-user flow yet.
    """
    # Imported lazily: the token store touches the secrets dir, which only the
    # seeding entrypoint needs (the factory class itself stays import-light).
    from application.spotify_authentication.token_store import (
        get_primary_user_id, has_user, list_user_ids,
    )

    if user:
        # Fail fast on a typo'd id: seeding for a user with no tokens would
        # make the engine fall back to the legacy bearer, silently crawling
        # the PRIMARY user's library instead of the intended one.
        if not has_user(user):
            raise SystemExit(
                f"No authorized user {user!r} under secrets/users/ "
                f"(known: {list_user_ids() or 'none'}). "
                f"Have them log in via /login first."
            )
        return [user]
    if all_users:
        users = list_user_ids()
        if not users:
            logger.warning('--all-users: no authorized users found under secrets/users/; '
                           'falling back to the legacy single-user identity.')
            return [None]
        return users
    return [get_primary_user_id()]  # may be None -> legacy envelope


def seed_crawls_for_user(user_id):
    """Publish the configured seed URLs for one user identity. Returns the
    per-seed published/skipped booleans."""
    seeded = []
    if CRAWL_LIKED_SONGS:
        seeded.append(SpotifyRequestFactory.request_liked_songs_first_page(
            depth_of_search=DEPTH_OF_SEARCH, user_id=user_id
        ))

    if CRAWL_FOLLOWED_PLAYLISTS:
        seeded.append(SpotifyRequestFactory.request_followed_playlists_first_page(
            depth_of_search=DEPTH_OF_SEARCH, user_id=user_id
        ))

    if CRAWL_FOLLOWED_ARTISTS:
        seeded.append(SpotifyRequestFactory.request_followed_artists_first_page(
            depth_of_search=DEPTH_OF_SEARCH, user_id=user_id
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
                driver=neo4j_driver, user_id=user_id
            ))
        finally:
            neo4j_driver.close()

    return seeded


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="Seed Spotify crawl requests (plan 06: per-user envelopes)."
    )
    scope = parser.add_mutually_exclusive_group()
    scope.add_argument("--user", default=CRAWL_USER, metavar="SPOTIFY_USER_ID",
                       help="seed for one authorized user (env: CRAWL_USER). "
                            "Default: the primary user, or legacy mode.")
    scope.add_argument("--all-users", action="store_true", default=CRAWL_ALL_USERS,
                       help="seed for every user under secrets/users/, sequentially "
                            "(env: CRAWL_ALL_USERS)")
    args = parser.parse_args()

    users = resolve_seed_users(user=args.user, all_users=args.all_users)

    if RESET_CRAWL_CATALOG:
        logger.info('RESET_CRAWL_CATALOG set: clearing the SHARED catalog dedup set.')
        reset_crawled_set()

    all_seeded = []
    for seed_user in users:
        if RESET_CRAWL:
            if seed_user is None:
                # Legacy semantics preserved: no-user mode clears the shared set.
                logger.info('RESET_CRAWL set: clearing the crawled-URL dedup set for a fresh crawl.')
                reset_crawled_set()
            else:
                logger.info(f'RESET_CRAWL set: clearing {seed_user}\'s per-user dedup set. '
                            f'(Catalog set is kept; set RESET_CRAWL_CATALOG=true to clear it too.)')
                reset_user_crawled_set(seed_user)

        all_seeded.extend(seed_crawls_for_user(seed_user))

    if all_seeded and not any(all_seeded):
        logger.warning(
            'No seed URLs were published - all are already in the crawled-URL set. '
            'Set RESET_CRAWL=true for a fresh crawl.'
        )
