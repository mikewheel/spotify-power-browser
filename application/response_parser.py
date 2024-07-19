import pandas

from application.requests_factory import SpotifyRequestFactory


class SpotifyResponseController:
    """
    Pull Spotify API responses off the queue and dynamically dispatch them to the appropriate response parser.
    """

    @classmethod
    def dispatch_to_response_parser(cls, msg):
        # TODO: look at the message coming off the queue, inspect either the URL or some other attribute
        #       and then decide which one of the parser classes you want to dispatch to
        raise NotImplementedError()


class LikedSongsPlaylistParser:
    """
    Parses responses from the Liked Songs endpoint: https://api.spotify.com/v1/me/tracks
    """

    def __init__(self, response):
        self.response = response
        self.df = self.parse_response()

    def parse_response(self):
        my_liked_songs = self.response["items"]

        rows_list = []

        for song in my_liked_songs:
            try:
                # Own data
                song_name = song["track"]["name"]
                song_external_url_spotify = song["track"]["external_urls"]["spotify"]
                song_id = song["track"]["id"]
                song_uri = song["track"]["uri"]
                song_is_explicit = song["track"]["explicit"]
                song_popularity = song["track"]["popularity"]

                # Album data
                song_album_name = song["track"]["album"]["name"]
                song_album_external_url_spotify = song["track"]["album"]["external_urls"]["spotify"]
                song_album_id = song["track"]["album"]["id"]
                song_album_uri = song["track"]["album"]["uri"]

                # First artist data
                song_first_artist_name = song["track"]["artists"][0]["name"]
                song_first_artist_external_url_spotify = song["track"]["artists"][0]["external_urls"]["spotify"]
                song_first_artist_id = song["track"]["artists"][0]["id"]
                song_first_artist_uri = song["track"]["artists"][0]["uri"]

            except KeyError as e:
                raise KeyError(f'{str(e)}\n\n{song}')

            else:
                rows_list.append({
                    "song_name": song_name,
                    "song_first_artist_name": song_first_artist_name,
                    "song_album_name": song_album_name,
                    "song_is_explicit": song_is_explicit,
                    "song_popularity": song_popularity,

                    "song_external_url_spotify": song_external_url_spotify,
                    "song_id": song_id,
                    "song_uri": song_uri,
                    "song_album_external_url_spotify": song_album_external_url_spotify,
                    "song_album_id": song_album_id,
                    "song_album_uri": song_album_uri,
                    "song_first_artist_external_url_spotify": song_first_artist_external_url_spotify,
                    "song_first_artist_id": song_first_artist_id,
                    "song_first_artist_uri": song_first_artist_uri
                })

        df = pandas.DataFrame(rows_list)
        return df

    def store_data(self):
        raise NotImplementedError()

    @property
    def song_ids(self):
        raise NotImplementedError()

    @property
    def artist_ids(self):
        raise NotImplementedError()

    def follow_links(self):
        for song in self.song_ids:
            SpotifyRequestFactory.request_song(song_uuid=song)

        for artist in self.artist_ids:
            SpotifyRequestFactory.request_artist(artist)


class FollowedPlaylistsResponseParser:
    """
    Parses responses from the Followed Playlists endpoint: https://api.spotify.com/v1/me/playlists
    """

    def __init__(self, response):
        self.response = response
        self.df = self.parse_response()

    def parse_response(self):
        raise NotImplementedError()

    def store_data(self):
        raise NotImplementedError()

    @property
    def song_ids(self):
        raise NotImplementedError()

    def follow_links(self):
        for song in self.song_ids:
            SpotifyRequestFactory.request_song(song_uuid=song)


def entrypoint():
    msg = None  # TODO: read from queue "Spotify API responses"
    SpotifyResponseController.dispatch_to_response_parser(msg)
