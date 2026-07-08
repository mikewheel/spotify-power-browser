---
name: connect-mcp
description: Connect an AI client (Claude Code, Claude Desktop) to the spotify-graph MCP server, verify it works, and troubleshoot. Use when asked to set up the MCP server, hook Claude to the graph, or debug MCP connection issues in this project.
---

# Connect the graph MCP server

Setup, tools, limitations, ChatGPT-gap: **[mcp_server/README.md](../../../mcp_server/README.md)**.

The short version:

- **Claude Code**: nothing to do — the repo's `.mcp.json` registers it; a
  fresh session in this repo picks it up.
- **Claude Desktop**: add the `spotify-graph` block from the README to
  `~/Library/Application Support/Claude/claude_desktop_config.json` with the
  absolute path to `scripts/mcp_server.sh`.
- **ChatGPT Desktop**: not supported (remote-HTTP-only client vs this stdio
  server) — the README explains the gap and the tunnel-shaped workaround to
  avoid.

Prerequisites: image built (`docker compose build`), Neo4j Desktop running,
`secrets/neo4j_credentials.yaml` present.

Verify: ask the client to call `graph_schema` — node counts should come back.
Troubleshooting order: (1) Docker running? (2) image built / worktree
`IMAGE_TAG` built? (3) Neo4j reachable — first tool call fails without it even
though the server lists tools fine; (4) code changes need a rebuild or the
bind-mount dev loop from the README. Server logs go to **stderr** (stdout is
the protocol channel).
