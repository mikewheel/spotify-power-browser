// Adjacent-artist discovery (plan 01): the discography-crawl seed worklist —
// every artist with at least $affinity_min liked tracks. CREATED edges to a
// liked track include both the track's performing artists and its album's
// artists, which is deliberate: an album artist you keep liking tracks from
// is taste-adjacent even when they aren't the per-track credit.
//
// Multiplayer (plan 06 T2): "liked" is the (:User)-[:LIKED] relationship
// (requires migration 0001). $user_id scopes the seed list to one user's
// taste — null means "any user", identical to the old behavior on a
// single-user graph, and the union of everyone's taste on a shared one.
MATCH (u:User)-[:LIKED]->(t:Track)<-[:CREATED]-(ar:Artist)
WHERE ($user_id IS NULL OR u.id = $user_id)
WITH ar, count(DISTINCT t) AS liked_tracks
WHERE liked_tracks >= $affinity_min AND ar.id IS NOT NULL
RETURN ar.id AS id, liked_tracks
ORDER BY liked_tracks DESC, id
;
