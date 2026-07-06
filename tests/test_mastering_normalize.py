"""Exhaustive unit tests for application.mastering.normalize (plan 03 T4).

Pure functions — no services needed. The case lists mirror the decoration
taxonomy in docs/plans/03-entity-mastering.md.
"""
import pytest

from application.mastering.normalize import NormalizedTitle, normalize


# ---------------------------------------------------------------------------
# Basic scrubbing: lowercase, unicode NFKD, punctuation/whitespace runs
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("title,expected", [
    ("Hello World", "hello world"),
    ("  Hello   World  ", "hello world"),
    ("HELLO, WORLD!!!", "hello world"),
    ("Café del Mar", "cafe del mar"),          # NFKD folds the accent
    ("Don't Stop Me Now", "dont stop me now"),  # apostrophe drops, no split
    ("Don’t Stop", "dont stop"),                # curly apostrophe too
    ("Song/Title\\Here", "song title here"),
    ("99 Problems", "99 problems"),
    ("", ""),
])
def test_scrubbing(title, expected):
    assert normalize(title).text == expected


def test_none_title_is_empty():
    result = normalize(None)
    assert result.text == "" and result.kind == "canonical"


# ---------------------------------------------------------------------------
# Suffix decorations: stripped, and recorded as the variant kind
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("title,text,kind", [
    ("Cathedral Bells - 2011 Remaster", "cathedral bells", "remaster"),
    ("Cathedral Bells - Remastered", "cathedral bells", "remaster"),
    ("Cathedral Bells - Remastered 2009", "cathedral bells", "remaster"),
    ("Cathedral Bells (Remastered)", "cathedral bells", "remaster"),
    ("Cathedral Bells (2011 Remaster)", "cathedral bells", "remaster"),
    ("Cathedral Bells [Remastered 2004]", "cathedral bells", "remaster"),
    ("Neon Skyline - Deluxe Edition", "neon skyline", "deluxe"),
    ("Neon Skyline - Deluxe", "neon skyline", "deluxe"),
    ("Neon Skyline (Deluxe Version)", "neon skyline", "deluxe"),
    ("Neon Skyline (Expanded Edition)", "neon skyline", "expanded"),
    ("Gutter Anthem - Single Version", "gutter anthem", "single_version"),
    ("Gutter Anthem (Single Version)", "gutter anthem", "single_version"),
    ("Gutter Anthem - Radio Edit", "gutter anthem", "radio_edit"),
    ("Gutter Anthem (Radio Edit)", "gutter anthem", "radio_edit"),
    ("Gutter Anthem - Bonus Track", "gutter anthem", "bonus_track"),
    ("Gutter Anthem (Bonus Track)", "gutter anthem", "bonus_track"),
    ("Cathedral Bells - Live", "cathedral bells", "live"),
    ("Cathedral Bells - Live at Wembley", "cathedral bells", "live"),
    ("Cathedral Bells (Live from Red Rocks)", "cathedral bells", "live"),
    ("Cathedral Bells (Live)", "cathedral bells", "live"),
    ("Cathedral Bells - Demo", "cathedral bells", "demo"),
    ("Cathedral Bells (Demo Version)", "cathedral bells", "demo"),
])
def test_decorations_strip_and_record_kind(title, text, kind):
    result = normalize(title)
    assert result.text == text
    assert result.kind == kind
    assert not result.is_remix


def test_stacked_decorations_strip_to_fixpoint():
    result = normalize("Song Name - Single Version - 2011 Remaster")
    assert result.text == "song name"
    # Outermost first: the remaster suffix came off before the single version.
    assert result.kinds == ("remaster", "single_version")
    assert result.kind == "remaster"


def test_undedecorated_title_is_canonical():
    result = normalize("Cathedral Bells")
    assert result.text == "cathedral bells"
    assert result.kind == "canonical"
    assert result.kinds == ()


@pytest.mark.parametrize("title,expected", [
    # 'live'/'demo' as words inside the title must NOT be treated as suffixes
    ("Live and Let Die", "live and let die"),
    ("Long Live the Queen", "long live the queen"),
    ("Arsonist - Live Wire", "arsonist live wire"),
    ("Demolition Man", "demolition man"),
])
def test_decoration_words_inside_titles_survive(title, expected):
    result = normalize(title)
    assert result.text == expected
    assert result.kind == "canonical"


# ---------------------------------------------------------------------------
# Remix credits: NEVER stripped — a remix is a different song
# ---------------------------------------------------------------------------

def test_remix_credit_is_kept_in_the_text():
    result = normalize("Cathedral Bells (Nightcrawler Remix)")
    assert result.text == "cathedral bells nightcrawler remix"
    assert result.base_text == "cathedral bells"
    assert result.kind == "remix"
    assert result.remix_credit == "nightcrawler"
    assert result.is_remix


def test_remix_never_normalizes_equal_to_its_parent():
    remix = normalize("Cathedral Bells (Nightcrawler Remix)")
    parent = normalize("Cathedral Bells")
    assert remix.text != parent.text
    assert remix.base_text == parent.text  # ...but the parent is resolvable


def test_hyphenated_remix_marker():
    result = normalize("One More Time - Skrillex Remix")
    assert result.text == "one more time skrillex remix"
    assert result.base_text == "one more time"
    assert result.kind == "remix"


def test_bare_remix_marker_has_empty_credit():
    result = normalize("Blue Monday (Remix)")
    assert result.remix_credit == ""
    assert result.text == "blue monday remix"
    assert result.base_text == "blue monday"


def test_decoration_behind_a_remix_still_strips():
    result = normalize("Song (X Remix) - Radio Edit")
    assert result.base_text == "song"
    assert result.text == "song x remix"
    assert result.kind == "remix"           # remix identity wins
    assert "radio_edit" in result.kinds     # ...but the strip is recorded


def test_two_remixes_of_one_song_differ_by_credit():
    a = normalize("Song (A Remix)")
    b = normalize("Song (B Remix)")
    assert a.text != b.text
    assert a.base_text == b.base_text


# ---------------------------------------------------------------------------
# feat./featuring/with: stripped only when redundant with credited artists
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("title", [
    "Umbrella (feat. Jay-Z)",
    "Umbrella (featuring Jay-Z)",
    "Umbrella (with Jay-Z)",
    "Umbrella [feat. Jay-Z]",
    "Umbrella - feat. Jay-Z",
    "Umbrella feat. Jay-Z",
    "Umbrella ft. Jay-Z",
])
def test_feat_stripped_when_artist_is_credited(title):
    result = normalize(title, artist_names=["Rihanna", "JAY-Z"])
    assert result.text == "umbrella"
    assert result.kind == "canonical"


def test_feat_kept_when_artist_not_credited():
    # The featured name is NOT among the credited artists -> it's signal.
    result = normalize("Umbrella (feat. Jay-Z)", artist_names=["Rihanna"])
    assert result.text == "umbrella feat jay z"


def test_feat_kept_when_no_artists_supplied():
    assert normalize("Umbrella (feat. Jay-Z)").text == "umbrella feat jay z"


def test_unparenthesized_with_is_not_a_credit():
    # "with" outside parens is a title word, never a feature clause.
    result = normalize("Dancing With Myself", artist_names=["Myself"])
    assert result.text == "dancing with myself"


def test_feat_clause_with_multiple_names_strips_when_one_is_credited():
    result = normalize("Song (feat. A & B)", artist_names=["X", "B"])
    assert result.text == "song"


def test_feat_before_decoration_strips_after_decoration():
    result = normalize(
        "Umbrella (feat. Jay-Z) - 2011 Remaster", artist_names=["Jay-Z"]
    )
    assert result.text == "umbrella"
    assert result.kind == "remaster"


# ---------------------------------------------------------------------------
# The mock catalog's crafted variants normalize the way clustering expects
# ---------------------------------------------------------------------------

def test_mock_variant_titles():
    assert normalize("Neon Skyline").text == "neon skyline"
    assert normalize("Gutter Anthem").text == "gutter anthem"
    remaster = normalize("Cathedral Bells - 2011 Remaster")
    original = normalize("Cathedral Bells")
    remix = normalize("Cathedral Bells (Nightcrawler Remix)")
    assert remaster.text == original.text
    assert remaster.kind == "remaster"
    assert remix.text != original.text
    assert remix.base_text == original.text


def test_normalized_title_is_frozen():
    result = normalize("Anything")
    assert isinstance(result, NormalizedTitle)
    with pytest.raises(AttributeError):
        result.text = "mutated"
