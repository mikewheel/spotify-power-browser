import pandas

from application.config import APPLICATION_DIR, DATA_DIR, SECRETS_DIR, USE_BATCH_ENDPOINTS, SPOTIFY_API_BASE_URL
from application.graph_database.connect import execute_query_against_neo4j
from application.loggers import get_logger
from application.requests_factory import SpotifyRequestFactory
from application.response_handlers.base_handler import BaseResponseHandler
from application.spotify_authentication.token_store import validate_user_id

logger = get_logger(__name__)

GRAPH_DATABASE_QUERIES_DIR = APPLICATION_DIR / "graph_database" / "queries"


class LikedSongsPlaylistResponseHandler(BaseResponseHandler):
    """
    Parses responses from the Liked Songs endpoint: https://api.spotify.com/v1/me/tracks
    Docs: https://developer.spotify.com/documentation/web-api/reference/get-users-saved-tracks
    """

    URL_PATTERN = f"{SPOTIFY_API_BASE_URL}/v1/me/tracks"
    DISK_LOCATION = DATA_DIR / "responses" / "liked_songs"

    with open(GRAPH_DATABASE_QUERIES_DIR / "insert_batch_of_liked_songs.cypher", "r") as f:
        CYPHER_QUERY = f.read()

    def __init__(self, request_url, depth_of_search, response, user_id=None):
        super().__init__(request_url, depth_of_search, response, user_id=user_id)

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

    @property
    def name(self):
        return f"liked_songs_{self.response['offset']}"

    def check_url_match(self, url):
        return False  # TODO

    def write_to_disk(self):
        # Multiplayer (plan 06): page filenames are keyed only by offset, so
        # each user's crawl archives under its own subdirectory — otherwise a
        # CRAWL_ALL_USERS run has user B silently overwrite user A's raw
        # response archive page by page. user_id=None keeps the legacy path
        # byte-for-byte. validate_user_id: the id becomes a path segment.
        directory = self.DISK_LOCATION
        if self.user_id is not None:
            directory = directory / validate_user_id(self.user_id)
        output_file = directory / f"{self.clean_name}.json"
        super()._write_to_disk(output_path=output_file)

    def write_to_neo4j(self, driver, database="neo4j"):

        tracks = [item["track"] | {"added_at": item["added_at"]}
                  for item in self.response["items"]]

        execute_query_against_neo4j(
            query=self.__class__.CYPHER_QUERY,
            driver=driver,
            database=database,
            tracks=tracks,
            # Plan 06: writes (:User {id})-[:LIKED {added_at}] edges when the
            # envelope carried a user; null keeps the legacy node-props-only
            # write (the Cypher's FOREACH no-ops).
            user_id=self.user_id
        )

    def follow_links(self):
        if self.depth_of_search <= 0:
            logger.debug(f'Ending recursion at {self.request_url}; depth of search equals zero.')
            return

        items = self.response["items"]

        # Follow-ups conserve the envelope's user (plan 06): the catalog URLs
        # below dedup in the shared set regardless of user, but the engine
        # keeps using the same bearer for the whole chain.
        if USE_BATCH_ENDPOINTS:
            # The page already carries full track objects (written to Neo4j by
            # this handler), so only the album/artist neighbors need fetching.
            SpotifyRequestFactory.request_batch(
                "albums",
                [song["track"]["album"]["id"] for song in items],
                depth_of_search=(self.depth_of_search - 1),
                user_id=self.user_id,
            )
            SpotifyRequestFactory.request_batch(
                "artists",
                [artist["id"] for song in items for artist in song["track"]["artists"]],
                depth_of_search=(self.depth_of_search - 1),
                user_id=self.user_id,
            )
            return

        for song in items:

            logger.info(f'Following song from Liked Songs: {song["track"]["name"]}')
            SpotifyRequestFactory.request_url(
                url=song["track"]["href"],
                depth_of_search=(self.depth_of_search - 1),
                user_id=self.user_id
            )

            logger.info(f'Following album from liked song {song["track"]["name"]}: {song["track"]["album"]["name"]}')
            SpotifyRequestFactory.request_url(
                url=song["track"]["album"]["href"],
                depth_of_search=(self.depth_of_search - 1),
                user_id=self.user_id
            )

            for artist in song["track"]["artists"]:
                logger.info(f'Following artist from liked song {song["track"]["name"]}: {artist["name"]}')
                SpotifyRequestFactory.request_url(
                    url=artist["href"],
                    depth_of_search=(self.depth_of_search - 1),
                    user_id=self.user_id
                )

    def write_to_sqlite(self):
        raise NotImplementedError()


if __name__ == "__main__":
    from json import loads

    from application.graph_database.connect import connect_to_neo4j
    from application.graph_database.initialize_database_environment import (
        initialize_database_environment as initialize_neo4j_environment
    )

    NEO4J_CREDENTIALS_FILE = SECRETS_DIR / "neo4j_credentials.yaml"

    neo4j_driver = connect_to_neo4j(NEO4J_CREDENTIALS_FILE)
    initialize_neo4j_environment(driver=neo4j_driver)

    with open(DATA_DIR / "responses" / "liked_songs" / "liked_songs_0.json", "r") as f:
        response = loads(f.read())

    parser = LikedSongsPlaylistResponseHandler(
        request_url=None,
        depth_of_search=None,
        response=response
    )

    parser.write_to_neo4j(driver=neo4j_driver)
