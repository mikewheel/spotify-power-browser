// Record a playlist this system created (plan 08). Every playlist the sync
// module is allowed to touch MUST have one of these nodes — that is the
// managed-only hard guard's source of truth.
//
// Anchored standalone for now: the (:User) node does not exist until plan 06
// lands, so ownership is carried by the owner_spotify_user_id property. When
// plan 06 introduces (:User), re-link this as
// (:User {id: owner_spotify_user_id})-[:HAS_MANAGED]->(:ManagedPlaylist).
WITH $playlist AS playlist

MERGE (p:ManagedPlaylist {spotify_id: playlist.spotify_id})
ON CREATE SET
    p.spotify_id = playlist.spotify_id,
    p.generator = playlist.generator,
    p.params_hash = playlist.params_hash,
    p.name = playlist.name,
    p.owner_spotify_user_id = playlist.owner_spotify_user_id,
    p.created_at = playlist.created_at
;
