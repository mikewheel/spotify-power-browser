// Playlist projection of the plan 01 §Design discovery query (kept verbatim
// in adjacent_discoveries_candidates.cypher): identical adjacency ranking,
// but a playlist needs TRACK ids, so each ranked candidate contributes one
// representative track — preferring one the library hasn't liked. Unify with
// plan 01's implementation when it lands.
//
// Deliberate deltas from the verbatim query, all playlist-serving:
//   - degrades gracefully before the popularity backfill (plan 01 T2): null
//     Artist.popularity = unknown -> INCLUDED and flagged via
//     popularity_unknown (nulls sort last in ascending order, so unknowns
//     rank after known-popularity candidates at the same bridge count)
//   - cand.id tie-breaker so the target order is deterministic across runs
//     (an order-significant playlist must not shuffle on ranking ties)
MATCH (mine:Artist)-[:CREATED]->(:Track {liked_songs: true})
WITH collect(DISTINCT mine) AS my_artists
UNWIND my_artists AS m
MATCH (m)-[:CREATED]->(t:Track)<-[:CREATED]-(cand:Artist)
WHERE NOT cand IN my_artists
  AND (cand.popularity IS NULL OR cand.popularity <= $max_popularity)
WITH cand, count(DISTINCT m) AS bridges
WHERE bridges >= $min_bridges
WITH cand, bridges
ORDER BY bridges DESC, cand.popularity ASC, cand.id ASC
LIMIT 50

// One representative track per candidate: prefer a track the library has NOT
// liked (a discovery playlist shouldn't feed you your own likes back), id as
// the deterministic tie-breaker. Input row order is preserved through CALL.
CALL (cand) {
    MATCH (cand)-[:CREATED]->(ct:Track)
    RETURN ct
    ORDER BY (ct.liked_songs IS NOT NULL) ASC, ct.id ASC
    LIMIT 1
}

RETURN
    ct.id AS track_id,
    cand.name AS artist_name,
    (cand.popularity IS NULL) AS popularity_unknown
;
