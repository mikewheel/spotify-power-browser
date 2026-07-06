"""`annotate` — cold-entry annotation CLI (plan 04, phase A / T2).

Search a track by name in the Neo4j graph, pick it, then add notes / cues /
sections from an interactive prompt loop. Positions are typed as M:SS(.mmm),
bare seconds, or '41000ms' (see timecode.parse_position).

Run inside the compose network (Neo4j on the host via the write worker's env):

    docker compose run --rm responses_write_to_neo4j \
        python3 -m application.annotations.annotate "track name"

I/O goes through injected input/print callables so the flow is testable
without a TTY.
"""
import argparse

from application.annotations.model import (
    AnnotationWriteError,
    Neo4jAnnotationWriter,
    normalize_kind,
)
from application.annotations.timecode import format_ms, parse_position
from application.config import SECRETS_DIR
from application.loggers import get_logger

logger = get_logger(__name__)

NEO4J_CREDENTIALS_FILE = SECRETS_DIR / "neo4j_credentials.yaml"

HELP_TEXT = """commands:
  n   add a note (freeform text)
  c   add a cue (position + label)
  s   add a section boundary (start position + label; end closed by the next boundary)
  l   list this track's annotations
  u   undo the last entry from this session
  h   this help
  q   quit"""


def pick_track(writer, search_term, in_=input, out=print):
    """Search the graph by name and let the user pick a match. None if no match."""
    matches = writer.search_tracks(search_term)
    if not matches:
        out(f'No tracks in the graph match {search_term!r}. (Only crawled tracks are annotatable.)')
        return None
    if len(matches) == 1:
        return matches[0]

    out(f'{len(matches)} matches:')
    for index, track in enumerate(matches):
        artists = ", ".join(a for a in track["artists"] if a) or "?"
        out(f'  [{index}] {artists} - {track["name"]} ({track["album"] or "?"})')
    while True:
        choice = in_("pick a number (or q): ").strip().lower()
        if choice == "q":
            return None
        if choice.isdigit() and int(choice) < len(matches):
            return matches[int(choice)]
        out("invalid choice")


def _prompt_position(in_, out, message):
    """Prompt until a parseable position (or blank to cancel). None = cancelled."""
    while True:
        raw = in_(message).strip()
        if not raw:
            return None
        try:
            return parse_position(raw)
        except ValueError as exc:
            out(str(exc))


def _list_annotations(writer, track, out):
    annotations = writer.fetch_annotations(track["id"])
    out(f'--- {track["name"]} ---')
    for section in annotations["sections"]:
        end = format_ms(section["end_ms"]) if section["end_ms"] is not None else "…"
        out(f'  section #{section["order"]} [{section["kind"]}] '
            f'{format_ms(section["start_ms"])}-{end}  {section["label"]}')
    for cue in annotations["cues"]:
        out(f'  cue @ {format_ms(cue["at_ms"])}  {cue["label"]}')
    for note in annotations["notes"]:
        position = f' @ {format_ms(note["at_ms"])}' if note["at_ms"] is not None else ""
        out(f'  note{position}: {note["text"]}')
    if not any(annotations.values()):
        out("  (none yet)")


def run_annotation_loop(writer, track, in_=input, out=print):
    """The interactive prompt loop for one track. Returns the session records."""
    session = []
    out(f'Annotating: {track["name"]}  ({format_ms(track.get("duration_ms"))})')
    out(HELP_TEXT)

    while True:
        command = in_("annotate> ").strip().lower()

        if command == "q":
            break
        elif command == "h":
            out(HELP_TEXT)
        elif command == "l":
            _list_annotations(writer, track, out)
        elif command == "n":
            text = in_("note text: ").strip()
            if not text:
                out("empty - discarded")
                continue
            session.append(writer.add_note(track["id"], text))
            out("noted.")
        elif command == "c":
            at_ms = _prompt_position(in_, out, "cue position (M:SS): ")
            if at_ms is None:
                out("cancelled")
                continue
            label = in_("cue label: ").strip() or "cue"
            session.append(writer.add_cue(track["id"], at_ms, label))
            out(f'cue @ {format_ms(at_ms)}: {label}')
        elif command == "s":
            start_ms = _prompt_position(in_, out, "section start (M:SS): ")
            if start_ms is None:
                out("cancelled")
                continue
            label = in_("section label: ").strip()
            if not label:
                out("empty - discarded")
                continue
            order = writer.next_section_order(track["id"])
            try:
                record = writer.add_section(track["id"], order, start_ms, label)
            except AnnotationWriteError as exc:
                # e.g. a section already starts at this ms - nothing written.
                out(f"!! not saved: {exc}")
                continue
            session.append(record)
            out(f'section #{order} [{normalize_kind(label)}] @ {format_ms(start_ms)}: {label}')
        elif command == "u":
            if not session:
                out("nothing to undo (this session)")
                continue
            record = session.pop()
            writer.undo(record)
            out(f'undid {record["type"]}: {record.get("label") or record.get("text") or record["id"]}')
        elif command:
            out(f'unknown command {command!r} - h for help')

    return session


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="annotate",
        description="Cold-entry annotation of a track already in the graph (plan 04 phase A).",
    )
    parser.add_argument("search_term", nargs="+", help="track name (substring, case-insensitive)")
    args = parser.parse_args(argv)
    search_term = " ".join(args.search_term)

    from application.graph_database.connect import connect_to_neo4j

    driver = connect_to_neo4j(NEO4J_CREDENTIALS_FILE)
    try:
        writer = Neo4jAnnotationWriter(driver)
        track = pick_track(writer, search_term)
        if track is None:
            return
        session = run_annotation_loop(writer, track)
        print(f'{len(session)} annotation(s) written to {track["name"]}.')
    finally:
        driver.close()


if __name__ == "__main__":
    main()
