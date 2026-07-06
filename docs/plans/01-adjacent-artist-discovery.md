# 01 — Adjacent-artist discovery (depth-2 collab crawl)

> Surface artists you've never heard of who are **structurally close** to your
> taste — collaborators-of-collaborators, weighted toward the obscure.
> **Effort: M–L.** Depends on: PR #16 (refresh fix). Unblocks: 02 (discography
> machinery), better 05/08 payloads.

## Vision

"Discover new artists that are relatively unknown, but adjacent to people I
already listen to." Expand the crawl one more artist-hop: for every artist in
the liked-songs graph, pull their **full discography** (albums → tracks), and
from those tracks harvest the **collaborating artists** (features, remixes,
split EPs) that aren't in the graph yet. Then rank that frontier by
*adjacency* (how many independent paths connect them to your taste) over
*popularity* (Spotify's 0–100 popularity + follower count — lower is more
interesting).

## Verified constraints (2026-07-06)

- `related-artists` and `recommendations` are **removed** for this app (404).
  The collab-graph approach isn't a workaround — it's the only mechanism, and
  it's better: explainable ("adjacent via Four Tet + Floating Points"), tunable,
  and it enriches the graph permanently.
- `artists/{id}/albums` returns **200** — discography crawling works.
- Batch `?ids=` endpoints work (re-verified) — **a batch album fetch returns each
  album's track list inline** (first 50 tracks), so album tracks come free.

## Current state in the repo

- `DEPTH_OF_SEARCH = 1` in `application/config.py` is the only thing keeping two
  **stub handlers** off the execution path (`application/response_handlers/artists/albums_of_artist.py`,
  `application/response_handlers/albums/tracks_of_album.py` — `# FIXME`, no class).
  This plan implements them (also closing Roadmap Stage 2's first bullet).
- Artist nodes store only `uri,id,name,spotify_url,type` (+ genre rels) — **no
  `popularity`/`followers`**, which the ranking needs (see
  `application/graph_database/queries/insert_batch_of_artists.cypher`).
- The Redis dedup set makes re-crawls cheap; batching keeps volumes sane.

## Design

### Crawl shape (not a blanket depth bump)

A naive `DEPTH_OF_SEARCH = 2` re-follows every track's album/artists exponentially.
Instead, introduce an explicit second crawl kind, gated by its own flag:

- `CRAWL_ARTIST_DISCOGRAPHIES` (`_env_bool`, default off) + `ARTIST_AFFINITY_MIN`
  (default 3): seed a discography crawl **only for artists with ≥ N liked
  tracks** — measure the threshold first with:
  ```cypher
  MATCH (a:Artist)-[:CREATED]->(t:Track {liked_songs: true})
  WITH a, count(t) AS liked WHERE liked >= 3 RETURN count(a)
  ```
- Seeder publishes `GET /v1/artists/{id}/albums?include_groups=album,single&limit=50`
  per qualifying artist (`application/requests_factory.py` gains a
  `request_artist_discographies()` entry).
- New handler `AlbumsOfArtist` implements the stub: for each album id in the
  response, request batched full albums (`/v1/albums?ids=`, chunks of 20 —
  reuse `request_batch` machinery). Full album objects flow through the existing
  `several_albums` → Neo4j path **and already embed their track lists**, so a
  separate tracks-of-album fetch is only needed for albums with > 50 tracks
  (rare; implement `TracksOfAlbum` for that pagination case).
- Track inserts from these albums arrive with their track-level `artists`
  arrays — the **collab frontier materializes automatically** via the existing
  `MERGE (ar:Artist)` in the Cypher. New artists get metadata enriched by a
  final batched `/v1/artists?ids=` sweep (existing `several_artists` handler).
- Set message depth so follow-links does **not** recurse further from these
  responses (frontier artists' own discographies are NOT crawled — that's
  depth 3 territory and a separate decision).

### Volume estimate (sanity-checked against the 2026-07-06 run)

~1,200 qualifying artists → ~1,800 album-list calls; ~12k unique albums → 600
batch-album calls; ~15k frontier artists → 300 batch-artist calls. **≈ 2,700
calls ≈ 20–25 min** at the observed ~140 req/min with zero 429s. Runs > 1h are
possible at low thresholds — hence the PR #16 dependency.

### Provenance + ranking

- Tag nodes created by this crawl: `SET a.crawl_source = coalesce(a.crawl_source, 'discography')`
  (liked-songs crawl sets `liked_songs = true` already; frontier artists have
  neither → identifiable).
- Enrich Artist Cypher with `popularity` and `followers.total` (`ON CREATE` +
  `ON MATCH SET` so the backfill sweep updates existing nodes too).
- Discovery query (the deliverable — also exposed as an 05 MCP tool and an 08
  playlist generator):
  ```cypher
  MATCH (mine:Artist)-[:CREATED]->(:Track {liked_songs: true})
  WITH collect(DISTINCT mine) AS my_artists
  UNWIND my_artists AS m
  MATCH (m)-[:CREATED]->(t:Track)<-[:CREATED]-(cand:Artist)
  WHERE NOT cand IN my_artists AND cand.popularity <= $max_popularity
  WITH cand, count(DISTINCT m) AS bridges,
       collect(DISTINCT m.name)[..5] AS via
  WHERE bridges >= $min_bridges
  RETURN cand.name, cand.popularity, cand.followers, bridges, via
  ORDER BY bridges DESC, cand.popularity ASC LIMIT 50
  ```

## Task breakdown

| # | Task | Touches | Done when |
|---|------|---------|-----------|
| T1 | Measure affinity distribution; pick default `ARTIST_AFFINITY_MIN` | one-off Cypher | Threshold documented in config comment |
| T2 | Enrich artist Cypher with `popularity`/`followers`; backfill sweep (batch `/v1/artists?ids=` over all 7.6k ids ≈ 152 calls) | `insert_batch_of_artists.cypher`, small backfill script | All Artist nodes have popularity |
| T3 | Config flags `CRAWL_ARTIST_DISCOGRAPHIES`, `ARTIST_AFFINITY_MIN` + compose passthrough | `config.py`, `compose.yaml` | Flags reach containers (check with the PR #15 test) |
| T4 | Seeder: publish qualifying artists' album-list URLs | `requests_factory.py` | Seeds visible in RabbitMQ |
| T5 | Implement `AlbumsOfArtist` handler (album-id harvest → batch album requests, pagination via `next`) | `artists/albums_of_artist.py`, dispatcher | Stub replaced; unit tests vs fixtures |
| T6 | Implement `TracksOfAlbum` for >50-track albums | `albums/tracks_of_album.py` | Stub replaced |
| T7 | Mock: add `/v1/artists/{id}/albums` + `/v1/albums/{id}/tracks` routes + catalog support | `mock_spotify/` | E2E discography crawl passes offline |
| T8 | E2E test: mock crawl with affinity gating; assert frontier artists exist w/o `liked_songs` | `tests/` | Green in `docker compose run --rm tests` |
| T9 | Live run (start small: `ARTIST_AFFINITY_MIN=10`), then production run | — | Frontier populated; volumes match estimate |
| T10 | Discovery query pack + doc | `application/graph_database/queries/discovery/` | Returns ranked unknowns with "via" explanations |

## Risks & open questions

- **Compilation/appears-on noise**: `include_groups=album,single` excludes
  compilations — deliberate. Revisit if remix-hunting matters (EDM: it might;
  `appears_on` is where remixes live — consider a follow-up flag).
- Popularity is Spotify-global, not scene-relative; a popularity-99 artist with
  20 bridges still ranks below an unknown with 3. Tune the ordering, or
  post-process with a normalized score (`bridges / log(followers+2)`).
- Genre filtering ("adjacent *within* EDM") is a natural v2 lever — the Genre
  rels are already there.
