// The plan 01 §Design discovery query (ranked candidate artists —
// collaborators-of-collaborators weighted toward the obscure). Kept here
// unchanged as the reference the playlist projection in
// adjacent_discoveries_tracks.cypher derives from; plan 01's own
// implementation should unify with (and own) this file when it lands.
//
// Multiplayer (plan 06 T2): the liked_songs:true node flag became the
// (:User)-[:LIKED] relationship (migration 0001), so "my taste" is now the
// $user_id parameter. Null = "any user" (legacy single-user graphs).
//
// Note the verbatim popularity filter drops null-popularity artists
// (null <= $max_popularity is null); the playlist projection deliberately
// includes-and-flags them instead.
MATCH (u:User)-[:LIKED]->(:Track)<-[:CREATED]-(mine:Artist)
WHERE ($user_id IS NULL OR u.id = $user_id)
WITH collect(DISTINCT mine) AS my_artists
UNWIND my_artists AS m
MATCH (m)-[:CREATED]->(t:Track)<-[:CREATED]-(cand:Artist)
WHERE NOT cand IN my_artists AND cand.popularity <= $max_popularity
WITH cand, count(DISTINCT m) AS bridges,
     collect(DISTINCT m.name)[..5] AS via
WHERE bridges >= $min_bridges
RETURN cand.name, cand.popularity, cand.followers, bridges, via
ORDER BY bridges DESC, cand.popularity ASC LIMIT 50
