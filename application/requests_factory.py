class SpotifyRequestFactory:
    """
    Template music metadata into the Spotify API URIs, and push them to a queue for pending API requests.
    """

    @staticmethod
    def request_url(url):
        # TODO: write to queue "Spotify API requests"
        raise NotImplementedError()

    @classmethod
    def request_liked_songs_first_page(cls):
        cls.request_url("https://api.spotify.com/v1/me/tracks")

    @classmethod
    def request_followed_playlists_first_page(cls):
        cls.request_url("https://api.spotify.com/v1/me/playlists")

    @classmethod
    def request_playlist(cls, playlist_uuid):
        cls.request_url(f"Spotify Playlist URL: {playlist_uuid}")

    @classmethod
    def request_song(cls, song_uuid):
        cls.request_url(f"Spotify Song URL: {song_uuid}")

    @classmethod
    def request_album(cls, album_uuid):
        cls.request_url(f"Spotify Album URL: {album_uuid}")

    @classmethod
    def request_artist(cls, artist_uuid):
        cls.request_url(f"Spotify Artist URL: {artist_uuid}")
