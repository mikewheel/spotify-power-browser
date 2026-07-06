// Overlap pack (plan 06 T9): the BRIDGE PLAYLIST — the plan's kicker query.
// Candidate artists in BOTH users' collab frontiers (plan 01 adjacency,
// computed per user, then intersected), contributing tracks NEITHER user has
// liked yet: music that is new to both of you AND structurally close to both
// of your tastes at once.
//
// Frontier(U) = artists who are not in U's liked-artist set but co-created
// tracks with at least $min_bridges of U's liked artists (the plan-01
// discovery ranking, per user). The bridge = Frontier(A) ∩ Frontier(B),
// ranked by combined adjacency — each candidate contributes one deterministic
// representative track no one has liked.
//
// Documented query pack (not executed by the pipeline — the plan-06 follow-up
// registers this as plan 08's `blend` generator + the MCP `shared_taste`
// tool). Requires migration 0001 and both users' crawls (and ideally
// a discography crawl so the frontier is rich).
//
// Params: $a, $b, $min_bridges (independent liked-artist paths per user, e.g. 2)

// --- user A's liked-artist set ---
MATCH (:User {id: $a})-[:LIKED]->(:Track)<-[:CREATED]-(ma:Artist)
WITH collect(DISTINCT ma) AS a_artists
// --- user B's liked-artist set ---
MATCH (:User {id: $b})-[:LIKED]->(:Track)<-[:CREATED]-(mb:Artist)
WITH a_artists, collect(DISTINCT mb) AS b_artists

// --- A's frontier: adjacency from A's artists to unknown candidates ---
UNWIND a_artists AS m_a
MATCH (m_a)-[:CREATED]->(:Track)<-[:CREATED]-(cand:Artist)
WHERE NOT cand IN a_artists AND NOT cand IN b_artists
WITH b_artists, cand, count(DISTINCT m_a) AS a_bridges
WHERE a_bridges >= $min_bridges

// --- ∩ B's frontier: the same candidate must bridge from B's side too ---
UNWIND b_artists AS m_b
MATCH (m_b)-[:CREATED]->(:Track)<-[:CREATED]-(cand)
WITH cand, a_bridges, count(DISTINCT m_b) AS b_bridges
WHERE b_bridges >= $min_bridges
WITH cand, a_bridges, b_bridges
ORDER BY a_bridges + b_bridges DESC, cand.popularity ASC, cand.id ASC
LIMIT 50

// --- one representative track per candidate that NEITHER user liked
//     (id tie-breaker keeps the playlist order deterministic across runs) ---
CALL (cand) {
    MATCH (cand)-[:CREATED]->(ct:Track)
    WHERE NOT EXISTS {
        MATCH (u:User)-[:LIKED]->(ct)
        WHERE u.id IN [$a, $b]
    }
    RETURN ct
    ORDER BY ct.id ASC
    LIMIT 1
}

RETURN ct.id AS track_id,
       ct.name AS track_name,
       cand.name AS artist,
       a_bridges,
       b_bridges,
       a_bridges + b_bridges AS bridge_total,
       (cand.popularity IS NULL) AS popularity_unknown
ORDER BY bridge_total DESC, cand.popularity ASC, cand.id ASC
;
