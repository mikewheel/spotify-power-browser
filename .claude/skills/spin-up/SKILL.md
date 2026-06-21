---
name: spin-up
description: Set up, run, and monitor the Spotify Power Browser pipeline locally with Docker Compose — bring up the stack, drive the one-time Spotify OAuth flow (handing the login to the human), verify the crawl, and watch it run. Use whenever asked to spin up / run / start / launch / set up / boot / or monitor this project locally.
---

# Spin up & run Spotify Power Browser locally

This project is a containerized crawler: `requests_factory` seeds a crawl →
RabbitMQ → `api_call_engine` calls the Spotify API → responses fan out to
workers that write JSON to `data/`, build a Neo4j graph, and follow links
(recursing). Redis dedups requests. The OAuth flow is **bundled into Compose**,
so it all comes up with one `docker compose up`.

Work from the repo root: `/Users/michael/software_projects/spotify-power-browser`.

## 0. Pre-flight (check before doing anything)

Run these and confirm before bringing the stack up:
```bash
docker ps >/dev/null 2>&1 && echo "Docker: up" || echo "Docker: START Docker Desktop first"
lsof -nP -iTCP:7687 -sTCP:LISTEN 2>/dev/null | grep -q . && echo "Neo4j: listening on 7687" || echo "Neo4j: START Neo4j Desktop (a DB on bolt://127.0.0.1:7687)"
ls secrets/spotify_client_id.secret secrets/spotify_client_secret.secret secrets/neo4j_credentials.yaml 2>/dev/null
```
- **Docker Desktop** must be running.
- **Neo4j Desktop** must have a database running on `127.0.0.1:7687`. The
  crawler reaches it from containers via `host.docker.internal` (already wired in
  `compose.yaml` with `extra_hosts`). Confirm `secrets/neo4j_credentials.yaml`
  matches the Neo4j Desktop password.
- `secrets/` must have the Spotify client id/secret. (Token files are written by
  the auth flow.)

## 1. (Optional) start fresh

The Redis dedup set **persists across runs** by design (resume). For a clean
re-crawl, either set `RESET_CRAWL=true` (step 3) or clear it, and optionally
reset the JSON cache:
```bash
# preserve + clear the on-disk JSON cache (gitignored)
mkdir -p "$HOME/spotify-power-browser-cache-backups"
mv data/responses "$HOME/spotify-power-browser-cache-backups/responses_$(date +%Y%m%d_%H%M%S)" 2>/dev/null; mkdir -p data/responses
```
If reusing an old token would skip a fresh OAuth, move stale tokens aside so the
auth gate waits for a real login:
```bash
mkdir -p secrets/_stale_token_backup
for f in spotify_api_token spotify_refresh_token spotify_authorization_code; do mv "secrets/$f.secret" "secrets/_stale_token_backup/" 2>/dev/null; done
```

## 2. Build & bring up

```bash
docker compose build           # first run / after code changes
docker compose up              # run in background (it streams logs and waits at the auth gate)
```
The stack starts RabbitMQ, Redis, and the response workers, then the
`spotify_authentication` service serves the login page and the pipeline **waits**
on a token healthcheck (patient: ~1h start_period). `api_call_engine` and
`requests_factory` stay parked until you authorize.

## 3. Drive the OAuth flow — HUMAN IN THE LOOP

You (the agent) **cannot** complete the Spotify login — hand it to the human.
- Confirm the auth page serves: `curl -sS -o /dev/null -w "%{http_code}\n" http://127.0.0.1:8000/login` (expect `301`).
- Open a browser to **http://127.0.0.1:8000/login** (use the Chrome DevTools MCP
  or Claude-in-Chrome). It redirects to Spotify's login/consent.
- **Pause and ask the human** to log into Spotify and click **Agree**. Then the
  callback writes tokens to `secrets/`, the healthcheck flips healthy, and
  Compose auto-starts the crawl.
- To run a fresh crawl as it starts: bring up with `RESET_CRAWL=true docker compose up`.

Detect completion:
```bash
ls -s secrets/spotify_api_token.secret 2>/dev/null && echo "token written" || echo "still waiting for human"
docker inspect --format '{{.State.Health.Status}}' spotify-power-browser-spotify_authentication-1
```

> If the auth gate timed out before the human finished (older config), just
> start the gated services manually once the token exists:
> `docker compose up -d api_call_engine requests_factory_start_crawls`.

## 4. Verify it's crawling

```bash
docker compose logs requests_factory_start_crawls | grep "STARTING FETCH"   # crawl seeded
docker compose logs api_call_engine | grep -cE 'GET:'                       # API calls made
find data/responses -name '*.json' | wc -l                                  # JSON landing on disk
```
Graph counts (one-off container against host Neo4j):
```bash
docker run --rm --add-host host.docker.internal:host-gateway -e NEO4J_HOSTNAME=host.docker.internal \
  -v "$PWD/secrets:/src/secrets" spotify-power-browser:latest python3 -c "
from application.config import SECRETS_DIR
from application.graph_database.connect import connect_to_neo4j
d=connect_to_neo4j(SECRETS_DIR/'neo4j_credentials.yaml')
for l in ['Track','Album','Artist','Genre']:
    r,_,_=d.execute_query(f'MATCH (n:{l}) RETURN count(n) c'); print(l, r[0]['c'])
d.close()"
```

## 5. Monitor

- **RabbitMQ UI — http://localhost:15672** (`guest`/`guest`), Queues tab: backlog
  + live message rates. **Done = rates flatline to 0 + queues empty.** Rates are
  bursty — watch the trend, not one sample.
- `docker compose logs -f api_call_engine` (GET stream) · `... responses_write_to_neo4j` (node counts).
- Throughput pulse: `docker compose logs --since 10s api_call_engine | grep -c 'GET:'` (0 = idle).

## 6. Tests

```bash
docker compose run --rm tests        # pytest; brings up rabbitmq+redis+spotify_mock, neo4j tests use the host Desktop
```

## Mock Spotify service — crawl offline, no real Spotify

`mock_spotify/` is a controllable Falcon facade of the Spotify API (profile-gated
`spotify_mock` compose service on :80, with a deterministic synthetic catalog and
self-referential hrefs). Use it to crawl with **no OAuth, no rate limits, and
reproducible data** — ideal for testing and demos. It's brought up automatically
by `docker compose run --rm tests`.

**Run the full pipeline against the mock** (no browser/OAuth step needed):
```bash
echo -n mock-access-token  > secrets/spotify_api_token.secret     # seed a fake token
echo -n mock-refresh-token > secrets/spotify_refresh_token.secret # (satisfies the auth gate)
RESET_CRAWL=true docker compose -f compose.yaml -f docker-compose.mock.yml up
```
The crawler hits the mock's self-referential URLs and builds the graph in Neo4j,
fully offline. Monitor exactly as in section 5.

**Inject failures** to exercise resilience (control plane lives on the mock):
```bash
# next request 429s with Retry-After 5, then resumes:
docker compose exec spotify_mock curl -s -XPOST localhost:80/_control/config \
  -H 'Content-Type: application/json' -d '{"fail_next_n":1,"fail_status":429,"retry_after":5}'
# a specific URL always 500s (exercises the dedup-rollback give-up path):
docker compose exec spotify_mock curl -s -XPOST localhost:80/_control/config \
  -H 'Content-Type: application/json' -d '{"fail_url_substring":"trk000005","fail_status":500}'
docker compose exec spotify_mock curl -s -XPOST localhost:80/_control/reset    # clear injection
```
`fail_status`: `429` (set `retry_after`) | `401` | `500`. Scale the catalog via env
on the `spotify_mock` service: `MOCK_N_TRACKS` / `MOCK_N_ALBUMS` / `MOCK_N_ARTISTS`.

**Design + roadmap:** `docs/mock-spotify-service.md` (Phase 0/1 done locally; the
AWS/Fargate deploy is Phase 3, not yet built).

## 7. Tear down

```bash
docker compose down                  # stops containers; redis_data volume + Neo4j data persist
docker compose down -v               # also wipe the Redis dedup volume
```

## Gotchas (learned the hard way)

- **Redirect URI must be `http://127.0.0.1:8000/callback`**, not `localhost`
  (Spotify rejects localhost as insecure), and it must be registered in the
  Spotify app dashboard. Symptom: a blank page reading `redirect_uri: Insecure`.
- **Neo4j on the host** collides with a containerized Neo4j on port 7687 — that's
  why the compose `neo4j` service is commented out and the app points at
  `host.docker.internal`. Don't run both.
- **No-dedup floods get rate-limited.** A large crawl with `CRAWLED_URL_DEDUP`
  off (or a code regression) can earn a multi-hour `429 Retry-After`. The 429
  backoff is capped at 10 min; if you get a long ban, the crawl effectively
  stalls — wait it out or use a different Spotify app.
- **A plain re-run does nothing** (the dedup set persists) — use `RESET_CRAWL=true`
  for a fresh crawl. The seeder logs a warning when every seed was already crawled.
- **Tokens last ~1h.** Long crawls rely on the 401-refresh path; a fresh token is
  written on each `/callback`.
- **`USE_BATCH_ENDPOINTS` is default-off.** Only enable after probing batch access
  with `_probe_batch_endpoints.py` (Spotify postponed, not cancelled, removing
  the `?ids=` endpoints for existing apps).
