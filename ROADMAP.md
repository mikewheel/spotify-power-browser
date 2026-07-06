# Spotify Power Browser — Roadmap & Status

_Last updated: 2026-07-06_

> **2026-07-06 — first full-library crawl completed** (12,547 tracks / 9,832
> albums / 7,587 artists / 634 genres, ~18 min, zero 429s, batching on), and a
> full set of forward-looking feature plans landed in **[docs/plans/](docs/plans/README.md)**:
> adjacent-artist discovery, listening completeness, entity mastering,
> annotations & DJ sets, a graph MCP server, multiplayer, beyond-Spotify
> (local files + SoundCloud), playlist write-back, and taste-over-time.
> Those plans supersede the sketches in Stages 2–4 below where they overlap
> (each plan says which). The **live-verified API surface** (what this app
> retains post-deprecations) is tabled in the plans README.

A personal data-engineering project that crawls the Spotify Web API and builds a
graph of your musical taste in Neo4j. This document is the single source of truth
for **where the project is** and **where it needs to go next**.

---

## 1. Architecture at a glance

A message-queue pipeline glued together by two RabbitMQ `direct` exchanges:

```
requests_factory ──► Requests exchange ──► api_call_engine ──► Spotify Web API
                                                  │
                                                  ▼
                                          Responses exchange  (fan-out ×4)
                                                  │
              ┌───────────────────┬───────────────┼───────────────────┐
              ▼                   ▼                ▼                   ▼
        write_to_disk      write_to_neo4j     follow_links      write_to_sqlite
        (JSON cache)       (graph insert)   (re-queues URLs)    (stubbed / OFF)
                                                  │
                                                  └──► back to Requests exchange
                                                       (recursive crawl, depth-limited)
```

- **`requests_factory.py`** — seeds a crawl by publishing Spotify URLs onto the Requests exchange.
- **`api_call_engine.py`** — consumes requests, makes the HTTP GET (handles 429/500/401, auto-paginates via `next`), and fans each response out to the four response handlers.
- **`response_handlers/`** — four worker roles selected by CLI arg: `write_to_disk`, `write_to_neo4j`, `follow_links`, `write_to_sqlite`.
- **`follow_links`** is what makes it a *crawler*: it re-queues the track/album/artist URLs found in a response at `depth − 1`.

### Graph data model (Neo4j)

- **Nodes:** `Track`, `Album`, `Artist`, `Genre` (uniqueness constraints on `Track.id`, `Album.id`, `Artist.id`).
- **Relationships:**
  - `(Album)-[:CONTAINS]->(Track)`
  - `(Artist)-[:CREATED]->(Track)` and `(Artist)-[:CREATED]->(Album)`
  - `(Album|Artist)-[:SPOTIFY_CLASSIFIED_AS]->(Genre)`
- Everything is `MERGE`d on stable Spotify IDs, so re-crawling is idempotent — and (see Stage 4) two users' libraries loaded into one DB would naturally share nodes.

---

## 2. Current status

### Works today
- End-to-end happy path for **Liked Songs at `DEPTH_OF_SEARCH = 1`**: crawl → cache to disk → build the Neo4j graph.
- Four implemented + wired handlers: `GetSingleTrack`, `GetSingleArtist`, `GetSingleAlbum`, `LikedSongsPlaylist`.
- Retry/backoff for HTTP 429 and 500; pagination via the `next` link.
- One-time OAuth (Authorization Code grant) via a small Falcon web service.

### Broken / unfinished
- **Four stub handlers** (crash with `KeyError` if reached):
  - `me/my_followed_playlists.py` — `# TODO: implement`
  - `me/my_followed_artists.py` — `# TODO: implement`
  - `artists/albums_of_artist.py` — `# FIXME`, no class
  - `albums/tracks_of_album.py` — `# FIXME`, no class
  - The `DEPTH_OF_SEARCH = 1` ceiling is the only thing keeping these off the execution path.
- **`write_to_sqlite` is `NotImplementedError` everywhere** (flag is off — leave it off).

### Known bugs
- ✅ **Token-refresh bug (`api_call_engine.py`)** — _fixed (Stage 1)._ `SPOTIFY_API_TOKEN` was read once at import and never updated after a 401 refresh → infinite refresh loop past the ~1h token. Now re-read from disk via `load_api_token()` after `refresh_spotify_auth()`.
- ✅ **Inverted 429 backoff (`api_call_engine.py`)** — _fixed (Stage 1)._ `sleep(max(Retry-After, 600))` floored the wait at 10 min and obeyed punitive values in full (a live crawl got a ~24h `Retry-After` and froze). Now `min(Retry-After, 600)`.

### Notable gaps
- **No UX / data viz.** The only way to see the graph is the Neo4j browser + hand-written Cypher. `pandas`/`jupyter`/`openpyxl` are dependencies but effectively unused.
- **No cloud / CI.** Local Docker Compose only; no Terraform/k8s/GitHub Actions. Compose currently hard-codes absolute `/Users/michael/...` mount paths.

---

## 3. Roadmap

### Stage 0 — Reproducible one-command run _(in progress)_
**Goal:** `docker compose up` brings up the entire system, including the auth flow, with no manual host-side steps.
- [x] Bundle the Spotify auth web service into Docker Compose (port 8000).
- [x] Gate the pipeline on auth completion via a token healthcheck (one `up`, waits for the human to authorize, then proceeds).
- [x] Point the pipeline at **Neo4j Desktop on the host** (`host.docker.internal:7687`) instead of the containerized Neo4j (which collides on port 7687).
- [x] Replace hard-coded `/Users/michael/...` mount paths with relative `./secrets` / `./data` paths for portability.
- [x] Add a `build:` context so `docker compose up --build` produces the image.

**Verified end-to-end on 2026-06-21:** one `docker compose up` → bundled OAuth (now `http://127.0.0.1:8000/callback` — Spotify rejects `localhost` as insecure) → crawl → Neo4j. The first live crawl also surfaced the rate-limit failure mode that motivated Stage 1.

### Stage 1 — Correctness, dedup & batch endpoints _(the branch's namesake)_
**What set the priorities:** the first live crawl (depth 1, ~12k Liked Songs) flooded Spotify with redundant per-song follow requests (no dedup) and got the app **rate-limited with a ~24h `Retry-After`**, which the inverted 429 sleep then obeyed in full. Dedup + the two bug fixes address this head-on.

- [x] **Fix the token-refresh bug** — re-read the token after a 401 refresh.
- [x] **Cap the 429 backoff** at 10 min (`max`→`min`) so a punitive `Retry-After` can't freeze the worker.
- [x] **Redis crawled-URL dedup** — durable Redis service (AOF + named volume); one persistent `spb:crawled_urls` set; `SADD`-skip at the `request_url` choke point (`CRAWLED_URL_DEDUP`, default on); `RESET_CRAWL` for a fresh crawl. The fix for the request flood.
- [x] **Batch endpoints behind a feature flag** (`USE_BATCH_ENDPOINTS`, **default off**) — `request_batch` (chunked `?ids=`, caps 50/20/50) + "Get Several" handlers + `UNWIND` Cypher + dispatcher routing + `follow_links` branch. A 20-song page → 3 calls instead of ~67 (~22× fewer at 12k scale).
- [x] **Live-verify batch access** — verified **2026-07-06** post-cooldown: the `?ids=` batch endpoints for tracks/albums/artists all return `200` for this app, so live crawls now run with `USE_BATCH_ENDPOINTS=true`. _Spotify only **postponed** removing them, so the per-item fallback (flag off) stays._
- [ ] _(later)_ Cross-response Neo4j batching (buffer N / flush on interval) — secondary; the API-call batching above is the bigger win.
- [ ] _(later)_ Remove the dead `check_url_match()` stubs.

### Stage 2 — Deeper crawls
**Goal:** crawl beyond Liked Songs at depth 1.
- [ ] Implement the four stub handlers (`followed_playlists`, `followed_artists`, `albums_of_artist`, `tracks_of_album`).
- [ ] Validate `DEPTH_OF_SEARCH > 1` doesn't explode rate limits; tune backoff.
- [ ] Add basic crawl observability (counts, progress, dead-letter for unroutable responses).

### Stage 3 — Visualization / UX
**Goal:** actually *browse* your taste graph — the "power browser" promise.
- [ ] Stand up a read API or notebook over the graph.
- [ ] Build a graph-explorer UI (e.g. force-directed view of artists/albums/genres, filters by popularity/genre/era).

### Stage 4 — Multi-user & overlap
**Goal:** "here's my graph, here's my friend's — merge and explore the overlap."
- [ ] Schema change: make ownership a **relationship**, not a node property — introduce `(:User)-[:LIKED {added_at}]->(:Track)` instead of `liked_songs`/`date_added_to_liked_songs` on the node. Overlap = tracks with `LIKED` edges from ≥2 users.
- [ ] Per-user token storage (DB, not fixed `secrets/*.secret` files).
- [ ] Add an OAuth `state` parameter to identify the user through the round-trip (also closes the current CSRF gap).
- [ ] Overlap/diff queries + visualizations (shared artists, divergent genres, Jaccard similarity).

### Stage 5 — Cloud (optional / later)
- [ ] Parameterize config via env vars; remove machine-specific paths.
- [ ] CI (build + lint + smoke test).
- [ ] Deploy target (managed RabbitMQ + Neo4j Aura + container host).

### Stage 6 — Mock Spotify service (testing + AWS) _(planned)_
A controllable facade of the Spotify API that can inject rate limiting / failures
between successful fetches. Unlocks the resilience + E2E + scale tests that
fixtures can't reach (the 429-cap, token-refresh, and dedup-rollback-on-500
paths), and doubles as a first AWS workload that informs the real migration.
**Design + phased plan: [docs/mock-spotify-service.md](docs/mock-spotify-service.md).**
- [ ] Phase 0: configurable Spotify base URLs (env-overridable; mock emits self-referential hrefs).
- [ ] Phase 1: local FastAPI mock + deterministic catalog as a Compose service; E2E / pagination / scale tests.
- [ ] Phase 2: failure-injection control plane; the resilience tests.
- [ ] Phase 3+: deploy to Fargate; inform the real-app AWS migration.

---

## 4. File map

| Area | Path |
|------|------|
| Feature flags / crawl config | `application/config.py` |
| Crawl seeding | `application/requests_factory.py` |
| API engine (HTTP + fan-out) | `application/api_call_engine.py` |
| OAuth web service | `application/spotify_authentication/api_authorization_web_service.py` |
| Token refresh | `application/spotify_authentication/refresh_token.py` |
| Message queue helpers | `application/message_queue/` |
| Graph connection + queries | `application/graph_database/` |
| Response handlers (one per endpoint) | `application/response_handlers/` |
| Orchestration | `compose.yaml`, `Dockerfile` |
