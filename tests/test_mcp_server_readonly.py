"""Pure-python tests for the MCP server's read-only layer: no services needed.

The write-clause guard and the row cap are the server's client-side safety
rails; they must hold without Neo4j running (the server-side READ_ACCESS
enforcement is exercised in tests/test_mcp_server_tools.py).
"""
import pytest

from mcp_server.readonly import WriteQueryError, assert_read_only, collect_rows, run_readonly_query


class _FakeRecord:
    def __init__(self, payload):
        self._payload = payload

    def data(self):
        return self._payload


@pytest.mark.parametrize('query', [
    'MATCH (t:Track) RETURN count(t)',
    'CALL db.labels() YIELD label RETURN label',
    'MATCH (a:Artist)-[:CREATED]->(t:Track) WHERE t.liked_songs RETURN a.name LIMIT 5',
    'UNWIND $names AS n MATCH (a:Artist) WHERE toLower(a.name) = toLower(n) RETURN a',
    'MATCH (a)-[r]->(b) RETURN DISTINCT labels(a), type(r), labels(b)',
    # Write keywords inside string literals must not trip the guard...
    "MATCH (t:Track) WHERE t.name CONTAINS 'set me free' RETURN t",
    'MATCH (t:Track) WHERE t.name = "Delete Forever" RETURN t',
    "MATCH (t:Track) WHERE t.name CONTAINS 'Drop It Like It''s Hot' RETURN t",
    # ...nor inside backtick-escaped identifiers...
    'MATCH (n) RETURN n.`data set` LIMIT 1',
    # ...nor inside comments.
    '// do not CREATE anything here\nMATCH (n) RETURN count(n)',
    '/* MERGE would be a write */ MATCH (n) RETURN count(n)',
    # A URL literal must not comment-out the rest of the line.
    "MATCH (a:Artist) WHERE a.spotify_url = 'https://open.spotify.com/artist/x' RETURN a",
])
def test_read_queries_pass_the_guard(query):
    assert assert_read_only(query) == query


@pytest.mark.parametrize('query, keyword', [
    ("CREATE (n:Evil {name: 'x'})", 'CREATE'),
    ("MERGE (n:Track {uri: 'spotify:track:x'})", 'MERGE'),
    ('MATCH (n:Track) DELETE n', 'DELETE'),
    ('MATCH (n) DETACH DELETE n', 'DETACH'),
    ("MATCH (n:Artist) SET n.popularity = 100 RETURN n", 'SET'),
    ('MATCH (n:Artist) REMOVE n.popularity RETURN n', 'REMOVE'),
    ('DROP CONSTRAINT track_uri_unique', 'DROP'),
    ('MATCH (n) FOREACH (x IN [1] | SET n.hacked = true)', 'FOREACH'),
    ("LOAD CSV FROM 'file:///x.csv' AS row RETURN row", 'LOAD CSV'),
    ("LOAD   CSV FROM 'file:///x.csv' AS row RETURN row", 'LOAD CSV'),
    # Case-insensitive, and inside CALL {} subqueries too.
    ("create (n:Evil)", 'CREATE'),
    ('MATCH (t:Track) CALL { WITH t merge (x:Evil)-[:R]->(t) } RETURN t', 'MERGE'),
])
def test_write_queries_are_rejected_with_the_offending_keyword(query, keyword):
    with pytest.raises(WriteQueryError) as excinfo:
        assert_read_only(query)
    message = str(excinfo.value)
    assert keyword in message
    assert 'read-only' in message


@pytest.mark.parametrize('query', ['', '   ', '\n\t'])
def test_empty_queries_are_rejected(query):
    with pytest.raises(WriteQueryError):
        assert_read_only(query)


def test_collect_rows_under_the_cap_is_not_truncated():
    records = [_FakeRecord({'i': i}) for i in range(3)]
    rows, truncated = collect_rows(iter(records), row_cap=5)
    assert rows == [{'i': 0}, {'i': 1}, {'i': 2}]
    assert truncated is False


def test_collect_rows_at_the_cap_exactly_is_not_truncated():
    records = [_FakeRecord({'i': i}) for i in range(5)]
    rows, truncated = collect_rows(iter(records), row_cap=5)
    assert len(rows) == 5
    assert truncated is False


def test_collect_rows_over_the_cap_truncates_and_stops_consuming():
    def record_stream():
        for i in range(1000):
            yield _FakeRecord({'i': i})

    stream = record_stream()
    rows, truncated = collect_rows(stream, row_cap=10)
    assert len(rows) == 10
    assert truncated is True
    # The stream was drained lazily: the 12th record is still unconsumed
    # (one extra was pulled to discover the cap was hit).
    assert next(stream).data() == {'i': 11}


def test_run_readonly_query_rejects_writes_before_touching_the_driver():
    # The guard must fire before any session is opened: an object with no
    # session() at all proves the driver is never touched.
    driver_that_must_not_be_used = object()
    with pytest.raises(WriteQueryError):
        run_readonly_query(driver_that_must_not_be_used, 'CREATE (n:Evil)')
