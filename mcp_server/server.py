"""FastMCP wiring: exposes the taste graph's tools and resources over stdio.

Thin layer only — each tool delegates to a plain function in mcp_server/tools/
(testable without the MCP SDK), and every one of those goes through the
read-only layer in mcp_server/readonly.py. Keep the tools thin over queries:
when the schema grows (plans 01/02/06), the queries change, not this file's
shape.
"""
import json

from mcp.server.fastmcp import FastMCP

from application.config import APPLICATION_DIR
from mcp_server.connection import get_driver
from mcp_server.loggers import get_logger
from mcp_server.readonly import MCP_QUERY_TIMEOUT_SECONDS, MCP_ROW_CAP, run_readonly_query
from mcp_server.tools import collaboration, completeness, schema, search

logger = get_logger(__name__)

QUERIES_DIR = APPLICATION_DIR / 'graph_database' / 'queries'

mcp = FastMCP(
    'spotify-graph',
    instructions=(
        'Read-only access to a personal Spotify taste graph in Neo4j: Track, Album, Artist, '
        'Genre nodes from a full liked-songs crawl (12.5k tracks / 7.6k artists as of '
        '2026-07-06). Start with graph_schema to see the live shape; use find_artist / '
        'find_track to resolve exact names before passing them to other tools; fall back to '
        'run_cypher_readonly for anything the purpose-built tools do not cover. All access '
        'is read-only — writes are rejected.'
    ),
)


@mcp.tool()
def graph_schema() -> dict:
    """The graph's live shape: node/relationship counts, connection patterns, and properties per label.

    Computed from the data on every call, so it reflects schema growth
    immediately. Call this first in a fresh session.
    """
    return schema.graph_schema(get_driver())


@mcp.tool()
def run_cypher_readonly(query: str, params: dict | None = None) -> dict:
    """Run an arbitrary read-only Cypher query against the taste graph.

    Escape hatch for questions the purpose-built tools don't cover. Queries
    containing write clauses (CREATE/MERGE/DELETE/SET/…) are rejected, results
    are capped (default 200 rows — the payload's `truncated` flag tells you if
    the cap bit; add LIMIT or aggregate to see more), and long-running queries
    time out (default 30s). Use $parameters via `params` rather than
    interpolating values into the query text.
    """
    return run_readonly_query(get_driver(), query, params=params)


@mcp.tool()
def find_artist(name: str, limit: int = 25) -> dict:
    """Find Artist nodes by fuzzy name (case-insensitive substring), closest match first.

    Use this to resolve exact artist names before calling collaborators_of /
    discover_adjacent / artist_completeness, which match names exactly.
    """
    return search.find_artist(get_driver(), name, limit=limit)


@mcp.tool()
def find_track(name: str, limit: int = 25) -> dict:
    """Find Track nodes by fuzzy name (case-insensitive substring) with their album and artists."""
    return search.find_track(get_driver(), name, limit=limit)


@mcp.tool()
def collaborators_of(artist_names: list[str], limit: int = 25) -> dict:
    """Artists who share track credits with the named artists, ranked by seeds bridged then shared tracks.

    Names are matched exactly (case-insensitive) — resolve them with
    find_artist first. `unmatched_names` in the payload lists inputs that
    matched no Artist node.
    """
    return collaboration.collaborators_of(get_driver(), artist_names, limit=limit)


@mcp.tool()
def discover_adjacent(
    seed_artist_names: list[str] | None = None,
    max_popularity: int = 40,
    min_bridges: int = 2,
    limit: int = 50,
) -> dict:
    """Discover unknown-but-adjacent artists: co-credited with your taste, weighted toward the obscure.

    With no seeds, bridges from every artist credited on a liked track; with
    seed_artist_names, bridges only from those artists (exact case-insensitive
    names — resolve via find_artist) and excludes anyone already in the
    liked-songs graph. An artist qualifies with at least `min_bridges`
    independent connections and popularity at most `max_popularity`.

    CAVEAT: Artist.popularity is not yet populated (plan 01 backfills it).
    Artists with NULL popularity are treated as UNKNOWN — included regardless
    of max_popularity, flagged popularity_unknown=true, and sorted after
    known-popularity peers. The payload repeats this caveat.
    """
    return collaboration.discover_adjacent(
        get_driver(),
        seed_artist_names=seed_artist_names,
        max_popularity=max_popularity,
        min_bridges=min_bridges,
        limit=limit,
    )


@mcp.tool()
def artist_completeness(artist_name: str, limit: int = 10) -> dict:
    """How much of an artist's catalog you've engaged with — DEGRADED MODE until plan 02 lands.

    Currently liked-vs-catalog: "heard" degrades to "liked", and the catalog is
    only what the graph knows (liked-songs crawl depth until plan 01's
    discography crawl runs). The payload's `mode` and `explanation` fields
    state this so results aren't over-claimed. Fuzzy name match; several
    matching artists are returned, largest in-graph catalog first.
    """
    return completeness.artist_completeness(get_driver(), artist_name, limit=limit)


@mcp.resource('schema://graph')
def schema_resource() -> str:
    """The live schema summary (same payload as the graph_schema tool), as JSON."""
    return json.dumps(schema.graph_schema(get_driver()), indent=2, default=str)


@mcp.resource('queries://cookbook')
def cookbook_resource() -> str:
    """The curated Cypher pack — the same files as application/graph_database/queries/."""
    sections = []
    for path in sorted(QUERIES_DIR.rglob('*.cypher')):
        sections.append(f'// ===== {path.relative_to(QUERIES_DIR)} =====\n{path.read_text()}')
    return '\n\n'.join(sections)


def main():
    logger.info(
        f'Starting spotify-graph MCP server on stdio '
        f'(row cap {MCP_ROW_CAP}, query timeout {MCP_QUERY_TIMEOUT_SECONDS}s)'
    )
    mcp.run(transport='stdio')
