// Adjacent-artist discovery (plan 01 T10): the deliverable query pack.
// Surface artists you've never heard of who are structurally close to your
// taste — collaborators-of-collaborators, weighted toward the obscure.
//
// This file is a documented query pack (not executed by the pipeline).
// Queries are separated by semicolons and take $-parameters. Keep literal
// semicolons out of the comments — tooling splits on them.
//
// Multiplayer (plan 06 T2): "my taste" is the $user_id parameter traversing
// (:User)-[:LIKED] (requires migration 0001). Every query below takes
// $user_id, where null means "any user" — identical to the pre-06 behavior on a
// single-user graph.
//
// Frontier provenance: nodes the discography crawl created carry
// crawl_source = 'discography' — liked tracks are the targets of [:LIKED]
// edges, and frontier artists have crawl_source and no inbound taste edges.


// ---------------------------------------------------------------------------
// 0. Affinity distribution (plan 01 T1): how many artists qualify for a
// discography crawl at each ARTIST_AFFINITY_MIN threshold. Run this BEFORE
// the first crawl and pick the threshold whose qualifying-artist count keeps
// the projected call volume comfortable (the plan's estimate: ~1,200 artists
// = ~2,700 calls = 20-25 min). The shipped default is 3.
// Params: $user_id
// ---------------------------------------------------------------------------
MATCH (u:User)-[:LIKED]->(t:Track)<-[:CREATED]-(a:Artist)
WHERE ($user_id IS NULL OR u.id = $user_id)
WITH a, count(DISTINCT t) AS liked
WITH collect(liked) AS liked_counts
UNWIND range(1, 20) AS threshold
RETURN threshold,
       size([c IN liked_counts WHERE c >= threshold]) AS qualifying_artists
ORDER BY threshold
;

// ---------------------------------------------------------------------------
// 1a. Adjacent-artist discovery — TRACK altitude (the plan-01 deliverable).
// Rank the collab frontier by adjacency (independent liked artists bridging
// to the candidate) over popularity (lower = more interesting), with a "via"
// explanation. A collab re-released on five editions counts five times:
// inflated — prefer 1b after a mastering run.
// Params: $user_id, $max_popularity (e.g. 40), $min_bridges (e.g. 2)
// ---------------------------------------------------------------------------
MATCH (u:User)-[:LIKED]->(:Track)<-[:CREATED]-(mine:Artist)
WHERE ($user_id IS NULL OR u.id = $user_id)
WITH collect(DISTINCT mine) AS my_artists
UNWIND my_artists AS m
MATCH (m)-[:CREATED]->(t:Track)<-[:CREATED]-(cand:Artist)
WHERE NOT cand IN my_artists AND cand.popularity <= $max_popularity
WITH cand, count(DISTINCT m) AS bridges,
     collect(DISTINCT m.name)[..5] AS via
WHERE bridges >= $min_bridges
RETURN cand.name AS artist, cand.popularity AS popularity, cand.followers AS followers,
       bridges, via
ORDER BY bridges DESC, cand.popularity ASC LIMIT 50
;

// ---------------------------------------------------------------------------
// 1b. Adjacent-artist discovery — SONG altitude (adopted verbatim from the
// plan-03 pack, queries/mastering/song_altitude_queries.cypher, so the two
// packs can't drift). Collabs count as DISTINCT Songs: a single collab spread
// across a single, an album cut, and a deluxe re-release is one shared song,
// not three. Requires a `python -m application.mastering.run` pass so every
// Track has its VERSION_OF edge.
// Params: $user_id, $max_popularity, $min_bridges
// ---------------------------------------------------------------------------
MATCH (u:User)-[:LIKED]->(:Track)<-[:CREATED]-(mine:Artist)
WHERE ($user_id IS NULL OR u.id = $user_id)
WITH collect(DISTINCT mine) AS my_artists
UNWIND my_artists AS m
MATCH (m)-[:CREATED]->(t:Track)<-[:CREATED]-(cand:Artist)
MATCH (t)-[:VERSION_OF]->(s:Song)
WHERE NOT cand IN my_artists AND cand.popularity <= $max_popularity
WITH cand, count(DISTINCT m) AS bridges, count(DISTINCT s) AS shared_songs,
     collect(DISTINCT m.name)[..5] AS via
WHERE bridges >= $min_bridges
RETURN cand.name AS artist, cand.popularity AS popularity, cand.followers AS followers,
       bridges, shared_songs, via
ORDER BY bridges DESC, shared_songs DESC, cand.popularity ASC LIMIT 50
;

// ---------------------------------------------------------------------------
// 2. Bonus: normalized obscurity-weighted ranking (the plan's "tune the
// ordering" note) — bridges relative to reach, so a popularity-99 artist
// with 20 bridges no longer buries an unknown with 3.
// Params: $user_id, $max_popularity, $min_bridges
// ---------------------------------------------------------------------------
MATCH (u:User)-[:LIKED]->(:Track)<-[:CREATED]-(mine:Artist)
WHERE ($user_id IS NULL OR u.id = $user_id)
WITH collect(DISTINCT mine) AS my_artists
UNWIND my_artists AS m
MATCH (m)-[:CREATED]->(t:Track)<-[:CREATED]-(cand:Artist)
WHERE NOT cand IN my_artists AND cand.popularity <= $max_popularity
WITH cand, count(DISTINCT m) AS bridges,
     collect(DISTINCT m.name)[..5] AS via
WHERE bridges >= $min_bridges
RETURN cand.name AS artist, cand.popularity AS popularity, cand.followers AS followers,
       bridges, via,
       bridges / log(coalesce(cand.followers, 0) + 2) AS adjacency_score
ORDER BY adjacency_score DESC, cand.popularity ASC LIMIT 50
;
