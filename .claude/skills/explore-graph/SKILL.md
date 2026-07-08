---
name: explore-graph
description: Explore the crawled taste graph in Neo4j — orientation queries, the ten common questions, two-user overlap analysis, MCP-assisted exploration. Use when asked to query the graph, analyze taste, find discoveries, compare users, or answer any "what does my music data say" question.
---

# Explore the taste graph

The tutorial is **[docs/exploring-the-graph.md](../../../docs/exploring-the-graph.md)**:
orientation queries, ten copy-paste questions (top artists, genre profile,
taste-over-time, deep cuts, discovery frontier, mastering roll-ups, album
loyalty), and the two-user overlap tour. What the nodes/edges mean:
[docs/data-model.md](../../../docs/data-model.md).

Ways to run queries, best first:

1. **MCP tools** (if connected — see the `connect-mcp` skill): `graph_schema`
   first, then `find_artist` / `collaborators_of` / `discover_adjacent`, and
   `run_cypher_readonly` for everything else. Read-only, row-capped.
2. **Curated query packs** in `application/graph_database/queries/`
   (`overlap/` takes `$a`/`$b` user ids; `discovery/`, `mastering/` too) —
   tested, parameterized, ready to paste into the Neo4j browser.
3. **Ad-hoc Cypher** against `bolt://127.0.0.1:7687` (credentials in
   `secrets/neo4j_credentials.yaml`).

Prerequisites worth checking before deep analysis:

- Artist `popularity` null everywhere? Run the enrichment:
  `docker compose run --rm responses_write_to_neo4j python3 -m application.discovery.backfill_artists`
- Duplicate-looking tracks? Run mastering first (`master-library` skill).
- Comparing two users? Both must be crawled (`onboard-second-user` skill).
