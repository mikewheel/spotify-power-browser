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


def url_is_new(url):
    """Atomically mark a URL as crawled.

    Returns True if the URL was newly added to the crawled set (it has not been
    requested before, so the caller should proceed), or False if it was already
    present (already requested -> the caller should skip it). Because the mark
    happens at request time, this dedupes in-flight requests, not just completed
    ones.
    """
    return get_redis_client().sadd(CRAWLED_URL_SET_KEY, url) == 1


def reset_crawled_set():
    """Delete the crawled-URL set so a fresh crawl starts clean."""
    existed = get_redis_client().delete(CRAWLED_URL_SET_KEY)
    logger.info(f'Reset crawled-URL dedup set "{CRAWLED_URL_SET_KEY}" (existed={bool(existed)})')
    return existed
