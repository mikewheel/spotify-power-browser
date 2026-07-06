import pytest

from application.requests_factory import SpotifyRequestFactory


@pytest.fixture
def captured(monkeypatch):
    """Capture request_url calls instead of publishing to RabbitMQ."""
    calls = []
    monkeypatch.setattr(
        SpotifyRequestFactory,
        "request_url",
        staticmethod(lambda url, depth_of_search=0, user_id=None: calls.append((url, depth_of_search))),
    )
    return calls


def _chunk_sizes(calls):
    return [url.split("ids=")[1].count(",") + 1 for url, _ in calls]


def test_tracks_chunk_to_cap_of_50(captured):
    SpotifyRequestFactory.request_batch("tracks", [f"id{i}" for i in range(120)], depth_of_search=2)
    assert _chunk_sizes(captured) == [50, 50, 20]
    assert all(u.startswith("https://api.spotify.com/v1/tracks?ids=") for u, _ in captured)
    assert all(depth == 2 for _, depth in captured)


def test_albums_chunk_to_cap_of_20(captured):
    SpotifyRequestFactory.request_batch("albums", [f"a{i}" for i in range(45)], depth_of_search=0)
    assert _chunk_sizes(captured) == [20, 20, 5]


def test_artists_chunk_to_cap_of_50(captured):
    SpotifyRequestFactory.request_batch("artists", [f"a{i}" for i in range(50)], depth_of_search=0)
    assert _chunk_sizes(captured) == [50]


def test_dedupes_and_drops_falsy_ids(captured):
    SpotifyRequestFactory.request_batch("artists", ["x", "x", "y", None, "", "z"], depth_of_search=0)
    assert len(captured) == 1
    assert captured[0][0].split("ids=")[1].split(",") == ["x", "y", "z"]


def test_empty_ids_is_a_noop(captured):
    SpotifyRequestFactory.request_batch("tracks", [], depth_of_search=0)
    assert captured == []
