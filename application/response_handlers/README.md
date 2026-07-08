# response_handlers/ — one class per Spotify endpoint

When a Spotify response comes off the queue, exactly one handler class knows
what to do with it. A handler answers three questions about its endpoint:
*where does this go on disk*, *which Cypher writes it to the graph*, and
*which links inside it are worth crawling next*.

## How dispatch works

[main.py](main.py) is the worker entry point
(`python3 main.py write_to_disk|write_to_neo4j|follow_links`). Its
`SpotifyResponseController.resolve_handler(url)` maps a URL to a class:

| URL shape | Handler | Notes |
|---|---|---|
| `/v1/me/tracks` | [me/my_liked_songs.py](me/my_liked_songs.py) `LikedSongsPlaylist…` | The crawl's usual starting point; writes `LIKED` edges per user |
| `/v1/tracks/{id}`, `/v1/albums/{id}`, `/v1/artists/{id}` | [tracks/single_track.py](tracks/single_track.py), [albums/single_album.py](albums/single_album.py), [artists/single_artist.py](artists/single_artist.py) | The per-item path (`USE_BATCH_ENDPOINTS=false`) |
| `/v1/tracks?ids=…`, `/v1/albums?ids=…`, `/v1/artists?ids=…` | [tracks/several_tracks.py](tracks/several_tracks.py), [albums/several_albums.py](albums/several_albums.py), [artists/several_artists.py](artists/several_artists.py) | The batch path (~22× fewer API calls) |
| `/v1/artists/{id}/albums` | [artists/albums_of_artist.py](artists/albums_of_artist.py) | Discography crawl: harvests album IDs, defers content to the batch handler |
| `/v1/albums/{id}/tracks` | [albums/tracks_of_album.py](albums/tracks_of_album.py) | Only for albums with >50 tracks (paginated track lists) |
| `/v1/me/playlists`, `/v1/me/following` | [me/my_followed_playlists.py](me/my_followed_playlists.py), [me/my_followed_artists.py](me/my_followed_artists.py) | **Not implemented** — placeholders for plan 02 |

[base_handler.py](base_handler.py) defines the interface;
[batch_handler.py](batch_handler.py) adds shared logic for the `?ids=`
endpoints (chunking, per-item disk writes, frontier-artist sweeps).

## Depth, in one paragraph

Every message carries `depth_of_search`. Handlers re-queue *neighbors* (albums,
artists found inside a response) at **depth − 1**; pagination (`next` links)
continues at the **same** depth because page 2 is the same resource, not a
hop. Depth 0 means "persist this, follow nothing." The discography crawl
seeds at depth 2 → albums fetched at depth 1 → collaborating "frontier"
artists enriched at depth 0, and nothing on that path ever emits another
discography URL — that invariant is what keeps the crawl finite. See
[docs/architecture.md](../../docs/architecture.md#level-3-inside-the-pipeline).

`write_to_sqlite()` on every handler is an unimplemented stub from the early
days (flag off; see ROADMAP).
