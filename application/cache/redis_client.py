"""Redis-backed crawled-URL dedup cache.

A single persistent SET (CRAWLED_URL_SET_KEY) holds every URL that has been
requested. The client is lazy, so importing this module never opens a
connection — only the services that actually call request_url (api_call_engine,
responses_follow_links, requests_factory) connect to Redis.
"""
import redis

from application.config import REDIS_HOSTNAME, REDIS_PORT
from application.loggers import get_logger

logger = get_logger(__name__)

CRAWLED_URL_SET_KEY = "spb:crawled_urls"

_client = None


def get_redis_client():
    """Lazily create and cache the Redis client singleton."""
    global _client
    if _client is None:
        logger.info(f'Connecting to Redis at {REDIS_HOSTNAME}:{REDIS_PORT}')
        _client = redis.Redis(
            host=REDIS_HOSTNAME,
            port=int(REDIS_PORT),
            decode_responses=True,
        )
    return _client


def _member(url, depth_of_search):
    # Key on (depth, url) so a resource reached again at a DEEPER depth (which
    # must expand further) is not blocked by an earlier shallower visit that
    # terminated. Same-depth duplicates (the flood the dedup targets) still
    # collapse to a single member.
    return f"{depth_of_search}|{url}"


def url_is_new(url, depth_of_search):
    """Atomically mark a (url, depth) pair as crawled.

    Returns True if newly added (the caller should proceed), or False if it was
    already present at this depth (skip). Marking at request time dedupes
    in-flight requests, not just completed ones.
    """
    return get_redis_client().sadd(CRAWLED_URL_SET_KEY, _member(url, depth_of_search)) == 1


def unmark_url(url, depth_of_search):
    """Remove a (url, depth) from the crawled set so a request that permanently
    failed (publish error, or fetch give-up) can be re-requested on a later
    follow or run, instead of being silently dropped forever."""
    return get_redis_client().srem(CRAWLED_URL_SET_KEY, _member(url, depth_of_search))


def reset_crawled_set():
    """Delete the crawled-URL set so a fresh crawl starts clean."""
    existed = get_redis_client().delete(CRAWLED_URL_SET_KEY)
    logger.info(f'Reset crawled-URL dedup set "{CRAWLED_URL_SET_KEY}" (existed={bool(existed)})')
    return existed
