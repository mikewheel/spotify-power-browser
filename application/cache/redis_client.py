"""Redis-backed crawled-URL dedup cache (+ OAuth state nonces, plan 06 T4).

Dedup sets (plan 06 T6 split):
  spb:crawled_urls              the SHARED CATALOG set: tracks/albums/artists
                                and every other non-user-relative URL. A track
                                fetched for user A need not be re-fetched for
                                user B — the node is already in the graph.
  spb:crawled_urls:<user_id>    one PER-USER set for user-relative URLs
                                (path under /v1/me): /v1/me/tracks means a
                                different resource per bearer, so user B's
                                liked-songs crawl must not be blocked by user
                                A's.

A message with no user_id (legacy / in-flight from an older version) keeps the
pre-multiplayer behavior: everything dedups against the shared set.

The client is lazy, so importing this module never opens a connection — only
the services that actually call request_url (api_call_engine,
responses_follow_links, requests_factory) and the OAuth web service connect.
"""
from urllib.parse import urlparse

import redis

from application.config import REDIS_HOSTNAME, REDIS_PORT
from application.loggers import get_logger

logger = get_logger(__name__)

CRAWLED_URL_SET_KEY = "spb:crawled_urls"
OAUTH_STATE_KEY_PREFIX = "spb:oauth_state:"
OAUTH_STATE_TTL_SECONDS = 600  # a human finishing a Spotify login comfortably

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


def _is_user_relative(url):
    """True for URLs whose meaning depends on the bearer token — the /v1/me
    subtree (liked songs, followed artists/playlists, player, profile)."""
    path = urlparse(url).path
    return path == "/v1/me" or path.startswith("/v1/me/")


def _set_key(url, user_id):
    """The dedup set a (url, user) pair belongs to. Catalog URLs — and ALL
    urls of legacy no-user messages — go to the shared set."""
    if user_id and _is_user_relative(url):
        return f"{CRAWLED_URL_SET_KEY}:{user_id}"
    return CRAWLED_URL_SET_KEY


def _member(url, depth_of_search):
    # Key on (depth, url) so a resource reached again at a DEEPER depth (which
    # must expand further) is not blocked by an earlier shallower visit that
    # terminated. Same-depth duplicates (the flood the dedup targets) still
    # collapse to a single member.
    return f"{depth_of_search}|{url}"


def url_is_new(url, depth_of_search, user_id=None):
    """Atomically mark a (url, depth) pair as crawled in the appropriate set
    (per-user for /v1/me URLs when user_id is known, shared otherwise).

    Returns True if newly added (the caller should proceed), or False if it was
    already present at this depth (skip). Marking at request time dedupes
    in-flight requests, not just completed ones.
    """
    return get_redis_client().sadd(_set_key(url, user_id), _member(url, depth_of_search)) == 1


def unmark_url(url, depth_of_search, user_id=None):
    """Remove a (url, depth) from its crawled set so a request that permanently
    failed (publish error, or fetch give-up) can be re-requested on a later
    follow or run, instead of being silently dropped forever."""
    return get_redis_client().srem(_set_key(url, user_id), _member(url, depth_of_search))


def reset_crawled_set():
    """Delete the SHARED catalog set so a fresh crawl starts clean (the legacy
    RESET_CRAWL behavior; per-user sets are reset separately)."""
    existed = get_redis_client().delete(CRAWLED_URL_SET_KEY)
    logger.info(f'Reset crawled-URL dedup set "{CRAWLED_URL_SET_KEY}" (existed={bool(existed)})')
    return existed


def reset_user_crawled_set(user_id):
    """Delete ONE user's per-user dedup set (their /v1/me/* URLs)."""
    key = f"{CRAWLED_URL_SET_KEY}:{user_id}"
    existed = get_redis_client().delete(key)
    logger.info(f'Reset per-user crawled-URL dedup set "{key}" (existed={bool(existed)})')
    return existed


###
# OAuth state nonces (plan 06 T4): single-use, TTL'd CSRF tokens minted by
# /login and consumed by /callback.
###

def store_oauth_state(nonce, ttl_seconds=OAUTH_STATE_TTL_SECONDS):
    """Persist a freshly minted state nonce with a TTL."""
    get_redis_client().set(f"{OAUTH_STATE_KEY_PREFIX}{nonce}", "1", ex=ttl_seconds)


def consume_oauth_state(nonce):
    """Atomically validate AND invalidate a state nonce (GETDEL: single-use).
    Returns True when the nonce was valid and unexpired."""
    if not nonce:
        return False
    return get_redis_client().getdel(f"{OAUTH_STATE_KEY_PREFIX}{nonce}") is not None
