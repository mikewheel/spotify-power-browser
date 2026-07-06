"""Live schema summary: labels, relationship types, patterns, properties, counts.

Computed from the data on every call (no cached doc to drift) — as plans
01/02/06 add labels and relationships, this tool picks them up for free. The
full scans are fine at the current graph size (~30k nodes / 2026-07-06 crawl);
revisit with count-store tricks if the graph grows orders of magnitude.
"""
from mcp_server.readonly import run_readonly_query

# Generous internal cap: a schema summary has one row per label/type/pattern,
# not per node, so even 1000 is far beyond what this graph will produce.
_SCHEMA_ROW_CAP = 1000

NODE_COUNTS_QUERY = '''\
MATCH (n)
UNWIND labels(n) AS label
RETURN label, count(*) AS count
ORDER BY count DESC
'''

RELATIONSHIP_COUNTS_QUERY = '''\
MATCH ()-[r]->()
RETURN type(r) AS relationship_type, count(*) AS count
ORDER BY count DESC
'''

RELATIONSHIP_PATTERNS_QUERY = '''\
MATCH (a)-[r]->(b)
WITH labels(a) AS from_labels, type(r) AS relationship, labels(b) AS to_labels, count(*) AS count
RETURN from_labels, relationship, to_labels, count
ORDER BY count DESC
'''

PROPERTIES_BY_LABEL_QUERY = '''\
MATCH (n)
UNWIND labels(n) AS label
UNWIND keys(n) AS key
WITH label, key ORDER BY key
RETURN label, collect(DISTINCT key) AS properties
ORDER BY label
'''


def graph_schema(driver):
    """Return the graph's live shape: what exists, how much of it, and how it connects."""
    return {
        'node_counts': run_readonly_query(driver, NODE_COUNTS_QUERY, row_cap=_SCHEMA_ROW_CAP)['rows'],
        'relationship_counts': run_readonly_query(driver, RELATIONSHIP_COUNTS_QUERY, row_cap=_SCHEMA_ROW_CAP)['rows'],
        'relationship_patterns': run_readonly_query(driver, RELATIONSHIP_PATTERNS_QUERY, row_cap=_SCHEMA_ROW_CAP)['rows'],
        'properties_by_label': run_readonly_query(driver, PROPERTIES_BY_LABEL_QUERY, row_cap=_SCHEMA_ROW_CAP)['rows'],
    }
