# 05 — Graph MCP server (AI over your taste graph)

> A private MCP server that lets Claude (Code/Desktop) query the Neo4j taste
> graph through purpose-built tools — "map my Release Radar onto artists I
> want more of", "find niche artists who collaborated with these five".
> **Effort: S–M.** No hard dependencies (tools grow as 01/02/06 land).
> The highest leverage-per-line in the whole list — build first.

## Vision

The graph is already queryable by hand; the MCP server makes it *conversational*.
Ask analytical questions in English, get Cypher-backed answers with the graph as
ground truth. Every later plan (discovery, completeness, blends) lands as one
more tool here.

## Design

### Server shape

- **Python, official `mcp` SDK (FastMCP)** — new top-level package `mcp_server/`
  (peer of `mock_spotify/`), same Docker image, no new heavy deps.
- **Transport: stdio** for local Claude Code/Desktop use (no network exposure,
  no auth surface). A containerized streamable-HTTP variant is a later option —
  note that Neo4j Desktop is host-local, so stdio-on-host is the natural fit;
  run via `poetry run python -m mcp_server` with `NEO4J_HOSTNAME=127.0.0.1`.
- **Read-only by construction**: every session opens with
  `routing_control=READ` / read access mode — the server rejects writes at the
  transaction layer (Community Edition has no RBAC; this is the enforcement
  point). The `run_cypher` tool additionally refuses queries containing
  write clauses (belt + suspenders, friendly error).

### Tools (v1)

| Tool | Signature | Backing |
|------|-----------|---------|
| `graph_schema` | `()` → labels, rel types, property keys, counts | `db.schema.visualization` + counts |
| `run_cypher_readonly` | `(query, params?)` → rows (capped, e.g. 200) | read session |
| `find_artist` / `find_track` | `(name)` → matched nodes w/ ids | fuzzy `CONTAINS`/index |
| `discover_adjacent` | `(seed_artist_names?, max_popularity=40, min_bridges=2)` | plan 01's query |
| `artist_completeness` | `(artist_name)` → heard/catalog/queue | plan 02's query (degrades gracefully pre-02: liked-vs-catalog) |
| `collaborators_of` | `(artist_names[])` → shared collaborators ranked | pure graph |
| `shared_taste` | `(user_a, user_b)` → intersection/difference summary | post-plan-06 |
| `map_playlist_to_graph` | `(playlist_id_or_url)` → tracks matched to graph + "want-more" ranking | needs playlist read (see below) |

Resources: `schema://graph` (the schema doc) and `queries://cookbook` (the
curated Cypher pack — same files as `application/graph_database/queries/`).

### The Release Radar question (probe before building T6)

`map_playlist_to_graph` on **Spotify-generated** playlists (Release Radar,
Discover Weekly) hits the 2024-11 restriction on algorithmic/editorial
playlists *for new apps*. Whether this 2023 app is grandfathered is **unknown —
probe it** (one GET of the Release Radar playlist id with the live token;
extend `_probe_api_surface.py`). If blocked: the fallback is "Like the songs
you care about / add to a personal playlist" → personal playlists read fine.

### Registration

- Project-local `.mcp.json` (stdio command) → Claude Code picks it up in-repo.
- Claude Desktop config snippet documented in the README (same command).
- Env: `NEO4J_HOSTNAME=127.0.0.1`, creds file path — reuse
  `connect_to_neo4j(SECRETS_DIR / 'neo4j_credentials.yaml')`.

## Task breakdown

| # | Task | Done when |
|---|------|-----------|
| T1 | Scaffold `mcp_server/` + FastMCP + read-only Neo4j session helper | `mcp dev` smoke test lists tools |
| T2 | `graph_schema`, `run_cypher_readonly` (+ write-clause guard + row cap) | Claude Code answers "how many tracks?" via the tool |
| T3 | `find_artist`/`find_track` + `collaborators_of` + `discover_adjacent` | English question → ranked unknown artists, live |
| T4 | `artist_completeness` (pre-02 degraded mode documented) | Returns liked-vs-catalog today |
| T5 | `.mcp.json` + Desktop snippet + cookbook resource | Fresh session uses it with zero setup |
| T6 | Probe algorithmic-playlist access; implement `map_playlist_to_graph` (or the documented fallback) | Release Radar question answered either way |
| T7 | Tests: tool functions against the test graph (mock catalog crawled into a scratch DB, or fixture graph) | Green in compose tests |

## Risks & open questions

- **Cypher injection ≈ non-issue at read-only**, but the row cap and query
  timeout (`execute_query(timeout_=…)`) keep a pathological generated query
  from hanging the session — set both.
- Schema drift as plans land → `graph_schema` is computed live, and the
  cookbook is the single place to update; keep tools thin over queries.
- Multi-user (plan 06) will want per-user parameterization — design tool
  signatures with an optional `user` param from day one, defaulting to the
  sole user.
