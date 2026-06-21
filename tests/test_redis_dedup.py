import pytest

from application.cache.redis_client import url_is_new, unmark_url, reset_crawled_set


@pytest.fixture(autouse=True)
def _clean(redis_client):
    # redis_client fixture skips the whole module if Redis isn't reachable.
    reset_crawled_set()
    yield
    reset_crawled_set()


def test_first_request_new_then_deduped():
    url = "https://api.spotify.com/v1/tracks/dedup1"
    assert url_is_new(url, 0) is True
    assert url_is_new(url, 0) is False


def test_dedup_is_depth_aware():
    url = "https://api.spotify.com/v1/tracks/dedup2"
    assert url_is_new(url, 0) is True
    assert url_is_new(url, 1) is True   # a deeper request is allowed through
    assert url_is_new(url, 1) is False


def test_unmark_makes_url_requestable_again():
    url = "https://api.spotify.com/v1/tracks/dedup3"
    assert url_is_new(url, 0) is True
    unmark_url(url, 0)
    assert url_is_new(url, 0) is True   # rolled back -> re-requestable


def test_reset_clears_the_set():
    url = "https://api.spotify.com/v1/tracks/dedup4"
    url_is_new(url, 0)
    reset_crawled_set()
    assert url_is_new(url, 0) is True
