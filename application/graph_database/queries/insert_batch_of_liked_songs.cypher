// Iterate over a list of tracks.
//
// Multiplayer (plan 06 T5): $user_id carries the envelope's user. When known,
// ownership is written as (:User {id})-[:LIKED {added_at}]->(:Track) — the
// FOREACH-over-conditional-list idiom below no-ops when $user_id is null, so
// legacy messages (no user_id) keep the exact pre-multiplayer write. The
// legacy node props (liked_songs / date_added_to_liked_songs, incl. the
// Album/Artist flags) are ONLY written in legacy mode ($user_id null): they
// are the single-user rollback dataset for migration 0001, and a per-user
// crawl writing them would corrupt it into a cross-user union with
// last-writer-wins timestamps (and re-arm the 0001-rerun misattribution).
// Per-user crawls write ONLY the (:User)-[:LIKED] layer. The props are kept
// for one release (rollback window — dropped by migration
// 0002_drop_legacy_liked_props when its preconditions hold).
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
    // The track's OWN performing artists, in credit order (CREATED edges also
    // include album artists and lose order, so mastering needs this list to
    // know the primary artist).
    t.artist_ids = [artist IN track.artists | artist.id],
    // Legacy rollback props: legacy mode only (SET to null is a no-op).
    t.liked_songs = CASE WHEN $user_id IS NULL THEN true ELSE null END,
    t.date_added_to_liked_songs = CASE WHEN $user_id IS NULL THEN track.added_at ELSE null END
ON MATCH SET
    // Legacy rollback props: preserved verbatim under per-user crawls.
    t.liked_songs = CASE WHEN $user_id IS NULL THEN true ELSE t.liked_songs END,
    t.date_added_to_liked_songs =
        CASE WHEN $user_id IS NULL THEN track.added_at ELSE t.date_added_to_liked_songs END,
    // Entity mastering (plan 03): refresh the enrichment fields on re-insert so
    // backfills update existing nodes; coalesce so a payload that lacks a field
    // can't erase a previously stored value.
    t.isrc = coalesce(track.external_ids.isrc, t.isrc),
    t.album_type = coalesce(track.album.album_type, t.album_type),
    t.linked_from_id = coalesce(track.linked_from.id, t.linked_from_id),
    t.artist_ids = coalesce([artist IN track.artists | artist.id], t.artist_ids)

// Ownership relationship (plan 06): no-op when $user_id is null.
FOREACH (uid IN CASE WHEN $user_id IS NULL THEN [] ELSE [$user_id] END |
    MERGE (u:User {id: uid})
    MERGE (u)-[l:LIKED]->(t)
    SET l.added_at = track.added_at
)

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
    al.liked_songs = CASE WHEN $user_id IS NULL THEN true ELSE null END
ON MATCH SET
    al.liked_songs = CASE WHEN $user_id IS NULL THEN true ELSE al.liked_songs END

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
    ar.liked_songs = CASE WHEN $user_id IS NULL THEN true ELSE null END
ON MATCH SET
    ar.liked_songs = CASE WHEN $user_id IS NULL THEN true ELSE ar.liked_songs END

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
    ar.liked_songs = CASE WHEN $user_id IS NULL THEN true ELSE null END
ON MATCH SET
    ar.liked_songs = CASE WHEN $user_id IS NULL THEN true ELSE ar.liked_songs END

MERGE (t)<-[:CREATED]-(ar)
;