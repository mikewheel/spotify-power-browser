from json import loads

import pandas

from application.response_handlers.me.my_liked_songs import LikedSongsPlaylistResponseHandler

URL = "https://api.spotify.com/v1/me/tracks"


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


def test_write_to_disk_legacy_path_is_unchanged(make, tmp_path, monkeypatch):
    # user_id=None (legacy single-user message): the pre-multiplayer filename,
    # directly under the archive dir.
    monkeypatch.setattr(LikedSongsPlaylistResponseHandler, "DISK_LOCATION", tmp_path)
    page = make.liked_page([make.track(1)], offset=20)

    LikedSongsPlaylistResponseHandler(URL, 0, page).write_to_disk()

    assert (tmp_path / "liked_songs_20.json").is_file()


def test_write_to_disk_namespaces_the_archive_per_user(make, tmp_path, monkeypatch):
    # Page filenames are keyed only by offset, so a CRAWL_ALL_USERS run with
    # two authorized users would otherwise overwrite user A's raw-response
    # archive with user B's pages at the same offsets.
    monkeypatch.setattr(LikedSongsPlaylistResponseHandler, "DISK_LOCATION", tmp_path)
    page_a = make.liked_page([make.track(1)], offset=0)
    page_b = make.liked_page([make.track(2)], offset=0)   # same offset, other user

    LikedSongsPlaylistResponseHandler(URL, 0, page_a, user_id="alice").write_to_disk()
    LikedSongsPlaylistResponseHandler(URL, 0, page_b, user_id="bob").write_to_disk()

    alice_file = tmp_path / "alice" / "liked_songs_0.json"
    bob_file = tmp_path / "bob" / "liked_songs_0.json"
    assert alice_file.is_file() and bob_file.is_file()
    # each archive is a faithful record of ITS user's crawl
    assert loads(alice_file.read_text())["items"][0]["track"]["id"] == "trk1"
    assert loads(bob_file.read_text())["items"][0]["track"]["id"] == "trk2"
