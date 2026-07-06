// Overlap pack (plan 06 T9): shared artists, weighted by BOTH users'
// affection — the "you like EDM, I like EDM, where do we agree" ranking.
//
// An artist is shared when both users have liked at least one track carrying
// that artist's CREATED credit. mutual_depth (the smaller of the two liked
// counts) ranks by how deep the SHARED affection runs: an artist one user
// adores and the other tried once ranks below one both keep coming back to.
//
// This file is a documented query pack (not executed by the pipeline).
// Queries take $-parameters. No literal semicolons in these comments —
// tooling splits this file on them.
// Requires migration 0001 (ownership as (:User)-[:LIKED]).
//
// Params: $a, $b (the two Spotify user ids)
MATCH (:User {id: $a})-[:LIKED]->(ta:Track)<-[:CREATED]-(ar:Artist)
WITH ar, count(DISTINCT ta) AS a_likes
MATCH (:User {id: $b})-[:LIKED]->(tb:Track)<-[:CREATED]-(ar)
WITH ar, a_likes, count(DISTINCT tb) AS b_likes
RETURN ar.name AS artist,
       ar.id AS artist_id,
       a_likes,
       b_likes,
       CASE WHEN a_likes < b_likes THEN a_likes ELSE b_likes END AS mutual_depth,
       a_likes + b_likes AS combined_likes
ORDER BY mutual_depth DESC, combined_likes DESC, artist ASC
LIMIT 100
;
