#!/usr/bin/env bash
# Launch the graph MCP server over stdio inside the project Docker image.
#
# Registered in the project-root .mcp.json (Claude Code) and usable verbatim
# from Claude Desktop — see mcp_server/README.md. Neo4j Desktop runs on the
# host, so the container reaches it via host.docker.internal, exactly like the
# responses_write_to_neo4j service in compose.yaml. -i keeps stdin open (it
# carries the JSON-RPC frames); logs go to stderr.
#
# Requires the spotify-power-browser image (docker compose build). Honors the
# per-worktree IMAGE_TAG (see compose.yaml / .claude hook); defaults to latest.
set -euo pipefail

# Resolve the repo root from this script's location so registration works no
# matter what directory the MCP client launches the command from.
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# Use this worktree's image tag: prefer an exported IMAGE_TAG, else read it from
# the worktree .env the SessionStart hook writes, else fall back to latest.
IMAGE_TAG="${IMAGE_TAG:-$(grep -E '^IMAGE_TAG=' "${REPO_ROOT}/.env" 2>/dev/null | tail -1 | cut -d= -f2-)}"
IMAGE="spotify-power-browser:${IMAGE_TAG:-latest}"

exec docker run --rm -i \
    --add-host host.docker.internal:host-gateway \
    -e NEO4J_HOSTNAME="${NEO4J_HOSTNAME:-host.docker.internal}" \
    -e MCP_ROW_CAP="${MCP_ROW_CAP:-200}" \
    -e MCP_QUERY_TIMEOUT_SECONDS="${MCP_QUERY_TIMEOUT_SECONDS:-30}" \
    -v "${REPO_ROOT}/secrets":/src/secrets \
    "$IMAGE" \
    python3 -m mcp_server
