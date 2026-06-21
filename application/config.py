"""Lightweight config to direct the scraping process."""
import os
from pathlib import Path

PROJECT_ROOT_DIR = Path(__file__).absolute().parent.parent
APPLICATION_DIR = PROJECT_ROOT_DIR / 'application'
DATA_DIR = PROJECT_ROOT_DIR / 'data'
SECRETS_DIR = PROJECT_ROOT_DIR / 'secrets'


def _env_bool(name, default):
    """Parse a boolean feature flag from the environment, falling back to default."""
    val = os.environ.get(name)
    if val is None:
        return default
    return val.strip().lower() in ('1', 'true', 'yes', 'on')

###
# Which searches to kick off
###
CRAWL_LIKED_SONGS = True
CRAWL_FOLLOWED_PLAYLISTS = False
CRAWL_FOLLOWED_ARTISTS = False

###
# Which response topics are implemented and should be activated for this execution of the application
###
WRITE_RESPONSES_TO_DISK = True
WRITE_RESPONSES_TO_NEO4J = True
FOLLOW_LINKS_IN_RESPONSES = True
WRITE_RESPONSES_TO_SQLITE = False

# How many nearest-neighbors the application should pull before it stops searching
DEPTH_OF_SEARCH = 1

# Hostnames are env-overridable so the same image can point at either a
# containerized broker/DB (compose service name) or one running on the host
# (e.g. Neo4j Desktop via host.docker.internal). Defaults preserve the
# all-in-Docker behavior.
RABBITMQ_HOSTNAME = os.environ.get('RABBITMQ_HOSTNAME', 'rabbitmq')
RABBITMQ_PORT = None  # Right now Pika is just using the default

NEO4J_HOSTNAME = os.environ.get('NEO4J_HOSTNAME', 'neo4j')
NEO4J_PORT = os.environ.get('NEO4J_PORT', '7687')

REDIS_HOSTNAME = os.environ.get('REDIS_HOSTNAME', 'redis')
REDIS_PORT = os.environ.get('REDIS_PORT', '6379')

###
# Crawl efficiency
###
# Skip publishing a request whose URL is already in the Redis "crawled" set.
CRAWLED_URL_DEDUP = _env_bool('CRAWLED_URL_DEDUP', True)

# Use Spotify's multi-id batch endpoints (GET /v1/{type}?ids=) when fetching
# tracks/albums/artists. Default OFF: existing apps currently RETAIN batch access,
# but Spotify only POSTPONED (did not cancel) removing it, and access can only be
# live-verified via application/_probe_batch_endpoints.py once the rate limit
# clears. Flip on via env (USE_BATCH_ENDPOINTS=true) after probing.
USE_BATCH_ENDPOINTS = _env_bool('USE_BATCH_ENDPOINTS', False)
