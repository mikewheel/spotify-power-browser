from pathlib import Path
from json import dump

import pandas

from application.loggers import get_logger
from application.requests_factory import SpotifyRequestFactory

logger = get_logger(__name__)

BASE_DIR = Path(__file__).parent.parent.parent
DATA_DIR = BASE_DIR / "data"


class LikedSongsPlaylistParser:
    """
    Parses responses from the Liked Songs endpoint: https://api.spotify.com/v1/me/tracks
    Docs: https://developer.spotify.com/documentation/web-api/reference/get-users-saved-tracks
    """

    URL_PATTERN = "https://api.spotify.com/v1/me/tracks"
    DISK_LOCATION = DATA_DIR / "responses" / "liked_songs"

    def __init__(self, request_url, depth_of_search, response):
        self.request_url = request_url
        self.depth_of_search = depth_of_search
        self.response = response

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

    def write_to_disk(self):
        output_file = self.DISK_LOCATION / f"liked_songs_{self.response['offset']}.json"
        output_file.parent.mkdir(parents=True, exist_ok=True)

        with open(output_file, "w") as f:
            dump(self.response, f, indent=4)

        logger.info(f'SUCCESS: {output_file.name}')

    def write_to_sqlite(self):
        raise NotImplementedError()

    def write_to_neo4j(self):
        raise NotImplementedError()

    def follow_links(self):
        if self.depth_of_search <= 0:
            logger.debug(f'Ending recursion at {self.request_url}; depth of search equals zero.')
            return

        for song in self.response["items"]:

            logger.info(f'Following song: {song["track"]["name"]}')
            SpotifyRequestFactory.request_url(
                url=song["track"]["href"],
                depth_of_search=(self.depth_of_search - 1)
            )

            logger.info(f'Following album: {song["track"]["album"]["name"]}')
            SpotifyRequestFactory.request_url(
                url=song["track"]["album"]["href"],
                depth_of_search=(self.depth_of_search - 1)
            )

            for artist in song["track"]["artists"]:
                logger.info(f'Following artist on song: {artist["name"]}')
                SpotifyRequestFactory.request_url(
                    url=artist["href"],
                    depth_of_search=(self.depth_of_search - 1)
                )
