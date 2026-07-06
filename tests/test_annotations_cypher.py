"""Round-trip tests for the annotation Cypher (plan 04 T1) against a real
Neo4j — the neo4j_driver fixture skips the module when the database isn't
reachable. Distinctive CYTESTANN uris/ids keep cleanup surgical."""
import pytest

from application.annotations.model import Neo4jAnnotationWriter, TrackNotInGraphError

TRACK_ID = "CYTESTANN1"
MISSING_TRACK_ID = "CYTESTANN_NOT_CRAWLED"


@pytest.fixture(autouse=True)
def _cytest_track(neo4j_driver):
    """A throwaway Track to annotate; purge it AND its annotations around each
    test (annotations hang off the track, so follow the rels to find them)."""
    purge = (
        "MATCH (t:Track) WHERE t.uri CONTAINS 'CYTESTANN' "
        "OPTIONAL MATCH (t)-[:HAS_NOTE|HAS_CUE|HAS_SECTION]->(a) "
        "DETACH DELETE t, a"
    )
    neo4j_driver.execute_query(purge)
    neo4j_driver.execute_query(
        "MERGE (t:Track {uri: 'spotify:track:CYTESTANN1'}) "
        "SET t.id = $track_id, t.name = 'CYTESTANN Strobe', t.duration_ms = 634000",
        track_id=TRACK_ID,
    )
    yield
    neo4j_driver.execute_query(purge)


@pytest.fixture
def writer(neo4j_driver):
    return Neo4jAnnotationWriter(neo4j_driver)


def test_uniqueness_constraints_apply_for_annotation_labels(neo4j_driver):
    from application.graph_database.initialize_database_environment import (
        apply_uniqueness_constraints,
    )
    apply_uniqueness_constraints(neo4j_driver)
    records, _, _ = neo4j_driver.execute_query("SHOW CONSTRAINTS YIELD name RETURN name")
    names = {record["name"] for record in records}
    assert {"note_id_uniqueness", "cue_id_uniqueness", "section_id_uniqueness"} <= names


def test_note_and_cue_round_trip(writer):
    note = writer.add_note(TRACK_ID, "that switch-up", at_ms=130000)
    cue = writer.add_cue(TRACK_ID, 41000, "the drop")
    annotations = writer.fetch_annotations(TRACK_ID)
    assert [n["text"] for n in annotations["notes"]] == ["that switch-up"]
    assert annotations["notes"][0]["at_ms"] == 130000
    assert annotations["cues"][0]["id"] == cue["id"]
    assert annotations["cues"][0]["at_ms"] == 41000
    # undo removes them again
    writer.undo(note)
    writer.undo(cue)
    annotations = writer.fetch_annotations(TRACK_ID)
    assert annotations["notes"] == [] and annotations["cues"] == []


def test_cold_entry_note_has_no_position(writer):
    writer.add_note(TRACK_ID, "just a thought")
    note = writer.fetch_annotations(TRACK_ID)["notes"][0]
    assert note["at_ms"] is None


def test_sections_chain_next_and_close_open_ends(writer, neo4j_driver):
    writer.add_section(TRACK_ID, 0, 0, "intro")
    writer.add_section(TRACK_ID, 1, 64000, "buildup 1")
    writer.add_section(TRACK_ID, 2, 130000, "drop 1")

    sections = writer.fetch_annotations(TRACK_ID)["sections"]
    assert [s["order"] for s in sections] == [0, 1, 2]
    assert [s["kind"] for s in sections] == ["intro", "buildup", "drop"]
    # each boundary closed its predecessor; the last stays open (track end)
    assert [s["end_ms"] for s in sections] == [64000, 130000, None]

    records, _, _ = neo4j_driver.execute_query(
        "MATCH (t:Track {id: $track_id})-[:HAS_SECTION]->(a:Section)-[:NEXT]->(b:Section) "
        "RETURN a.order AS a, b.order AS b ORDER BY a.order",
        track_id=TRACK_ID,
    )
    assert [(record["a"], record["b"]) for record in records] == [(0, 1), (1, 2)]


def test_explicit_end_ms_is_not_overwritten_by_next_boundary(writer):
    writer.add_section(TRACK_ID, 0, 0, "intro", end_ms=30000)  # explicitly closed early
    writer.add_section(TRACK_ID, 1, 64000, "buildup 1")
    sections = writer.fetch_annotations(TRACK_ID)["sections"]
    assert sections[0]["end_ms"] == 30000  # coalesce keeps the explicit value


def test_undo_section_reopens_previous_end(writer):
    writer.add_section(TRACK_ID, 0, 0, "intro")
    boundary = writer.add_section(TRACK_ID, 1, 64000, "buildup 1")
    writer.undo(boundary)
    sections = writer.fetch_annotations(TRACK_ID)["sections"]
    assert len(sections) == 1
    assert sections[0]["end_ms"] is None  # reopened: runs to track end again


def test_writes_against_a_track_missing_from_the_graph_raise(writer, neo4j_driver):
    """The insert Cypher MATCHes the Track (no MERGE, no placeholders): when
    the track isn't in the graph the query is a silent no-op at the database
    level, so the writer MUST turn the zero-match into a loud error instead of
    reporting success (a whole live-listening session was silently lost)."""
    with pytest.raises(TrackNotInGraphError):
        writer.add_note(MISSING_TRACK_ID, "lost thought", at_ms=130000)
    with pytest.raises(TrackNotInGraphError):
        writer.add_cue(MISSING_TRACK_ID, 41000, "the drop")
    with pytest.raises(TrackNotInGraphError):
        writer.add_section(MISSING_TRACK_ID, 0, 0, "intro")
    # no placeholder Track and no orphan annotation nodes were created
    records, _, _ = neo4j_driver.execute_query(
        "MATCH (t:Track {id: $track_id}) RETURN count(t) AS tracks", track_id=MISSING_TRACK_ID
    )
    assert records[0]["tracks"] == 0
    records, _, _ = neo4j_driver.execute_query(
        "MATCH (a) WHERE (a:Note OR a:Cue OR a:Section) AND NOT (a)<-[]-(:Track) "
        "RETURN count(a) AS orphans"
    )
    assert records[0]["orphans"] == 0


def test_track_in_graph_probe(writer):
    assert writer.track_in_graph(TRACK_ID) is True
    assert writer.track_in_graph(MISSING_TRACK_ID) is False


def test_nudge_cue_moves_at_ms(writer):
    cue = writer.add_cue(TRACK_ID, 41000, "hit")
    writer.nudge(cue, 41500)
    assert writer.fetch_annotations(TRACK_ID)["cues"][0]["at_ms"] == 41500


def test_nudge_section_moves_start_and_chained_previous_end(writer):
    writer.add_section(TRACK_ID, 0, 0, "intro")
    boundary = writer.add_section(TRACK_ID, 1, 64000, "buildup 1")
    writer.nudge(boundary, 63500)
    sections = writer.fetch_annotations(TRACK_ID)["sections"]
    assert sections[1]["start_ms"] == 63500
    assert sections[0]["end_ms"] == 63500  # the chained boundary moved with it


def test_next_section_order_uses_max_not_count(writer):
    writer.add_section(TRACK_ID, 0, 0, "intro")
    middle = writer.add_section(TRACK_ID, 1, 64000, "buildup 1")
    writer.add_section(TRACK_ID, 2, 130000, "drop 1")
    writer.undo(middle)  # a hole in the orders must not cause a collision
    assert writer.next_section_order(TRACK_ID) == 3


def test_search_tracks_finds_by_case_insensitive_substring(writer):
    matches = writer.search_tracks("cytestann str")
    assert [m["id"] for m in matches] == [TRACK_ID]
    assert matches[0]["duration_ms"] == 634000


def test_duplicate_annotation_id_rejected_once_constraints_applied(writer, neo4j_driver):
    from application.graph_database.initialize_database_environment import (
        apply_uniqueness_constraints,
    )
    from application.annotations import model

    apply_uniqueness_constraints(neo4j_driver)
    params = model.build_note_params(TRACK_ID, "one")
    writer._execute(model.INSERT_NOTE_QUERY, **params)
    with pytest.raises(Exception):
        writer._execute(model.INSERT_NOTE_QUERY, **params)  # same uuid: unique id violated
