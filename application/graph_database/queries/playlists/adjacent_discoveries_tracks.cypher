// Playlist projection of the plan 01 §Design discovery query (kept verbatim
// in adjacent_discoveries_candidates.cypher): identical adjacency ranking,
// but a playlist needs TRACK ids, so each ranked candidate contributes one
// representative track — preferring one the user hasn't liked. Unify with
// plan 01's implementation when it lands.
//
// Multiplayer (plan 06 T2): "liked" is the (:User)-[:LIKED] relationship
// (migration 0001). $user_id scopes both the taste seed AND the
// already-liked exclusion. Null = "any user": on a single-user graph this is
// exactly the old behavior, and on a shared graph it means "liked by anyone".
//
// Deliberate deltas from the verbatim query, all playlist-serving:
//   - degrades gracefully before the popularity backfill (plan 01 T2): null
//     Artist.popularity = unknown -> INCLUDED and flagged via
//     popularity_unknown (nulls sort last in ascending order, so unknowns
//     rank after known-popularity candidates at the same bridge count)
//   - cand.id tie-breaker so the target order is deterministic across runs
//     (an order-significant playlist must not shuffle on ranking ties)
MATCH (u:User)-[:LIKED]->(:Track)<-[:CREATED]-(mine:Artist)
WHERE ($user_id IS NULL OR u.id = $user_id)
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

// One representative track per candidate: prefer a track the user has NOT
// liked (a discovery playlist shouldn't feed you your own likes back), id as
// the deterministic tie-breaker. Input row order is preserved through CALL.
CALL (cand) {
    MATCH (cand)-[:CREATED]->(ct:Track)
    RETURN ct
    ORDER BY EXISTS {
        MATCH (lu:User)-[:LIKED]->(ct)
        WHERE ($user_id IS NULL OR lu.id = $user_id)
    } ASC, ct.id ASC
    LIMIT 1
}

RETURN
    ct.id AS track_id,
    cand.name AS artist_name,
    (cand.popularity IS NULL) AS popularity_unknown
;
