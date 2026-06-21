import pandas

from application.response_handlers.me.my_liked_songs import LikedSongsPlaylistResponseHandler


def test_parse_response_returns_dataframe(make):
    # Exercises the pandas DataFrame path (guards against a pandas major bump).
    page = make.liked_page([make.track(1), make.track(2)])
    handler = LikedSongsPlaylistResponseHandler("https://api.spotify.com/v1/me/tracks", 0, page)

    df = handler.parse_response()

    assert isinstance(df, pandas.DataFrame)
    assert len(df) == 2
    assert {"song_name", "song_first_artist_name", "song_album_name"} <= set(df.columns)


def test_name_property_uses_offset(make):
    page = make.liked_page([make.track(1)], offset=40)
    handler = LikedSongsPlaylistResponseHandler("https://api.spotify.com/v1/me/tracks", 0, page)
    assert handler.name == "liked_songs_40"
