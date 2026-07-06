# Spotify Power Browser

For tastemakers and audiophiles of all kinds. A data-engineering pipeline that
crawls the Spotify Web API and builds a graph of your musical taste in Neo4j.

It runs as a set of containerized workers wired together by RabbitMQ, with a
Redis-backed crawl dedup cache — the whole thing comes up with a single
`docker compose up`, including the one-time Spotify OAuth flow.

## Architecture

```
requests_factory ──► Requests exchange ──► api_call_engine ──► Spotify Web API
   (seeds a crawl)      (RabbitMQ)         (GET, retry/backoff)      │
                                                                     ▼
                                              Responses exchange (fan-out ×4, RabbitMQ)
                                                                     │
            ┌────────────────────┬───────────────────┬──────────────┴────────┐
            ▼                    ▼                   ▼                        ▼
      write_to_disk        write_to_neo4j       follow_links            write_to_sqlite
      (JSON cache)         (graph insert)     (re-queues URLs)            (stub, off)
                                                     │
                                                     └──► back to Requests exchange
                                                          (recursive crawl, depth-limited)
```

- **Graph model:** `Track`, `Album`, `Artist`, `Genre` nodes; `CONTAINS`,
  `CREATED`, `SPOTIFY_CLASSIFIED_AS` relationships. Everything is `MERGE`d on
  stable Spotify IDs, so re-crawling is idempotent.
- **Dedup:** every outbound request flows through one choke point
  (`requests_factory.request_url`) and is checked against a durable Redis set, so
  redundant follow requests don't flood the API (and trip rate limits).

## Prerequisites

- **Docker Desktop** (running).
- **Neo4j Desktop** with a database running (`bolt://127.0.0.1:7687`). The crawler
  connects to it from inside Docker via `host.docker.internal`. _(Alternatively,
  run Neo4j fully in Docker — see the commented `neo4j` service in
  `compose.yaml`.)_
- **A registered Spotify app** (https://developer.spotify.com/dashboard) with:
  - the **redirect URI `http://127.0.0.1:8000/callback`** registered (Spotify
    rejects `localhost` as insecure — it must be the loopback IP).
  - its client ID and secret available for `secrets/` (below).

## Setup

Populate `secrets/` (all gitignored):

| File | Contents |
|------|----------|
| `secrets/spotify_client_id.secret` | your Spotify app client ID |
| `secrets/spotify_client_secret.secret` | your Spotify app client secret |
| `secrets/neo4j_credentials.yaml` | `username: neo4j` / `password: <your Neo4j Desktop password>` |

The OAuth token files are written here automatically by the auth flow.

## Run

```bash
docker compose up
```

What happens, in one command:
1. RabbitMQ, Redis, and the response workers start.
2. The **bundled Spotify auth service** serves a login page and the pipeline
   **waits** (a token healthcheck gates it) until you authorize.
3. Open **http://127.0.0.1:8000/login**, log into Spotify, click **Agree**. The
   callback writes your tokens to `secrets/`.
4. The healthcheck flips green, the gate releases, and the crawl of your Liked
   Songs begins — writing JSON to `data/responses/` and the graph to Neo4j.

## Configuration (`application/config.py`, all env-overridable)

| Setting | Default | Purpose |
|---------|---------|---------|
| `CRAWL_LIKED_SONGS` | `True` | crawl your saved tracks |
| `DEPTH_OF_SEARCH` | `1` | how far to follow neighbors |
| `CRAWLED_URL_DEDUP` | `True` | skip already-requested URLs (Redis) |
| `RESET_CRAWL` | `False` | clear the dedup set for a fresh crawl (set `true` to re-crawl from scratch) |
| `USE_BATCH_ENDPOINTS` | `False` | use Spotify's `?ids=` batch endpoints (~22× fewer calls) — see note below |
| `NEO4J_HOSTNAME` / `REDIS_HOSTNAME` / `RABBITMQ_HOSTNAME` | service names | point at host vs container services |

> **Batch endpoints:** Spotify postponed (not cancelled) removing the multi-id
> `?ids=` endpoints for existing apps. Verify with `_probe_batch_endpoints.py`
> before enabling; the per-item path is the safe default.

## Monitoring

- **RabbitMQ Management UI — http://localhost:15672** (`guest`/`guest`): the
  Queues tab shows per-stage backlog and live message rates. The crawl is done
  when rates flatline to 0 and queues are empty.
- **Logs:** `docker compose logs -f api_call_engine` (the live GET stream),
  `docker compose logs -f responses_write_to_neo4j` (node/edge counts).
- **Throughput pulse:** `docker compose logs --since 10s api_call_engine | grep -c 'GET:'` (0 = idle).
- **Graph:** the Neo4j Desktop browser, e.g. `MATCH (a:Artist)-[:CREATED]->(t:Track) RETURN a,t LIMIT 100`.
- **Disk cache:** `find data/responses -name '*.json' | wc -l`.

## Tests

```bash
docker compose run --rm tests
```

A pytest suite (unit + integration) that brings up RabbitMQ + Redis and targets
the host Neo4j Desktop; integration tests skip if a service is down.

## Annotations (notes, cues, section maps)

Timestamped listening annotations over crawled tracks (plan 04, phases A–B):
`(:Track)-[:HAS_NOTE|HAS_CUE|HAS_SECTION]->(…)`, sections chained with `NEXT`.

- **Cold entry** — search a track by name in the graph, annotate from prompts:
  ```bash
  docker compose run --rm responses_write_to_neo4j \
      python3 -m application.annotations.annotate "track name"
  ```
- **Live capture** — put an album on (any device), keep a terminal open, tap
  keys as it plays. Polls `/v1/me/player` ~1s; hotkeys: `n` note, `c` cue,
  `s` section boundary, `u` undo, `+`/`-` nudge 500ms, `q` quit + summary:
  ```bash
  docker compose run --rm responses_write_to_neo4j \
      python3 -m application.annotations.listen
  ```

> **Scope note:** live capture reads `GET /v1/me/player`, which requires the
> `user-read-playback-state` OAuth scope — part of the bundled re-auth
> (docs/plans/README.md, "Do these first"); until you re-authorize, it 403s
> against live Spotify. It works today against the mock:
> `docker compose run --rm -e SPOTIFY_API_BASE_URL=http://spotify_mock …`.

## Stack

Python 3.13 · Poetry 2.4 · RabbitMQ 4 · Redis 8 · Neo4j 6 (driver) · Falcon 4 ·
pika · pandas 3.

## More

- **Roadmap & status:** [ROADMAP.md](ROADMAP.md)
- **Design notes (mock Spotify service, AWS):** [docs/](docs/)
