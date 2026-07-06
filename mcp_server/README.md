# spotify-graph MCP server

A **read-only** MCP server that lets AI clients (Claude Code, Claude Desktop)
query the Neo4j taste graph through purpose-built tools — plan
[05](../docs/plans/05-graph-mcp-server.md). It runs over **stdio inside the
project Docker image** (write once, run everywhere) and talks to Neo4j Desktop
on the host, exactly like the `responses_write_to_neo4j` compose service.

## Setup

1. Build the image once: `docker compose build` (installs the `mcp` SDK and
   copies `mcp_server/` in).
2. Have Neo4j Desktop running with `secrets/neo4j_credentials.yaml` in place
   (the server starts fine without it; the first tool call needs it).

### Claude Code

Nothing to do — the project-root [`.mcp.json`](../.mcp.json) registers the
server via [`scripts/mcp_server.sh`](../scripts/mcp_server.sh); a fresh session
in this repo picks it up automatically.

### Claude Desktop

Add to `~/Library/Application Support/Claude/claude_desktop_config.json`
(macOS), with the absolute path to your checkout:

```json
{
  "mcpServers": {
    "spotify-graph": {
      "command": "bash",
      "args": ["/Users/michael/software_projects/spotify-power-browser/scripts/mcp_server.sh"]
    }
  }
}
```

## Tools (v1)

| Tool | Signature | Notes |
|------|-----------|-------|
| `graph_schema` | `()` | Live labels / rel types / patterns / properties / counts — call first |
| `run_cypher_readonly` | `(query, params?)` | Escape hatch; write clauses rejected, rows capped, timeout |
| `find_artist` / `find_track` | `(name, limit=25)` | Fuzzy CONTAINS lookup; resolve exact names for the tools below |
| `collaborators_of` | `(artist_names[], limit=25)` | Shared track credits, ranked by seeds bridged |
| `discover_adjacent` | `(seed_artist_names?, max_popularity=40, min_bridges=2, limit=50)` | Plan 01's discovery query |
| `artist_completeness` | `(artist_name, limit=10)` | **Degraded mode**: liked-vs-catalog until plan 02 lands |

Resources: `schema://graph` (live schema JSON) and `queries://cookbook`
(the curated Cypher pack from `application/graph_database/queries/`).

Deferred: `shared_taste` needs plan 06's multi-user schema;
`map_playlist_to_graph` needs a live probe of algorithmic-playlist access
(plan 05 §T6) before it's worth building.

### Known caveat: popularity

`Artist.popularity` is **not yet populated** (plan 01's backfill adds it).
`discover_adjacent` / `collaborators_of` treat NULL popularity as *unknown*:
those artists are included regardless of `max_popularity`, flagged
`popularity_unknown: true`, and sorted after known-popularity peers. Every
payload repeats this caveat.

## Read-only enforcement (belt + suspenders)

1. Every session opens with `default_access_mode=READ_ACCESS`, so **Neo4j
   itself** rejects writes — including write *procedures* a keyword scan can't
   see (Community Edition has no RBAC; this is the enforcement point).
2. A word-boundary guard rejects queries containing
   `CREATE/MERGE/DELETE/DETACH/SET/REMOVE/DROP/FOREACH/LOAD CSV` with a
   friendly error, after stripping string literals, backtick identifiers and
   comments (so `CONTAINS 'set me free'` doesn't false-positive).
3. Row cap (`MCP_ROW_CAP`, default 200 — results carry a `truncated` flag) and
   query timeout (`MCP_QUERY_TIMEOUT_SECONDS`, default 30) bound pathological
   generated queries.

## Environment

| Variable | Default | Meaning |
|----------|---------|---------|
| `NEO4J_HOSTNAME` | `host.docker.internal` (set by the wrapper) | Where Neo4j lives |
| `MCP_ROW_CAP` | `200` | Max rows any query returns |
| `MCP_QUERY_TIMEOUT_SECONDS` | `30` | Server-side query timeout |

The wrapper script forwards all three from the host environment.

## Development loop

Code changes need an image rebuild (`docker compose build`) to reach the
server — or bind-mount your working copy over the baked-in package while
iterating:

```bash
docker run --rm -i \
    --add-host host.docker.internal:host-gateway \
    -e NEO4J_HOSTNAME=host.docker.internal \
    -v "$(pwd)/secrets":/src/secrets \
    -v "$(pwd)/mcp_server":/src/mcp_server \
    spotify-power-browser:latest python3 -m mcp_server
```

Never print to **stdout** from server code — stdio transport uses it for
JSON-RPC frames. `mcp_server/loggers.py` streams to stderr for exactly this
reason (unlike `application/loggers.py`).

Tests: `tests/test_mcp_server_readonly.py` runs anywhere (pure Python);
`tests/test_mcp_server_tools.py` needs Neo4j and skips when it's unreachable;
`tests/test_mcp_server_wiring.py` needs the `mcp` SDK (i.e. a rebuilt image)
and skips without it. All run under `docker compose run --rm tests`.
