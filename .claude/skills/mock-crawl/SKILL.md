---
name: mock-crawl
description: Run the full pipeline offline against the bundled mock Spotify — no real account, deterministic catalog, on-demand failure injection. Use when asked to run offline, demo the pipeline, test failure handling live, or crawl without touching real Spotify.
---

# Run a mock-backed crawl (offline)

Background: [docs/delivery.md](../../../docs/delivery.md#path-3-the-offline-mock-crawl)
and [mock_spotify/README.md](../../../mock_spotify/README.md).

```bash
# mock tokens satisfy the auth gate (no OAuth needed)
echo -n mock-access-token  > secrets/spotify_api_token.secret
echo -n mock-refresh-token > secrets/spotify_refresh_token.secret

RESET_CRAWL=true docker compose -f compose.yaml -f docker-compose.mock.yml up
```

The overlay points every service's Spotify URLs at `http://spotify_mock`; the
crawl runs entirely offline against a deterministic ~60-track catalog
(size knobs: `MOCK_N_TRACKS` etc.). Monitor exactly like a real crawl
([docs/observability.md](../../../docs/observability.md)).

Inject failures mid-run to watch the engine cope:

```bash
docker compose exec spotify_mock curl -s -X POST http://localhost/_control/config \
    -d '{"fail_next_n": 5, "fail_status": 429, "retry_after": 2}'
docker compose exec spotify_mock curl -s -X POST http://localhost/_control/reset
```

Cautions: don't overwrite real tokens — check whether
`secrets/spotify_api_token.secret` holds a real token before step 1 (back it
up or run from a worktree checkout); and the mock writes mock nodes into
whatever Neo4j the stack points at, so prefer a scratch database (or
`RESET_CRAWL=true` + purge `MATCH (t:Track) WHERE t.id STARTS WITH 'trk' DETACH DELETE t`
afterwards).
