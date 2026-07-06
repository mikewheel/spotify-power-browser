"""Manual mastering overrides: forced merges and splits, because the
heuristics WILL be wrong somewhere and Michael will notice.

The overrides file lives outside the repo (default: secrets/
mastering_overrides.yaml, path overridable via the MASTERING_OVERRIDES_PATH
env var); a documented example is tracked at
application/mastering/overrides.example.yaml. A missing file means "no
overrides" — never an error, so the batch job runs before any override has
ever been written.
"""
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from application.loggers import get_logger

logger = get_logger(__name__)


@dataclass
class Overrides:
    # Each inner list is a group of Spotify track ids forced into ONE Song.
    merges: list = field(default_factory=list)
    # Each inner list is a group of track ids torn OUT of whatever cluster the
    # heuristics placed them in, into a Song of their own (the group itself
    # stays together — a singleton list means "this track stands alone").
    splits: list = field(default_factory=list)

    def __bool__(self):
        return bool(self.merges or self.splits)


def _groups(entries, section):
    """Accept both `- tracks: [a, b]` mappings and bare `- [a, b]` lists."""
    groups = []
    for entry in entries or []:
        if isinstance(entry, dict):
            tracks = entry.get("tracks")
        else:
            tracks = entry
        if not isinstance(tracks, list) or not all(isinstance(t, str) for t in tracks):
            raise ValueError(
                f"Malformed {section} override entry (want a list of track ids "
                f"or a mapping with a 'tracks' list): {entry!r}"
            )
        if tracks:
            groups.append(list(tracks))
    return groups


def load_overrides(path):
    """Load forced merges/splits from a YAML file; missing file -> empty."""
    path = Path(path)
    if not path.exists():
        logger.info(f"No mastering overrides file at {path}; proceeding without overrides.")
        return Overrides()

    with open(path, "r") as f:
        raw = yaml.safe_load(f) or {}

    if not isinstance(raw, dict):
        raise ValueError(f"Overrides file {path} must be a mapping with 'merge'/'split' keys.")

    overrides = Overrides(
        merges=_groups(raw.get("merge"), "merge"),
        splits=_groups(raw.get("split"), "split"),
    )
    logger.info(
        f"Loaded mastering overrides from {path}: "
        f"{len(overrides.merges)} merge group(s), {len(overrides.splits)} split group(s)."
    )
    return overrides
