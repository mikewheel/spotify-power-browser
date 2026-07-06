"""Offline tests for the annotation model layer (plan 04 T1/T2): param-builder
shapes, the contract between builders and the Cypher files, and the timecode
helpers. No services required."""
import re
from datetime import datetime
from uuid import UUID

import pytest

from application.annotations import model
from application.annotations.timecode import format_ms, parse_position


def _fields_accessed(query, param_name):
    """All `param.field` accesses in a Cypher query, e.g. note.text."""
    return set(re.findall(rf"\b{param_name}\.(\w+)", query))


def test_note_params_shape():
    params = model.build_note_params("trk1", "that switch-up at 2:10")
    note = params["note"]
    assert set(note) == {"track_id", "id", "text", "at_ms", "created_at"}
    UUID(note["id"])  # app-side uuid4, parseable
    assert note["at_ms"] is None  # cold entry: no position
    datetime.fromisoformat(note["created_at"])  # tz-aware ISO 8601
    assert datetime.fromisoformat(note["created_at"]).tzinfo is not None


def test_note_params_with_live_position():
    assert model.build_note_params("trk1", "hi", at_ms=130000.7)["note"]["at_ms"] == 130000


def test_cue_params_shape():
    cue = model.build_cue_params("trk1", 41000, "the drop")["cue"]
    assert set(cue) == {"track_id", "id", "at_ms", "label", "created_at"}
    assert cue["at_ms"] == 41000 and cue["label"] == "the drop"
    UUID(cue["id"])


def test_section_params_shape_and_derived_kind():
    section = model.build_section_params("trk1", 0, 0, "Buildup 2")["section"]
    assert set(section) == {
        "track_id", "id", "order", "start_ms", "end_ms", "label", "kind", "created_at"
    }
    assert section["kind"] == "buildup"  # derived from the label's first word
    assert section["end_ms"] is None  # open until the next boundary
    UUID(section["id"])


def test_section_kind_outside_vocabulary_is_custom():
    assert model.build_section_params("trk1", 0, 0, "weird bit")["section"]["kind"] == "custom"


def test_section_explicit_kind_validated():
    section = model.build_section_params("trk1", 1, 5000, "the good part", kind="drop")["section"]
    assert section["kind"] == "drop"
    with pytest.raises(ValueError):
        model.build_section_params("trk1", 1, 5000, "x", kind="guitar-solo")


@pytest.mark.parametrize("label,expected", [
    ("intro", "intro"),
    ("Drop 1", "drop"),
    ("  OUTRO  ", "outro"),
    ("", "custom"),
    (None, "custom"),
    ("second verse", "custom"),  # kind keys off the FIRST word only
])
def test_normalize_kind(label, expected):
    assert model.normalize_kind(label) == expected


@pytest.mark.parametrize("query,param_name,builder_keys", [
    (model.INSERT_NOTE_QUERY, "note", {"track_id", "id", "text", "at_ms", "created_at"}),
    (model.INSERT_CUE_QUERY, "cue", {"track_id", "id", "at_ms", "label", "created_at"}),
    (
        model.INSERT_SECTION_QUERY,
        "section",
        {"track_id", "id", "order", "start_ms", "end_ms", "label", "kind", "created_at"},
    ),
])
def test_insert_queries_only_touch_built_params(query, param_name, builder_keys):
    # Every `param.field` the Cypher reads must exist in the builder's output,
    # and the query must actually take the map as $param.
    assert f"${param_name}" in query
    assert _fields_accessed(query, param_name) <= builder_keys


@pytest.mark.parametrize("query,expected_params", [
    (model.FETCH_NOTES_QUERY, {"$track_id"}),
    (model.FETCH_CUES_QUERY, {"$track_id"}),
    (model.FETCH_SECTIONS_QUERY, {"$track_id"}),
    (model.FETCH_TRACKS_BY_NAME_QUERY, {"$search_term"}),
    (model.DELETE_ANNOTATION_QUERY, {"$annotation_id"}),
    (model.DELETE_SECTION_QUERY, {"$section_id"}),
    (model.NUDGE_ANNOTATION_QUERY, {"$annotation_id", "$at_ms"}),
    (model.NEXT_SECTION_ORDER_QUERY, {"$track_id"}),
])
def test_parameterized_queries_use_exactly_the_params_the_writer_passes(query, expected_params):
    assert set(re.findall(r"\$\w+", query)) == expected_params


def test_uniqueness_constraints_appended_for_annotation_labels():
    from application.config import APPLICATION_DIR
    constraints_file = (
        APPLICATION_DIR / "graph_database" / "queries" / "apply_uniqueness_constraints_to_nodes.cypher"
    )
    text = constraints_file.read_text()
    for name in ("note_id_uniqueness", "cue_id_uniqueness", "section_id_uniqueness"):
        assert name in text


@pytest.mark.parametrize("text,expected", [
    ("2:10", 130000),
    ("2:10.5", 130500),
    ("1:02:03", 3723000),
    ("90", 90000),
    ("90.25", 90250),
    ("41000ms", 41000),
    ("0", 0),
])
def test_parse_position(text, expected):
    assert parse_position(text) == expected


@pytest.mark.parametrize("bad", ["", None, "abc", "1:2:3:4", "-5", "12ms34"])
def test_parse_position_rejects_garbage(bad):
    with pytest.raises(ValueError):
        parse_position(bad)


@pytest.mark.parametrize("ms,expected", [
    (0, "0:00"),
    (130000, "2:10"),
    (130500, "2:10.500"),
    (3723000, "62:03"),
    (None, "-:--"),
])
def test_format_ms(ms, expected):
    assert format_ms(ms) == expected


def test_parse_format_round_trip():
    for ms in (0, 500, 41000, 130500, 3_600_000):
        assert parse_position(format_ms(ms)) == ms
