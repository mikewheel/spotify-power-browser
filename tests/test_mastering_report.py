"""Tests for the mastering review report (plan 03 T6) — pure rendering,
no services."""
from application.mastering.cluster import cluster_tracks
from application.mastering.overrides import Overrides
from application.mastering.report import render_review_report, write_review_report
from application.mastering.run import overrides_path_from_env


def rec(tid, name, isrc=None, duration_ms=200000, explicit=False, artist="artA"):
    return {
        "id": tid, "name": name, "isrc": isrc, "linked_from_id": None,
        "duration_ms": duration_ms, "explicit": explicit,
        "artist_ids": [artist], "artist_names": ["Artist A"],
    }


def _result():
    return cluster_tracks([
        # ISRC-backed pair: unambiguous, should sort BELOW the heuristic ones
        rec("t1", "Neon Skyline", isrc="SHARED"),
        rec("t2", "Neon Skyline - Deluxe Edition", isrc="SHARED"),
        # heuristic-only pair with a wide (>1s) duration spread: most ambiguous
        rec("t3", "Gutter Anthem", isrc="I3", duration_ms=200000),
        rec("t4", "Gutter Anthem", isrc="I4", duration_ms=202500, explicit=True),
        # heuristic-only pair with a tight spread: middle of the report
        rec("t5", "Cathedral Bells", isrc="I5", duration_ms=183000),
        rec("t6", "Cathedral Bells - 2011 Remaster", isrc="I6", duration_ms=183200),
        # a remix with a resolvable parent -> a REMIX_OF line
        rec("t7", "Cathedral Bells (Nightcrawler Remix)", isrc="I7", duration_ms=184000),
        # a singleton (summarized in the counts, no section of its own)
        rec("t8", "Loner", isrc="I8"),
    ])


def test_report_renders_and_counts():
    report = render_review_report(_result())
    assert report.startswith("# Mastering review")
    assert "**8** Tracks assigned" in report
    assert "**1** REMIX_OF edges" in report
    assert "**1** clusters flagged for review" in report
    assert "overrides always win" in report


def test_report_sorted_by_ambiguity():
    report = render_review_report(_result())
    # heuristic-only + wide spread first, then heuristic-only tight spread,
    # then the ISRC-backed cluster.
    gutter = report.index("Gutter Anthem")
    cathedral = report.index("Cathedral Bells")
    neon = report.index("Neon Skyline")
    assert gutter < cathedral < neon


def test_report_flags_and_member_rows():
    report = render_review_report(_result())
    assert "heuristic-only, duration spread 2500 ms" in report
    assert "| `t3` |" in report and "| clean |" in report
    assert "| `t4` |" in report and "| explicit |" in report
    assert "| remaster |" in report
    # Singletons don't get their own section.
    assert "Loner" not in report


def test_report_includes_warnings():
    result = _result()
    result.warnings.append("Track tX links from ghost, which is not in the graph; ignored.")
    report = render_review_report(result)
    assert "## Warnings" in report and "ghost" in report


def test_report_marks_split_derived_songs():
    # A split-derived Song (here the shared-ISRC case, where the id also gets
    # a :split: suffix) must be visible in the report even as a singleton.
    result = cluster_tracks(
        [
            rec("t1", "Neon Skyline", isrc="SHARED"),
            rec("t2", "Neon Skyline - Deluxe Edition", isrc="SHARED"),
        ],
        overrides=Overrides(splits=[["t2"]]),
    )
    report = render_review_report(result)
    assert "## Manual splits" in report
    assert "SHARED:split:" in report
    assert "`t2`" in report


def test_write_review_report_writes_the_file(tmp_path):
    path = write_review_report(_result(), output_path=tmp_path / "mastering_review.md")
    assert path.exists()
    assert path.read_text().startswith("# Mastering review")


def test_empty_result_still_renders(tmp_path):
    result = cluster_tracks([])
    report = render_review_report(result)
    assert "_No multi-version clusters were formed this run._" in report


def test_overrides_path_env_wins(monkeypatch):
    monkeypatch.setenv("MASTERING_OVERRIDES_PATH", "/somewhere/else.yaml")
    assert overrides_path_from_env() == "/somewhere/else.yaml"
    monkeypatch.delenv("MASTERING_OVERRIDES_PATH")
    assert overrides_path_from_env().endswith("secrets/mastering_overrides.yaml")
