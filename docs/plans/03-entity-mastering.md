# 03 — Entity mastering (canonical Songs across re-releases)

> One song, one node: fold deluxe editions, single-vs-album releases, and
> clean/explicit variants into canonical `(:Song)` masters so the graph reads
> the way a listener thinks. **Effort: M.** Improves: 01, 02, 07, 09.
> No hard dependencies.

## Vision

"A decent amount of noise when artists re-release songs under different
albums." Today every distinct Spotify track ID is its own `(:Track)` node —
correct at the *release* level, noisy at the *song* level. Introduce a
mastering layer that groups variants, without ever destroying release-level
truth.

## The identity ladder (strongest evidence first)

1. **ISRC** (`external_ids.isrc` on full track objects) — the recording
   industry's canonical ID for *a recording*. Same ISRC ⇒ same recording ⇒
   same Song, no questions. Covers the classic single-then-album and
   standard-then-deluxe cases (labels reuse the ISRC).
   **Not stored today** — the insert Cypher keeps no `external_ids` (see
   `insert_batch_of_tracks.cypher`) → enrichment + backfill required (T1–T3).
2. **Spotify `linked_from`** — track relinking (market-specific duplicate IDs).
   Cheap to honor when present.
3. **Heuristic clustering** — for different-ISRC variants that are still "the
   same song" to a human (clean vs explicit edits, remasters, re-recordings):
   same normalized title + same primary artist id + duration within ±3s.
4. **Manual overrides** — a YAML of forced merges/splits, because heuristics
   *will* be wrong somewhere and Michael will notice.

## Title normalization (the heart of level 3)

`normalize(title)` pipeline, order matters, each rule unit-tested:
- Lowercase; Unicode NFKD; strip punctuation/whitespace runs.
- Strip **suffix decorations** (regex, end-anchored, repeat until fixpoint):
  `- 2011 remaster(ed)?`, `- deluxe( edition)?`, `- single version`,
  `- radio edit`, `- bonus track`, `(remaster(ed)?( \d{4})?)`, `(deluxe.*)`,
  `(expanded.*)`, `(live( at .*)?)` → **but record what was stripped as the
  variant `kind`** (`remaster`, `live`, `radio_edit`, …).
- **Never strip remix credits** — `(Artist B Remix)` is a *different song* in
  DJ reality (this matters for plan 04; a remix rolls up to its own Song, with
  a `(:Song)-[:REMIX_OF]->(:Song)` edge when the parent is resolvable).
- `feat./featuring/with` clauses: strip from title, but only after the featured
  name is already among the track's credited artists (else keep — it's signal).

## Design

### Model (additive — Track/Album stay untouched)

```
(:Song {id, title})                    // id = the ISRC when known, else a hash
(:Track)-[:VERSION_OF {kind, confidence, method}]->(:Song)
(:Song)-[:REMIX_OF {confidence}]->(:Song)
(:AlbumRelease? — phase 2)             // album-level mastering deferred
```
- `kind`: `canonical | remaster | live | radio_edit | clean | explicit | demo | remix`
- `method`: `isrc | linked_from | heuristic | manual`; `confidence`: 0–1.
- Every Track gets exactly one VERSION_OF (a singleton cluster is fine —
  ubiquitous Song level means queries can always aggregate at one altitude).
- Album-level mastering (`EDITION_OF` grouping standard/deluxe releases) is
  **phase 2** — song-level delivers most of the value; album grouping falls
  out of shared track-Song sets almost for free once Songs exist.

### Pipeline (offline batch, not in the crawl path)

`python -m application.mastering.run` — idempotent, re-runnable after every
crawl:
1. Backfill/refresh missing ISRCs (batch `/v1/tracks?ids=` over tracks lacking
   `isrc`; 12.5k tracks ≈ 250 calls, minutes).
2. Cluster: ISRC exact groups → linked_from unions → heuristic pass over the
   remainder (blocking key: `(primary_artist_id, normalize(title)[0:8])` to
   keep comparisons local) → apply manual overrides last (they win).
3. MERGE Songs + VERSION_OF; **never delete** — reassignment updates the edge.
4. Emit a **review report**: clusters formed this run, sorted by descending
   ambiguity (heuristic-only clusters with duration spread > 1s first), as
   markdown → `data/mastering_review.md`. Human skims, adds overrides, reruns.

### What queries gain

- Plan 01 discovery stops counting a single collab five times across releases.
- Plan 02 completeness counts *songs heard*, not *releases heard* (a deluxe
  album no longer shows 30% unheard when you've heard every song).
- Bloom: aggregate at Song altitude — visibly less hairball.

## Task breakdown

| # | Task | Touches | Done when |
|---|------|---------|-----------|
| T1 | Store `isrc`, `album_type`, `linked_from.id` in track Cyphers (`ON CREATE` + `ON MATCH`) | `insert_*_tracks.cypher`, liked-songs Cypher | New crawls persist them |
| T2 | Mock catalog: emit ISRCs (incl. deliberate duplicate-ISRC + clean/explicit twins for tests) | `mock_spotify/catalog.py` | Fixtures expose variant cases |
| T3 | Backfill script (batch refetch tracks missing `isrc`) | `application/mastering/backfill.py` | 0 tracks without isrc (minus is_local) |
| T4 | `normalize()` + variant-kind extraction, exhaustively unit-tested (build the test list from real graph dupes: `MATCH (t:Track) WITH t.name AS n, count(*) AS c WHERE c>1 …`) | `application/mastering/normalize.py` | Tests cover remaster/deluxe/live/feat/remix cases |
| T5 | Clustering job + Song/VERSION_OF writes + overrides YAML | `application/mastering/run.py`, `secrets/../mastering_overrides.yaml` (tracked example) | Re-runnable; graph gains Songs |
| T6 | Review report generator | same | `data/mastering_review.md` renders, sorted by ambiguity |
| T7 | E2E test against mock twins from T2 | `tests/test_mastering.py` | Green |
| T8 | Rewrite the plan-01/02 deliverable queries at Song altitude | `queries/` | Both altitudes documented |

## Risks & open questions

- ISRC coverage isn't 100% (very old/indie releases) — the heuristic tier and
  the review loop exist precisely for the tail.
- Same-titled *different* songs by one artist (common: intros, interludes,
  "Untitled") — duration gate + review report catch these; overrides fix.
- Re-recordings ("Taylor's Version" pattern) share title+artist but differ in
  ISRC and often duration → land as separate Songs with `kind: canonical` each;
  arguably correct. Document the stance.
- Cross-platform identity (local files, SoundCloud) extends this ladder — see
  plan 07; keep `Song.id` platform-neutral (ISRC or content hash, never a
  Spotify id).
