# tests/ — the suite, file by file

How to run it, how it's layered, and why it can't clobber your real data:
[docs/testing.md](../docs/testing.md). This page is the index.

```bash
docker compose run --rm tests                    # everything
docker compose run --rm tests python3 -m pytest tests/test_dispatcher.py -v
```

## Fixtures worth knowing ([conftest.py](conftest.py))

- `guard_real_secrets_untouched` (autouse) — snapshots `secrets/` before each
  test and fails the test if anything changed. The tripwire behind PR #27.
- `rabbitmq_channel`, `redis_client`, `neo4j_driver`, `mock_base` — connect
  or `pytest.skip()`. Skips mean a service wasn't up; failures mean a bug.

## The files, grouped

**Pipeline mechanics** — `test_config` (env parsing), `test_dispatcher`
(URL → handler routing), `test_batch_handler` (chunking/pagination/depth),
`test_request_batch` (Spotify's 50/20/50 ID caps), `test_liked_songs`
(response parsing), `test_rabbitmq` (queue durability flags),
`test_redis_dedup` (shared vs per-user sets, rollback), `test_neo4j_cypher`
(insert queries against a real graph).

**Auth** — `test_oauth_service` (login/callback/CSRF state), `test_token_store`
(namespacing, primary mirror), `test_refresh_token` (client auth, both-way
mirror).

**Resilience** — `test_engine_resilience` (429 cap / 401 refresh / 500
give-up + dedup rollback, via mock failure injection),
`test_engine_consumer_resilience` (queues survive reconnects),
`test_engine_multiuser` (token envelopes per user).

**End-to-end** — `test_e2e_crawl` (liked songs → graph), `test_discovery_e2e`
(the depth-2 discography crawl), `test_multiplayer_e2e` (two users, overlap
queries, migrations — the best narrative read in the suite),
`test_mastering_e2e`.

**Features** — `test_mastering_normalize` / `_clustering` / `_overrides` /
`_backfill` / `_report`; `test_annotations_model` / `_annotate` / `_cypher` /
`_tracker` / `_mock_player`; `test_playlist_generators` / `_sync` / `_mock`.

**MCP server** — `test_mcp_server_readonly` (the write-blocking guard),
`test_mcp_server_tools` (each tool against seeded data),
`test_mcp_server_wiring` (registration completeness).

**The mock itself** — `test_mock_service`, `test_mock_multiuser`.
