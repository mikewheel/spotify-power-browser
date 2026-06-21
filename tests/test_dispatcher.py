import pytest

from application.response_handlers import (
    GetSingleAlbumResponseHandler,
    GetSingleArtistResponseHandler,
    GetSingleTrackResponseHandler,
    LikedSongsPlaylistResponseHandler,
    GetSeveralTracksResponseHandler,
    GetSeveralAlbumsResponseHandler,
    GetSeveralArtistsResponseHandler,
)
from application.response_handlers.main import SpotifyResponseController


@pytest.mark.parametrize(
    "url,expected",
    [
        ("https://api.spotify.com/v1/tracks/abc123", GetSingleTrackResponseHandler),
        ("https://api.spotify.com/v1/albums/abc123", GetSingleAlbumResponseHandler),
        ("https://api.spotify.com/v1/artists/abc123", GetSingleArtistResponseHandler),
        ("https://api.spotify.com/v1/me/tracks", LikedSongsPlaylistResponseHandler),
        # pagination URL (offset/limit, no ids) still routes to the collection handler
        ("https://api.spotify.com/v1/me/tracks?offset=20&limit=20", LikedSongsPlaylistResponseHandler),
        # batch URLs route by the ?ids= resource type
        ("https://api.spotify.com/v1/tracks?ids=a,b,c", GetSeveralTracksResponseHandler),
        ("https://api.spotify.com/v1/albums?ids=a,b", GetSeveralAlbumsResponseHandler),
        ("https://api.spotify.com/v1/artists?ids=a", GetSeveralArtistsResponseHandler),
    ],
)
def test_resolve_handler_routes_correctly(url, expected):
    assert SpotifyResponseController.resolve_handler(url) is expected


def test_unmapped_url_raises_value_error():
    with pytest.raises(ValueError):
        SpotifyResponseController.resolve_handler("https://api.spotify.com/v1/audiobooks/xyz")


def test_unknown_batch_resource_type_raises():
    with pytest.raises(ValueError):
        SpotifyResponseController.resolve_handler("https://api.spotify.com/v1/episodes?ids=a,b")
