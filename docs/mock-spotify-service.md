# Design notes: a mock Spotify service (testing + AWS)

_Status: idea / planning. Not yet built. Captured 2026-06-21._

A controllable **facade of the Spotify Web API** the crawler depends on, that can
**inject rate limiting / failures between successful fetches**. Two payoffs:

1. **Testing** — makes the whole pipeline hermetically, deterministically
   testable, including the resilience paths that fixtures can't reach.
2. **AWS** — a safe, self-hosted target that doubles as a first AWS workload and
   informs the eventual production migration of the real app.

---

## 1. Why this is the high-value next step for test coverage

The current suite (`tests/`) covers logic against static fixtures and the
backing services (Redis/RabbitMQ/Neo4j). What it **cannot** exercise today is the
Spotify side and, crucially, the failure/resilience behavior — which is exactly
where the real bugs were:

| Behavior | Currently testable? | With the mock |
|---|---|---|
| 429 backoff cap (the 24h-freeze bug, review #5) | ✗ (needs a 429 with a punitive `Retry-After`) | inject a 429 + `Retry-After`, assert the cap + retry |
| Token refresh on 401 (the infinite-refresh bug) | ✗ (needs a live token expiry) | inject a 401 after N calls, assert refresh + token re-read + resume |
| **Dedup rollback on 500-exhaustion (review #1, HIGH)** | ✗ ("crafted fixtures do not exercise the retry-exhaustion path") | inject persistent 500s for a URL, assert it's un-marked + re-crawlable |
| Full crawl → graph (E2E) | ✗ (no Spotify) | seed → mock → assert Neo4j == synthetic catalog |
| Pagination (`next` chain) | ✗ | multi-page catalog, assert full traversal |
| Dedup at scale / batch call reduction | ✗ (would hit the real rate limit) | 12k synthetic catalog, assert ~22× fewer calls, no wall |
| Batch vs single equivalence | partial (fixtures) | crawl with `USE_BATCH_ENDPOINTS` on/off, assert identical graph |

So the mock is the unlock for the **second tier** of testing (E2E, resilience,
scale) on top of the unit/integration tier already in place.

---

## 2. What it implements (the crawler's surface, per Spotify's docs)

**Phase 1 (happy path):**
- Auth facade (`accounts.spotify.com`): `POST /api/token` for the
  `authorization_code` and `refresh_token` grants → returns a fake
  `access_token` / `refresh_token` / `expires_in`. (`GET /authorize` can short-
  circuit to the callback with a fake `code`, or be skipped in test mode.)
- API facade (`api.spotify.com`):
  - `GET /v1/me/tracks?offset=&limit=` — paginated liked songs with a `next` link.
  - `GET /v1/tracks/{id}`, `/v1/albums/{id}`, `/v1/artists/{id}`.
  - `GET /v1/tracks?ids=`, `/v1/albums?ids=`, `/v1/artists?ids=` — batch; honor
    the 50/20/50 caps and return `null` for unknown ids (real behavior the batch
    handler already filters).

**Phase 2 (deeper crawl, mirrors the unimplemented handlers):**
`/v1/me/playlists`, `/v1/me/following`, `/v1/albums/{id}/tracks`,
`/v1/artists/{id}/albums`.

Response **shapes must match real Spotify** (the fields the handlers/Cypher
consume), reflecting the current post-Feb-2026 field set.

---

## 3. The deterministic synthetic catalog

A seeded generator builds an internally-consistent graph:
- N liked songs over a smaller pool of artists/albums, with **realistic sharing**
  (the same album/artist recurs across songs) so dedup and batching actually
  matter.
- Every referenced id resolves: a liked song's `album.id` is fetchable at
  `/albums/{id}` and via the batch endpoint; artists likewise.
- Parametrizable size: 10 songs for a fast E2E test, 12k for a scale test.
- Deterministic from `(seed, size)` so assertions are exact and reproducible.

**Gotcha to bake in:** the crawler follows the *absolute* `href`/`next` URLs in
responses. So the mock must emit **self-referential** hrefs (pointing at its own
base URL), or the engine will follow them to real Spotify. The mock generates
hrefs from its configured public base URL.

---

## 4. Failure / rate-limit injection (the defining feature)

A small **control plane** to set the mock's behavior per run, e.g.
`POST /_control/config`:
- `rate_limit_after_n` → return `429` with a chosen `Retry-After` after N
  successful responses, then resume (models the real 24h penalty).
- `rate_limit_probability` → p chance of `429` per request.
- `token_expiry_after_n` → return `401` after N requests, forcing a refresh.
- `server_error_burst` → inject `500`s (up to / beyond the retry cap) to exercise
  the dedup-rollback give-up path.
- `latency_ms` → injected delay, for timeout/throughput behavior.

State (counters, config) is per-token or global. A test sets a mode, runs the
crawl, and asserts the crawler's response (backoff, refresh, rollback, eventual
completion or graceful give-up).

---

## 5. Architecture — local and AWS (one image, two homes)

**Recommended: a containerized HTTP app (FastAPI/Flask), the same image run
locally and on AWS.** This fits the "Dockerize everything" preference: it runs as
a Compose `spotify_mock` service for tests *and* deploys unchanged to AWS.

- **Local:** Compose service `spotify_mock`; the crawler points at it via
  configurable base URLs (see §6). The test suite gets a `spotify_mock` fixture.
- **AWS:** the same image on **ECS/Fargate behind an ALB** (or App Runner).
  In-memory deterministic data needs no datastore; if multi-instance state is
  wanted, back the control config + counters with DynamoDB or ElastiCache.

Alternative: **API Gateway + Lambda** (per-endpoint Lambdas, DynamoDB for
state). More AWS-native and scales to zero, but harder to run identically
locally (SAM/LocalStack) — less aligned with the container-everywhere approach.
The containerized option is the recommendation; the Lambda option is the
fallback if a serverless cost profile is preferred.

---

## 6. Prerequisite refactor (small, env-overridable — matches the existing pattern)

Make the Spotify base URLs configurable (today they're hard-coded to
`https://api.spotify.com` / `https://accounts.spotify.com`):
- `SPOTIFY_API_BASE_URL` (default `https://api.spotify.com`)
- `SPOTIFY_ACCOUNTS_BASE_URL` (default `https://accounts.spotify.com`)

Touch points: `requests_factory` (URL construction + `request_batch`),
`api_call_engine` (it follows absolute hrefs/next — so this works *as long as the
mock emits self-referential hrefs*, §3), the OAuth web service, and
`refresh_token`. This mirrors the existing `RABBITMQ_HOSTNAME` / `NEO4J_HOSTNAME`
env-override pattern, so it's a clean, low-risk change — and it's the one thing
that must land before the mock is useful.

---

## 7. Phased plan

- **Phase 0 — prereq:** configurable base URLs; confirm the engine follows the
  mock's self-referential hrefs. (Small.)
- **Phase 1 — local mock + happy path:** FastAPI container, deterministic
  catalog, Phase-1 endpoints; add a `spotify_mock` Compose service + test
  fixture. Unlocks E2E + pagination + scale tests, fully Dockerized.
- **Phase 2 — failure injection:** the control plane (§4). Unlocks the resilience
  tests (429 cap, token refresh, dedup rollback) — the highest-value coverage.
- **Phase 3 — deploy to AWS (Fargate):** the mock becomes a load-test target and
  an AWS spike (ALB, task def, IaC).
- **Phase 4 — real-app AWS migration, informed by the above:** map the pipeline
  to managed services — workers → ECS/Fargate (or Lambda), RabbitMQ → Amazon MQ
  or SQS, Neo4j → Neo4j Aura, Redis → ElastiCache, secrets → Secrets Manager,
  OAuth tokens → per-user storage (ties into the Stage 4 multi-user work).

---

## 8. Why it's worth it

- Turns the three scariest, currently-untestable failure modes into push-button
  regression tests — before they bite again in production.
- Lets the crawler be developed, CI-tested, and demoed with **no real Spotify app,
  no OAuth, no rate limits**.
- The rate-limit facade is exactly how you'd validate production resilience
  before pointing the AWS deployment at the real (rate-limited) Spotify.
- Building the mock on AWS de-risks the real migration: same primitives (Fargate,
  ALB, IaC, DynamoDB/ElastiCache) on a throwaway workload first.
