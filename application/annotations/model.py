"""Annotation model layer (plan 04, phases A-B): Notes, Cues, and Sections
attached to Tracks.

Split so the interesting parts test offline:
  - build_*_params are pure (app-side uuid4 ids + UTC created_at timestamps)
    and define the exact param shapes the Cypher under
    application/graph_database/queries/annotations/ consumes;
  - Neo4jAnnotationWriter is the thin execution layer over the bolt driver.
    It implements the writer protocol PlaybackTracker (listen.py) expects:
    add_note / add_cue / add_section / undo / nudge / next_section_order.
"""
from datetime import datetime, timezone
from uuid import uuid4

from application.config import APPLICATION_DIR
from application.graph_database.connect import execute_query_against_neo4j
from application.loggers import get_logger

logger = get_logger(__name__)

ANNOTATION_QUERIES_DIR = APPLICATION_DIR / "graph_database" / "queries" / "annotations"

# Section.kind vocabulary — EDM and song-form both first-class (plan 04 A).
SECTION_KINDS = (
    "intro", "verse", "chorus", "bridge", "buildup", "drop",
    "breakdown", "interlude", "outro", "custom",
)


def _load_query(name):
    with open(ANNOTATION_QUERIES_DIR / f"{name}.cypher", "r") as f:
        return f.read()


INSERT_NOTE_QUERY = _load_query("insert_note")
INSERT_CUE_QUERY = _load_query("insert_cue")
INSERT_SECTION_QUERY = _load_query("insert_section")
FETCH_NOTES_QUERY = _load_query("fetch_notes_for_track")
FETCH_CUES_QUERY = _load_query("fetch_cues_for_track")
FETCH_SECTIONS_QUERY = _load_query("fetch_sections_for_track")
FETCH_TRACKS_BY_NAME_QUERY = _load_query("fetch_tracks_by_name")
DELETE_ANNOTATION_QUERY = _load_query("delete_annotation")
DELETE_SECTION_QUERY = _load_query("delete_section_and_reopen_previous")
NUDGE_ANNOTATION_QUERY = _load_query("nudge_annotation")
NEXT_SECTION_ORDER_QUERY = _load_query("next_section_order")


def _now_iso():
    return datetime.now(timezone.utc).isoformat()


def normalize_kind(label):
    """Derive Section.kind from a freeform label: 'Buildup 2' -> 'buildup',
    anything outside the vocabulary -> 'custom'."""
    words = (label or "").strip().lower().split()
    first = words[0] if words else ""
    return first if first in SECTION_KINDS else "custom"


def build_note_params(track_id, text, at_ms=None):
    """Param shape for insert_note.cypher. at_ms is optional: set during live
    capture, null for cold entry."""
    return {
        "note": {
            "track_id": track_id,
            "id": str(uuid4()),
            "text": text,
            "at_ms": None if at_ms is None else int(at_ms),
            "created_at": _now_iso(),
        }
    }


def build_cue_params(track_id, at_ms, label):
    """Param shape for insert_cue.cypher."""
    return {
        "cue": {
            "track_id": track_id,
            "id": str(uuid4()),
            "at_ms": int(at_ms),
            "label": label,
            "created_at": _now_iso(),
        }
    }


def build_section_params(track_id, order, start_ms, label, kind=None, end_ms=None):
    """Param shape for insert_section.cypher. kind derives from the label
    unless given explicitly (then it must be in the vocabulary); end_ms stays
    null for an open section (closed by the next boundary or track end)."""
    if kind is None:
        kind = normalize_kind(label)
    elif kind not in SECTION_KINDS:
        raise ValueError(f"unknown section kind {kind!r}; expected one of {SECTION_KINDS}")
    return {
        "section": {
            "track_id": track_id,
            "id": str(uuid4()),
            "order": int(order),
            "start_ms": int(start_ms),
            "end_ms": None if end_ms is None else int(end_ms),
            "label": label,
            "kind": kind,
            "created_at": _now_iso(),
        }
    }


class Neo4jAnnotationWriter:
    """Writes annotations straight to Neo4j via the bolt driver.

    Each add_* returns a flat record dict ({"type": ..., **params}) that the
    CLIs keep on their undo stacks and hand back to undo()/nudge().
    """

    def __init__(self, driver, database="neo4j"):
        self.driver = driver
        self.database = database

    def _execute(self, query, **params):
        execute_query_against_neo4j(
            query=query, driver=self.driver, database=self.database, **params
        )

    def _fetch(self, query, **params):
        records, _, _ = self.driver.execute_query(query, database_=self.database, **params)
        return [dict(record) for record in records]

    def add_note(self, track_id, text, at_ms=None):
        params = build_note_params(track_id, text, at_ms=at_ms)
        self._execute(INSERT_NOTE_QUERY, **params)
        return {"type": "note", **params["note"]}

    def add_cue(self, track_id, at_ms, label):
        params = build_cue_params(track_id, at_ms, label)
        self._execute(INSERT_CUE_QUERY, **params)
        return {"type": "cue", **params["cue"]}

    def add_section(self, track_id, order, start_ms, label, kind=None, end_ms=None):
        params = build_section_params(track_id, order, start_ms, label, kind=kind, end_ms=end_ms)
        self._execute(INSERT_SECTION_QUERY, **params)
        return {"type": "section", **params["section"]}

    def undo(self, record):
        if record["type"] == "section":
            self._execute(DELETE_SECTION_QUERY, section_id=record["id"])
        else:
            self._execute(DELETE_ANNOTATION_QUERY, annotation_id=record["id"])
        logger.info(f'Undid {record["type"]} {record["id"]}')

    def nudge(self, record, at_ms):
        self._execute(NUDGE_ANNOTATION_QUERY, annotation_id=record["id"], at_ms=int(at_ms))

    def next_section_order(self, track_id):
        rows = self._fetch(NEXT_SECTION_ORDER_QUERY, track_id=track_id)
        return rows[0]["next_order"] if rows else 0

    def search_tracks(self, search_term):
        return self._fetch(FETCH_TRACKS_BY_NAME_QUERY, search_term=search_term)

    def fetch_annotations(self, track_id):
        return {
            "notes": self._fetch(FETCH_NOTES_QUERY, track_id=track_id),
            "cues": self._fetch(FETCH_CUES_QUERY, track_id=track_id),
            "sections": self._fetch(FETCH_SECTIONS_QUERY, track_id=track_id),
        }
