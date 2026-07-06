"""Playlist write-back (plan 08): materialize graph insights as real,
auto-maintained Spotify playlists.

Layout:
  - model.py      ManagedPlaylist param builders (pure) + graph stores
  - generators.py the named Cypher generators (target track-id lists)
  - sync.py       guarded idempotent diff-sync + the CLI entrypoint
"""
