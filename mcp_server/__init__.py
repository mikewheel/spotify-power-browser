"""A read-only MCP server exposing the Neo4j taste graph to AI clients.

Runs over stdio inside the project Docker image (see scripts/mcp_server.sh);
registered for Claude Code via the project-root .mcp.json and for Claude
Desktop via the snippet in mcp_server/README.md. Every query goes through the
read-only layer in mcp_server/readonly.py — this server never writes to the
graph; writes happen through the crawl pipeline.
"""
