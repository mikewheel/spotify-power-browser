// Migration 0001 — multiplayer ownership (plan 06 T1).
//
// Ownership becomes a relationship: user-ness moves off node properties
// (liked_songs: true, date_added_to_liked_songs) onto an explicit
//   (:User {id, display_name, added_at})-[:LIKED {added_at}]->(:Track)
// layer, so a second user's crawl can share every catalog node while keeping
// their own relationship layer distinct.
//
// Run AFTER the User uniqueness constraint exists (it ships in
// apply_uniqueness_constraints_to_nodes.cypher, applied automatically by the
// write_to_neo4j worker on startup, or manually via
// application/graph_database/initialize_database_environment.py), then:
//
//   python3 -m application.graph_database.migrations.run 0001_multiplayer_ownership \
//       --me <your_spotify_user_id> [--display-name "Your Name"]
//
// (--me defaults to the primary user recorded by the multi-user OAuth flow,
// when one exists.)
//
// Idempotent ONLY on a still-single-user graph: every statement is
// MERGE-based and the LIKED added_at SET coalesces (never clobbers), so
// re-running is safe UNTIL another user's (:User)-[:LIKED] layer exists.
// Past that point the runner ABORTS: per-user crawls could have flagged
// their own tracks liked_songs=true, and statement 2 would gift those to
// $me. 0001 is strictly a pre-multiplayer migration (guard in run.py).
//
// ROLLBACK / DEPRECATION PLAN: the legacy node properties (Track.liked_songs,
// Track.date_added_to_liked_songs, and the Album/Artist liked_songs flags)
// are DELIBERATELY KEPT for one release so this migration can be rolled back
// by simply ignoring the new (:User) layer. The cleanup that drops them is
// 0002_drop_legacy_liked_props.cypher — do not run it until every query pack
// and the MCP server branch have been confirmed on the (:User)-[:LIKED]
// traversal.
//
// Params (injected by the runner):
//   $me            the Spotify user id the existing single-user data belongs to
//   $display_name  optional display name for the User node (null to skip)
//   $added_at      the migration timestamp (ISO 8601), stamped on a new User

// 1. The user node. added_at records when this user joined THIS graph.
MERGE (u:User {id: $me})
ON CREATE SET u.added_at = $added_at
SET u.display_name = coalesce($display_name, u.display_name)
;

// 2. Liked songs: node flag -> (:User)-[:LIKED {added_at}] relationship.
//    added_at carries the Spotify library timestamp forward, preserving the
//    "when did I like this" signal per user instead of per node. coalesce:
//    a re-run must never overwrite an already-lifted timestamp with whatever
//    a later crawl left on the node prop.
MATCH (u:User {id: $me})
MATCH (t:Track) WHERE t.liked_songs = true
MERGE (u)-[l:LIKED]->(t)
SET l.added_at = coalesce(l.added_at, t.date_added_to_liked_songs)
;

// 3. Plan 08's ManagedPlaylist nodes were anchored standalone ("the (:User)
//    node does not exist until plan 06 lands" — insert_managed_playlist.cypher
//    header). It has landed: re-link every managed playlist to its owner.
//    MERGE on the User is deliberate — a playlist created for a user who has
//    not been migrated/authorized yet still gets a User anchor.
MATCH (p:ManagedPlaylist)
WHERE p.owner_spotify_user_id IS NOT NULL
MERGE (owner:User {id: p.owner_spotify_user_id})
MERGE (owner)-[:HAS_MANAGED]->(p)
;
