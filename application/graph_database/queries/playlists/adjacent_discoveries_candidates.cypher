// The plan 01 §Design discovery query, VERBATIM (ranked candidate artists —
// collaborators-of-collaborators weighted toward the obscure). Kept here
// unchanged as the reference the playlist projection in
// adjacent_discoveries_tracks.cypher derives from; plan 01's own
// implementation should unify with (and own) this file when it lands.
//
// Note the verbatim popularity filter drops null-popularity artists
// (null <= $max_popularity is null); the playlist projection deliberately
// includes-and-flags them instead.
MATCH (mine:Artist)-[:CREATED]->(:Track {liked_songs: true})
WITH collect(DISTINCT mine) AS my_artists
UNWIND my_artists AS m
MATCH (m)-[:CREATED]->(t:Track)<-[:CREATED]-(cand:Artist)
WHERE NOT cand IN my_artists AND cand.popularity <= $max_popularity
WITH cand, count(DISTINCT m) AS bridges,
     collect(DISTINCT m.name)[..5] AS via
WHERE bridges >= $min_bridges
RETURN cand.name, cand.popularity, cand.followers, bridges, via
ORDER BY bridges DESC, cand.popularity ASC LIMIT 50
