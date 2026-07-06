// The managed-only hard guard (plan 08): before mutating a playlist, sync
// resolves its Spotify id through this query. No node => refuse and raise —
// hand-made playlists are constitutionally untouchable.
MATCH (p:ManagedPlaylist {spotify_id: $spotify_id})
RETURN
    p.spotify_id AS spotify_id,
    p.generator AS generator,
    p.params_hash AS params_hash,
    p.name AS name,
    p.owner_spotify_user_id AS owner_spotify_user_id,
    p.created_at AS created_at,
    p.last_synced AS last_synced
;
