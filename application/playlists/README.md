# playlists/ — the graph writes back to Spotify

Everything else in this project reads from Spotify. This module is the one
place that writes — it turns graph queries into real playlists in your
Spotify client, under strict guardrails.

## Using it

```bash
# See what would change (dry-run is the default — nothing is written)
python3 -m application.playlists.sync adjacent-discoveries

# Actually do it
python3 -m application.playlists.sync adjacent-discoveries --apply

# Other generators
python3 -m application.playlists.sync exploration-queue "Floating Points" --apply
python3 -m application.playlists.sync blend <user_a> <user_b> --apply
```

| Generator | Playlist it maintains | Needs |
|---|---|---|
| `adjacent-discoveries` | Unknown artists adjacent to your taste (bridges-ranked, popularity-capped) | a discography crawl |
| `exploration-queue <artist>` | That artist's albums you haven't explored, flattened in release order | a discography crawl |
| `blend <a> <b>` | Tracks new to both users but adjacent to both tastes | two crawled users |
| `time-capsule <year>` | Songs you liked that year | plan 09 (not yet) |

## The safety model (worth trusting)

- **Dry-run by default.** `--apply` is always an explicit choice.
- **Managed-only writes.** Every playlist this system creates is recorded as
  a `(:ManagedPlaylist)` node; before any Spotify write the code checks the
  target is on that list and refuses otherwise. It is structurally unable to
  touch a playlist you made by hand.
- **Diff, don't rebuild.** Sync computes adds/removes against the current
  state (chunked ≤100 per request, Spotify's cap) instead of wiping and
  rewriting; a full rewrite happens only when order matters and has drifted.
- **Snapshots.** The last three intended track lists are stored on the node
  (`target_snapshots`) so a bad generator run can be rolled back.
- Playlists are created private, named `[SPB] …`, with a "do not edit"
  description — clearly machine-owned in your client.

Files: [generators.py](generators.py) (the registry — a generator is a Cypher
query + identity params, hashed so the same inputs always map to the same
playlist), [sync.py](sync.py) (diff + apply + refresh-on-401),
[model.py](model.py) (the ManagedPlaylist node builders). Requires the
`playlist-modify-private` scope ([docs/auth.md](../../docs/auth.md)).

Tests: `test_playlist_generators.py`, `test_playlist_sync.py`,
`test_playlist_mock.py` (full CRUD against the mock).
