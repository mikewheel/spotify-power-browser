"""The identity ladder (plan 03) as pure functions over plain dicts — no
Neo4j, so the whole pipeline is unit-testable offline. run.py owns the graph
I/O on either side.

Input: track records, one dict per (:Track):

    {
        "id": "4uLU6...",            # Spotify track id (required)
        "name": "Cathedral Bells - 2011 Remaster",
        "isrc": "USMCK2600056" | None,
        "linked_from_id": "7GhIk..." | None,   # Spotify track relinking
        "duration_ms": 184000 | None,
        "explicit": bool,
        "artist_ids": ["art1", ...],    # first element = primary artist
        "artist_names": ["Artist 1", ...],  # for feat-clause stripping
    }

The ladder, strongest evidence first:
    1. ISRC exact groups              -> method 'isrc',        confidence 1.0
    2. Spotify linked_from unions     -> method 'linked_from', confidence 0.95
    3. Heuristic: same normalized title + same primary artist + duration
       within +/-3s, blocked on (primary_artist_id, norm_title[:8])
                                      -> method 'heuristic',   confidence 0.85
    4. Manual overrides (win)         -> method 'manual',      confidence 1.0

Song.id is platform-neutral (plan 07 compatibility): the ISRC when the cluster
has exactly one distinct ISRC, else 'song:' + sha1 of the sorted member
ISRCs/track-ids. Never a bare Spotify id.

Stances (documented per the plan's open questions):
- Re-recordings ("Taylor's Version") differ in ISRC and usually duration, so
  they land as separate Songs, each kind 'canonical'. Deliberate.
- The graph supplies artist_ids from t.artist_ids — the performing artists in
  credit order, persisted by the insert Cyphers. Legacy nodes without that
  field fall back to sorted CREATED-edge ids (unordered and polluted by album
  artists), a weaker primary proxy until the ISRC backfill refreshes them.
"""
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from hashlib import sha1

from application.mastering.normalize import normalize
from application.mastering.overrides import Overrides

# Heuristic duration gate: variants of one recording sit within a few seconds;
# same-titled *different* songs (intros, interludes, "Untitled") usually don't.
DURATION_TOLERANCE_MS = 3000

CONFIDENCE = {"isrc": 1.0, "linked_from": 0.95, "heuristic": 0.85, "manual": 1.0}

# Blocking-key title prefix length (keeps heuristic comparisons local).
_BLOCK_PREFIX = 8


@dataclass(frozen=True)
class Member:
    track_id: str
    kind: str          # canonical | remaster | live | ... | clean | explicit | remix
    method: str        # isrc | linked_from | heuristic | manual
    confidence: float
    isrc: str = None
    name: str = None
    duration_ms: int = None


@dataclass(frozen=True)
class SongCluster:
    song_id: str
    title: str
    members: tuple
    heuristic_only: bool      # >1 member and nothing stronger than heuristics
    duration_spread_ms: int   # max - min member duration (0 when unknown)


@dataclass(frozen=True)
class RemixEdge:
    remix_song_id: str
    parent_song_id: str
    confidence: float


@dataclass
class MasteringResult:
    clusters: list = field(default_factory=list)
    remix_edges: list = field(default_factory=list)
    warnings: list = field(default_factory=list)

    @property
    def multi_member_clusters(self):
        return [c for c in self.clusters if len(c.members) > 1]


class _UnionFind:
    def __init__(self, ids):
        self.parent = {i: i for i in ids}

    def find(self, i):
        root = i
        while self.parent[root] != root:
            root = self.parent[root]
        while self.parent[i] != root:  # path compression
            self.parent[i], i = root, self.parent[i]
        return root

    def union(self, a, b):
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            # Deterministic: smaller id becomes the root.
            lo, hi = sorted((ra, rb))
            self.parent[hi] = lo


def track_record_from_api(track):
    """Convert a full Spotify track object (API/mock shape) into the plain
    record cluster_tracks() consumes."""
    return {
        "id": track["id"],
        "name": track.get("name"),
        "isrc": (track.get("external_ids") or {}).get("isrc"),
        "linked_from_id": (track.get("linked_from") or {}).get("id"),
        "duration_ms": track.get("duration_ms"),
        "explicit": bool(track.get("explicit")),
        "artist_ids": [a["id"] for a in track.get("artists") or []],
        "artist_names": [a.get("name") for a in track.get("artists") or []],
    }


def compute_song_id(members):
    """The ISRC when the cluster has exactly one distinct ISRC; otherwise a
    deterministic hash of the members. Never a bare Spotify id."""
    isrcs = sorted({m.isrc for m in members if m.isrc})
    if len(isrcs) == 1:
        return isrcs[0]
    keys = sorted(m.isrc or m.track_id for m in members)
    return "song:" + sha1("|".join(keys).encode("utf-8")).hexdigest()


def _primary_artist(record):
    artist_ids = record.get("artist_ids") or []
    return artist_ids[0] if artist_ids else None


def cluster_tracks(records, overrides=None):
    """Run the identity ladder over track records. Pure and deterministic:
    the same input (in any order) yields the same MasteringResult."""
    overrides = overrides or Overrides()
    result = MasteringResult()

    by_id = {}
    for record in records:
        if record["id"] in by_id:
            result.warnings.append(f"Duplicate track record for id {record['id']}; keeping the first.")
            continue
        by_id[record["id"]] = record

    norms = {
        tid: normalize(rec.get("name"), rec.get("artist_names") or ())
        for tid, rec in by_id.items()
    }

    uf = _UnionFind(sorted(by_id))
    linked_ids = set()

    # --- 1. ISRC exact groups --------------------------------------------
    by_isrc = defaultdict(list)
    for tid in sorted(by_id):
        isrc = by_id[tid].get("isrc")
        if isrc:
            by_isrc[isrc].append(tid)
    for group in by_isrc.values():
        for other in group[1:]:
            uf.union(group[0], other)

    # --- 2. linked_from unions -------------------------------------------
    for tid in sorted(by_id):
        target = by_id[tid].get("linked_from_id")
        if not target:
            continue
        if target in by_id:
            uf.union(tid, target)
            linked_ids.update((tid, target))
        else:
            result.warnings.append(
                f"Track {tid} links from {target}, which is not in the graph; ignored."
            )

    # --- 3. Heuristic pass, blocked to keep comparisons local -------------
    blocks = defaultdict(list)
    for tid in sorted(by_id):
        primary = _primary_artist(by_id[tid])
        text = norms[tid].text
        if primary and text:
            blocks[(primary, text[:_BLOCK_PREFIX])].append(tid)
    for block in blocks.values():
        exact = defaultdict(list)
        for tid in block:
            exact[norms[tid].text].append(tid)
        for group in exact.values():
            if len(group) < 2:
                continue
            # Sort by duration and chain-union neighbors within tolerance, so
            # a pathological far pair never merges directly (only via a chain,
            # which the review report's duration-spread metric surfaces).
            group = sorted(group, key=lambda t: (by_id[t].get("duration_ms") or 0, t))
            for a, b in zip(group, group[1:]):
                da, db = by_id[a].get("duration_ms"), by_id[b].get("duration_ms")
                # Unknown durations do NOT merge — the gate is the only thing
                # separating same-titled different songs, so stay conservative.
                if da is not None and db is not None and abs(da - db) <= DURATION_TOLERANCE_MS:
                    uf.union(a, b)

    # --- 4. Manual overrides last (they win) ------------------------------
    manual_ids = set()
    for group in overrides.merges:
        known = [t for t in group if t in by_id]
        for missing in set(group) - set(known):
            result.warnings.append(f"Merge override references unknown track {missing}; ignored.")
        for other in known[1:]:
            uf.union(known[0], other)
        manual_ids.update(known)

    clusters_by_root = defaultdict(list)
    for tid in by_id:
        clusters_by_root[uf.find(tid)].append(tid)
    groups = [sorted(g) for g in clusters_by_root.values()]

    # Splits tear their tracks out into a Song of their own (group stays whole).
    for split_group in overrides.splits:
        known = sorted(t for t in split_group if t in by_id)
        for missing in set(split_group) - set(known):
            result.warnings.append(f"Split override references unknown track {missing}; ignored.")
        if not known:
            continue
        known_set = set(known)
        groups = [[t for t in g if t not in known_set] for g in groups]
        groups.append(known)
        manual_ids.update(known)
    # Deterministic regardless of input order: sort groups by first member.
    groups = sorted([g for g in groups if g], key=lambda g: g[0])

    # --- Build SongClusters ------------------------------------------------
    clusters = []
    parent_lookup = {}   # (primary_artist_id, base normalized text) -> song_id
    remix_members = []   # (song_id, primary_artist_id, base_text)

    for group in groups:
        group_records = [by_id[t] for t in group]
        isrc_counts = Counter(r["isrc"] for r in group_records if r.get("isrc"))
        linked_in_group = {
            t for t in group
            if t in linked_ids and (
                by_id[t].get("linked_from_id") in group
                or any(by_id[o].get("linked_from_id") == t for o in group)
            )
        }

        # Do explicit/clean twins coexist among the undecorated members?
        canonical_explicit_flags = {
            bool(by_id[t].get("explicit"))
            for t in group
            if norms[t].kind == "canonical"
        }
        has_explicit_twins = len(canonical_explicit_flags) > 1

        members = []
        for tid in group:
            record, norm = by_id[tid], norms[tid]

            if tid in manual_ids:
                method = "manual"
            elif record.get("isrc") and (isrc_counts[record["isrc"]] >= 2 or len(group) == 1):
                method = "isrc"
            elif tid in linked_in_group:
                method = "linked_from"
            else:
                method = "heuristic"
            confidence = 1.0 if len(group) == 1 else CONFIDENCE[method]

            if norm.is_remix:
                kind = "remix"
            elif norm.kind != "canonical":
                kind = norm.kind
            elif has_explicit_twins:
                kind = "explicit" if record.get("explicit") else "clean"
            else:
                kind = "canonical"

            members.append(Member(
                track_id=tid,
                kind=kind,
                method=method,
                confidence=confidence,
                isrc=record.get("isrc"),
                name=record.get("name"),
                duration_ms=record.get("duration_ms"),
            ))

        members = tuple(sorted(members, key=lambda m: m.track_id))
        song_id = compute_song_id(members)
        # Least-decorated display title: shortest original name, ties lexical.
        title = min((m.name or "" for m in members), key=lambda n: (len(n), n))
        durations = [m.duration_ms for m in members if m.duration_ms is not None]
        spread = max(durations) - min(durations) if durations else 0
        heuristic_only = len(members) > 1 and all(m.method == "heuristic" for m in members)

        clusters.append(SongCluster(
            song_id=song_id,
            title=title,
            members=members,
            heuristic_only=heuristic_only,
            duration_spread_ms=spread,
        ))

        for tid in group:
            norm = norms[tid]
            primary = _primary_artist(by_id[tid])
            if norm.is_remix:
                remix_members.append((song_id, primary, norm.base_text))
            elif primary and norm.text:
                parent_lookup.setdefault((primary, norm.text), song_id)

    # --- (:Song)-[:REMIX_OF]->(:Song) where the parent is resolvable -------
    seen_edges = set()
    for song_id, primary, base_text in remix_members:
        parent = parent_lookup.get((primary, base_text))
        if parent and parent != song_id and (song_id, parent) not in seen_edges:
            seen_edges.add((song_id, parent))
            result.remix_edges.append(RemixEdge(
                remix_song_id=song_id, parent_song_id=parent, confidence=0.9,
            ))

    result.clusters = sorted(clusters, key=lambda c: c.song_id)
    result.remix_edges.sort(key=lambda e: (e.remix_song_id, e.parent_song_id))
    return result
