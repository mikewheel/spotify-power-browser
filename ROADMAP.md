# Spotify Power Browser — Roadmap & Status

_Last updated: 2026-06-21_

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
- 🐛 **Token-refresh bug (`api_call_engine.py`).** `SPOTIFY_API_TOKEN` is read from disk **once at import**. On a 401, `refresh_spotify_auth()` writes a fresh token to disk but the in-memory global is never updated, so the retry reuses the **stale** token → **infinite refresh loop** on any crawl that outlives the ~1h token. Short crawls finish before expiry, which is why it's gone unnoticed. _Fix: re-read the token (or consume the refresh return value) inside the 401 branch._

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
- [ ] Replace hard-coded `/Users/michael/...` mount paths with relative/`${PWD}` paths for portability.
- [ ] Add a `build:` context so `docker compose up --build` produces the image.

### Stage 1 — Correctness & the batching refactor _(the branch's namesake)_
**Goal:** finish what `refactor_to_enable_batching_of_api_requests` set out to do.
- [ ] Fix the token-refresh bug (Stage 0 prerequisite for any long crawl).
- [ ] Convert `single_track` / `single_artist` / `single_album` handlers from single inserts to batch (`UNWIND`) inserts. _Note: `LikedSongsPlaylist` is the one already-converted proof of concept._
- [ ] Add **cross-response batching** in the `write_to_neo4j` consumer (buffer N responses / flush on interval) — the real "scale out the API calls" win.
- [ ] Remove the dead `check_url_match()` stubs or wire them into routing.

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
