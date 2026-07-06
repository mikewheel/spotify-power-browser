"""Tests for the manual-overrides YAML loader (plan 03 T5)."""
import pytest

from application.mastering.overrides import Overrides, load_overrides


def test_missing_file_means_no_overrides(tmp_path):
    overrides = load_overrides(tmp_path / "nope.yaml")
    assert overrides.merges == [] and overrides.splits == []
    assert not overrides


def test_loads_tracks_mappings_and_bare_lists(tmp_path):
    path = tmp_path / "overrides.yaml"
    path.write_text(
        "merge:\n"
        "  - tracks: [a1, a2]\n"
        "    reason: same recording\n"
        "  - [b1, b2, b3]\n"
        "split:\n"
        "  - tracks: [c1]\n"
    )
    overrides = load_overrides(path)
    assert overrides.merges == [["a1", "a2"], ["b1", "b2", "b3"]]
    assert overrides.splits == [["c1"]]
    assert overrides


def test_empty_file_is_fine(tmp_path):
    path = tmp_path / "overrides.yaml"
    path.write_text("")
    assert not load_overrides(path)


def test_malformed_entry_raises(tmp_path):
    path = tmp_path / "overrides.yaml"
    path.write_text("merge:\n  - tracks: not-a-list\n")
    with pytest.raises(ValueError, match="Malformed merge"):
        load_overrides(path)


def test_non_mapping_document_raises(tmp_path):
    path = tmp_path / "overrides.yaml"
    path.write_text("- just\n- a\n- list\n")
    with pytest.raises(ValueError, match="must be a mapping"):
        load_overrides(path)


def test_tracked_example_file_parses():
    from application.config import APPLICATION_DIR
    overrides = load_overrides(APPLICATION_DIR / "mastering" / "overrides.example.yaml")
    assert overrides.merges and overrides.splits


def test_overrides_dataclass_defaults():
    assert not Overrides()
    assert Overrides(merges=[["x"]])
