// Resolve a managed playlist by its generator identity (create-if-missing key).
MATCH (p:ManagedPlaylist {generator: $generator, params_hash: $params_hash})
RETURN
    p.spotify_id AS spotify_id,
    p.generator AS generator,
    p.params_hash AS params_hash,
    p.name AS name,
    p.owner_spotify_user_id AS owner_spotify_user_id,
    p.created_at AS created_at,
    p.last_synced AS last_synced
;
