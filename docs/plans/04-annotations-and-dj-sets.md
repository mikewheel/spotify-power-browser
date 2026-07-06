# 04 — Song annotations & DJ set planning

> Timestamped notes and section maps over every song; DJ sets as graph
> traversals with transition notes; eventually a live heads-up display at the
> controller. **Effort: XL — four independently shippable phases.**
> Depends on: bundled scope re-auth (phase B), plan 07-local for BPM/key
> (phase C richness). Feeds: the most personal value in the whole project.

## Vision

Three layers, each valuable alone:
1. **Impressions** — freeform notes on a song ("that switch-up at 2:10 👀").
2. **Section maps** — `intro → buildup 1 → drop 1 → interlude → buildup 2 →
   drop 2 → outro`, manually labelled (a deliberate, mindful listening project).
3. **DJ sets** — ordered traversals through annotated tracks, transitions
   modeled as overlaps between *sections*, with notes on technique; then a HUD
   that follows live playback through the planned set.

## Verified constraints (2026-07-06)

- **`/v1/audio-analysis` is removed for this app** (403, no message) — Spotify
  will not hand us sections/bars/beats/tempo/key. Section data comes from:
  **(a) manual annotation** (which Michael explicitly *wants* to do),
  **(b) Rekordbox/Serato exports** (cue points, BPM, key — see plan 07),
  **(c) local audio analysis** (librosa/Essentia on owned files — plan 07).
- `/v1/me/player` (playback state) is scope-gated, not removed — the same
  family as recently-played (verified alive). Scope: `user-read-playback-state`.
  → **The annotation capture trick: listen on any device, hit a hotkey in a
  terminal, we read the current track + position from the API.** No custom
  player needed for v1.
- Spotify Web Playback SDK (browser-embedded player, Premium) remains an
  option for phase D's HUD — verify at build time; not load-bearing.

## Design

### Phase A — model + manual entry (S)

```
(:Note {id, text, created_at})            (:Track)-[:HAS_NOTE]->(:Note)
(:Cue  {id, at_ms, label, created_at})    (:Track)-[:HAS_CUE]->(:Cue)
(:Section {order, start_ms, end_ms, label, kind})
(:Track)-[:HAS_SECTION]->(:Section), (:Section)-[:NEXT]->(:Section)
```
- `Section.kind` enum-ish: `intro|verse|chorus|bridge|buildup|drop|breakdown|interlude|outro|custom`
  (EDM + song-form vocabularies both first-class).
- Attach to **Track**, not Song (plan 03): timestamps are recording-specific
  (the radio edit's drop is at a different ms). Song-level rollups happen in
  queries via `VERSION_OF`.
- CLI for cold entry: `spb annotate <track-search-term>` → picks track, prompts.

### Phase B — live capture while listening (M) ⭐ the unlock

`spb listen` — a terminal loop that polls `GET /v1/me/player` (~1s):
- Displays current track + position; hotkeys:
  `n` note (prompt) · `c` cue at current ms (prompt for label) ·
  `s` section-boundary mark (label prompt; auto-chains NEXT; end_ms set by the
  next boundary or track end) · `u` undo last.
- Position accuracy ±1–2s (poll latency) — fine for section boundaries; cue
  fine-tuning happens in phase C/D UIs or by nudging (`+`/`-` 500ms keys).
- Writes straight to Neo4j via the bolt driver. Session summary on exit.
- This turns the labelling project into: *put on an album, keep one terminal
  open, tap keys as it plays.*

### Phase C — DJ set planning (M–L)

```
(:DJSet {name, created_at, notes})
(:DJSet)-[:INCLUDES {order}]->(:Track)
(:Transition {technique, notes})
(:DJSet)-[:HAS_TRANSITION]->(:Transition)
(:Transition)-[:FROM_SECTION]->(:Section)   // e.g. outro of A
(:Transition)-[:TO_SECTION]->(:Section)     // e.g. intro/buildup of B
```
- Compatibility scoring (requires BPM/key — from Rekordbox import or local
  analysis, plan 07; or manual `Track.bpm/key` properties as stopgap):
  Camelot-wheel key adjacency + BPM within ±6% → "playable next" query:
  ```cypher
  MATCH (a:Track {id:$current})-[:HAS_SECTION]->(:Section {kind:'outro'})
  MATCH (b:Track) WHERE abs(b.bpm - a.bpm)/a.bpm <= 0.06
    AND b.camelot IN compatible($a.camelot)
    AND (b)-[:HAS_SECTION]->(:Section {kind:'intro'})
  RETURN b ORDER BY … 
  ```
- Set builder CLI/queries first; a visual editor is deliberately out of scope
  until the HUD phase proves the model.

### Phase D — performance HUD (L, standalone app)

Single-page web app (Falcon serves static + a small JSON API, same image):
- Big dark-room-friendly view: current track's **section timeline** with a
  progress needle (from `/v1/me/player` polling), transition notes for the
  next planned track, and the "playable next" alternates if going off-plan.
- Graph traversal rendering: the set as a path, current node highlighted.
- Reality check documented up front: Spotify isn't a DJ deck — the HUD is a
  *navigator* over planned sets and annotations, not a mixer. With plan 07
  (local files + Rekordbox), the same HUD reads Rekordbox's bridge or runs
  against local playback — that's the true DJ-booth mode.

## Task breakdown

| # | Task | Phase | Done when |
|---|------|-------|-----------|
| T1 | Annotation model Cypher + constraints + insert queries | A | Nodes/rels writable, uniqueness enforced |
| T2 | `spb annotate` cold-entry CLI | A | Note/cue/section entry works |
| T3 | Scope `user-read-playback-state` (in the bundled re-auth) | B | `/v1/me/player` returns 200 |
| T4 | `spb listen` capture loop with hotkeys + undo + nudge | B | Live session annotates a real album hands-on |
| T5 | Mock: `/v1/me/player` route with scripted playback for tests | B | Capture loop testable offline |
| T6 | Manual `bpm`/`key`/`camelot` properties + set model + compatibility queries | C | "Playable next" returns sane candidates |
| T7 | Set builder CLI (`spb set new/add/reorder/annotate-transition`) | C | A real set plan persists in the graph |
| T8 | HUD web app (read-only v1: timeline + needle + next-transition) | D | Usable in a dark room on a laptop next to the controller |
| T9 | (with plan 07) Rekordbox XML cue/BPM/key import → Sections/Cues | C/D | Existing cues appear on graph tracks |

## Risks & open questions

- Polling accuracy (±1–2s) may frustrate precise cue work — mitigations: nudge
  keys (B), Rekordbox import (exact), local-file annotation player (07).
- Annotation is labor. The design leans into that (mindful listening is the
  point) — but sequence the library: exploration queue from plan 02 doubles as
  the annotation queue.
- Free-vs-Premium: `/v1/me/player` needs an active device and Premium for some
  state transitions; read-only polling works broadly — verify early in T4.
