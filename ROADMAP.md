# Spotify Power Browser — Roadmap & Status

_Last updated: 2026-07-08_

Where the project **is** and where it goes **next**. How things work is
documented in [docs/](docs/README.md); feature designs live in
[docs/plans/](docs/plans/README.md).

## Where the project is

The first full-library crawl completed 2026-07-06: **12,547 tracks / 9,832
albums / 7,587 artists / 634 genres in ~18 minutes**, zero rate-limit errors,
batch endpoints on. Since then, six of the nine feature plans have shipped:

| Shipped | What you get | PR |
|---|---|---|
| One-command run | `docker compose up` including the OAuth flow, healthcheck-gated | #2 |
| Crawl correctness | Redis dedup, capped 429 backoff, token refresh with client auth, durable queues, consumer reconnect | #2 #14 #16 #26 #29 |
| Mock Spotify + resilience tests | offline crawls, failure injection, the test suite | #11–#13 |
| Plan 01 — adjacent-artist discovery | depth-2 discography crawl, frontier artists, popularity backfill | #22 |
| Plan 03 — entity mastering | canonical Songs across re-releases, review-report loop | #20 |
| Plan 04 (A+B) — annotations | cold-entry + live hotkey capture of notes/cues/sections | #21 |
| Plan 05 — graph MCP server | AI exploration of the graph, read-only | #19 |
| Plan 06 — multiplayer | `(:User)-[:LIKED]` ownership layer, migrations, overlap query pack | #24 |
| Plan 08 — playlist write-back | managed playlists, diff-sync, dry-run default | #23 |

## What's next

**Feature plans, in rough priority order** (designs in docs/plans/):

- [ ] **Plan 02 — listening completeness.** Ingest Spotify's extended
  streaming-history export into `(:User)-[:DID]->(:Play)` nodes; upgrade
  `artist_completeness` out of degraded mode. Blocked on requesting the
  export (days–weeks of lead time), not on code. Would also implement the two
  remaining handler stubs (`my_followed_playlists`, `my_followed_artists`).
- [ ] **Plan 09 — taste over time.** The `added_at` data is already in the
  graph; needs the analytics/report layer (year-in-review, `time-capsule`
  playlist generator).
- [ ] **Plan 07 — beyond Spotify.** Local files + SoundCloud. XL effort,
  spike first.
- [ ] **Plan 04 phases C+D** — DJ set planning + playback HUD on top of
  annotations.

**Platform work:**

- [ ] **MCP `shared_taste` tool** — plan 06's schema shipped; wrap the overlap
  query pack as a first-class tool (today it's reachable via the cookbook).
- [ ] **CI** — a GitHub Actions workflow (build image, run the
  non-Neo4j-dependent test subset). Nothing blocks this; it just hasn't been
  wanted yet.
- [ ] **AWS migration** — mock-service-first strategy per
  [docs/mock-spotify-service.md](docs/mock-spotify-service.md): deploy the
  mock to Fargate as the learning workload, then the real pipeline
  (workers → Fargate, RabbitMQ → Amazon MQ/SQS, Redis → ElastiCache,
  Neo4j → Aura, secrets → Secrets Manager).
- [ ] **Graph-explorer UI** — the original "power browser" promise; today the
  Neo4j browser + MCP server stand in.
- [ ] **Observability upgrades** if unattended runs ever matter: turn on the
  structured-log formatter, add basic metrics
  (see [docs/observability.md](docs/observability.md#the-gaps-things-you-might-expect-and-wont-find)).

**Known dead weight (cleanup candidates):**

- `write_to_sqlite` — a fourth response-handler role that was never
  implemented: flag off, every handler raises `NotImplementedError`, a queue
  is bound for nothing. Remove it or build it; today it's noise.
- `check_url_match()` — declared on every handler, never called.
- The commented-out `StructuredLoggingFormatter` in `application/loggers.py`
  — either wire it to a flag or drop it.

## History (compressed)

Stages 0–1 of the original roadmap (one-command run; dedup + batch endpoints
+ the 429/token-refresh bug fixes) completed 2026-06/07 and are described
above. The original Stage 2–6 sketches were superseded by the numbered plans
in [docs/plans/](docs/plans/README.md) — each plan says what it supersedes.
Two live-crawl war stories worth remembering when touching the engine: a
punitive 24-hour `Retry-After` once froze the crawl (hence the 10-minute
backoff cap), and an exclusive/auto-delete queue once discarded ~950 queued
requests on a reconnect (hence durable named queues everywhere).
