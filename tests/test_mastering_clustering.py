"""Unit tests for the pure clustering core (plan 03 T5/T7): the identity
ladder on plain dicts — no Neo4j, no mock service, fully offline."""
import pytest

from application.mastering.cluster import (
    DURATION_TOLERANCE_MS,
    cluster_tracks,
    compute_song_id,
    track_record_from_api,
)
from application.mastering.overrides import Overrides


def rec(tid, name, isrc=None, linked_from_id=None, duration_ms=200000,
        explicit=False, artist="artA", artist_name="Artist A"):
    return {
        "id": tid,
        "name": name,
        "isrc": isrc,
        "linked_from_id": linked_from_id,
        "duration_ms": duration_ms,
        "explicit": explicit,
        "artist_ids": [artist],
        "artist_names": [artist_name],
    }


def cluster_of(result, track_id):
    for c in result.clusters:
        if any(m.track_id == track_id for m in c.members):
            return c
    raise AssertionError(f"No cluster contains {track_id}")


def member_of(result, track_id):
    for c in result.clusters:
        for m in c.members:
            if m.track_id == track_id:
                return m
    raise AssertionError(f"No member for {track_id}")


# ---------------------------------------------------------------------------
# Tier 1: ISRC
# ---------------------------------------------------------------------------

def test_same_isrc_merges_regardless_of_title_and_duration():
    # The deluxe re-release case: label reused the ISRC. Same recording, done.
    result = cluster_tracks([
        rec("t1", "Neon Skyline", isrc="USMCK2600052"),
        rec("t2", "Neon Skyline - Deluxe Edition", isrc="USMCK2600052", duration_ms=290000),
    ])
    c = cluster_of(result, "t1")
    assert {m.track_id for m in c.members} == {"t1", "t2"}
    assert c.song_id == "USMCK2600052"  # exactly one distinct ISRC -> the ISRC
    assert all(m.method == "isrc" and m.confidence == 1.0 for m in c.members)


def test_different_isrcs_do_not_merge_on_isrc_alone():
    result = cluster_tracks([
        rec("t1", "Completely Different", isrc="ISRC1"),
        rec("t2", "Another Thing Entirely", isrc="ISRC2"),
    ])
    assert len(result.clusters) == 2


# ---------------------------------------------------------------------------
# Tier 2: linked_from
# ---------------------------------------------------------------------------

def test_linked_from_unions_the_two_ids():
    result = cluster_tracks([
        rec("t1", "Some Song", isrc="ISRC1"),
        rec("t2", "Some Song", isrc="ISRC2", linked_from_id="t1", duration_ms=290000),
    ])
    c = cluster_of(result, "t1")
    assert {m.track_id for m in c.members} == {"t1", "t2"}
    assert member_of(result, "t2").method == "linked_from"
    # Two distinct ISRCs -> deterministic hash id, never a bare Spotify id.
    assert c.song_id.startswith("song:")


def test_linked_from_to_unknown_track_is_ignored_with_warning():
    result = cluster_tracks([rec("t1", "Some Song", linked_from_id="ghost")])
    assert len(result.clusters) == 1
    assert any("ghost" in w for w in result.warnings)


# ---------------------------------------------------------------------------
# Tier 3: heuristics (normalized title + primary artist + duration gate)
# ---------------------------------------------------------------------------

def test_clean_explicit_twins_merge_and_get_kinds():
    result = cluster_tracks([
        rec("t1", "Gutter Anthem", isrc="ISRC1", explicit=True, duration_ms=201000),
        rec("t2", "Gutter Anthem", isrc="ISRC2", explicit=False, duration_ms=200000),
    ])
    c = cluster_of(result, "t1")
    assert {m.track_id for m in c.members} == {"t1", "t2"}
    assert member_of(result, "t1").kind == "explicit"
    assert member_of(result, "t2").kind == "clean"
    assert all(m.method == "heuristic" for m in c.members)
    assert c.heuristic_only


def test_remaster_suffix_merges_with_original():
    result = cluster_tracks([
        rec("t1", "Cathedral Bells - 2011 Remaster", isrc="ISRC1", duration_ms=184000),
        rec("t2", "Cathedral Bells", isrc="ISRC2", duration_ms=183000),
    ])
    c = cluster_of(result, "t1")
    assert {m.track_id for m in c.members} == {"t1", "t2"}
    assert member_of(result, "t1").kind == "remaster"
    assert member_of(result, "t2").kind == "canonical"


def test_duration_gate_blocks_same_titled_different_songs():
    # "Untitled" intro vs "Untitled" closer: same name, wildly different length.
    result = cluster_tracks([
        rec("t1", "Untitled", isrc="ISRC1", duration_ms=45000),
        rec("t2", "Untitled", isrc="ISRC2", duration_ms=45000 + DURATION_TOLERANCE_MS + 1),
    ])
    assert len(result.clusters) == 2


def test_unknown_duration_does_not_merge():
    result = cluster_tracks([
        rec("t1", "Some Song", isrc="ISRC1", duration_ms=None),
        rec("t2", "Some Song", isrc="ISRC2", duration_ms=200000),
    ])
    assert len(result.clusters) == 2


def test_different_primary_artist_blocks_heuristic_merge():
    result = cluster_tracks([
        rec("t1", "Some Song", isrc="ISRC1", artist="artA"),
        rec("t2", "Some Song", isrc="ISRC2", artist="artB"),
    ])
    assert len(result.clusters) == 2


def test_feat_credit_redundant_with_artists_still_merges():
    result = cluster_tracks([
        rec("t1", "Umbrella (feat. Jay-Z)", isrc="ISRC1"),
        rec("t2", "Umbrella", isrc="ISRC2"),
    ])
    # Both records credit only "Artist A", so the feat clause is signal -> kept.
    assert len(result.clusters) == 2

    records = [
        rec("t1", "Umbrella (feat. Jay-Z)", isrc="ISRC1"),
        rec("t2", "Umbrella", isrc="ISRC2"),
    ]
    records[0]["artist_ids"] = ["artA", "artJ"]
    records[0]["artist_names"] = ["Artist A", "Jay-Z"]
    result = cluster_tracks(records)
    assert {m.track_id for m in cluster_of(result, "t1").members} == {"t1", "t2"}


# ---------------------------------------------------------------------------
# Remixes: never merged with the parent, but REMIX_OF when resolvable
# ---------------------------------------------------------------------------

def test_remix_does_not_merge_with_parent_but_gets_remix_of_edge():
    result = cluster_tracks([
        rec("t1", "Cathedral Bells", isrc="ISRC1", duration_ms=183000),
        rec("t2", "Cathedral Bells (Nightcrawler Remix)", isrc="ISRC2", duration_ms=184500),
    ])
    assert len(result.clusters) == 2  # duration was tempting; title identity wins
    remix_cluster = cluster_of(result, "t2")
    parent_cluster = cluster_of(result, "t1")
    assert member_of(result, "t2").kind == "remix"
    assert result.remix_edges and result.remix_edges[0].remix_song_id == remix_cluster.song_id
    assert result.remix_edges[0].parent_song_id == parent_cluster.song_id


def test_remix_without_resolvable_parent_has_no_edge():
    result = cluster_tracks([
        rec("t1", "Orphan Groove (Somebody Remix)", isrc="ISRC1"),
    ])
    assert result.remix_edges == []
    assert member_of(result, "t1").kind == "remix"


def test_two_copies_of_the_same_remix_merge_together():
    result = cluster_tracks([
        rec("t1", "Song (X Remix)", isrc="ISRC1"),
        rec("t2", "Song (X Remix)", isrc="ISRC2"),
        rec("t3", "Song", isrc="ISRC3"),
    ])
    assert {m.track_id for m in cluster_of(result, "t1").members} == {"t1", "t2"}
    assert len(result.remix_edges) == 1  # deduped, one edge to the parent


# ---------------------------------------------------------------------------
# Tier 4: manual overrides win
# ---------------------------------------------------------------------------

def test_merge_override_forces_a_cluster():
    result = cluster_tracks(
        [
            rec("t1", "Totally Different A", isrc="ISRC1"),
            rec("t2", "Totally Different B", isrc="ISRC2"),
        ],
        overrides=Overrides(merges=[["t1", "t2"]]),
    )
    c = cluster_of(result, "t1")
    assert {m.track_id for m in c.members} == {"t1", "t2"}
    assert all(m.method == "manual" and m.confidence == 1.0 for m in c.members)


def test_split_override_tears_tracks_out():
    # Heuristics would merge these twins; the override says they're different.
    result = cluster_tracks(
        [
            rec("t1", "Same Title", isrc="ISRC1", duration_ms=200000),
            rec("t2", "Same Title", isrc="ISRC2", duration_ms=200500),
        ],
        overrides=Overrides(splits=[["t2"]]),
    )
    assert len(result.clusters) == 2
    assert member_of(result, "t2").method == "manual"


def test_override_with_unknown_ids_warns_and_continues():
    result = cluster_tracks(
        [rec("t1", "A Song", isrc="ISRC1")],
        overrides=Overrides(merges=[["t1", "missing"]], splits=[["also-missing"]]),
    )
    assert len(result.clusters) == 1
    assert sum("ignored" in w for w in result.warnings) == 2


# ---------------------------------------------------------------------------
# Song identity, determinism, shapes
# ---------------------------------------------------------------------------

def test_singleton_with_isrc_uses_the_isrc_as_song_id():
    result = cluster_tracks([rec("t1", "Loner", isrc="USXYZ1234567")])
    c = result.clusters[0]
    assert c.song_id == "USXYZ1234567"
    assert c.members[0].method == "isrc"
    assert c.members[0].kind == "canonical"
    assert c.members[0].confidence == 1.0


def test_singleton_without_isrc_hashes_never_a_bare_spotify_id():
    result = cluster_tracks([rec("t1", "Loner", isrc=None)])
    assert result.clusters[0].song_id.startswith("song:")
    assert "t1" not in result.clusters[0].song_id


def test_song_id_is_stable_under_member_order():
    members_a = cluster_tracks([
        rec("t1", "Twin", isrc="ISRC1"),
        rec("t2", "Twin", isrc="ISRC2"),
    ]).clusters[0].song_id
    members_b = cluster_tracks([
        rec("t2", "Twin", isrc="ISRC2"),
        rec("t1", "Twin", isrc="ISRC1"),
    ]).clusters[0].song_id
    assert members_a == members_b


def test_compute_song_id_rules():
    from application.mastering.cluster import Member

    def m(tid, isrc):
        return Member(track_id=tid, kind="canonical", method="heuristic",
                      confidence=0.85, isrc=isrc)

    # Exactly one DISTINCT ISRC -> the ISRC, even when a member lacks one
    # (the cluster's recording identity is known; a later backfill that
    # confirms the same ISRC keeps the Song id stable).
    assert compute_song_id([m("t1", "ISRC1"), m("t2", None)]) == "ISRC1"
    # Two distinct ISRCs -> deterministic hash over ISRCs + isrc-less ids.
    hashed = compute_song_id([m("t1", "ISRC1"), m("t2", "ISRC2"), m("t3", None)])
    assert hashed.startswith("song:")
    assert hashed == compute_song_id([m("t3", None), m("t2", "ISRC2"), m("t1", "ISRC1")])


def test_every_track_lands_in_exactly_one_cluster():
    records = [
        rec("t1", "Gutter Anthem", isrc="I1", explicit=True, duration_ms=201000),
        rec("t2", "Gutter Anthem", isrc="I2", explicit=False),
        rec("t3", "Unrelated", isrc="I3"),
        rec("t4", "Cathedral Bells (Nightcrawler Remix)", isrc="I4"),
    ]
    result = cluster_tracks(records)
    seen = [m.track_id for c in result.clusters for m in c.members]
    assert sorted(seen) == ["t1", "t2", "t3", "t4"]


def test_result_is_deterministic_and_idempotent():
    records = [
        rec("t1", "Gutter Anthem", isrc="I1", explicit=True, duration_ms=201000),
        rec("t2", "Gutter Anthem", isrc="I2", explicit=False),
        rec("t3", "Neon Skyline", isrc="SHARED"),
        rec("t4", "Neon Skyline - Deluxe Edition", isrc="SHARED"),
    ]
    a = cluster_tracks(records)
    b = cluster_tracks(list(reversed(records)))
    assert [c.song_id for c in a.clusters] == [c.song_id for c in b.clusters]
    assert [[m.track_id for m in c.members] for c in a.clusters] == \
           [[m.track_id for m in c.members] for c in b.clusters]


def test_title_prefers_least_decorated_name():
    result = cluster_tracks([
        rec("t1", "Neon Skyline - Deluxe Edition", isrc="SHARED"),
        rec("t2", "Neon Skyline", isrc="SHARED"),
    ])
    assert result.clusters[0].title == "Neon Skyline"


def test_duration_spread_reported():
    result = cluster_tracks([
        rec("t1", "Twin", isrc="SHARED", duration_ms=200000),
        rec("t2", "Twin", isrc="SHARED", duration_ms=202500),
    ])
    assert result.clusters[0].duration_spread_ms == 2500


# ---------------------------------------------------------------------------
# API-shape conversion
# ---------------------------------------------------------------------------

def test_track_record_from_api(make):
    track = make.track(1, isrc="USTST0000001", linked_from_id="trk0")
    record = track_record_from_api(track)
    assert record["id"] == "trk1"
    assert record["isrc"] == "USTST0000001"
    assert record["linked_from_id"] == "trk0"
    assert record["duration_ms"] == 200000
    assert record["artist_ids"] == ["art1"]
    assert record["artist_names"] == ["Artist 1"]


def test_track_record_from_api_tolerates_missing_fields(make):
    track = make.track(2, isrc="")  # no external_ids at all
    record = track_record_from_api(track)
    assert record["isrc"] is None
    assert record["linked_from_id"] is None
