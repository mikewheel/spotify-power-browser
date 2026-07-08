# graph_database/ — Neo4j connection, queries, migrations

Everything Cypher lives here, as `.cypher` files (or `.jinja` templates)
rather than strings in Python — so queries are readable, diffable, and
reusable in the Neo4j browser. What the data *means* is told in
[docs/data-model.md](../../docs/data-model.md).

| Path | What's in it |
|---|---|
| [connect.py](connect.py) | Driver setup; credentials from `secrets/neo4j_credentials.yaml`; hostname from `NEO4J_HOSTNAME` (in Docker: `host.docker.internal` → your Neo4j Desktop) |
| [initialize_database_environment.py](initialize_database_environment.py) | Applies the uniqueness constraints at startup |
| [queries/](queries/) (root) | The crawl's insert queries: single and batch variants for tracks/albums/artists/liked-songs |
| [queries/discovery/](queries/discovery/) | Discography-seed selection + album/track inserts for the adjacent-artist crawl |
| [queries/mastering/](queries/mastering/) | Song cluster merges, `REMIX_OF` edges, ISRC backfill fetches |
| [queries/overlap/](queries/overlap/) | The two-user comparison pack — see the [guided tour](../../docs/exploring-the-graph.md#the-shared-music-space-when-a-friends-library-is-loaded) |
| [queries/annotations/](queries/annotations/) | Note/Cue/Section inserts, the `NEXT`-chain maintenance, undo/nudge |
| [queries/playlists/](queries/playlists/) | ManagedPlaylist bookkeeping + the playlist generators' source queries |
| [migrations/](migrations/) | Numbered `.cypher` migrations + [run.py](migrations/run.py), the runner |

## Conventions

- **MERGE on stable IDs, never CREATE** — re-crawling is idempotent by
  construction.
- **Ownership on edges, not node properties** — `(:User)-[:LIKED]->(:Track)`;
  catalog nodes stay shared (established by migration 0001).
- **`WITH` between `MERGE` and any `CALL {}` subquery** — Neo4j 5.26-line
  servers reject the shorthand that Desktop tolerates (learned in PR #18).

## Migrations

```bash
python3 -m application.graph_database.migrations.run 0001_multiplayer_ownership \
    --me <your_spotify_user_id> --display-name "You"
```

Each migration runs in one transaction. `run.py` refuses migrations whose
header says `DO NOT RUN` (that's [0002](migrations/0002_drop_legacy_liked_props.cypher),
the legacy-property cleanup, held back until the multiplayer rollback window
closes) and refuses 0001 on a graph that already has another user's data.
There is no applied-migrations table — with two migrations, idempotence +
guards stand in for one.
