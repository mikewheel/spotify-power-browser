// Record a playlist this system created (plan 08). Every playlist the sync
// module is allowed to touch MUST have one of these nodes — that is the
// managed-only hard guard's source of truth.
//
// Plan 06 (multiplayer) landed the (:User) ownership layer: new managed
// playlists are anchored (:User {id: owner_spotify_user_id})-[:HAS_MANAGED]->
// at insert time (below), and migration 0001_multiplayer_ownership re-linked
// the ones created before plan 06. The owner_spotify_user_id property stays —
// it is the insert's source value and the legacy-compat handle.
WITH $playlist AS playlist

MERGE (p:ManagedPlaylist {spotify_id: playlist.spotify_id})
ON CREATE SET
    p.spotify_id = playlist.spotify_id,
    p.generator = playlist.generator,
    p.params_hash = playlist.params_hash,
    p.name = playlist.name,
    p.owner_spotify_user_id = playlist.owner_spotify_user_id,
    p.created_at = playlist.created_at

MERGE (owner:User {id: playlist.owner_spotify_user_id})
MERGE (owner)-[:HAS_MANAGED]->(p)
;
