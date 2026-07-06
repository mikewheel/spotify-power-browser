"""Title normalization for entity mastering (plan 03) — the heart of the
heuristic tier of the identity ladder.

normalize() reduces a track title to the comparison key used for clustering,
recording WHAT was stripped as the variant kind. Deliberate stances:

- Remix credits are NEVER stripped: "(Artist B Remix)" is a different song in
  DJ reality. The credit stays inside the normalized text (so a remix can never
  merge with its parent) and is surfaced via remix_credit / base_text so the
  clustering layer can emit (:Song)-[:REMIX_OF]->(:Song) edges.
- feat./featuring/with clauses are stripped only when the featured name is
  already among the track's credited artists — otherwise the clause is signal
  and stays in the title.
- Re-recordings ("Taylor's Version" pattern) share title + artist but differ in
  ISRC and usually duration; they land as separate Songs, each kind
  'canonical'. That is deliberate: a re-recording is a different recording.
"""
import re
import unicodedata
from dataclasses import dataclass

# Suffix decorations: end-anchored, stripped repeatedly until fixpoint so
# stacked suffixes ("Song - Single Version - 2011 Remaster") all come off.
# Each strip records its kind. Order decides which kind is recorded first for
# a stacked title (outermost decoration strips first).
_DECORATION_PATTERNS = [
    # "- 2011 Remaster", "- Remastered 2009", "(Remastered)", "(2011 Remaster)"
    ("remaster", re.compile(r"\s*-\s*(?:\d{4}\s+)?remaster(?:ed)?(?:\s+\d{4})?\s*$")),
    ("remaster", re.compile(r"\s*[(\[]\s*(?:\d{4}\s+)?remaster(?:ed)?(?:\s+\d{4})?\s*[)\]]\s*$")),
    # "- Deluxe Edition", "(Deluxe ...)"
    ("deluxe", re.compile(r"\s*-\s*deluxe(?:\s+edition)?\s*$")),
    ("deluxe", re.compile(r"\s*[(\[]\s*deluxe[^)\]]*[)\]]\s*$")),
    # "(Expanded ...)"
    ("expanded", re.compile(r"\s*-\s*expanded(?:\s+edition)?\s*$")),
    ("expanded", re.compile(r"\s*[(\[]\s*expanded[^)\]]*[)\]]\s*$")),
    # "- Single Version"
    ("single_version", re.compile(r"\s*-\s*single\s+version\s*$")),
    ("single_version", re.compile(r"\s*[(\[]\s*single\s+version\s*[)\]]\s*$")),
    # "- Radio Edit"
    ("radio_edit", re.compile(r"\s*-\s*radio\s+edit\s*$")),
    ("radio_edit", re.compile(r"\s*[(\[]\s*radio\s+edit\s*[)\]]\s*$")),
    # "- Bonus Track"
    ("bonus_track", re.compile(r"\s*-\s*bonus\s+track\s*$")),
    ("bonus_track", re.compile(r"\s*[(\[]\s*bonus\s+track\s*[)\]]\s*$")),
    # "- Live", "- Live at Wembley", "(Live from ...)"
    ("live", re.compile(r"\s*-\s*live(?:\s+(?:at|from|in)\s+.*)?\s*$")),
    ("live", re.compile(r"\s*[(\[]\s*live(?:\s+(?:at|from|in)\s+[^)\]]*)?\s*[)\]]\s*$")),
    # "- Demo", "(Demo Version)"
    ("demo", re.compile(r"\s*-\s*demo(?:\s+version)?\s*$")),
    ("demo", re.compile(r"\s*[(\[]\s*demo(?:\s+version)?\s*[)\]]\s*$")),
]

# Remix markers. The credit (possibly empty, e.g. "(Remix)") is extracted so
# the marker survives normalization in a canonical form and REMIX_OF parents
# can be resolved from base_text.
#
# The hyphen form anchors at the LAST whitespace-delimited " - " separator:
# the greedy <base> pushes the match rightward, and requiring whitespace on
# both sides keeps internal hyphens ("Re-Wired", "T-Shirt", "Jay-Z") inside
# the base/credit instead of truncating the base at the first hyphen (which
# missed the real REMIX_OF parent — or hit a wrong one).
_REMIX_PATTERNS = [
    re.compile(r"\s*[(\[]\s*(?P<credit>[^()\[\]]*?)\s*remix\s*[)\]]\s*$"),
    re.compile(r"^(?P<base>.*\S)\s+-\s+(?P<credit>.*?)\s*remix\s*$"),
]

# feat./featuring/with clauses — parenthesized anywhere-at-end, or a bare
# trailing "feat." clause. Unparenthesized "with" is deliberately NOT matched
# ("Dancing With Myself" is a title, not a credit).
_FEAT_PATTERNS = [
    re.compile(r"\s*[(\[]\s*(?:feat\.?|ft\.?|featuring|with)\s+([^)\]]+?)\s*[)\]]\s*$"),
    re.compile(r"\s*-\s*(?:feat\.?|ft\.?|featuring)\s+(.+?)\s*$"),
    re.compile(r"\s+(?:feat\.?|ft\.?|featuring)\s+(.+?)\s*$"),
]

_APOSTROPHES = re.compile(r"['’ʼ]")
_NON_ALNUM = re.compile(r"[^0-9a-z]+")


def _scrub(text):
    """Unicode NFKD -> drop combining marks -> drop apostrophes (don't -> dont)
    -> collapse punctuation/whitespace runs to single spaces."""
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = _APOSTROPHES.sub("", text)
    return _NON_ALNUM.sub(" ", text).strip()


def _artist_in_clause(clause, artist_names):
    """True when any credited artist appears in the featured-credit clause."""
    clause_scrubbed = f" {_scrub(clause.lower())} "
    for name in artist_names:
        name_scrubbed = _scrub(str(name).lower())
        if name_scrubbed and f" {name_scrubbed} " in clause_scrubbed:
            return True
    return False


@dataclass(frozen=True)
class NormalizedTitle:
    text: str                 # the comparison key (remix credit retained)
    base_text: str            # text minus the remix marker (== text if no remix)
    kind: str                 # 'remix' | first stripped decoration | 'canonical'
    kinds: tuple = ()         # every decoration kind stripped, in strip order
    remix_credit: str = None  # None = not a remix; may be "" ("(Remix)")

    @property
    def is_remix(self):
        return self.remix_credit is not None


def normalize(title, artist_names=()):
    """Normalize a track title for song-identity comparison.

    artist_names: the track's credited artist names — needed to decide whether
    a feat./featuring clause is redundant (strippable) or signal (kept).
    """
    working = (title or "").lower().strip()

    kinds = []
    remix_credit = None

    # Strip end-anchored decorations until fixpoint. Remix markers are pulled
    # OUT (and remembered) rather than dropped, so an inner decoration behind
    # one ("Song (X Remix) - Radio Edit") still strips.
    changed = True
    while changed and working:
        changed = False

        for kind, pattern in _DECORATION_PATTERNS:
            new = pattern.sub("", working)
            if new != working:
                kinds.append(kind)
                working = new
                changed = True
                break
        if changed:
            continue

        if remix_credit is None:  # only the outermost remix marker is the credit
            for pattern in _REMIX_PATTERNS:
                match = pattern.search(working)
                if match:
                    remix_credit = match.group("credit").strip()
                    groups = match.groupdict()
                    # Hyphen form: the base is the greedy prefix before the
                    # LAST " - " separator. Paren form: everything before the
                    # end-anchored marker.
                    if "base" in groups:
                        working = groups["base"]
                    else:
                        working = working[:match.start()]
                    changed = True
                    break
            if changed:
                continue

        for pattern in _FEAT_PATTERNS:
            match = pattern.search(working)
            if match and _artist_in_clause(match.group(1), artist_names):
                working = working[:match.start()]
                changed = True
                break

    base_text = _scrub(working)
    if remix_credit is not None:
        text = _scrub(f"{base_text} {remix_credit} remix")
    else:
        text = base_text

    if remix_credit is not None:
        kind = "remix"
    elif kinds:
        kind = kinds[0]
    else:
        kind = "canonical"

    return NormalizedTitle(
        text=text,
        base_text=base_text,
        kind=kind,
        kinds=tuple(kinds),
        remix_credit=remix_credit,
    )
