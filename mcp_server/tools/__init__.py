"""Tool implementations: plain functions over a Neo4j driver.

Kept free of any ``mcp`` import so they can be unit-tested (and reused by
scripts) without the MCP SDK installed; mcp_server/server.py wraps them as
FastMCP tools.
"""
