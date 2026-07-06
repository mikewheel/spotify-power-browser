import pytest

from application.cache.redis_client import (
    consume_oauth_state,
    reset_crawled_set,
    reset_user_crawled_set,
    store_oauth_state,
    unmark_url,
    url_is_new,
)

TEST_USERS = ("dedup-user-a", "dedup-user-b")


@pytest.fixture(autouse=True)
def _clean(redis_client):
    # redis_client fixture skips the whole module if Redis isn't reachable.
    def wipe():
        reset_crawled_set()
        for user in TEST_USERS:
            reset_user_crawled_set(user)
    wipe()
    yield
    wipe()


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


###
# Plan 06 T6: per-user /v1/me/* split, shared catalog set.
###

def test_me_urls_dedup_per_user():
    url = "https://api.spotify.com/v1/me/tracks"
    assert url_is_new(url, 1, user_id="dedup-user-a") is True
    # The SAME url is a different resource for a different bearer:
    assert url_is_new(url, 1, user_id="dedup-user-b") is True
    # ...but each user's own re-request is deduped.
    assert url_is_new(url, 1, user_id="dedup-user-a") is False
    assert url_is_new(url, 1, user_id="dedup-user-b") is False


def test_catalog_urls_share_one_set_across_users():
    url = "https://api.spotify.com/v1/tracks/shared1"
    assert url_is_new(url, 0, user_id="dedup-user-a") is True
    # user B's crawl skips catalog work user A already requested:
    assert url_is_new(url, 0, user_id="dedup-user-b") is False
    assert url_is_new(url, 0) is False  # and legacy no-user traffic too


def test_legacy_no_user_me_urls_stay_in_the_shared_set():
    # Back-compat with in-flight messages that carry no user_id.
    url = "https://api.spotify.com/v1/me/tracks?offset=20"
    assert url_is_new(url, 1) is True
    assert url_is_new(url, 1) is False
    # A user-scoped request for the same URL is NOT blocked by legacy traffic.
    assert url_is_new(url, 1, user_id="dedup-user-a") is True


def test_unmark_respects_the_user_scope():
    url = "https://api.spotify.com/v1/me/tracks?offset=40"
    assert url_is_new(url, 1, user_id="dedup-user-a") is True
    unmark_url(url, 1, user_id="dedup-user-a")
    assert url_is_new(url, 1, user_id="dedup-user-a") is True


def test_reset_user_set_leaves_other_users_and_catalog_alone():
    me_url = "https://api.spotify.com/v1/me/tracks"
    catalog_url = "https://api.spotify.com/v1/tracks/shared2"
    url_is_new(me_url, 1, user_id="dedup-user-a")
    url_is_new(me_url, 1, user_id="dedup-user-b")
    url_is_new(catalog_url, 0, user_id="dedup-user-a")

    reset_user_crawled_set("dedup-user-a")

    assert url_is_new(me_url, 1, user_id="dedup-user-a") is True    # cleared
    assert url_is_new(me_url, 1, user_id="dedup-user-b") is False   # untouched
    assert url_is_new(catalog_url, 0, user_id="dedup-user-b") is False  # untouched


###
# Plan 06 T4: OAuth state nonces (single-use, TTL'd).
###

def test_oauth_state_is_single_use():
    store_oauth_state("nonce-abc")
    assert consume_oauth_state("nonce-abc") is True
    assert consume_oauth_state("nonce-abc") is False  # consumed -> replay fails


def test_unknown_or_empty_state_is_rejected():
    assert consume_oauth_state("never-minted") is False
    assert consume_oauth_state("") is False
    assert consume_oauth_state(None) is False


def test_oauth_state_expires(redis_client):
    store_oauth_state("nonce-ttl")
    ttl = redis_client.ttl("spb:oauth_state:nonce-ttl")
    assert 0 < ttl <= 600
