// Adjacent-artist discovery (plan 01): persist one page of GET
// /v1/albums/{id}/tracks — only reached for albums whose track list paginates
// past the 50 tracks embedded in a batch-album response. Same shape and
// provenance rules as insert_album_embedded_tracks.cypher.
//
// The album node normally exists already (created by the batch-album insert),
// but the response workers consume queues independently, so MERGE by the
// deterministic uri (spotify:album:{id}) tolerates out-of-order arrival.
MERGE (al:Album {uri: $album_uri})
ON CREATE SET
    al.uri = $album_uri,
    al.id = $album_id,
    al.crawl_source = 'discography'

WITH al
UNWIND $tracks as track

MERGE (t:Track {uri: track.uri})
ON CREATE SET
    t.uri = track.uri,
    t.id = track.id,
    t.name = track.name,
    t.explicit = track.explicit,
    t.is_local = track.is_local,
    t.duration_ms = track.duration_ms,
    t.type = track.type,
    t.href = track.href,
    t.spotify_url = track.external_urls.spotify,
    t.artist_ids = [artist IN track.artists | artist.id],
    t.crawl_source = 'discography'
ON MATCH SET
    t.artist_ids = coalesce([artist IN track.artists | artist.id], t.artist_ids)

MERGE (t)<-[:CONTAINS]-(al)

CALL (track, t) {
    UNWIND track.artists as artist
    MERGE (ar:Artist {uri: artist.uri})
    ON CREATE SET
        ar.uri = artist.uri,
        ar.id = artist.id,
        ar.name = artist.name,
        ar.spotify_url = artist.external_urls.spotify,
        ar.type = artist.type,
        ar.crawl_source = 'discography'
    MERGE (t)<-[:CREATED]-(ar)
}
;
