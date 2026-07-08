---
name: sync-playlists
description: Generate or update Spotify playlists from the graph (adjacent-discoveries, exploration-queue, blend) with dry-run/apply semantics and managed-playlist safety. Use when asked to create/update/sync a playlist, push discoveries to Spotify, or roll back a playlist change.
---

# Sync graph-generated playlists to Spotify

Full explanation and safety model:
**[application/playlists/README.md](../../../application/playlists/README.md)**.

```bash
# ALWAYS dry-run first (it's the default — prints the diff, writes nothing)
docker compose run --rm responses_write_to_neo4j \
    python3 -m application.playlists.sync adjacent-discoveries

# apply for real
docker compose run --rm responses_write_to_neo4j \
    python3 -m application.playlists.sync adjacent-discoveries --apply
```

Generators: `adjacent-discoveries` (needs a discography crawl),
`exploration-queue "<artist>"`, `blend <user_a> <user_b>` (needs two crawled
users). Requires the `playlist-modify-private` scope
([docs/auth.md](../../../docs/auth.md)).

Guardrails to respect (and tell the human about):

- Writes only to playlists recorded as `(:ManagedPlaylist)` — refuses
  hand-made playlists by construction. Never work around this.
- Show the human the dry-run diff before `--apply` unless they've already
  said to apply.
- Rollback: the node's `target_snapshots` keeps the last 3 track lists —
  procedure in the README.
