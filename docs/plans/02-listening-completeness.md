# 02 — Listening completeness (history + discography coverage)

> "Which artists do I love but haven't *properly* explored?" — full listening
> history joined against full discographies, with a mindful-exploration queue.
> **Effort: M (code) + external lead time.** Depends on: 01 (discography
> machinery), bundled scope re-auth, PR #16. Feeds: 08, 09.

## Vision

Two ingredients multiplied together:
1. **Denominator** — each artist's complete discography (plan 01's crawl).
2. **Numerator** — everything you've ever played, weighted by whether you
   *actually listened* (≥30s) vs skipped.

Deliverable: per-artist / per-album completeness scores and a ranked
"exploration queue" — albums with zero plays from artists with high affinity.

## Verified constraints (2026-07-06) — the honest reality of listening history

- `/v1/me/player/recently-played` → 403 **"Insufficient client scope"** — the
  endpoint is **alive** for this app; it needs the `user-read-recently-played`
  scope. But it only ever returns the **last 50 plays** — it's a *going-forward*
  capture mechanism, not an archive.
- `/v1/me/top/{artists,tracks}` → same status: alive, needs `user-top-read`.
  Gives ranked top-50 over ~4 weeks / ~6 months / years — a coarse affinity
  signal, not history.
- **"From the beginning of time" exists nowhere in the API.** The only source is
  Spotify's privacy data export (Account → Privacy → Download your data →
  check **Extended streaming history**). Takes days–weeks to arrive. This is a
  GDPR mechanism, unaffected by the API deprecations. **Request it on day 1.**

## Export format (what the importer must parse)

Two generations, both JSON:
- **Extended streaming history** (the one to request):
  `Streaming_History_Audio_*.json`, fields incl. `ts`, `ms_played`,
  `master_metadata_track_name`, `master_metadata_album_artist_name`,
  `master_metadata_album_album_name`, `spotify_track_uri`, `reason_start`,
  `reason_end`, `skipped`, `platform`, `conn_country`. **`spotify_track_uri`
  makes joining trivial** for the vast majority of rows.
- **Basic account data** (fallback; only ~1 year): `StreamingHistory{N}.json`
  with `endTime`, `artistName`, `trackName`, `msPlayed` — no URI → requires
  fuzzy matching (normalize per plan 03, match on title+artist).

## Design

### Data model (additive)

```
(:Play {ts, ms_played, reason_start, reason_end, skipped, platform, source})
(:User)-[:DID]->(:Play)-[:OF]->(:Track)
```
- `source`: `'export'` | `'poller'` (dedup boundary between the two ingest paths).
- Volume: years of listening ≈ 100k–500k Play nodes — trivial for Neo4j; index
  `(:Play).ts` and constrain uniqueness on `(user_id, ts)` (exports have
  second-precision timestamps; collisions are re-imports, which MERGE absorbs).
- The `(:User)` node comes from plan 06; **until 06 lands, create the single
  `(:User {id: <your spotify id>})` node** — forward-compatible, no migration
  later. Get the id from `GET /v1/me`.
- Aggregates for query speed (recomputed by the importer, not live):
  `(:User)-[:LISTENED_TO {play_count, ms_total, first_play, last_play}]->(:Track)`.

### Ingest paths

1. **Export importer** (CLI): `python -m application.ingest.streaming_history <dir>`
   — parses both format generations, MERGEs Plays idempotently, resolves tracks
   by URI (fallback: normalized title+artist per plan 03), reports unmatched
   rows to a CSV for manual/later resolution. Unmatched tracks that have URIs →
   publish crawl requests for them (they're tracks you played but never liked —
   the graph should still know them; requires plan 01's machinery running or a
   simple batch fetch).
2. **Recently-played poller** (new compose service, same image):
   `application/ingest/recently_played_poller.py` — every 20 min, GET
   recently-played with the `after` cursor (persist cursor in Redis:
   `spb:recently_played_cursor`). 50-track window ≈ 2.5h of continuous
   listening; 20-min cadence is ~7× safety margin. Writes the same Play shape
   (`source: 'poller'`). Idle-friendly: no plays → no writes.

### Completeness queries (the deliverable)

```cypher
// Artist completeness: % of discography tracks with a meaningful listen (≥30s)
MATCH (a:Artist)-[:CREATED]->(t:Track)
OPTIONAL MATCH (u:User {id:$me})-[l:LISTENED_TO]->(t) WHERE l.ms_total >= 30000
WITH a, count(t) AS catalog, count(l) AS heard
WHERE catalog >= 10
RETURN a.name, heard, catalog, toFloat(heard)/catalog AS completeness
ORDER BY completeness ASC
```
Plus: album-level completeness; the **exploration queue** (high affinity =
many liked tracks or high `top` rank, low completeness, sorted by album
release date); and "started but abandoned" albums (1–2 plays, never returned).

## Task breakdown

| # | Task | Touches | Done when |
|---|------|---------|-----------|
| T1 | **Human: request the extended export** (day 1!) | spotify.com privacy page | Confirmation email |
| T2 | Add scopes (bundle: `user-read-recently-played user-top-read` + plans 04/08's) and re-auth once | `api_authorization_web_service.py` | Probe returns 200 on recently-played |
| T3 | `(:User)` node + Play/LISTENED_TO model + constraints | `graph_database/queries/`, `initialize_database_environment.py` | Constraints exist |
| T4 | Export importer with both format generations + unmatched-row report | `application/ingest/` | Re-runnable; counts match export row totals |
| T5 | Poller service + Redis cursor + compose wiring | `application/ingest/`, `compose.yaml` | Plays appear ≤20 min after listening |
| T6 | Backfill fetch for played-but-unknown tracks | importer + batch machinery | Unmatched-with-URI count → ~0 |
| T7 | Top-items snapshot job (weekly, into `(:TopSnapshot)` or rel props) | `application/ingest/` | Affinity signal queryable |
| T8 | Completeness + exploration-queue query pack | `queries/completeness/` | Queries documented, return sane results |
| T9 | Tests: importer on fixture files (both generations); poller against mock (add `/v1/me/player/recently-played` route) | `tests/`, `mock_spotify/` | Green offline |

## Risks & open questions

- Export arrival is out of our control (days–weeks). All code paths (T3–T9) are
  buildable and testable against fixtures before it arrives.
- Pre-2014-ish export rows sometimes lack URIs → fuzzy matching needs plan 03's
  normalizer for good match rates; ship with exact-URI first, iterate.
- Podcasts/audiobooks appear in exports (`spotify_episode_uri`) — filter them
  out (or model later; out of scope here).
- Multiple devices offline-syncing can produce odd `ts` ordering — MERGE on
  `(user, ts)` absorbs it.
