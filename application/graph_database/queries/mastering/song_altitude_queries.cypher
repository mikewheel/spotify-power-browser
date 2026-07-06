// Entity mastering (plan 03 T8): the plan-01 (discovery) and plan-02
// (completeness) deliverable queries, documented at BOTH altitudes.
//
// Track altitude = release-level truth: every distinct Spotify track id
// counts. Song altitude = listener-level truth: aggregate through
// (:Track)-[:VERSION_OF]->(:Song) so re-releases collapse. Every Track has
// exactly one VERSION_OF after `python -m application.mastering.run`, so the
// two altitudes cover the same tracks — pick per question.
//
// This file is a documented query pack (not executed by the pipeline).
// Queries are separated by semicolons and take $-parameters. Keep literal
// semicolons out of the comments — tooling splits on them.
//
// Multiplayer (plan 06 T2): 1a/1b take $user_id and traverse
// (:User)-[:LIKED] (migration 0001) — null = "any user". 2a/2b were already
// forward-written against (:User) with the $me param (plan 02's naming) —
// both conventions resolve to the same (:User {id}) anchor.


// ---------------------------------------------------------------------------
// 1a. Adjacent-artist discovery (plan 01 deliverable) — TRACK altitude.
// A collab re-released on five editions counts five times: inflated.
// Params: $user_id, $max_popularity (e.g. 40), $min_bridges (e.g. 3)
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
// 1b. Adjacent-artist discovery — SONG altitude (the plan-03 improvement).
// Collabs are counted as DISTINCT Songs, so a single collab spread across a
// single, an album cut, and a deluxe re-release is one shared song, not
// three. shared_songs ranks candidates by real overlap depth.
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
// 2a. Artist listening completeness (plan 02 deliverable) — TRACK altitude.
// A deluxe album shows ~30% "unheard" when you have heard every song,
// because each re-released track counts as its own unheard item.
// NOTE: (:User) and [:LISTENED_TO {ms_total}] land with plan 02 — this query
// pack is forward-written for that schema.
// Params: $me (user id)
// ---------------------------------------------------------------------------
MATCH (a:Artist)-[:CREATED]->(t:Track)
OPTIONAL MATCH (u:User {id: $me})-[l:LISTENED_TO]->(t)
WHERE l.ms_total >= 30000
WITH a, count(DISTINCT t) AS catalog, count(DISTINCT l) AS heard
WHERE catalog >= 10
RETURN a.name AS artist, heard, catalog,
       toFloat(heard) / catalog AS completeness
ORDER BY completeness ASC
;

// ---------------------------------------------------------------------------
// 2b. Artist listening completeness — SONG altitude (the plan-03 improvement).
// "Songs heard", not "releases heard": a Song counts as heard when ANY of its
// versions has a meaningful (>=30s) listen.
// Params: $me (user id)
// ---------------------------------------------------------------------------
MATCH (a:Artist)-[:CREATED]->(:Track)-[:VERSION_OF]->(s:Song)
WITH DISTINCT a, s
OPTIONAL MATCH (u:User {id: $me})-[l:LISTENED_TO]->(:Track)-[:VERSION_OF]->(s)
WHERE l.ms_total >= 30000
WITH a, s, count(l) > 0 AS heard
WITH a, count(s) AS catalog, sum(CASE WHEN heard THEN 1 ELSE 0 END) AS heard
WHERE catalog >= 10
RETURN a.name AS artist, heard, catalog,
       toFloat(heard) / catalog AS completeness
ORDER BY completeness ASC
;

// ---------------------------------------------------------------------------
// 3. Bonus: Bloom / exploration at Song altitude — the visible-hairball fix.
// One row per Song with its version fan-out, most-duplicated first: a direct
// view of what mastering rolled up (and a sanity check after each run).
// ---------------------------------------------------------------------------
MATCH (t:Track)-[v:VERSION_OF]->(s:Song)
WITH s, count(t) AS versions, collect(DISTINCT v.kind) AS kinds
WHERE versions > 1
RETURN s.id AS song_id, s.title AS title, versions, kinds
ORDER BY versions DESC, title
;
