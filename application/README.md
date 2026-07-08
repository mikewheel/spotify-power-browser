# application/ — the pipeline

Everything the Docker Compose services actually run. The big picture (with
diagrams) is in [docs/architecture.md](../docs/architecture.md); this is the
door-by-door tour.

## The five files/folders that ARE the crawler

| Path | Role | Runs as |
|---|---|---|
| [config.py](config.py) | Every setting and feature flag, all env-overridable | imported everywhere |
| [requests_factory.py](requests_factory.py) | Seeds a crawl; the single choke point (`request_url`) every outbound URL passes through, where Redis dedup happens | `requests_factory_start_crawls` service |
| [api_call_engine.py](api_call_engine.py) | The only code that talks HTTP to Spotify: GETs, 429 backoff (capped 10 min), 500 retries, 401 token refresh, pagination | `api_call_engine` service |
| [response_handlers/](response_handlers/) | One class per Spotify endpoint; workers dispatch each response to the right one | the three `responses_*` services |
| [message_queue/](message_queue/) + [cache/](cache/) | RabbitMQ and Redis plumbing | imported by the above |

## The supporting cast

| Path | What it's for |
|---|---|
| [spotify_authentication/](spotify_authentication/) | OAuth login web app + token storage + refresh ([docs/auth.md](../docs/auth.md)) |
| [graph_database/](graph_database/) | Neo4j connection, all Cypher queries, migrations ([docs/data-model.md](../docs/data-model.md)) |
| [discovery/](discovery/) | Artist popularity/followers backfill (post-crawl enrichment) |
| [mastering/](mastering/) | Rolls duplicate releases into canonical Songs (post-crawl batch job) |
| [annotations/](annotations/) | Timestamped notes/cues/sections on tracks (interactive CLIs) |
| [playlists/](playlists/) | Writes graph-derived playlists back to Spotify (guarded, dry-run default) |
| [loggers.py](loggers.py) | Plain-text logging to stdout (a JSON formatter exists but is off) |

## How a change here reaches a running system

All of this is baked into the one shared Docker image, so:
`docker compose build && docker compose up`. Nothing is volume-mounted at
runtime except `secrets/`, `data/`, `tests/`, and `mock_spotify/`.
