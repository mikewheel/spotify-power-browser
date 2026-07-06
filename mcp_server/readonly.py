"""The read-only query layer every MCP tool goes through.

Enforcement is belt + suspenders:

1. **Server-side (the real enforcement point):** every session is opened with
   ``default_access_mode=READ_ACCESS``, so Neo4j itself rejects any write that
   reaches it — including write *procedures* (e.g. ``db.createLabel``) that a
   keyword scan can't see. Community Edition has no RBAC; this is the
   substitute.
2. **Client-side (friendlier errors):** ``assert_read_only()`` rejects queries
   containing write clauses before they're sent, with an actionable message
   instead of a raw ``Neo.ClientError``. String literals, backtick identifiers
   and comments are stripped first so ``WHERE t.name CONTAINS 'set me free'``
   doesn't false-positive. False *negatives* here are fine — layer 1 catches
   them.
3. **Resource limits:** a row cap (default 200) keeps a pathological generated
   query from flooding the client's context window, and a query timeout
   (default 30s) keeps one from hanging the session.
"""
import os
import re

from neo4j import Query, READ_ACCESS

# Row cap and query timeout, env-overridable like the flags in
# application/config.py (scripts/mcp_server.sh passes them through).
MCP_ROW_CAP = int(os.environ.get('MCP_ROW_CAP', '200'))
MCP_QUERY_TIMEOUT_SECONDS = float(os.environ.get('MCP_QUERY_TIMEOUT_SECONDS', '30'))

# Cypher clauses that mutate data or schema. DETACH is only ever part of
# DETACH DELETE, and FOREACH exists solely to perform updates, so both are
# safe to block outright. LOAD CSV is two words and handled separately.
WRITE_CLAUSES = ('CREATE', 'MERGE', 'DELETE', 'DETACH', 'SET', 'REMOVE', 'DROP', 'FOREACH')

_WRITE_CLAUSE_PATTERN = re.compile(r'\b(' + '|'.join(WRITE_CLAUSES) + r')\b', re.IGNORECASE)
_LOAD_CSV_PATTERN = re.compile(r'\bLOAD\s+CSV\b', re.IGNORECASE)

# Quoted segments whose contents must not trip the keyword scan: single- and
# double-quoted string literals (with backslash escapes) and backtick-escaped
# identifiers (backticks are escaped by doubling, not backslashes).
_QUOTED_SEGMENT_PATTERN = re.compile(
    r"'(?:[^'\\]|\\.)*'"
    r'|"(?:[^"\\]|\\.)*"'
    r'|`(?:[^`]|``)*`'
)
_LINE_COMMENT_PATTERN = re.compile(r'//[^\n]*')
_BLOCK_COMMENT_PATTERN = re.compile(r'/\*.*?\*/', re.DOTALL)


class WriteQueryError(ValueError):
    """Raised when a query submitted to the read-only server contains a write clause."""


def _strip_literals_and_comments(query):
    """Blank out quoted segments and comments so only live Cypher gets keyword-scanned.

    Strings go first: a comment marker inside a literal ('http://…') must not
    cause the rest of the line to be treated as a comment.
    """
    without_strings = _QUOTED_SEGMENT_PATTERN.sub(' ', query)
    without_block_comments = _BLOCK_COMMENT_PATTERN.sub(' ', without_strings)
    return _LINE_COMMENT_PATTERN.sub(' ', without_block_comments)


def assert_read_only(query):
    """Raise WriteQueryError if the query contains a write clause; return it otherwise."""
    if not query or not query.strip():
        raise WriteQueryError('Empty query. Provide a read (MATCH … RETURN …) Cypher query.')

    scannable = _strip_literals_and_comments(query)

    match = _WRITE_CLAUSE_PATTERN.search(scannable) or _LOAD_CSV_PATTERN.search(scannable)
    if match:
        keyword = ' '.join(match.group(0).upper().split())
        raise WriteQueryError(
            f"This MCP server is read-only, and the query contains the write clause '{keyword}'. "
            f'Rephrase it as a read (MATCH/RETURN) query — writes to the graph happen through '
            f'the crawl pipeline, not through MCP.'
        )
    return query


def collect_rows(records, row_cap):
    """Drain up to row_cap records into plain dicts; report whether more were left behind.

    Works on a streaming neo4j Result (stops consuming at the cap) or any
    iterable of objects with a .data() method.
    """
    rows = []
    truncated = False
    for record in records:
        if len(rows) >= row_cap:
            truncated = True
            break
        rows.append(record.data())
    return rows, truncated


def run_readonly_query(driver, query, params=None, row_cap=None, timeout=None, database='neo4j'):
    """Execute a Cypher query in a read-only session and return capped rows.

    Returns ``{'rows': [...], 'row_count': int, 'truncated': bool}`` where
    ``truncated`` means the row cap cut the result short (tighten the query or
    add LIMIT/aggregation to see the rest).
    """
    assert_read_only(query)
    row_cap = MCP_ROW_CAP if row_cap is None else row_cap
    timeout = MCP_QUERY_TIMEOUT_SECONDS if timeout is None else timeout

    with driver.session(database=database, default_access_mode=READ_ACCESS) as session:
        result = session.run(Query(query, timeout=timeout), params or {})
        rows, truncated = collect_rows(result, row_cap)

    return {'rows': rows, 'row_count': len(rows), 'truncated': truncated}
