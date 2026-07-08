# scripts/ — operational helpers

| Script | What it does | Run it when |
|---|---|---|
| [mcp_server.sh](mcp_server.sh) | Launches the MCP server as `docker run --rm -i` on the shared image, wiring `host.docker.internal` → Neo4j Desktop and mounting `secrets/` read-only. Registered in [.mcp.json](../.mcp.json), so Claude runs it for you. | You normally don't — MCP clients do. |
| [worktree_compose_env.sh](worktree_compose_env.sh) | Gives each Claude worktree its own image tag + compose project (gitignored `.env`) and strips host ports (gitignored `compose.override.yaml`). No-op outside `.claude/worktrees/`. Wired as a SessionStart hook. | Automatically, at session start. Safe by hand. |
| [probes/](probes/) | One-off scripts that verified which Spotify endpoints this app retains post-deprecation (results tabled in [docs/plans/README.md](../docs/plans/README.md)). | Only if Spotify changes API policy again. |

Background: [docs/delivery.md](../docs/delivery.md).
