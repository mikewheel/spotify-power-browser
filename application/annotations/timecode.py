"""Millisecond <-> human timecode helpers for the annotation CLIs.

Pure stdlib, pure functions — unit-testable offline.
"""


def parse_position(text):
    """Parse a playback position into milliseconds.

    Accepted forms:
      "2:10"      -> 130000   (M:SS)
      "2:10.5"    -> 130500   (fractional seconds)
      "1:02:03"   -> 3723000  (H:MM:SS)
      "90"        -> 90000    (bare number = seconds)
      "90.25"     -> 90250
      "41000ms"   -> 41000    (explicit milliseconds)

    Raises ValueError on anything else.
    """
    if text is None:
        raise ValueError("position is required")
    cleaned = text.strip().lower()
    if not cleaned:
        raise ValueError("position is required")

    if cleaned.endswith("ms"):
        try:
            ms = int(cleaned[:-2].strip())
        except ValueError:
            raise ValueError(f"invalid millisecond position: {text!r}")
        if ms < 0:
            # Same rule as the colon/seconds path below: playback positions
            # can't be negative, and a negative ms corrupts sort order and
            # section chains downstream.
            raise ValueError(f"position cannot be negative: {text!r}")
        return ms

    parts = cleaned.split(":")
    if len(parts) > 3:
        raise ValueError(f"invalid position: {text!r}")

    try:
        seconds = float(parts[-1])
        for exponent, part in enumerate(reversed(parts[:-1]), start=1):
            seconds += int(part) * 60 ** exponent
    except ValueError:
        raise ValueError(f"invalid position: {text!r}")

    if seconds < 0:
        raise ValueError(f"position cannot be negative: {text!r}")
    return round(seconds * 1000)


def format_ms(ms):
    """Render milliseconds as M:SS, with a .mmm suffix only when sub-second
    precision is present (nudges make these common)."""
    if ms is None:
        return "-:--"
    ms = int(ms)
    minutes, remainder = divmod(ms, 60_000)
    seconds, millis = divmod(remainder, 1000)
    base = f"{minutes}:{seconds:02d}"
    return f"{base}.{millis:03d}" if millis else base
