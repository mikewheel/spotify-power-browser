"""Shared test fixtures.

`make` exposes small factories for the Spotify object shapes the handlers and
Cypher consume. The service fixtures (redis_client / rabbitmq_channel /
neo4j_driver) connect to the real backing services and `pytest.skip()` when one
isn't reachable, so the suite runs anywhere and the integration tests light up
when the services are up (e.g. via the Docker Compose `tests` service).
"""
from types import SimpleNamespace

import pytest


def _artist(i, popularity=None, followers=None):
    """popularity/followers: None -> deterministic defaults; "" -> omit the
    field entirely (a simplified artist object, e.g. a track credit, carries
    neither -- plan 01 discovery relies on coalesce keeping stored values)."""
    artist = {
        "uri": f"spotify:artist:{i}",
        "id": f"art{i}",
        "name": f"Artist {i}",
        "external_urls": {"spotify": f"https://open.spotify.com/artist/art{i}"},
        "href": f"https://api.spotify.com/v1/artists/art{i}",
        "type": "artist",
        "genres": [],
    }
    if popularity != "":
        artist["popularity"] = 50 if popularity is None else popularity
    if followers != "":
        artist["followers"] = {"href": None, "total": 1000 if followers is None else followers}
    return artist


def _album(i, artists=None):
    return {
        "uri": f"spotify:album:{i}",
        "id": f"alb{i}",
        "name": f"Album {i}",
        "release_date": "2020-01-01",
        "release_date_precision": "day",
        "total_tracks": 10,
        "album_type": "album",
        "external_urls": {"spotify": f"https://open.spotify.com/album/alb{i}"},
        "href": f"https://api.spotify.com/v1/albums/alb{i}",
        "type": "album",
        "artists": [_artist(i)] if artists is None else artists,
        "genres": [],
    }


def _track(i, album=None, artists=None, isrc=None, linked_from_id=None):
    """isrc: None -> deterministic default; "" -> omit external_ids entirely
    (a very old/indie release without one)."""
    track = {
        "uri": f"spotify:track:{i}",
        "id": f"trk{i}",
        "name": f"Track {i}",
        "explicit": False,
        "is_local": False,
        "duration_ms": 200000,
        "popularity": 50,
        "type": "track",
        "href": f"https://api.spotify.com/v1/tracks/trk{i}",
        "external_urls": {"spotify": f"https://open.spotify.com/track/trk{i}"},
        "album": _album(i) if album is None else album,
        "artists": [_artist(i)] if artists is None else artists,
    }
    if isrc != "":
        track["external_ids"] = {"isrc": f"ISRC{i}" if isrc is None else isrc}
    if linked_from_id is not None:
        track["linked_from"] = {
            "id": linked_from_id,
            "uri": f"spotify:track:{linked_from_id}",
            "type": "track",
        }
    return track


def _liked_page(tracks, offset=0, next_url=None):
    return {
        "href": "https://api.spotify.com/v1/me/tracks",
        "items": [{"added_at": "2021-01-01T00:00:00Z", "track": t} for t in tracks],
        "limit": 20,
        "offset": offset,
        "next": next_url,
        "total": 100,
    }


@pytest.fixture
def make():
    """Factories for Spotify object shapes: make.track/album/artist/liked_page."""
    return SimpleNamespace(artist=_artist, album=_album, track=_track, liked_page=_liked_page)


@pytest.fixture
def redis_client():
    from application.cache.redis_client import get_redis_client
    try:
        client = get_redis_client()
        client.ping()
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"Redis not reachable: {exc}")
    return client


@pytest.fixture
def rabbitmq_channel():
    from application.message_queue.connect import connect_to_rabbitmq_exchange
    from application.message_queue.constants import RequestsExchange
    try:
        connection, channel = connect_to_rabbitmq_exchange(
            RequestsExchange.EXCHANGE_NAME.value, RequestsExchange.EXCHANGE_TYPE.value
        )
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"RabbitMQ not reachable: {exc}")
    yield channel
    connection.close()


@pytest.fixture
def mock_base():
    """Base URL of the mock Spotify service; skips if it isn't reachable."""
    import requests
    base = "http://spotify_mock"
    try:
        requests.post(f"{base}/_control/reset", timeout=3).raise_for_status()
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"Mock Spotify service not reachable: {exc}")
    yield base
    try:
        requests.post(f"{base}/_control/reset", timeout=3)
    except Exception:  # noqa: BLE001
        pass


@pytest.fixture
def neo4j_driver():
    from application.config import SECRETS_DIR
    from application.graph_database.connect import connect_to_neo4j
    try:
        driver = connect_to_neo4j(SECRETS_DIR / "neo4j_credentials.yaml")
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"Neo4j not reachable: {exc}")
    yield driver
    driver.close()
