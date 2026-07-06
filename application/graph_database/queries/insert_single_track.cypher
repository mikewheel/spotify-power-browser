WITH $track as track

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
    t.isrc = track.external_ids.isrc,
    t.album_type = track.album.album_type,
    t.linked_from_id = track.linked_from.id,
    // The track's OWN performing artists, in credit order (CREATED edges also
    // include album artists and lose order, so mastering needs this list to
    // know the primary artist).
    t.artist_ids = [artist IN track.artists | artist.id]
// Entity mastering (plan 03): refresh the enrichment fields on re-insert so
// backfills update existing nodes; coalesce so a payload that lacks a field
// can't erase a previously stored value.
ON MATCH SET
    t.isrc = coalesce(track.external_ids.isrc, t.isrc),
    t.album_type = coalesce(track.album.album_type, t.album_type),
    t.linked_from_id = coalesce(track.linked_from.id, t.linked_from_id),
    t.artist_ids = coalesce([artist IN track.artists | artist.id], t.artist_ids)

MERGE (al:Album {uri: track.album.uri})
ON CREATE SET
    al.uri = track.album.uri,
    al.id = track.album.id,
    al.name = track.album.name,
    al.release_date = track.album.release_date,
    al.release_date_precision = track.album.release_date_precision,
    al.total_tracks = track.album.total_tracks,
    al.album_type = track.album.album_type,
    al.spotify_url = track.album.external_urls.spotify,
    al.type = track.album.type,
    al.href = track.album.href

MERGE (t)<-[:CONTAINS]-(al)

// Link the artists credited on the track's album. Independent CALL subquery so
// an empty album.artists list can't drop the track's row before its own
// performing artists are linked below.
CALL (track, t, al) {
    UNWIND track.album.artists as artist
    MERGE (ar:Artist {uri: artist.uri})
    ON CREATE SET
        ar.uri = artist.uri,
        ar.id = artist.id,
        ar.name = artist.name,
        ar.spotify_url = artist.external_urls.spotify,
        ar.type = artist.type
    MERGE (t)<-[:CREATED]-(ar)
    MERGE (al)<-[:CREATED]-(ar)
}

// Link the track's own performing artists
CALL (track, t) {
    UNWIND track.artists as artist
    MERGE (ar:Artist {uri: artist.uri})
    ON CREATE SET
        ar.uri = artist.uri,
        ar.id = artist.id,
        ar.name = artist.name,
        ar.spotify_url = artist.external_urls.spotify,
        ar.type = artist.type
    MERGE (t)<-[:CREATED]-(ar)
}
;
