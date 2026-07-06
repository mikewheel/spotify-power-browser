from application.config import CRAWL_ARTIST_DISCOGRAPHIES, DATA_DIR
from application.graph_database.connect import execute_query_against_neo4j
from application.requests_factory import SpotifyRequestFactory
from application.response_handlers.batch_handler import (
    SeveralResourcesResponseHandler,
    GRAPH_DATABASE_QUERIES_DIR,
)


class GetSeveralAlbumsResponseHandler(SeveralResourcesResponseHandler):
    """Get Several Albums: https://api.spotify.com/v1/albums?ids=...
    Docs: https://developer.spotify.com/documentation/web-api/reference/get-multiple-albums

    Full album objects embed their first 50 tracks (album.tracks). In a
    discography crawl (plan 01, CRAWL_ARTIST_DISCOGRAPHIES=true) those
    embedded tracks are the collab frontier, so this handler additionally:
      - persists them to Neo4j (insert_album_embedded_tracks.cypher),
      - batch-follows their track credits so frontier artists land enriched
        with popularity/followers,
      - follows the nested album.tracks.next for >50-track albums (same
        depth, and independent of the depth gate: pagination continues a
        resource, it isn't a hop -- matching the engine's unconditional
        top-level `next` follow, which fires even at depth 0).
    All three are gated on the flag so default (liked-songs) crawls are
    byte-for-byte unchanged.
    """

    RESPONSE_KEY = "albums"
    FILE_PREFIX = "album"
    NEO4J_PARAM = "albums"
    DISK_LOCATION = DATA_DIR / "responses" / "albums"

    with open(GRAPH_DATABASE_QUERIES_DIR / "insert_batch_of_albums.cypher", "r") as f:
        CYPHER_QUERY = f.read()

    with open(GRAPH_DATABASE_QUERIES_DIR / "discovery" / "insert_album_embedded_tracks.cypher", "r") as f:
        EMBEDDED_TRACKS_CYPHER_QUERY = f.read()

    def write_to_neo4j(self, driver, database="neo4j"):
        super().write_to_neo4j(driver, database=database)
        if CRAWL_ARTIST_DISCOGRAPHIES:
            # After the albums exist, persist their embedded track lists (the
            # Cypher no-ops per album when the payload carries no tracks).
            execute_query_against_neo4j(
                query=self.__class__.EMBEDDED_TRACKS_CYPHER_QUERY,
                driver=driver,
                database=database,
                albums=self.items,
            )

    def follow_links(self):
        if CRAWL_ARTIST_DISCOGRAPHIES:
            # Albums with more than 50 tracks embed only their first page;
            # follow the nested tracks.next like the engine follows top-level
            # pagination: at the SAME depth and BEFORE the depth gate below.
            # Pagination continues a resource, it isn't a hop -- and since
            # write_to_neo4j persists the embedded first-50 regardless of
            # depth, gating this continuation on depth would silently truncate
            # >50-track albums that arrive at depth 0 (review fix). The
            # continuation is never depth-decremented, so the tracks-page
            # chain can't recurse past pagination's own end.
            for album in self.items:
                next_tracks_url = (album.get("tracks") or {}).get("next")
                if next_tracks_url:
                    SpotifyRequestFactory.request_url(
                        url=next_tracks_url,
                        depth_of_search=self.depth_of_search,
                    )

        if self.depth_of_search <= 0:
            return

        # Batch-follow the albums' own artists.
        artist_ids = [artist["id"] for album in self.items for artist in album["artists"]]

        if CRAWL_ARTIST_DISCOGRAPHIES:
            # Frontier enrichment (plan 01): the embedded track credits carry
            # collaborators that may exist nowhere else in the graph.
            # request_batch de-dups ids and Redis de-dups whole chunk URLs, so
            # already-swept artists cost nothing.
            artist_ids += [
                artist["id"]
                for album in self.items
                for track in (album.get("tracks") or {}).get("items", [])
                for artist in track["artists"]
            ]

        SpotifyRequestFactory.request_batch(
            "artists",
            artist_ids,
            depth_of_search=(self.depth_of_search - 1),
        )
