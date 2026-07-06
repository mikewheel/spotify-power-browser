// Overlap pack (plan 06 T9): "A loves, B never heard" — artists user A keeps
// coming back to that user B has ZERO liked tracks from. The recommendation
// seed for a blend session ("here's what I'd play you first").
//
// "Never heard" is currently approximated by "never liked": true
// listened-but-not-liked knowledge needs plan 02's (:User)-[:DID]->(:Play)
// history — when that lands, tighten the NOT EXISTS to exclude played artists
// too (and this comment is the marker to find).
//
// Documented query pack (not executed by the pipeline). Requires migration
// 0001.
//
// Params: $a, $b, $min_likes (how much affection counts as "loves", e.g. 3)
MATCH (:User {id: $a})-[:LIKED]->(t:Track)<-[:CREATED]-(ar:Artist)
WITH ar, count(DISTINCT t) AS a_likes, collect(DISTINCT t.name)[..3] AS sample_tracks
WHERE a_likes >= $min_likes
  AND NOT EXISTS {
      MATCH (:User {id: $b})-[:LIKED]->(:Track)<-[:CREATED]-(ar)
  }
RETURN ar.name AS artist,
       ar.id AS artist_id,
       a_likes,
       sample_tracks
ORDER BY a_likes DESC, artist ASC
LIMIT 50
;
