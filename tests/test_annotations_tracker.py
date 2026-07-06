"""Offline tests for PlaybackTracker (plan 04 T4): the poll-and-dispatch core
of `listen`, driven with a fake fetch, fake clock, scripted prompts, and a fake
writer — no TTY, no HTTP, no Neo4j."""
import pytest

from application.annotations import model
from application.annotations.listen import NUDGE_STEP_MS, PlaybackTracker


class FakeClock:
    def __init__(self, start=1000.0):
        self.now = start

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds


class FakeWriter:
    """Reuses the real param builders so records match production shapes."""

    def __init__(self, existing_orders=None):
        self.records = []
        self.undone = []
        self.nudges = []
        self.existing_orders = existing_orders or {}

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

    def nudge(self, record, at_ms):
        self.nudges.append((record["id"], at_ms))

    def next_section_order(self, track_id):
        return self.existing_orders.get(track_id, 0)


def _item(track_id="trk1", name="Strobe", duration_ms=634000):
    return {
        "id": track_id,
        "name": name,
        "duration_ms": duration_ms,
        "artists": [{"name": "deadmau5"}],
    }


def _state(track_id="trk1", progress_ms=41000, is_playing=True, **item_kwargs):
    return {
        "is_playing": is_playing,
        "progress_ms": progress_ms,
        "item": _item(track_id, **item_kwargs),
    }


def _tracker(states, writer=None, prompts=(), clock=None, prompt_advances=0.0):
    """Build a tracker over scripted playback states and prompt answers.
    prompt_advances simulates typing time: the clock moves while the prompt
    blocks, which must NOT move already-captured positions."""
    clock = clock or FakeClock()
    writer = writer if writer is not None else FakeWriter()
    state_iter = iter(states)
    prompt_iter = iter(prompts)

    def fetch():
        return next(state_iter)

    def prompt(_message):
        clock.advance(prompt_advances)
        return next(prompt_iter)

    return PlaybackTracker(fetch, writer, prompt, clock=clock), writer, clock


def test_poll_tracks_current_item():
    tracker, _, _ = _tracker([_state(progress_ms=41000)])
    state = tracker.poll()
    assert state["item"]["id"] == "trk1"
    assert tracker.track["name"] == "Strobe"
    assert tracker.position_ms() == 41000


def test_position_advances_with_wallclock_while_playing():
    tracker, _, clock = _tracker([_state(progress_ms=41000, is_playing=True)])
    tracker.poll()
    clock.advance(2.5)
    assert tracker.position_ms() == 43500


def test_position_frozen_while_paused():
    tracker, _, clock = _tracker([_state(progress_ms=41000, is_playing=False)])
    tracker.poll()
    clock.advance(10)
    assert tracker.position_ms() == 41000


def test_position_clamped_to_duration():
    tracker, _, clock = _tracker([_state(progress_ms=633000, duration_ms=634000)])
    tracker.poll()
    clock.advance(60)
    assert tracker.position_ms() == 634000


def test_no_active_playback():
    tracker, writer, _ = _tracker([None], prompts=["should not be asked"])
    assert tracker.poll() is None
    assert tracker.position_ms() is None
    assert "no active playback" in tracker.handle_key("c")
    assert writer.records == []
    assert "-- no active playback --" in tracker.status_line()


def test_cue_captured_at_keypress_time_not_after_prompt():
    # The label takes 5s to type; the cue must land at the keypress position.
    tracker, writer, clock = _tracker(
        [_state(progress_ms=41000)], prompts=["the drop"], prompt_advances=5.0
    )
    tracker.poll()
    clock.advance(1.0)  # 42000 at keypress
    feedback = tracker.handle_key("c")
    assert writer.records[0]["at_ms"] == 42000
    assert "the drop" in feedback


def test_note_carries_position_and_empty_note_discarded():
    tracker, writer, _ = _tracker([_state(progress_ms=10000)], prompts=["nice pads", "   "])
    tracker.poll()
    tracker.handle_key("n")
    assert writer.records[0]["type"] == "note" and writer.records[0]["at_ms"] == 10000
    assert tracker.handle_key("n") == "empty - discarded"
    assert len(writer.records) == 1


def test_sections_chain_orders_from_graph_seed():
    writer = FakeWriter(existing_orders={"trk1": 3})  # 3 cold-entry sections exist
    tracker, _, _ = _tracker(
        [_state(progress_ms=0)], writer=writer, prompts=["buildup 1", "drop 1"]
    )
    tracker.poll()
    tracker.handle_key("s")
    tracker.handle_key("s")
    sections = [r for r in writer.records if r["type"] == "section"]
    assert [s["order"] for s in sections] == [3, 4]
    assert [s["kind"] for s in sections] == ["buildup", "drop"]


def test_section_orders_are_per_track():
    tracker, writer, _ = _tracker(
        [_state("trk1"), _state("trk2")], prompts=["intro", "intro"]
    )
    tracker.poll()
    tracker.handle_key("s")
    tracker.poll()  # album plays on: next track
    tracker.handle_key("s")
    sections = writer.records
    assert sections[0]["track_id"] == "trk1" and sections[0]["order"] == 0
    assert sections[1]["track_id"] == "trk2" and sections[1]["order"] == 0


def test_undo_pops_and_releases_section_order():
    tracker, writer, _ = _tracker(
        [_state()], prompts=["intro", "buildup 1", "buildup for real"]
    )
    tracker.poll()
    tracker.handle_key("s")  # order 0
    tracker.handle_key("s")  # order 1
    feedback = tracker.handle_key("u")
    assert "undid section" in feedback
    assert writer.undone[0]["order"] == 1
    tracker.handle_key("s")  # must reuse order 1, not skip to 2
    assert writer.records[-1]["order"] == 1
    assert len(tracker.session) == 2  # the undone record left the summary


def test_undo_on_empty_stack():
    tracker, writer, _ = _tracker([_state()])
    tracker.poll()
    assert tracker.handle_key("u") == "nothing to undo"
    assert writer.undone == []


def test_nudge_moves_last_capture_both_ways_and_floors_at_zero():
    tracker, writer, _ = _tracker([_state(progress_ms=200)], prompts=["hit"])
    tracker.poll()
    tracker.handle_key("c")  # cue at 200ms
    assert "nudged" in tracker.handle_key("+")
    assert writer.records[0]["at_ms"] == 200 + NUDGE_STEP_MS
    tracker.handle_key("-")
    tracker.handle_key("-")  # 200 - 500 floors at 0
    assert writer.records[0]["at_ms"] == 0
    assert writer.nudges[-1] == (writer.records[0]["id"], 0)


def test_nudge_section_moves_start_ms():
    tracker, writer, _ = _tracker([_state(progress_ms=60000)], prompts=["drop 2"])
    tracker.poll()
    tracker.handle_key("s")
    tracker.handle_key("-")
    assert writer.records[0]["start_ms"] == 60000 - NUDGE_STEP_MS


def test_nudge_with_nothing_captured():
    tracker, _, _ = _tracker([_state()])
    tracker.poll()
    assert tracker.handle_key("+") == "nothing to nudge"


def test_quit_and_unmapped_keys():
    tracker, _, _ = _tracker([_state()])
    tracker.poll()
    assert tracker.handle_key("x") == ""
    assert not tracker.quit_requested
    tracker.handle_key("q")
    assert tracker.quit_requested


def test_session_summary_counts_by_type_and_track():
    tracker, _, _ = _tracker(
        [_state("trk1"), _state("trk2")],
        prompts=["note one", "hit", "intro"],
    )
    tracker.poll()
    tracker.handle_key("n")
    tracker.handle_key("c")
    tracker.poll()
    tracker.handle_key("s")
    summary = tracker.session_summary()
    assert summary["total"] == 3
    assert summary["by_type"] == {"note": 1, "cue": 1, "section": 1}
    assert set(summary["by_track"]) == {"trk1", "trk2"}
    assert len(summary["by_track"]["trk1"]) == 2


def test_status_line_shows_track_position_and_capture_count():
    tracker, _, _ = _tracker([_state(progress_ms=130000)], prompts=["hit"])
    tracker.poll()
    tracker.handle_key("c")
    line = tracker.status_line()
    assert "deadmau5 - Strobe" in line
    assert "2:10" in line
    assert "(1 captured)" in line
