# mock_spotify/ — a fake Spotify you can boss around

A small Falcon app that impersonates both `api.spotify.com` and
`accounts.spotify.com` well enough for the whole pipeline to run against it —
offline, deterministic, and with failures available on demand. It exists so
the resilience paths (429 backoff, 401 refresh, 500 give-up) can be *tested*
instead of waited for, and so full crawls can run with no real account
([docs/delivery.md](../docs/delivery.md#path-3-the-offline-mock-crawl)).

## What it serves

- **Crawl surface:** `/v1/me/tracks` (paginated, per-bearer identity),
  single + batch tracks/albums/artists, discographies
  (`/v1/artists/{id}/albums`, `/v1/albums/{id}/tracks`).
- **Auth surface:** `/authorize` (round-trips your CSRF state) and
  `/api/token` (code + refresh grants, enforcing HTTP Basic like the real
  thing).
- **Feature surfaces:** `/v1/me/player` (a controllable "now playing" for
  annotation tests), `/v1/me`, playlist CRUD (create/read/update/add/remove
  with `snapshot_id` bumps and the 100-track cap).

[catalog.py](catalog.py) fabricates the data *functionally* — `trk000017`
always reconstructs to the same track, so there's no database and every run
is reproducible. The catalog includes deliberately tricky corners: a
second overlapping user (`mockuser2`), a >50-album artist (forces
pagination), frontier collaborators who exist only on discography tracks,
and near-duplicate track variants that exercise the mastering heuristics.

## The control plane

```bash
curl -X POST http://spotify_mock/_control/config \
     -d '{"fail_next_n": 3, "fail_status": 429, "retry_after": 1}'
curl -X POST http://spotify_mock/_control/reset      # back to clean state
curl http://spotify_mock/_control/health
```

`fail_next_n` / `fail_url_substring` + `fail_status` inject 429/401/500 at
will; `player_*` keys drive the fake player; `token_user` chooses which mock
user the next login mints tokens for. This is the API the resilience tests
lean on.

## Running it

As a compose service (profile-gated): `docker compose --profile mock up
spotify_mock`, or implicitly via the tests / the mock-crawl overlay
([docker-compose.mock.yml](../docker-compose.mock.yml)). It listens on
port 80 inside the network at `http://spotify_mock`. Size knobs
(`MOCK_N_TRACKS`, …) are env vars — see [catalog.py](catalog.py).

Design history: [docs/mock-spotify-service.md](../docs/mock-spotify-service.md).
