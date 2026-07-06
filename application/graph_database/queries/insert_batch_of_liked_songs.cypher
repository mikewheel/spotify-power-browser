// Iterate over a list of tracks
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
    t.isrc = track.external_ids.isrc,
    t.album_type = track.album.album_type,
    t.linked_from_id = track.linked_from.id,
    t.liked_songs = true,
    t.date_added_to_liked_songs = track.added_at
ON MATCH SET
    t.liked_songs = true,
    t.date_added_to_liked_songs = track.added_at,
    // Entity mastering (plan 03): refresh the enrichment fields on re-insert so
    // backfills update existing nodes; coalesce so a payload that lacks a field
    // can't erase a previously stored value.
    t.isrc = coalesce(track.external_ids.isrc, t.isrc),
    t.album_type = coalesce(track.album.album_type, t.album_type),
    t.linked_from_id = coalesce(track.linked_from.id, t.linked_from_id)

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
    al.href = track.album.href,
    al.liked_songs = true
ON MATCH SET
    al.liked_songs = true

MERGE (t)<-[:CONTAINS]-(al)

// Inner for loop over artists in track's album
WITH track UNWIND track.album.artists as artist

MATCH (t:Track {uri: track.uri})
MATCH (al:Album {uri: track.album.uri})

MERGE (ar:Artist {uri: artist.uri})
ON CREATE SET
    ar.uri = artist.uri,
    ar.id = artist.id,
    ar.name = artist.name,
    ar.spotify_url = artist.external_urls.spotify,
    ar.type = artist.type,
    ar.liked_songs = true
ON MATCH SET
    ar.liked_songs = true

MERGE (t)<-[:CREATED]-(ar)
MERGE (al)<-[:CREATED]-(ar)

// Inner for loop over track's own artists
WITH track UNWIND track.artists as artist

MATCH (t:Track {uri: track.uri})

MERGE (ar:Artist {uri: artist.uri})
ON CREATE SET
    ar.uri = artist.uri,
    ar.id = artist.id,
    ar.name = artist.name,
    ar.spotify_url = artist.external_urls.spotify,
    ar.type = artist.type,
    ar.liked_songs = true
ON MATCH SET
    ar.liked_songs = true

MERGE (t)<-[:CREATED]-(ar)
;