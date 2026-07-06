# 06 — Multiplayer (shared graphs, intersection & difference)

> Crawl two (or 25) authenticated users into one graph, then *join where they
> overlap*: shared artists, divergent genres, taste similarity — the "you like
> EDM, I like EDM, where do we differ?" machine. **Effort: L.**
> Depends on: PR #16. Expands: Roadmap Stage 4 (this plan supersedes its
> sketch). Feeds: 05 (`shared_taste` tools), 08 (blend playlists), 09.

## Vision

Multiple Spotify accounts authorize this app; each gets their liked songs /
followed artists / playlists / listening history crawled into the **same**
Neo4j database. Because every catalog node MERGEs on stable Spotify IDs, two
users' libraries **share catalog nodes by construction** — the "join" is free.
What's per-user is the *relationship* layer. Then the synthesis: overlap and
difference queries, Jaccard similarity, genre radars — heavily agentic via the
MCP server.

## Design

### 1. Ownership becomes a relationship (the schema migration)

Today user-ness is baked into node properties (`liked_songs: true`,
`date_added_to_liked_songs`) — meaningless with two users. Migrate to:

```
(:User {id, display_name, added_at})
(:User)-[:LIKED {added_at}]->(:Track)
(:User)-[:FOLLOWS]->(:Artist)
(:User)-[:OWNS_PLAYLIST]->(:Playlist)      // with plan 02: (:User)-[:DID]->(:Play)
```

Migration (one-off script under `application/graph_database/migrations/`):
```cypher
MERGE (u:User {id: $me})
WITH u MATCH (t:Track) WHERE t.liked_songs = true
MERGE (u)-[l:LIKED]->(t) SET l.added_at = t.date_added_to_liked_songs
```
Keep the old node properties through one release for rollback, then a cleanup
migration drops them. All existing queries that filter on `liked_songs: true`
get rewritten to traverse from `(:User)` (grep: the flag appears in the three
`insert_batch_*` Cyphers and several plans' queries).

### 2. Per-user auth (replaces the fixed secrets files)

- **Token store**: `secrets/users/<spotify_user_id>/{access_token,refresh_token}.secret`
  (same file-based approach, now namespaced; a DB/Redis store is a later
  refinement — files keep the Docker mount story unchanged).
- **OAuth `state` param** (closes the CSRF gap *and* identifies the user through
  the round-trip): `/login` mints a nonce → stores in Redis with a TTL →
  Spotify reflects it to `/callback` → callback validates the nonce, exchanges
  the code, calls `GET /v1/me` with the fresh token, and files the tokens under
  that user id. The login page becomes an "add a user" flow — hit it once per
  friend.
- **Refresh** becomes per-user: `refresh_spotify_auth(user_id)` reads/writes the
  namespaced files (builds on PR #16's fix).
- **Ops note**: a development-mode Spotify app allows **25 users**, each
  allowlisted by email in the developer dashboard (User Management) *before*
  they authorize. Document the invite runbook.

### 3. Crawl orchestration (sequential per user)

Rate limits are per-app, so parallel per-user crawls fight each other —
**sequential** is kinder and simpler:
- Message envelope gains `user_id` (factory → engine → handlers). The engine
  keeps a small per-user token cache: `get_api_token(user_id)`,
  401-refresh per user.
- `/me/*` URLs are inherently per-user → the Redis dedup key becomes
  `spb:crawled_urls:<user_id>` for user-relative URLs, while **catalog URLs
  stay in a shared set** (a track fetched for user A need not be re-fetched
  for user B — the node's already there). Split by URL pattern
  (`/v1/me/` prefix) in `redis_client.py`.
- Seeder CLI: `python application/requests_factory.py --user <id>` (compose
  can run it N times, or a small wrapper iterates `secrets/users/*`).
- Handlers write `(:User)-[:LIKED]` etc. using the envelope's `user_id`.

### 4. The synthesis layer (the kicker)

Query pack `queries/overlap/` + MCP tools (plan 05):
```cypher
// Shared artists, weighted by both users' affection
MATCH (a:User {id:$a})-[:LIKED]->(:Track)<-[:CREATED]-(ar:Artist)
MATCH (b:User {id:$b})-[:LIKED]->(:Track)<-[:CREATED]-(ar)
WITH ar, count(DISTINCT a) AS _, … RETURN ar.name, …
// Jaccard over liked-artist sets; genre radar diff; 
// "artists A loves that B has never played" (needs plan 02's Plays)
// "the bridge playlist": tracks by artists BOTH like, that NEITHER has liked yet (plan 01 frontier ∩ both users' adjacency)
```
The "shared taste synthesis" narrative (agentic exploration, blend reports) is
exactly what the MCP server + Claude are for — the queries are the API.

## Task breakdown

| # | Task | Touches | Done when |
|---|------|---------|-----------|
| T1 | `(:User)` model + migration script + old-property deprecation plan | migrations/ | Your data reachable via `(:User)` |
| T2 | Rewrite bundled queries off `liked_songs: true` | queries/, plans' Cyphers | Both altitudes green |
| T3 | Namespaced token store + per-user refresh | `spotify_authentication/` | Two token dirs coexist |
| T4 | OAuth `state` (Redis nonce) + callback → `/v1/me` → user filing | auth web service | CSRF closed; user id derived, not assumed |
| T5 | Envelope `user_id` through factory/engine/handlers + per-user token cache | core pipeline | Mock E2E with 2 fake users green |
| T6 | Redis dedup split (per-user `/me/*`, shared catalog) | `cache/redis_client.py` | Second user's crawl skips shared catalog |
| T7 | Mock: second user's liked-songs fixture + `/v1/me` per token | `mock_spotify/` | Offline 2-user E2E |
| T8 | Dashboard allowlist runbook + friend invite flow doc | docs | A friend can onboard in <10 min |
| T9 | Overlap query pack + `shared_taste` MCP tool | queries/, mcp_server/ | Blend report generated for 2 real users |
| T10 | Live: onboard user #2, sequential crawl, blend session | — | The kicker, demonstrated |

## Risks & open questions

- **Shared catalog dedup across users** means user B's crawl won't refresh
  stale catalog nodes — acceptable (MERGE would no-op anyway); `RESET_CRAWL`
  semantics become per-user + catalog flags (design in T6).
- Privacy: friend's listening data lands in *your* Neo4j. Be explicit when
  inviting; deletion = `MATCH (u:User {id:$x}) DETACH DELETE u` + their Plays
  (document it — a real "right to be forgotten" one-liner).
- Two users' crawls in one app budget: fine at 2, plan batching windows at 25.
