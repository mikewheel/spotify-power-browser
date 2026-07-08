---
name: annotate-listening
description: Capture notes, cue points, and section maps on tracks — cold entry by track name or live hotkey capture while music plays. Use when asked to annotate a track, mark cues/sections, run a listening session, or query existing annotations.
---

# Annotate tracks

Full guide (hotkeys, formats, graph shape):
**[application/annotations/README.md](../../../application/annotations/README.md)**.

```bash
# Cold entry: search the graph by name, annotate from prompts
docker compose run --rm responses_write_to_neo4j \
    python3 -m application.annotations.annotate "track name"

# Live capture: start playback anywhere, then tap hotkeys in this terminal
# (n note · c cue · s section · u undo · +/- nudge 500ms · q quit+summary)
docker compose run --rm responses_write_to_neo4j \
    python3 -m application.annotations.listen
```

Constraints to check first: the track must already be in the graph (inserts
MATCH, never create — crawl first); live capture needs the
`user-read-playback-state` scope ([docs/auth.md](../../../docs/auth.md)) and
polls ~1 s, so positions are ±1–2 s (nudge with `+`/`-`). Against the mock,
add `-e SPOTIFY_API_BASE_URL=http://spotify_mock` and drive the fake player
via `POST /_control/config` ([mock_spotify/README.md](../../../mock_spotify/README.md)).

Read annotations back:
`MATCH (t:Track)-[:HAS_NOTE|HAS_CUE|HAS_SECTION]->(x) RETURN t.name, labels(x), x`.
