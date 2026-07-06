# 09 — Taste over time (bonus plan: your musical eras from data you already have)

> Liking-rate timelines, genre drift, era detection, artist loyalty curves,
> year-in-review reports — powered by `added_at` timestamps **already sitting
> in your graph today**, upgraded by plan 02's play history when it lands.
> **Effort: S–M.** Depends on: nothing (v1) / plan 02 (v2 depth).
> _Claude-suggested addition._

## Why this plan exists

Every liked song carries `date_added_to_liked_songs` (verified: stored by
`insert_batch_of_liked_songs.cypher` since day one) — 12,547 timestamped taste
events spanning your whole Spotify life, **queryable right now**. That's a
longitudinal dataset most people would kill for, and it's the narrative layer
("who was I in 2019?") that makes the graph *feel* like a life archive. It also
finally gives `pandas` (a dependency since forever, used never — see ROADMAP
§Notable gaps) a job.

## Design

### v1 — likes-based (buildable today)

Analytics module `application/analytics/` (pandas over Cypher extracts) + a
report generator emitting self-contained HTML (inline SVG charts via
matplotlib; add as dev-friendly dep) to `data/reports/`:

- **Liking-rate timeline** — likes/month since account birth; annotated peaks
  ("the 847-song month"). One Cypher, one resample.
- **Genre drift** — per quarter, the genre-share vector of that quarter's
  likes (via Artist→Genre); stacked-area chart; long-tail genres bucketed.
- **Era detection** — cosine distance between consecutive quarters'
  genre-share vectors; distance > threshold ⇒ era boundary; label eras by
  their top-3 distinguishing genres. (Simple, explainable — no ML pomp.)
- **Artist arcs** — first-like date, cumulative likes per artist; "discovery
  cohorts" (artists you found in era X and still like vs abandoned).
- **Rediscovery candidates** — artists with heavy old likes and nothing recent
  (pre-plan-02 proxy for "haven't listened in ages").
- **`spb report year-in-review <year>`** — the flagship: new artists
  discovered, genre shifts, era membership, top liking streaks, longest gap,
  the time-capsule track list (→ plan 08's generator).

### v2 — plays-based (after plan 02)

The same analytics gain a second axis (what you *played*, not just claimed):
listening-vs-liking divergence; true artist loyalty half-life (play decay
after discovery); skip-rate by era; seasonality (winter genres are real);
"albums that soundtracked <month>" from play density.

### Delivery formats

1. HTML reports (v1) — zero-infra, shareable.
2. Saved-query pack + Bloom perspective (era-colored) for interactive spelunking.
3. MCP tools (plan 05): `taste_timeline`, `era_of(date)`, `year_in_review(year)`
   — the agentic path ("compare my 2019 and 2023 selves").

## Task breakdown

| # | Task | Done when |
|---|------|-----------|
| T1 | Extraction Cyphers (likes+dates+genres) + pandas loaders | DataFrame round-trip tested |
| T2 | Timeline + genre-drift + era detection with unit-tested boundaries | Eras look *right* to Michael (the only test that matters) |
| T3 | Year-in-review HTML generator (matplotlib inline-SVG, self-contained) | `data/reports/2025.html` opens beautifully |
| T4 | Rediscovery + artist-arc queries → cookbook + MCP tools | Queryable via Claude |
| T5 | (post-02) plays-based v2 metrics | Divergence report exists |
| T6 | Time-capsule generator handoff to plan 08 | `[SPB] 2019 Time Capsule` on your phone |

## Risks & open questions

- `added_at` ≠ discovery date (bulk-liking sprees skew eras) — era detection on
  *rates* + genre *shares* is robust to spree volume, but call it out in
  report footnotes; plan 02's play data corrects it properly.
- Genre vocabulary is Spotify's (634 tags, uneven granularity) — bucket via a
  small curated rollup map (checked-in YAML, editable) before charting.
- Timezone: `added_at` is UTC; day-level charts should shift to local — store
  the offset choice in one place.
