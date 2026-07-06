"""`listen` — live annotation capture while listening (plan 04, phase B / T4).

Polls GET {SPOTIFY_API_BASE_URL}/v1/me/player (~1s) for the currently playing
track and turns single keypresses into graph annotations:

    n  note (text prompt)        c  cue at the current position (label prompt)
    s  section boundary (label prompt; NEXT-chained, end set by the next boundary)
    u  undo the last capture     +/-  nudge the last capture by 500ms
    q  quit (prints a session summary)

Positions are captured AT KEYPRESS TIME (before the prompt blocks), estimated
from the last poll plus wall-clock elapsed — accuracy is poll-latency bound
(±1-2s); the nudge keys are the fine-tuning story for now.

Layering: PlaybackTracker is the pure poll-and-dispatch loop over injected
fetch / writer / prompt / clock callables — unit-testable without a TTY or any
services. main() is the thin stdlib-only terminal layer (termios/tty/select).

Run against the mock (no OAuth scope needed):
    docker compose run --rm -e SPOTIFY_API_BASE_URL=http://spotify_mock \
        responses_write_to_neo4j python3 -m application.annotations.listen

Live Spotify use requires the `user-read-playback-state` scope, which lands
with the bundled re-auth (plans README "Do these first"; plan 04 T3).
"""
import argparse
import select
import sys
import termios
import time
import tty
from collections import Counter

import requests

from application.annotations.model import Neo4jAnnotationWriter
from application.annotations.timecode import format_ms
from application.config import SECRETS_DIR, SPOTIFY_API_BASE_URL
from application.loggers import get_logger

logger = get_logger(__name__)

NEO4J_CREDENTIALS_FILE = SECRETS_DIR / "neo4j_credentials.yaml"
SPOTIFY_API_TOKEN_FILE = SECRETS_DIR / "spotify_api_token.secret"

NUDGE_STEP_MS = 500
POLL_INTERVAL_SECONDS = 1.0

HOTKEYS_HELP = (
    "hotkeys: [n]ote  [c]ue  [s]ection  [u]ndo  [+/-] nudge 500ms  [q]uit"
)


class PlaybackTracker:
    """Poll-and-dispatch core of `listen`: pure over injected callables.

    fetch_playback() -> the /v1/me/player payload dict ({is_playing,
        progress_ms, item: <track object>}) or None (no active device).
    writer -> the annotation writer protocol (Neo4jAnnotationWriter or a fake):
        add_note / add_cue / add_section / undo / nudge / next_section_order.
    prompt(message) -> str: blocking text entry (the TTY layer drops out of raw
        mode for it; tests inject a stub).
    clock() -> float seconds (monotonic): drives between-poll position
        estimation, injectable for deterministic tests.
    """

    def __init__(self, fetch_playback, writer, prompt, clock=time.monotonic):
        self.fetch_playback = fetch_playback
        self.writer = writer
        self.prompt = prompt
        self.clock = clock

        self.track = None  # the /v1/me/player item currently playing
        self.is_playing = False
        self._progress_ms = 0
        self._polled_at = None

        self.undo_stack = []
        self.session = []  # surviving records, for the exit summary
        self._next_orders = {}  # track_id -> next section order (seeded from the graph)
        self.quit_requested = False

    # --- polling -----------------------------------------------------------

    def poll(self):
        """Refresh playback state. Returns the payload, or None when idle."""
        state = self.fetch_playback()
        if not state or not state.get("item"):
            self.track = None
            self.is_playing = False
            self._progress_ms = 0
            self._polled_at = None
            return None
        self.track = state["item"]
        self.is_playing = bool(state.get("is_playing"))
        self._progress_ms = int(state.get("progress_ms") or 0)
        self._polled_at = self.clock()
        return state

    def position_ms(self):
        """Estimated position: last polled progress plus wall-clock elapsed
        while playing, clamped to the track duration. None when idle."""
        if self.track is None:
            return None
        position = self._progress_ms
        if self.is_playing and self._polled_at is not None:
            position += int((self.clock() - self._polled_at) * 1000)
        duration = self.track.get("duration_ms")
        return min(position, duration) if duration else position

    # --- key dispatch ------------------------------------------------------

    def handle_key(self, key):
        """Dispatch one keypress; returns a feedback line for the TTY layer."""
        if key == "q":
            self.quit_requested = True
            return "bye"
        if key == "u":
            return self._undo()
        if key in ("+", "-"):
            return self._nudge(NUDGE_STEP_MS if key == "+" else -NUDGE_STEP_MS)
        if key in ("n", "c", "s"):
            if self.track is None:
                return "no active playback - start something on any device first"
            # Capture the position at KEYPRESS time, before the prompt blocks.
            at_ms = self.position_ms()
            if key == "n":
                return self._add_note(at_ms)
            if key == "c":
                return self._add_cue(at_ms)
            return self._add_section(at_ms)
        return ""  # unmapped key: ignore silently

    def _record(self, record):
        self.undo_stack.append(record)
        self.session.append(record)
        return record

    def _add_note(self, at_ms):
        text = (self.prompt("note> ") or "").strip()
        if not text:
            return "empty - discarded"
        self._record(self.writer.add_note(self.track["id"], text, at_ms=at_ms))
        return f'note @ {format_ms(at_ms)}: {text}'

    def _add_cue(self, at_ms):
        label = (self.prompt("cue label> ") or "").strip() or "cue"
        self._record(self.writer.add_cue(self.track["id"], at_ms, label))
        return f'cue @ {format_ms(at_ms)}: {label}'

    def _add_section(self, at_ms):
        label = (self.prompt("section label> ") or "").strip()
        if not label:
            return "empty - discarded"
        track_id = self.track["id"]
        order = self._claim_section_order(track_id)
        record = self._record(self.writer.add_section(track_id, order, at_ms, label))
        return f'section #{order} [{record["kind"]}] @ {format_ms(at_ms)}: {label}'

    def _claim_section_order(self, track_id):
        if track_id not in self._next_orders:
            # Seed from the graph so live capture appends after cold entries.
            self._next_orders[track_id] = self.writer.next_section_order(track_id)
        order = self._next_orders[track_id]
        self._next_orders[track_id] = order + 1
        return order

    def _undo(self):
        if not self.undo_stack:
            return "nothing to undo"
        record = self.undo_stack.pop()
        self.writer.undo(record)
        if record in self.session:
            self.session.remove(record)
        if record["type"] == "section":
            # Give the order back so the next boundary doesn't skip a slot.
            track_id = record["track_id"]
            self._next_orders[track_id] = min(
                self._next_orders.get(track_id, record["order"]), record["order"]
            )
        label = record.get("label") or record.get("text") or record["id"]
        return f'undid {record["type"]}: {label}'

    def _nudge(self, delta_ms):
        record = self.undo_stack[-1] if self.undo_stack else None
        position_key = None
        if record is not None:
            position_key = "start_ms" if record["type"] == "section" else "at_ms"
            if record.get(position_key) is None:
                record = None
        if record is None:
            return "nothing to nudge"
        new_ms = max(0, int(record[position_key]) + delta_ms)
        self.writer.nudge(record, new_ms)
        record[position_key] = new_ms
        return f'{record["type"]} nudged to {format_ms(new_ms)}'

    # --- display -----------------------------------------------------------

    def status_line(self):
        if self.track is None:
            return "-- no active playback --"
        artists = ", ".join(a.get("name", "?") for a in self.track.get("artists", []))
        state = ">" if self.is_playing else "||"
        return (
            f'{state} {artists} - {self.track["name"]}  '
            f'{format_ms(self.position_ms())}/{format_ms(self.track.get("duration_ms"))}  '
            f'({len(self.session)} captured)'
        )

    def session_summary(self):
        by_track = {}
        for record in self.session:
            by_track.setdefault(record["track_id"], []).append(record)
        return {
            "total": len(self.session),
            "by_type": dict(Counter(record["type"] for record in self.session)),
            "by_track": by_track,
        }


# --- live fetch over HTTP ----------------------------------------------------

def _read_token():
    with open(SPOTIFY_API_TOKEN_FILE, "r") as f:
        return f.read().strip()


def fetch_playback_from_api():
    """GET /v1/me/player with the crawl's token. None on 204 (no active
    device). One 401 -> refresh -> retry, mirroring the engine's behavior."""
    for attempt in (1, 2):
        response = requests.get(
            f"{SPOTIFY_API_BASE_URL}/v1/me/player",
            headers={"Authorization": f"Bearer {_read_token()}"},
        )
        if response.status_code == 204:
            return None
        if response.status_code == 401 and attempt == 1:
            logger.warning("HTTP 401: access token expired; refreshing...")
            from application.spotify_authentication.refresh_token import refresh_spotify_auth
            refresh_spotify_auth()
            continue
        if response.status_code == 403:
            raise SystemExit(
                "403 from /v1/me/player: the token lacks the user-read-playback-state "
                "scope (pending the bundled re-auth, plan 04 T3). Against the mock "
                "(SPOTIFY_API_BASE_URL=http://spotify_mock) no scope is needed."
            )
        response.raise_for_status()
        return response.json()


# --- thin TTY layer (stdlib only: termios/tty/select) ------------------------

def _redraw(line):
    sys.stdout.write("\r\x1b[K" + line)
    sys.stdout.flush()


def _print_summary(summary):
    print(f'\nSession summary: {summary["total"]} annotation(s) '
          f'{summary["by_type"] or ""}')
    for track_id, records in summary["by_track"].items():
        print(f'  {track_id}:')
        for record in records:
            position = record.get("start_ms") if record["type"] == "section" else record.get("at_ms")
            position_text = f'@ {format_ms(position)}' if position is not None else ""
            body = record.get("label") or record.get("text") or ""
            print(f'    {record["type"]:<8} {position_text:<10} {body}')


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="listen",
        description="Live annotation capture from the currently playing track (plan 04 phase B).",
    )
    parser.add_argument(
        "--interval", type=float, default=POLL_INTERVAL_SECONDS,
        help="seconds between /v1/me/player polls (default 1.0)",
    )
    args = parser.parse_args(argv)

    from application.graph_database.connect import connect_to_neo4j

    driver = connect_to_neo4j(NEO4J_CREDENTIALS_FILE)
    writer = Neo4jAnnotationWriter(driver)

    stdin_fd = sys.stdin.fileno()
    saved_termios = termios.tcgetattr(stdin_fd)

    def prompt(message):
        # Drop back to cooked mode for line-edited text entry, then re-arm.
        termios.tcsetattr(stdin_fd, termios.TCSADRAIN, saved_termios)
        try:
            sys.stdout.write("\n")
            return input(message)
        finally:
            tty.setcbreak(stdin_fd)

    tracker = PlaybackTracker(fetch_playback_from_api, writer, prompt)

    print(f'Polling {SPOTIFY_API_BASE_URL}/v1/me/player every {args.interval}s')
    print(HOTKEYS_HELP)

    tty.setcbreak(stdin_fd)
    try:
        last_poll = 0.0
        while not tracker.quit_requested:
            now = time.monotonic()
            if now - last_poll >= args.interval:
                try:
                    tracker.poll()
                except requests.exceptions.ConnectionError as exc:
                    _redraw(f'!! player poll failed: {exc.__class__.__name__} (retrying)')
                last_poll = now
            _redraw(tracker.status_line())
            readable, _, _ = select.select([sys.stdin], [], [], 0.25)
            if readable:
                key = sys.stdin.read(1)
                feedback = tracker.handle_key(key)
                if feedback:
                    sys.stdout.write("\r\x1b[K  " + feedback + "\n")
    finally:
        termios.tcsetattr(stdin_fd, termios.TCSADRAIN, saved_termios)
        driver.close()

    _print_summary(tracker.session_summary())


if __name__ == "__main__":
    main()
