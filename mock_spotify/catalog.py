"""A deterministic, self-consistent synthetic Spotify catalog.

Purely functional: any id reconstructs to a fixed object, so the same crawl is
reproducible and every referenced id resolves. Albums/artists are shared across
tracks (so dedup and batching actually matter). Object shapes match what the
crawler's handlers + Cypher consume (see tests/conftest.py), and all hrefs are
self-referential (point back at this mock) so the engine follows them here.
"""
import os

# How the crawler reaches this mock (and what the hrefs must point at).
PUBLIC_BASE_URL = os.environ.get("MOCK_PUBLIC_BASE_URL", "http://spotify_mock")

# Catalog size (env-tunable for scale tests).
N_TRACKS = int(os.environ.get("MOCK_N_TRACKS", "60"))
N_ALBUMS = int(os.environ.get("MOCK_N_ALBUMS", "20"))
N_ARTISTS = int(os.environ.get("MOCK_N_ARTISTS", "15"))


def _n(prefix, identifier):
    """Extract the integer suffix from an id like 'trk000007' -> 7, or None."""
    if not isinstance(identifier, str) or not identifier.startswith(prefix):
        return None
    suffix = identifier[len(prefix):]
    return int(suffix) if suffix.isdigit() else None


def _isrc(i):
    """Deterministic ISRC for track i (CC-XXX-YY-NNNNN, mock registrant MCK)."""
    return f"USMCK26{i:05d}"


# ---------------------------------------------------------------------------
# Entity-mastering variant cases (plan 03). Fixed track indices near the top of
# the default catalog (requires MOCK_N_TRACKS >= 59, default 60) whose fields
# deviate from the generated pattern so tests can exercise the identity ladder:
#
#   52/53  deluxe re-release pair -- two track ids SHARING one ISRC (labels
#          reuse the ISRC when a deluxe edition re-ships the same recording)
#   54/55  explicit/clean twins   -- different ISRCs, same title + primary
#          artist, durations within +/-3s (heuristic-tier merge)
#   56/57  remaster + original    -- different ISRCs; 56 carries the
#          " - 2011 Remaster" suffix normalize() must strip (kind: remaster)
#   58     "(Nightcrawler Remix)" -- a remix of 56/57's song that must NOT
#          merge with it (remix credits are never stripped); duration is
#          deliberately within tolerance to tempt a naive matcher
#
# All variants share primary artist 3 so the heuristic blocking key
# (primary_artist_id, normalized-title prefix) actually groups them.
# ---------------------------------------------------------------------------
VARIANTS = {
    52: {"name": "Neon Skyline", "isrc": _isrc(52), "artist_i": 3},
    53: {"name": "Neon Skyline", "isrc": _isrc(52), "artist_i": 3},
    54: {"name": "Gutter Anthem", "explicit": True, "artist_i": 3, "duration_ms": 201000},
    55: {"name": "Gutter Anthem", "explicit": False, "artist_i": 3, "duration_ms": 200000},
    56: {"name": "Cathedral Bells - 2011 Remaster", "artist_i": 3, "duration_ms": 184000},
    57: {"name": "Cathedral Bells", "artist_i": 3, "duration_ms": 183000},
    58: {"name": "Cathedral Bells (Nightcrawler Remix)", "artist_i": 3, "duration_ms": 184500},
}

# Convenience ids for tests (hit these via GET /v1/tracks?ids=...).
DELUXE_PAIR_IDS = ("trk000052", "trk000053")
CLEAN_EXPLICIT_TWIN_IDS = ("trk000054", "trk000055")
REMASTER_PAIR_IDS = ("trk000056", "trk000057")
REMIX_TRACK_ID = "trk000058"


def artist(i):
    aid = f"art{i % N_ARTISTS:06d}"
    return {
        "uri": f"spotify:artist:{aid}",
        "id": aid,
        "name": f"Artist {i % N_ARTISTS}",
        "external_urls": {"spotify": f"https://open.spotify.com/artist/{aid}"},
        "href": f"{PUBLIC_BASE_URL}/v1/artists/{aid}",
        "type": "artist",
        "genres": [f"genre-{i % 5}"],
    }


def album(i):
    alid = f"alb{i % N_ALBUMS:06d}"
    # Two artists per album, derived from the album number (shared across tracks).
    artists = [artist(i % N_ALBUMS), artist((i % N_ALBUMS) + 1)]
    return {
        "uri": f"spotify:album:{alid}",
        "id": alid,
        "name": f"Album {i % N_ALBUMS}",
        "release_date": "2020-01-01",
        "release_date_precision": "day",
        "total_tracks": 10,
        "album_type": "album",
        "external_urls": {"spotify": f"https://open.spotify.com/album/{alid}"},
        "href": f"{PUBLIC_BASE_URL}/v1/albums/{alid}",
        "type": "album",
        "artists": artists,
        "genres": [],
    }


def track(i):
    tid = f"trk{i:06d}"
    v = VARIANTS.get(i, {})
    return {
        "uri": f"spotify:track:{tid}",
        "id": tid,
        "name": v.get("name", f"Track {i}"),
        "explicit": v.get("explicit", False),
        "is_local": False,
        "duration_ms": v.get("duration_ms", 200000),
        "popularity": 50,
        "type": "track",
        "href": f"{PUBLIC_BASE_URL}/v1/tracks/{tid}",
        "external_urls": {"spotify": f"https://open.spotify.com/track/{tid}"},
        "external_ids": {"isrc": v.get("isrc", _isrc(i))},
        "album": album(i),          # track i lives on album (i % N_ALBUMS)
        # The performing artist (variants pin a shared primary artist).
        "artists": [artist(v.get("artist_i", i))],
    }


def get_by_id(resource_type, identifier):
    """Resolve a single resource by id, or None if it doesn't exist (Spotify
    returns null for unknown ids on the batch endpoints)."""
    if resource_type == "tracks":
        n = _n("trk", identifier)
        return track(n) if n is not None and 0 <= n < N_TRACKS else None
    if resource_type == "albums":
        n = _n("alb", identifier)
        return album(n) if n is not None and 0 <= n < N_ALBUMS else None
    if resource_type == "artists":
        n = _n("art", identifier)
        return artist(n) if n is not None and 0 <= n < N_ARTISTS else None
    return None


def liked_songs_page(offset, limit):
    """A page of saved tracks with a self-referential `next` link (or null)."""
    items = [
        {"added_at": "2021-01-01T00:00:00Z", "track": track(i)}
        for i in range(offset, min(offset + limit, N_TRACKS))
    ]
    next_offset = offset + limit
    next_url = (
        f"{PUBLIC_BASE_URL}/v1/me/tracks?offset={next_offset}&limit={limit}"
        if next_offset < N_TRACKS else None
    )
    return {
        "href": f"{PUBLIC_BASE_URL}/v1/me/tracks?offset={offset}&limit={limit}",
        "items": items,
        "limit": limit,
        "offset": offset,
        "next": next_url,
        "total": N_TRACKS,
    }


###
# Player state (GET /v1/me/player) — plan 04 phase B live-capture testing.
# Driven via POST /_control/config with player_* keys (app.py forwards them):
#   {"player_track_id": "trk000003", "player_progress_ms": 41000,
#    "player_is_playing": true, "player_advance": true}
# With player_advance, progress advances with wall-clock time from the moment
# of configuration — computed functionally from the elapsed time (no ticking
# state), flowing across track boundaries like an album playing through.
# player_track_id: null => no active device => 204.
###
import time  # noqa: E402  (appended section per plan 04; stdlib, safe mid-file)

_PLAYER_DEFAULTS = {
    "track_id": "trk000000",
    "progress_ms": 0,
    "is_playing": True,
    "advance": False,
}
_PLAYER = dict(_PLAYER_DEFAULTS)
_PLAYER["configured_at"] = time.time()

_PLAYER_CONTROL_KEYS = {
    "player_track_id": "track_id",
    "player_progress_ms": "progress_ms",
    "player_is_playing": "is_playing",
    "player_advance": "advance",
}


def configure_player(cfg):
    """Apply player_* keys from a /_control/config payload; ignore the rest.
    Any accepted key re-anchors the wall-clock advance origin."""
    touched = False
    for control_key, state_key in _PLAYER_CONTROL_KEYS.items():
        if control_key in cfg:
            _PLAYER[state_key] = cfg[control_key]
            touched = True
    if touched:
        _PLAYER["configured_at"] = time.time()
    return {f"player_{k}": _PLAYER[k] for k in _PLAYER_DEFAULTS}


def reset_player():
    """Back to defaults (called by POST /_control/reset)."""
    _PLAYER.update(_PLAYER_DEFAULTS)
    _PLAYER["configured_at"] = time.time()


def player_state():
    """The GET /v1/me/player payload, or None (=> 204, no active device)."""
    track_id = _PLAYER["track_id"]
    n = _n("trk", track_id) if track_id else None
    if n is None or not (0 <= n < N_TRACKS):
        return None

    progress = int(_PLAYER["progress_ms"])
    if _PLAYER["advance"] and _PLAYER["is_playing"]:
        progress += int((time.time() - _PLAYER["configured_at"]) * 1000)

    # Flow across track boundaries like an album playing through.
    current = track(n)
    while progress >= current["duration_ms"] and n + 1 < N_TRACKS:
        progress -= current["duration_ms"]
        n += 1
        current = track(n)
    progress = min(progress, current["duration_ms"])

    return {
        "device": {"id": "mock-device", "is_active": True, "name": "Mock Device", "type": "Computer"},
        "timestamp": int(time.time() * 1000),
        "is_playing": bool(_PLAYER["is_playing"]),
        "progress_ms": progress,
        "currently_playing_type": "track",
        "item": current,
    }
