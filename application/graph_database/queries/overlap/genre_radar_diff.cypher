// Overlap pack (plan 06 T9): genre radar diff — per-genre liked-track counts
// for both users side by side, plus each user's share of their own library in
// that genre. Feed the shares to a radar chart (or Claude) to see WHERE two
// EDM-likers actually diverge.
//
// Genres attach to Artists ((:Artist)-[:SPOTIFY_CLASSIFIED_AS]->(:Genre), the
// insert-artist Cyphers), so a track counts toward a genre through any of its
// crediting artists. share_* normalizes by the user's own total liked-track
// count: absolute counts are library-size-biased, shares are comparable.
//
// Documented query pack (not executed by the pipeline). Requires migration
// 0001, and genre coverage improves after the artist enrichment sweep
// (simplified track credits carry no genres until then).
//
// Params: $a, $b
MATCH (ua:User {id: $a})
MATCH (ub:User {id: $b})
OPTIONAL MATCH (ua)-[:LIKED]->(ta:Track)
WITH ua, ub, count(DISTINCT ta) AS a_total
OPTIONAL MATCH (ub)-[:LIKED]->(tb:Track)
WITH ua, ub, a_total, count(DISTINCT tb) AS b_total

MATCH (g:Genre)
OPTIONAL MATCH (ua)-[:LIKED]->(gta:Track)<-[:CREATED]-(:Artist)-[:SPOTIFY_CLASSIFIED_AS]->(g)
WITH ub, a_total, b_total, g, count(DISTINCT gta) AS a_likes
OPTIONAL MATCH (ub)-[:LIKED]->(gtb:Track)<-[:CREATED]-(:Artist)-[:SPOTIFY_CLASSIFIED_AS]->(g)
WITH a_total, b_total, g, a_likes, count(DISTINCT gtb) AS b_likes
WHERE a_likes > 0 OR b_likes > 0

RETURN g.name AS genre,
       a_likes,
       b_likes,
       CASE WHEN a_total = 0 THEN 0.0 ELSE toFloat(a_likes) / a_total END AS a_share,
       CASE WHEN b_total = 0 THEN 0.0 ELSE toFloat(b_likes) / b_total END AS b_share,
       abs(CASE WHEN a_total = 0 THEN 0.0 ELSE toFloat(a_likes) / a_total END
           - CASE WHEN b_total = 0 THEN 0.0 ELSE toFloat(b_likes) / b_total END)
           AS divergence
ORDER BY divergence DESC, genre ASC
;
