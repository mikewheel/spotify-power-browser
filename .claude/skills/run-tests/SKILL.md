---
name: run-tests
description: Run the Spotify Power Browser test suite in Docker and interpret the results (skips vs failures, service dependencies, safety rails). Use when asked to run tests, verify a change, check the suite, or investigate a test failure in this project.
---

# Run the test suite

Everything you need to know is in **[docs/testing.md](../../../docs/testing.md)**
(the four layers, safety rails, gaps) and **[tests/README.md](../../../tests/README.md)**
(per-file index). Short version:

```bash
docker compose run --rm tests                          # everything
docker compose run --rm tests python3 -m pytest tests/test_dispatcher.py -v
docker compose run --rm tests python3 -m pytest tests/ -k "mastering" -v
```

Compose brings up RabbitMQ, Redis, and the mock Spotify automatically.

## Interpreting results

- **Skips are normal**: Neo4j-dependent tests skip when Neo4j Desktop isn't
  running; `mcp` wiring tests skip on a stale image. Failures are never normal.
- **After changing code, rebuild first**: `docker compose build` (tests/ and
  mock_spotify/ are volume-mounted, but application/ and mcp_server/ are baked
  into the image).
- **"test wrote to the REAL secrets dir"** — the test is missing a tmp_path
  monkeypatch for token paths; see the `store` fixture in
  `tests/test_token_store.py` and docs/testing.md.
- In a Claude worktree the stack is auto-isolated (own image tag + project,
  no host ports) — safe to run alongside a live crawl on the primary checkout.
