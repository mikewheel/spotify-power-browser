// Adjacent-artist discovery (plan 01): the discography-crawl seed worklist —
// every artist with at least $affinity_min liked tracks. CREATED edges to a
// liked track include both the track's performing artists and its album's
// artists, which is deliberate: an album artist you keep liking tracks from
// is taste-adjacent even when they aren't the per-track credit.
MATCH (ar:Artist)-[:CREATED]->(t:Track {liked_songs: true})
WITH ar, count(DISTINCT t) AS liked_tracks
WHERE liked_tracks >= $affinity_min AND ar.id IS NOT NULL
RETURN ar.id AS id, liked_tracks
ORDER BY liked_tracks DESC, id
;
