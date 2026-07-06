// Adjacent-artist discovery (plan 01): persist the track lists a Get Several
// Albums response embeds (album.tracks.items, first 50 per album). This is
// how the collab frontier materializes: each simplified track carries its own
// artists array, and MERGE creates stub Artist nodes for collaborators the
// graph has never seen (enriched later by the batched /v1/artists?ids= sweep).
//
// Simplified track objects have no external_ids/album/popularity fields, so
// only what's present is set; the coalesce(payload, existing) ON MATCH pattern
// (plan 03) keeps previously stored enrichment intact. Nodes created here are
// tagged crawl_source = 'discography' (liked tracks are the targets of
// (:User)-[:LIKED] edges since plan 06 — legacy graphs also still carry the
// deprecated liked_songs flag until migration 0002 runs — while frontier
// nodes have crawl_source and no inbound taste edges).
UNWIND $albums as album

MATCH (al:Album {uri: album.uri})

// UNWIND of a missing/empty list yields no rows, which is the correct no-op
// for an album object that carries no embedded tracks.
UNWIND album.tracks.items as track

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
    t.album_type = album.album_type,
    t.artist_ids = [artist IN track.artists | artist.id],
    t.crawl_source = 'discography'
ON MATCH SET
    t.album_type = coalesce(album.album_type, t.album_type),
    t.artist_ids = coalesce([artist IN track.artists | artist.id], t.artist_ids)

MERGE (t)<-[:CONTAINS]-(al)

// Link the track's performing artists (the collab frontier). Scoped CALL
// subquery so one track's empty artists list can't drop sibling rows.
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
