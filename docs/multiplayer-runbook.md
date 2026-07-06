# Multiplayer runbook (plan 06)

Two (or up to 25) Spotify accounts, one Neo4j graph. Catalog nodes are shared
by construction (MERGE on stable Spotify ids); what's per-user is the
relationship layer: `(:User {id})-[:LIKED {added_at}]->(:Track)`, plus
`[:HAS_MANAGED]` for plan-08 playlists and, later, `[:FOLLOWS]` / plan 02's
`[:DID]->(:Play)`.

## 0. One-time setup (before the first friend)

1. **Run migration 0001** so your existing single-user data joins the new
   ownership model (the rewritten queries all traverse `(:User)-[:LIKED]`):

   ```bash
   docker compose run --rm requests_factory_start_crawls \
       python3 -m application.graph_database.migrations.run \
       0001_multiplayer_ownership --me <your_spotify_user_id> --display-name "You"
   ```

   Idempotent — re-running is safe. Your Spotify user id is the `id` field of
   `GET /v1/me` (also shown on the `/login` page once you've re-authorized).
   The legacy node properties (`liked_songs`, `date_added_to_liked_songs`)
   are **kept for one release** as the rollback path; the cleanup migration
   `0002_drop_legacy_liked_props` is a guarded stub — its header lists the
   preconditions, and the runner refuses it without `--force`.

2. **Re-authorize yourself once** through the new flow (`/login` → *Add a
   user*). That files your tokens under `secrets/users/<your_id>/` and records
   you as the **primary user**.

### Primary-user semantics (load-bearing)

The **first** account to authorize becomes the primary user
(`secrets/users/.primary_user`). The primary's tokens are mirrored to the
legacy `secrets/spotify_api_token.secret` / `spotify_refresh_token.secret`
files on every save/refresh, because:

- the compose auth-gate healthcheck tests `-s secrets/spotify_api_token.secret`
  — one `docker compose up` still waits for a human login and then starts;
- every legacy code path (messages without a `user_id`, `get_api_token()`
  no-arg callers like the playlist sync and backfills) reads the legacy files.

Don't delete the legacy files or the `.primary_user` marker. The primary is
sticky by design; a second user authorizing never steals it. Only a **login**
through the OAuth callback can claim an empty primary slot — background token
refreshes never do, so an unattended crawl can't silently promote an arbitrary
user while the slot is vacant (see §4).

## 1. Spotify dashboard allowlist (development mode = 25 users)

A development-mode Spotify app only accepts allowlisted accounts. **Before** a
friend hits the login page:

1. <https://developer.spotify.com/dashboard> → your app → **Settings** →
   **User Management**.
2. Add the friend's **name + the email of their Spotify account** → Save.
3. Dev mode caps at **25 users**. (Beyond that Spotify requires an extended
   quota request — out of scope here.)

If they aren't allowlisted, Spotify errors at the consent screen — nothing to
debug on our side.

## 2. Friend onboarding (< 10 minutes)

1. **You:** allowlist their email (step 1) — ~2 min.
2. **You:** have the stack up (`docker compose up`) and, if they aren't on
   your machine, a tunnel/port-forward for `:8000` (the redirect URI is
   `http://127.0.0.1:8000/callback`, so simplest is: they sit at your machine
   or SSH-forward `-L 8000:127.0.0.1:8000`).
3. **Friend:** open `http://127.0.0.1:8000/login` → **Add a user** → log in
   with THEIR Spotify account → consent. The callback validates the CSRF
   `state`, derives their user id from `GET /v1/me`, and files tokens under
   `secrets/users/<their_id>/` — ~3 min.
4. **You:** crawl their library (sequentially — rate limits are per-app):

   ```bash
   CRAWL_USER=<their_id> docker compose up requests_factory_start_crawls
   # or every authorized user, one after another:
   CRAWL_ALL_USERS=true docker compose up requests_factory_start_crawls
   ```

   Their liked songs land as `(:User {id: their_id})-[:LIKED]` edges; shared
   catalog nodes join yours automatically. Catalog URLs already crawled for
   you are skipped (shared dedup set); their `/v1/me/*` URLs dedup in their
   own set (`spb:crawled_urls:<their_id>`).
5. **Blend:** run the overlap pack
   (`application/graph_database/queries/overlap/`) with `$a`/`$b` = your two
   user ids — shared artists, Jaccard, genre radar diff, "A loves, B never
   heard", and the bridge playlist.

**Privacy — say it out loud when inviting:** their listening data lands in
*your* Neo4j instance. Deletion is one command (below).

## 3. Re-crawl semantics (`RESET_CRAWL`)

| Flags | Effect |
|---|---|
| `RESET_CRAWL=true CRAWL_USER=<id>` | clears **that user's** per-user dedup set (their `/v1/me/*` URLs) — a fresh crawl of their library. The shared catalog set is kept: catalog nodes are shared and MERGE would no-op anyway, so re-fetching them only burns rate limit. |
| `RESET_CRAWL=true` (legacy, no user recorded) | pre-multiplayer behavior: clears the shared set. |
| `RESET_CRAWL_CATALOG=true` | additionally clears the **shared catalog** set (e.g. to refresh stale popularity numbers). Combine with `RESET_CRAWL` as needed. |

## 4. Right to be forgotten (deletion one-liner)

Everything a user owns in the graph — the User node, their LIKED/FOLLOWS/
HAS_MANAGED edges, and (once plan 02 lands) their Play nodes, which hang off
`(:User)-[:DID]->(:Play)`:

```cypher
MATCH (u:User {id: $x})
OPTIONAL MATCH (u)-[:DID]->(p:Play)
DETACH DELETE u, p
```

Shared catalog nodes (tracks/albums/artists) stay — they were never "theirs".
Then remove their tokens:

```bash
rm -r secrets/users/<their_id>/
```

(If they were the primary user, also remove `secrets/users/.primary_user` and
the legacy `secrets/spotify_*.secret` files, then re-authorize whoever should
be primary next — the next **login** becomes the new primary. The slot stays
empty until that login: other users' background token refreshes keep working
but never claim it.)

## 5. Follow-ups on other branches (integration notes)

The MCP server (plan 05) lives on its own branch and was deliberately **not**
touched here. When the branches meet, apply the same `liked_songs: true` →
`(:User)-[:LIKED]` + `$user_id` rewrite there:

- **`discover_adjacent`** — backed by plan 01's adjacency query: same rewrite
  as `queries/discovery/adjacent_artist_discovery.cypher` on this branch
  (taste seed becomes `(u:User)-[:LIKED]->(:Track)<-[:CREATED]-(mine)` with
  `($user_id IS NULL OR u.id = $user_id)`).
- **`artist_completeness`** — its pre-plan-02 degraded mode ("liked vs
  catalog") filters on `liked_songs: true`; rewrite like
  `queries/playlists/exploration_queue_tracks.cypher`. (Its full plan-02 mode
  was already forward-written against `(:User)` with `$me`.)
- **`queries://cookbook` resource** — serves the files under
  `application/graph_database/queries/`; it picks the rewritten packs up
  automatically on merge, but re-snapshot any cached copies.
- **`run_cypher_readonly` / `graph_schema` / `find_*` / `collaborators_of`**
  — no liked-filter, no change needed (schema output will now include
  `User`/`LIKED`, which is correct).
- **NEW: `shared_taste(user_a, user_b)` tool** (the plan's table already
  reserves it) — thin wrapper over this branch's overlap pack
  (`queries/overlap/*.cypher`): shared_artists_weighted + liked_artist_jaccard
  + genre_radar_diff + a_loves_b_never_heard (+ bridge_playlist as the
  "blend" suggestion list). Keep the tool thin over the pack, per the plan's
  cookbook-first note.
- **Plan 08 follow-up:** register a `blend <user_a> <user_b>` playlist
  generator backed by `queries/overlap/bridge_playlist.cypher`
  (`application/playlists/generators.py` documents the registration point).
- **Migration 0002** must not run until the MCP branch has shipped its
  rewrite (see the stub's header checklist).
