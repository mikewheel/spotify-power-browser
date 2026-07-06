"""FastMCP wiring: the server registers the v1 toolset and resources.

Needs the `mcp` SDK (in the image once it's rebuilt with the new lockfile);
skips cleanly where it isn't installed. No Neo4j required — the driver is
lazy, and a server that can't even import/list tools without the DB would
break client startup.
"""
import asyncio

import pytest

pytest.importorskip('mcp', reason='mcp SDK not installed (image predates the lockfile bump)')

from mcp_server import server  # noqa: E402  (import must follow the importorskip)

EXPECTED_TOOLS = {
    'graph_schema',
    'run_cypher_readonly',
    'find_artist',
    'find_track',
    'collaborators_of',
    'discover_adjacent',
    'artist_completeness',
}


def test_all_v1_tools_are_registered():
    tools = asyncio.run(server.mcp.list_tools())
    assert {tool.name for tool in tools} == EXPECTED_TOOLS


def test_every_tool_has_a_docstring_description():
    tools = asyncio.run(server.mcp.list_tools())
    for tool in tools:
        assert tool.description, f'{tool.name} has no description'


def test_discover_adjacent_documents_the_popularity_caveat_and_defaults():
    tools = asyncio.run(server.mcp.list_tools())
    discover = next(t for t in tools if t.name == 'discover_adjacent')
    assert 'popularity' in discover.description.lower()
    properties = discover.inputSchema['properties']
    assert properties['max_popularity']['default'] == 40
    assert properties['min_bridges']['default'] == 2
    assert discover.inputSchema.get('required', []) == []  # all params optional


def test_schema_and_cookbook_resources_are_registered():
    resources = asyncio.run(server.mcp.list_resources())
    uris = {str(resource.uri) for resource in resources}
    assert uris == {'schema://graph', 'queries://cookbook'}


def test_cookbook_resource_serves_the_curated_query_pack():
    contents = asyncio.run(server.mcp.read_resource('queries://cookbook'))
    text = list(contents)[0].content
    assert 'apply_uniqueness_constraints_to_nodes.cypher' in text
    assert 'MERGE' in text  # it really is the insert query pack
