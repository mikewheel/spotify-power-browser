"""Offline unit tests for the adjacent-artist discovery crawl (plan 01):
dispatcher routing for the sub-resource endpoints, the AlbumsOfArtist /
TracksOfAlbum handlers, the flag-gated frontier behavior on batch-album
responses, the discography seeder, and the popularity backfill. No services
needed -- the queue/HTTP/Neo4j edges are injected."""
import pytest
import requests

from application.requests_factory import SpotifyRequestFactory
from application.response_handlers import (
    GetAlbumsOfArtistResponseHandler,
    GetSeveralAlbumsResponseHandler,
    GetTracksOfAlbumResponseHandler,
)
from application.response_handlers.main import SpotifyResponseController


# ---------------------------------------------------------------------------
# fixtures / helpers
# ---------------------------------------------------------------------------

def _capture_request_url(monkeypatch):
    calls = []
    monkeypatch.setattr(
        "application.requests_factory.SpotifyRequestFactory.request_url",
        staticmethod(lambda url, depth_of_search=0: calls.append((url, depth_of_search))),
    )
    return calls


def _capture_request_batch(monkeypatch):
    calls = []
    monkeypatch.setattr(
        "application.requests_factory.SpotifyRequestFactory.request_batch",
        classmethod(lambda cls, rtype, ids, depth_of_search=0: calls.append((rtype, list(ids), depth_of_search))),
    )
    return calls


def _albums_list_page(album_ids, next_url=None):
    """A GET /v1/artists/{id}/albums page (simplified album objects)."""
    return {
        "href": "http://spotify_mock/v1/artists/art1/albums?offset=0&limit=50",
        "items": [{"id": album_id, "name": f"Album {album_id}", "album_type": "album"} for album_id in album_ids],
        "limit": 50,
        "offset": 0,
        "next": next_url,
        "total": len(album_ids),
    }


def _album_with_embedded_tracks(make, i, track_artist_ids, tracks_next=None):
    """A full album object as returned by GET /v1/albums?ids=..."""
    album = make.album(i)
    album["tracks"] = {
        "href": f"https://api.spotify.com/v1/albums/alb{i}/tracks?offset=0&limit=50",
        "items": [
            {
                "uri": f"spotify:track:emb{i}{n}",
                "id": f"emb{i}{n}",
                "name": f"Embedded {i}-{n}",
                # simplified artist credits: id/uri/name only (no popularity)
                "artists": [
                    {"id": artist_id, "uri": f"spotify:artist:{artist_id}", "name": artist_id,
                     "external_urls": {"spotify": "x"}, "type": "artist"}
                    for artist_id in artist_ids
                ],
            }
            for n, artist_ids in enumerate(track_artist_ids)
        ],
        "limit": 50,
        "offset": 0,
        "next": tracks_next,
        "total": len(track_artist_ids),
    }
    return album


# ---------------------------------------------------------------------------
# dispatcher: sub-resource routing
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "url,expected",
    [
        ("https://api.spotify.com/v1/artists/abc123/albums", GetAlbumsOfArtistResponseHandler),
        # pagination + query params still route to the same handler
        ("https://api.spotify.com/v1/artists/abc123/albums?include_groups=album,single&limit=50&offset=50",
         GetAlbumsOfArtistResponseHandler),
        ("https://api.spotify.com/v1/albums/xyz789/tracks?offset=50&limit=50", GetTracksOfAlbumResponseHandler),
        # a mock-host URL (no port, different netloc) routes identically
        ("http://spotify_mock/v1/artists/art000000/albums?limit=50", GetAlbumsOfArtistResponseHandler),
    ],
)
def test_resolve_handler_routes_subresources(url, expected):
    assert SpotifyResponseController.resolve_handler(url) is expected


@pytest.mark.parametrize(
    "url",
    [
        "https://api.spotify.com/v1/artists/abc123/related-artists",  # removed endpoint
        "https://api.spotify.com/v1/playlists/abc123/tracks",         # unmapped parent type
    ],
)
def test_unknown_subresource_raises(url):
    with pytest.raises(ValueError):
        SpotifyResponseController.resolve_handler(url)


# ---------------------------------------------------------------------------
# GetAlbumsOfArtistResponseHandler (T5)
# ---------------------------------------------------------------------------

def test_albums_of_artist_batches_album_ids_at_decremented_depth(monkeypatch):
    calls = _capture_request_url(monkeypatch)
    page = _albums_list_page([f"alb{i:03d}" for i in range(25)])
    GetAlbumsOfArtistResponseHandler(
        "http://spotify_mock/v1/artists/art1/albums?limit=50", 2, page
    ).follow_links()

    # 25 ids -> /v1/albums?ids= chunks of 20 via the request_batch machinery
    assert len(calls) == 2
    assert [url.split("ids=")[1].count(",") + 1 for url, _ in calls] == [20, 5]
    assert all("/v1/albums?ids=" in url for url, _ in calls)
    assert all(depth == 1 for _, depth in calls)  # decremented from 2


def test_albums_of_artist_terminates_at_depth_zero(monkeypatch):
    calls = _capture_request_url(monkeypatch)
    GetAlbumsOfArtistResponseHandler(
        "http://spotify_mock/v1/artists/art1/albums", 0, _albums_list_page(["alb1"])
    ).follow_links()
    assert calls == []


def test_albums_of_artist_neo4j_write_is_a_noop():
    handler = GetAlbumsOfArtistResponseHandler(
        "http://spotify_mock/v1/artists/art1/albums", 2, _albums_list_page(["alb1"])
    )
    handler.write_to_neo4j(driver=None)  # must not touch the driver at all


def test_albums_of_artist_parses_artist_id_and_disk_name(tmp_path, monkeypatch):
    monkeypatch.setattr(GetAlbumsOfArtistResponseHandler, "DISK_LOCATION", tmp_path)
    handler = GetAlbumsOfArtistResponseHandler(
        "http://spotify_mock/v1/artists/art000007/albums?offset=50&limit=50",
        2,
        _albums_list_page(["alb1"]) | {"offset": 50},
    )
    assert handler.artist_id == "art000007"
    handler.write_to_disk()
    assert (tmp_path / "albums_of_artist_art000007_50.json").exists()


# ---------------------------------------------------------------------------
# GetTracksOfAlbumResponseHandler (T6)
# ---------------------------------------------------------------------------

def _tracks_page(artist_ids_per_track, offset=50):
    return {
        "href": f"http://spotify_mock/v1/albums/alb1/tracks?offset={offset}&limit=50",
        "items": [
            {
                "uri": f"spotify:track:tail{n}",
                "id": f"tail{n}",
                "name": f"Tail {n}",
                "artists": [{"id": artist_id, "uri": f"spotify:artist:{artist_id}", "name": artist_id,
                             "external_urls": {"spotify": "x"}, "type": "artist"} for artist_id in artist_ids],
            }
            for n, artist_ids in enumerate(artist_ids_per_track)
        ],
        "limit": 50,
        "offset": offset,
        "next": None,
        "total": offset + len(artist_ids_per_track),
    }


def test_tracks_of_album_sweeps_track_credits_at_decremented_depth(monkeypatch):
    calls = _capture_request_batch(monkeypatch)
    GetTracksOfAlbumResponseHandler(
        "http://spotify_mock/v1/albums/alb1/tracks?offset=50", 1, _tracks_page([["a1"], ["a1", "fr1"]])
    ).follow_links()
    assert calls == [("artists", ["a1", "a1", "fr1"], 0)]


def test_tracks_of_album_terminates_at_depth_zero(monkeypatch):
    calls = _capture_request_batch(monkeypatch)
    GetTracksOfAlbumResponseHandler(
        "http://spotify_mock/v1/albums/alb1/tracks?offset=50", 0, _tracks_page([["a1"]])
    ).follow_links()
    assert calls == []


def test_tracks_of_album_parses_album_id():
    handler = GetTracksOfAlbumResponseHandler(
        "http://spotify_mock/v1/albums/dal000042/tracks?offset=50&limit=50", 1, _tracks_page([])
    )
    assert handler.album_id == "dal000042"


# ---------------------------------------------------------------------------
# GetSeveralAlbumsResponseHandler: flag-gated frontier behavior
# ---------------------------------------------------------------------------

FLAG = "application.response_handlers.albums.several_albums.CRAWL_ARTIST_DISCOGRAPHIES"


def test_batch_albums_flag_off_keeps_existing_behavior(make, monkeypatch):
    monkeypatch.setattr(FLAG, False)
    batch_calls = _capture_request_batch(monkeypatch)
    url_calls = _capture_request_url(monkeypatch)

    album = _album_with_embedded_tracks(
        make, 1, [["art1"], ["art1", "artFRONTIER"]], tracks_next="http://x/v1/albums/alb1/tracks?offset=50"
    )
    GetSeveralAlbumsResponseHandler(None, 1, {"albums": [album]}).follow_links()

    # only the albums' own artists; no track-credit sweep, no tracks.next follow
    assert batch_calls == [("artists", ["art1"], 0)]
    assert url_calls == []


def test_batch_albums_flag_on_sweeps_frontier_and_follows_tracks_next(make, monkeypatch):
    monkeypatch.setattr(FLAG, True)
    batch_calls = _capture_request_batch(monkeypatch)
    url_calls = _capture_request_url(monkeypatch)

    album = _album_with_embedded_tracks(
        make, 1, [["art1"], ["art1", "artFRONTIER"]], tracks_next="http://x/v1/albums/alb1/tracks?offset=50"
    )
    GetSeveralAlbumsResponseHandler(None, 1, {"albums": [album]}).follow_links()

    # album artists + embedded track credits, one artists batch at depth-1
    assert batch_calls == [("artists", ["art1", "art1", "art1", "artFRONTIER"], 0)]
    # nested tracks.next followed at the SAME depth (pagination, not a hop)
    assert url_calls == [("http://x/v1/albums/alb1/tracks?offset=50", 1)]


def test_batch_albums_flag_on_tolerates_albums_without_embedded_tracks(make, monkeypatch):
    monkeypatch.setattr(FLAG, True)
    batch_calls = _capture_request_batch(monkeypatch)
    url_calls = _capture_request_url(monkeypatch)

    GetSeveralAlbumsResponseHandler(None, 1, {"albums": [make.album(1)]}).follow_links()
    assert batch_calls == [("artists", ["art1"], 0)]
    assert url_calls == []


def test_batch_albums_flag_on_still_terminates_at_depth_zero(make, monkeypatch):
    monkeypatch.setattr(FLAG, True)
    batch_calls = _capture_request_batch(monkeypatch)
    album = _album_with_embedded_tracks(make, 1, [["art1"]], tracks_next="http://x/next")
    GetSeveralAlbumsResponseHandler(None, 0, {"albums": [album]}).follow_links()
    assert batch_calls == []


# ---------------------------------------------------------------------------
# discography seeder (T4)
# ---------------------------------------------------------------------------

class FakeDriver:
    def __init__(self, records):
        self.records = records
        self.queries = []

    def execute_query(self, query, **kwargs):
        self.queries.append((query, kwargs))
        return self.records, None, None


def test_seeder_publishes_albums_list_urls_at_seed_depth(monkeypatch):
    calls = _capture_request_url(monkeypatch)
    driver = FakeDriver([{"id": "art000001"}, {"id": "art000002"}])

    published = SpotifyRequestFactory.request_artist_discographies(driver=driver)

    assert len(published) == 2
    assert [url for url, _ in calls] == [
        "https://api.spotify.com/v1/artists/art000001/albums?include_groups=album,single&limit=50",
        "https://api.spotify.com/v1/artists/art000002/albums?include_groups=album,single&limit=50",
    ]
    # every seed carries the documented discography depth
    assert all(depth == SpotifyRequestFactory.DISCOGRAPHY_SEED_DEPTH for _, depth in calls)
    # the worklist query was parameterized with the configured threshold, and
    # (plan 06) traverses (:User)-[:LIKED] with a null user scope by default
    (query, kwargs), = driver.queries
    assert ":LIKED]" in query and "$user_id" in query
    assert kwargs == {"affinity_min": 3, "user_id": None}


def test_seed_depth_reaches_the_frontier_sweep_and_no_further():
    # seed(2) -> albums list -> batch albums(1) -> artist sweep(0) -> terminal.
    # 2 is the minimum depth at which the frontier enrichment still fires; a
    # regression here silently stops enriching (or starts over-crawling).
    assert SpotifyRequestFactory.DISCOGRAPHY_SEED_DEPTH == 2


# ---------------------------------------------------------------------------
# popularity backfill (T2)
# ---------------------------------------------------------------------------

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


def test_fetch_artists_batch_builds_the_batch_url_and_filters_nulls(make):
    from application.discovery.backfill_artists import fetch_artists_batch

    calls = []

    def http_get(url, headers=None):
        calls.append((url, headers))
        return FakeResponse(payload={"artists": [make.artist(1), None, make.artist(2)]})

    artists = fetch_artists_batch(["art1", "gone", "art2"], http_get=http_get, token="tok")
    assert [a["id"] for a in artists] == ["art1", "art2"]  # nulls dropped
    url, headers = calls[0]
    assert url.endswith("/v1/artists?ids=art1,gone,art2")
    assert headers == {"Authorization": "Bearer tok"}


def test_fetch_artists_batch_gives_up_after_max_429s():
    from application.discovery.backfill_artists import MAX_429_RETRIES, fetch_artists_batch

    attempts = []

    def http_get(url, headers=None):
        attempts.append(url)
        return FakeResponse(status_code=429, headers={"Retry-After": "1"})

    with pytest.raises(requests.exceptions.HTTPError, match="max retry count"):
        fetch_artists_batch(["art1"], http_get=http_get, token="tok", wait=lambda s: None)
    assert len(attempts) == MAX_429_RETRIES


def test_fetch_artists_batch_retries_500_then_succeeds(make):
    from application.discovery.backfill_artists import fetch_artists_batch

    responses = [FakeResponse(status_code=500), FakeResponse(payload={"artists": [make.artist(1)]})]
    artists = fetch_artists_batch(
        ["art1"], http_get=lambda url, headers=None: responses.pop(0),
        token="tok", wait=lambda s: None,
    )
    assert len(artists) == 1


def test_backfill_retry_policy_matches_the_engine():
    from application import api_call_engine
    from application.discovery import backfill_artists
    assert backfill_artists.MAX_429_RETRIES == api_call_engine.MAX_HTTP_429_RETRIES_PER_REQUEST
    assert backfill_artists.MAX_RETRY_AFTER_SECONDS == api_call_engine.MAX_RETRY_AFTER_SECONDS


def test_backfill_writes_batches_through_the_artist_handler(make):
    from application.discovery.backfill_artists import backfill_missing_popularity

    written = []

    class Driver(FakeDriver):
        pass

    # worklist: two artists missing popularity; after the "write", none remain.
    worklists = [[{"id": "art1"}, {"id": "art2"}], []]
    driver = Driver([])
    driver.execute_query = lambda query, **kwargs: (worklists.pop(0), None, None)

    def http_get(url, headers=None):
        return FakeResponse(payload={"artists": [make.artist(1), make.artist(2)]})

    import application.response_handlers.artists.several_artists as several_artists
    original = several_artists.GetSeveralArtistsResponseHandler.write_to_neo4j
    several_artists.GetSeveralArtistsResponseHandler.write_to_neo4j = (
        lambda self, driver, database="neo4j": written.append([a["id"] for a in self.items])
    )
    try:
        stats = backfill_missing_popularity(driver, http_get=http_get, token="tok", wait=lambda s: None)
    finally:
        several_artists.GetSeveralArtistsResponseHandler.write_to_neo4j = original

    assert written == [["art1", "art2"]]
    assert stats == {"targeted": 2, "refreshed": 2, "still_missing": 0}


# ---------------------------------------------------------------------------
# conftest factory shape (T2)
# ---------------------------------------------------------------------------

def test_make_artist_carries_popularity_and_followers_by_default(make):
    artist = make.artist(1)
    assert artist["popularity"] == 50
    assert artist["followers"] == {"href": None, "total": 1000}


def test_make_artist_can_omit_the_enrichment_fields(make):
    simplified = make.artist(1, popularity="", followers="")
    assert "popularity" not in simplified and "followers" not in simplified
    custom = make.artist(1, popularity=7, followers=42)
    assert custom["popularity"] == 7 and custom["followers"]["total"] == 42
