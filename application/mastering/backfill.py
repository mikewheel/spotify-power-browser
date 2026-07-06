"""ISRC enrichment backfill (plan 03 T3): batch-refetch every Track that has
no `isrc` yet and refresh it in Neo4j.

    python -m application.mastering.backfill

Synchronous and offline (not part of the crawl pipeline): reads the worklist
from Neo4j, GETs the verified-alive batch endpoint /v1/tracks?ids= in chunks
of 50 (12.5k tracks ~ 250 calls, minutes), and pushes the full track objects
back through the existing several-tracks insert Cypher, whose ON MATCH SET
now refreshes isrc / album_type / linked_from_id. Bounded 429/500 retries
mirror the crawl engine's policy so a punitive Retry-After can't hang the run.

Live prerequisites: a Spotify token in secrets/spotify_api_token.secret and
Neo4j reachable — which is why this script ships written-but-unrun and gets
exercised for real as a post-merge step.
"""
from time import sleep

import requests

from application.api_call_engine import get_api_token
from application.config import APPLICATION_DIR, SECRETS_DIR, SPOTIFY_API_BASE_URL
from application.graph_database.connect import connect_to_neo4j
from application.loggers import get_logger

logger = get_logger(__name__)

MASTERING_QUERIES_DIR = APPLICATION_DIR / "graph_database" / "queries" / "mastering"
NEO4J_CREDENTIALS_FILE = SECRETS_DIR / "neo4j_credentials.yaml"

BATCH_SIZE = 50            # /v1/tracks?ids= accepts at most 50 ids
MAX_429_RETRIES = 5        # mirror api_call_engine's bounded rate-limit policy
MAX_500_RETRIES = 5
MAX_RETRY_AFTER_SECONDS = 600
DEFAULT_RETRY_AFTER_SECONDS = 60


def chunked(items, size=BATCH_SIZE):
    """Split a list into consecutive chunks of at most `size`."""
    return [items[i:i + size] for i in range(0, len(items), size)]


def fetch_track_ids_missing_isrc(driver, database="neo4j"):
    with open(MASTERING_QUERIES_DIR / "fetch_track_ids_missing_isrc.cypher", "r") as f:
        query = f.read()
    records, _, _ = driver.execute_query(query, database_=database)
    return [record["id"] for record in records]


def _retry_after_seconds(response):
    try:
        retry_after = int(response.headers.get("Retry-After"))
    except (TypeError, ValueError):
        retry_after = DEFAULT_RETRY_AFTER_SECONDS
    return min(retry_after, MAX_RETRY_AFTER_SECONDS)


def fetch_tracks_batch(ids, http_get=requests.get, token=None, wait=sleep):
    """GET one /v1/tracks?ids= batch with bounded 429/500 retries.

    http_get / token / wait are injectable for offline tests. Returns the
    resolved (non-null) full track objects.
    """
    url = f"{SPOTIFY_API_BASE_URL}/v1/tracks?ids={','.join(ids)}"
    errors_429 = errors_500 = 0

    while True:
        response = http_get(
            url, headers={"Authorization": f"Bearer {token or get_api_token()}"}
        )

        if response.status_code == 429:
            errors_429 += 1
            if errors_429 >= MAX_429_RETRIES:
                raise requests.exceptions.HTTPError(
                    f"HTTP 429 rate limiting for {url} exceeded max retry count of {MAX_429_RETRIES}"
                )
            seconds = _retry_after_seconds(response)
            logger.warning(f"HTTP 429 #{errors_429} on backfill batch; waiting {seconds}s...")
            wait(seconds)
            continue

        if response.status_code >= 500:
            errors_500 += 1
            if errors_500 >= MAX_500_RETRIES:
                raise requests.exceptions.HTTPError(
                    f"HTTP {response.status_code} for {url} exceeded max retry count of {MAX_500_RETRIES}"
                )
            logger.warning(f"HTTP {response.status_code} #{errors_500} on backfill batch; waiting 5s...")
            wait(5)
            continue

        response.raise_for_status()
        return [track for track in response.json()["tracks"] if track is not None]


def backfill_missing_isrcs(driver, database="neo4j", http_get=requests.get,
                           token=None, wait=sleep):
    """The whole backfill against an existing driver. Returns run stats."""
    # Import here: the handler module pulls in the request-factory stack,
    # which this offline script only needs for its Cypher + write path.
    from application.response_handlers.tracks.several_tracks import GetSeveralTracksResponseHandler

    track_ids = fetch_track_ids_missing_isrc(driver, database=database)
    batches = chunked(track_ids)
    logger.info(f"Backfilling {len(track_ids)} tracks without isrc in {len(batches)} batches.")

    refreshed = 0
    for batch_number, ids in enumerate(batches, start=1):
        tracks = fetch_tracks_batch(ids, http_get=http_get, token=token, wait=wait)
        if tracks:
            handler = GetSeveralTracksResponseHandler(
                request_url=None, depth_of_search=0, response={"tracks": tracks}
            )
            handler.write_to_neo4j(driver=driver, database=database)
        refreshed += len(tracks)
        unresolved = len(ids) - len(tracks)
        if unresolved:
            logger.warning(f"Batch {batch_number}: {unresolved} id(s) did not resolve (deleted from catalog?).")
        logger.info(f"Batch {batch_number}/{len(batches)}: refreshed {len(tracks)} tracks.")

    remaining = fetch_track_ids_missing_isrc(driver, database=database)
    if remaining:
        # Some catalog entries genuinely lack an ISRC (very old/indie
        # releases) — the heuristic tier and the review loop cover the tail.
        logger.warning(f"{len(remaining)} tracks still have no isrc after the refetch.")
    else:
        logger.info("Backfill complete: 0 non-local tracks without isrc.")

    return {"targeted": len(track_ids), "refreshed": refreshed, "still_missing": len(remaining)}


def main():
    driver = connect_to_neo4j(NEO4J_CREDENTIALS_FILE)
    try:
        stats = backfill_missing_isrcs(driver)
        logger.info(f"Backfill stats: {stats}")
    finally:
        driver.close()


if __name__ == "__main__":
    main()
