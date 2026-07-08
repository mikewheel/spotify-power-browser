# annotations/ — timestamped notes on your music

Turn listening into data: attach notes, cue points, and section maps
(intro/buildup/drop/…) to tracks in the graph, either from your keyboard
after the fact or live while the music plays.

## Two ways in

**Cold entry** — search the graph by name, annotate from prompts:

```bash
docker compose run --rm responses_write_to_neo4j \
    python3 -m application.annotations.annotate "silver soul"
```

**Live capture** — start playback anywhere (phone, desktop), keep this
terminal focused, tap keys as the song plays:

```bash
docker compose run --rm responses_write_to_neo4j \
    python3 -m application.annotations.listen
```

| Key | Action |
|---|---|
| `n` | note at the current position (prompts for text) |
| `c` | cue point (prompts for a label — "drop", "sax comes in") |
| `s` | section boundary (label → kind is inferred: "Buildup 2" → `buildup`) |
| `u` | undo the last capture |
| `+` / `-` | nudge the last capture ±500 ms |
| `q` | quit and print the session summary |

Live capture polls `GET /v1/me/player` about once a second, so positions are
accurate to ~1–2 s — nudge if it matters. It needs the
`user-read-playback-state` scope (part of the standard bundled login,
[docs/auth.md](../../docs/auth.md)); against the mock
(`-e SPOTIFY_API_BASE_URL=http://spotify_mock`) no real account is needed.

## What lands in the graph

`(:Track)-[:HAS_NOTE|HAS_CUE|HAS_SECTION]->` nodes; Sections additionally
chain via `NEXT` edges kept in start-time order even when you mark boundaries
out of order. Tracks must already exist in the graph — inserts `MATCH`, never
create. Model and invariants: [model.py](model.py), Cypher in
[queries/annotations/](../graph_database/queries/annotations/), story in
[docs/data-model.md](../../docs/data-model.md#story-4-a-listening-session-leaves-a-trail-annotations).

[timecode.py](timecode.py) parses positions (`1:23`, `83`, `41000ms`).

Plan 04's later phases (DJ set planning, playback HUD) are designed but not
built — see [docs/plans/04-annotations-and-dj-sets.md](../../docs/plans/04-annotations-and-dj-sets.md).
