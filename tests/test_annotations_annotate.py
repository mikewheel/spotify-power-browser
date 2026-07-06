"""Offline tests for the cold-entry annotate CLI flow (plan 04 T2): scripted
input/output against a fake writer — no TTY, no services."""
import pytest

from application.annotations import annotate
from application.annotations import model


class FakeWriter:
    """In-memory stand-in for Neo4jAnnotationWriter; reuses the real param
    builders so records have the production shape."""

    def __init__(self, tracks=None):
        self.tracks = tracks or []
        self.records = []
        self.undone = []

    def search_tracks(self, search_term):
        return [t for t in self.tracks if search_term.lower() in t["name"].lower()]

    def add_note(self, track_id, text, at_ms=None):
        record = {"type": "note", **model.build_note_params(track_id, text, at_ms=at_ms)["note"]}
        self.records.append(record)
        return record

    def add_cue(self, track_id, at_ms, label):
        record = {"type": "cue", **model.build_cue_params(track_id, at_ms, label)["cue"]}
        self.records.append(record)
        return record

    def add_section(self, track_id, order, start_ms, label, kind=None, end_ms=None):
        record = {
            "type": "section",
            **model.build_section_params(track_id, order, start_ms, label, kind=kind, end_ms=end_ms)["section"],
        }
        self.records.append(record)
        return record

    def undo(self, record):
        self.undone.append(record)
        self.records.remove(record)

    def next_section_order(self, track_id):
        orders = [r["order"] for r in self.records if r["type"] == "section" and r["track_id"] == track_id]
        return max(orders, default=-1) + 1

    def fetch_annotations(self, track_id):
        mine = [r for r in self.records if r["track_id"] == track_id]
        return {
            "notes": [r for r in mine if r["type"] == "note"],
            "cues": [r for r in mine if r["type"] == "cue"],
            "sections": [r for r in mine if r["type"] == "section"],
        }


def _track(track_id="trk1", name="Strobe", album="Album", artists=("deadmau5",)):
    return {"id": track_id, "name": name, "duration_ms": 634000, "album": album, "artists": list(artists)}


def _scripted(lines):
    """An input() double fed from a list; raises if the script runs dry."""
    iterator = iter(lines)
    return lambda _prompt="": next(iterator)


@pytest.fixture
def out():
    lines = []

    def _out(message=""):
        lines.append(str(message))

    _out.lines = lines
    return _out


def test_pick_track_single_match_returns_immediately(out):
    writer = FakeWriter(tracks=[_track()])
    picked = annotate.pick_track(writer, "strobe", in_=_scripted([]), out=out)
    assert picked["id"] == "trk1"


def test_pick_track_multiple_matches_prompts_for_choice(out):
    writer = FakeWriter(tracks=[_track("trk1", "Strobe"), _track("trk2", "Strobe (Club Edit)")])
    picked = annotate.pick_track(writer, "strobe", in_=_scripted(["banana", "1"]), out=out)
    assert picked["id"] == "trk2"
    assert any("invalid" in line for line in out.lines)


def test_pick_track_no_match_returns_none(out):
    assert annotate.pick_track(FakeWriter(), "ghost", in_=_scripted([]), out=out) is None


def test_loop_note_cue_section_then_quit(out):
    writer = FakeWriter(tracks=[_track()])
    session = annotate.run_annotation_loop(
        writer,
        _track(),
        in_=_scripted([
            "n", "that switch-up",         # note
            "c", "2:10", "the drop",       # cue at 130000
            "s", "0:00", "intro",          # section 0
            "s", "1:04", "buildup 1",      # section 1 (order chained)
            "q",
        ]),
        out=out,
    )
    assert [r["type"] for r in session] == ["note", "cue", "section", "section"]
    cue = session[1]
    assert cue["at_ms"] == 130000 and cue["label"] == "the drop"
    sections = [r for r in session if r["type"] == "section"]
    assert [s["order"] for s in sections] == [0, 1]
    assert sections[1]["kind"] == "buildup"


def test_loop_undo_removes_last_entry(out):
    writer = FakeWriter(tracks=[_track()])
    session = annotate.run_annotation_loop(
        writer,
        _track(),
        in_=_scripted(["n", "keep me", "n", "typo", "u", "q"]),
        out=out,
    )
    assert len(session) == 1 and session[0]["text"] == "keep me"
    assert len(writer.undone) == 1 and writer.undone[0]["text"] == "typo"


def test_loop_rejects_bad_position_then_accepts(out):
    writer = FakeWriter(tracks=[_track()])
    session = annotate.run_annotation_loop(
        writer,
        _track(),
        in_=_scripted(["c", "nonsense", "1:30", "hit", "q"]),
        out=out,
    )
    assert session[0]["at_ms"] == 90000


def test_loop_blank_position_cancels(out):
    writer = FakeWriter(tracks=[_track()])
    session = annotate.run_annotation_loop(
        writer, _track(), in_=_scripted(["c", "", "q"]), out=out,
    )
    assert session == [] and writer.records == []


def test_loop_empty_note_discarded_and_undo_on_empty_session(out):
    writer = FakeWriter(tracks=[_track()])
    session = annotate.run_annotation_loop(
        writer, _track(), in_=_scripted(["n", "   ", "u", "q"]), out=out,
    )
    assert session == [] and writer.records == []
    assert any("nothing to undo" in line for line in out.lines)
