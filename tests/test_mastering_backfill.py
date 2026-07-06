"""Offline unit tests for the ISRC backfill script (plan 03 T3). The HTTP
layer is injected, so no live Spotify (or mock service) is needed; the
Neo4j-facing pieces are covered in test_mastering_e2e.py behind the skip
fixture."""
import pytest
import requests

from application.mastering.backfill import (
    BATCH_SIZE,
    MAX_429_RETRIES,
    MAX_RETRY_AFTER_SECONDS,
    chunked,
    fetch_tracks_batch,
)


class FakeResponse:
    def __init__(self, status_code=200, payload=None, headers=None):
        self.status_code = status_code
        self._payload = payload or {}
        self.headers = headers or {}

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.exceptions.HTTPError(f"HTTP {self.status_code}")


def test_chunked_splits_at_batch_size():
    ids = [f"t{i}" for i in range(BATCH_SIZE * 2 + 3)]
    batches = chunked(ids)
    assert [len(b) for b in batches] == [BATCH_SIZE, BATCH_SIZE, 3]
    assert [i for b in batches for i in b] == ids


def test_chunked_empty():
    assert chunked([]) == []


def test_fetch_tracks_batch_builds_the_batch_url_and_filters_nulls(make):
    calls = []

    def http_get(url, headers=None):
        calls.append((url, headers))
        return FakeResponse(payload={"tracks": [make.track(1), None, make.track(2)]})

    tracks = fetch_tracks_batch(["trk1", "gone", "trk2"], http_get=http_get, token="tok")
    assert [t["id"] for t in tracks] == ["trk1", "trk2"]  # nulls dropped
    url, headers = calls[0]
    assert url.endswith("/v1/tracks?ids=trk1,gone,trk2")
    assert headers == {"Authorization": "Bearer tok"}


def test_fetch_tracks_batch_retries_429_honoring_capped_retry_after(make):
    responses = [
        FakeResponse(status_code=429, headers={"Retry-After": "7"}),
        FakeResponse(status_code=429, headers={"Retry-After": str(10**6)}),  # punitive
        FakeResponse(payload={"tracks": [make.track(1)]}),
    ]
    waits = []
    tracks = fetch_tracks_batch(
        ["trk1"], http_get=lambda url, headers=None: responses.pop(0),
        token="tok", wait=waits.append,
    )
    assert len(tracks) == 1
    assert waits == [7, MAX_RETRY_AFTER_SECONDS]  # honored, then capped


def test_fetch_tracks_batch_gives_up_after_max_429s():
    def http_get(url, headers=None):
        return FakeResponse(status_code=429, headers={"Retry-After": "1"})

    with pytest.raises(requests.exceptions.HTTPError, match="max retry count"):
        fetch_tracks_batch(["trk1"], http_get=http_get, token="tok", wait=lambda s: None)


def test_fetch_tracks_batch_retries_500_then_succeeds(make):
    responses = [
        FakeResponse(status_code=500),
        FakeResponse(payload={"tracks": [make.track(1)]}),
    ]
    tracks = fetch_tracks_batch(
        ["trk1"], http_get=lambda url, headers=None: responses.pop(0),
        token="tok", wait=lambda s: None,
    )
    assert len(tracks) == 1


def test_fetch_tracks_batch_gives_up_after_max_500s():
    def http_get(url, headers=None):
        return FakeResponse(status_code=500)

    with pytest.raises(requests.exceptions.HTTPError, match="max retry count"):
        fetch_tracks_batch(["trk1"], http_get=http_get, token="tok", wait=lambda s: None)


def test_fetch_tracks_batch_raises_on_4xx():
    def http_get(url, headers=None):
        return FakeResponse(status_code=403)

    with pytest.raises(requests.exceptions.HTTPError):
        fetch_tracks_batch(["trk1"], http_get=http_get, token="tok")


def test_missing_retry_after_header_defaults():
    from application.mastering.backfill import DEFAULT_RETRY_AFTER_SECONDS, _retry_after_seconds
    assert _retry_after_seconds(FakeResponse(status_code=429)) == DEFAULT_RETRY_AFTER_SECONDS
    assert _retry_after_seconds(
        FakeResponse(status_code=429, headers={"Retry-After": "Wed, 21 Oct 2026 07:28:00 GMT"})
    ) == DEFAULT_RETRY_AFTER_SECONDS


def test_max_retries_matches_engine_policy():
    # The backfill mirrors the crawl engine's bounded rate-limit policy.
    from application import api_call_engine
    assert MAX_429_RETRIES == api_call_engine.MAX_HTTP_429_RETRIES_PER_REQUEST
    assert MAX_RETRY_AFTER_SECONDS == api_call_engine.MAX_RETRY_AFTER_SECONDS
