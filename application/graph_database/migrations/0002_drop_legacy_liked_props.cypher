// Migration 0002 — drop the legacy liked-songs node properties (plan 06 T1
// deprecation plan). ***STUB — DO NOT RUN YET.***
//
// 0001_multiplayer_ownership.cypher kept Track.liked_songs /
// Track.date_added_to_liked_songs (and the Album/Artist liked_songs flags)
// for one release as the rollback path. Run THIS migration only when ALL of
// the following are true:
//
//   1. 0001 has been run for every authorized user's data,
//   2. every query pack in this repo reads (:User)-[:LIKED] (done in plan 06
//      T2 — grep 'liked_songs: true' returns nothing executable),
//   3. the MCP server branch (plan 05) has shipped its matching rewrite (see
//      docs/multiplayer-runbook.md "Follow-ups on other branches"),
//   4. one full release has passed without needing the rollback.
//
//   python3 -m application.graph_database.migrations.run 0002_drop_legacy_liked_props
//
// Idempotent: REMOVE on an absent property is a no-op.

MATCH (t:Track) WHERE t.liked_songs IS NOT NULL
REMOVE t.liked_songs, t.date_added_to_liked_songs
;

MATCH (al:Album) WHERE al.liked_songs IS NOT NULL
REMOVE al.liked_songs
;

MATCH (ar:Artist) WHERE ar.liked_songs IS NOT NULL
REMOVE ar.liked_songs
;
