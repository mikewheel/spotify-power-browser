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
        # Full artist objects always carry popularity + followers (plan 01
        # ranks the collab frontier by them). Liked-catalog artists are
        # deliberately mainstream next to the frontier's single digits.
        "popularity": 60 + (i % N_ARTISTS),
        "followers": {"href": None, "total": 10000 * ((i % N_ARTISTS) + 1)},
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
    # Plan 01 discography namespaces (dal / dtk / fra) live in their own
    # functional generators, appended at the end of this module.
    discovery_object = _discovery_get_by_id(resource_type, identifier)
    if discovery_object is not None:
        return discovery_object
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


###
# Adjacent-artist discovery (plan 01) — discography catalog.
#
# Three extra id namespaces, purely functional like the base catalog:
#   dal{artist:03d}{j:03d}         discography album j of liked artist {artist}
#   dtk{artist:02d}{j:02d}{k:02d}  track k on that album
#   fra{n:06d}                     a "frontier" collaborator: credited ONLY on
#                                  discography collab tracks — reachable
#                                  nowhere else in the catalog (never on liked
#                                  pages, base albums, or base tracks)
#
# Every liked artist has DISCOG_ALBUMS_PER_ARTIST albums; artist 0 has
# DISCOG_ALBUMS_ARTIST_0 (> the crawler's limit=50) so the albums-list route's
# pagination is exercised. Track FRONTIER_TRACK_INDEX of every discography
# album is a collab crediting frontier artist (artist + j) % N_FRONTIER_ARTISTS
# — sharing frontier collaborators across liked artists gives the discovery
# ranking real bridge counts (> 1) to order by.
#
# No >50-track album is generated: track-list pagination is covered by the
# albums-list route here and by unit fixtures for GetTracksOfAlbumResponseHandler
# (the mock's /v1/albums/{id}/tracks route still paginates any album on demand).
###

DISCOG_ALBUMS_PER_ARTIST = int(os.environ.get("MOCK_DISCOG_ALBUMS", "3"))
DISCOG_ALBUMS_ARTIST_0 = int(os.environ.get("MOCK_DISCOG_ALBUMS_ARTIST_0", "55"))
DISCOG_TRACKS_PER_ALBUM = 4
FRONTIER_TRACK_INDEX = 1
N_FRONTIER_ARTISTS = 5


def n_discog_albums(artist_i):
    return DISCOG_ALBUMS_ARTIST_0 if artist_i == 0 else DISCOG_ALBUMS_PER_ARTIST


def frontier_artist(n):
    """A collaborator that exists nowhere in the base catalog: deliberately
    obscure (single-digit popularity), so the discovery ranking surfaces it."""
    fid = f"fra{n % N_FRONTIER_ARTISTS:06d}"
    return {
        "uri": f"spotify:artist:{fid}",
        "id": fid,
        "name": f"Frontier Collaborator {n % N_FRONTIER_ARTISTS}",
        "external_urls": {"spotify": f"https://open.spotify.com/artist/{fid}"},
        "href": f"{PUBLIC_BASE_URL}/v1/artists/{fid}",
        "type": "artist",
        "genres": [f"genre-{n % 5}"],
        "popularity": 3 + (n % N_FRONTIER_ARTISTS),
        "followers": {"href": None, "total": 40 + 7 * (n % N_FRONTIER_ARTISTS)},
    }


def discog_track(artist_i, j, k):
    """A simplified track object (as embedded in album.tracks.items — no
    album/external_ids/popularity, matching the real API's shape there)."""
    tid = f"dtk{artist_i:02d}{j:02d}{k:02d}"
    artists = [artist(artist_i)]
    if k == FRONTIER_TRACK_INDEX:
        artists.append(frontier_artist((artist_i + j) % N_FRONTIER_ARTISTS))
    return {
        "uri": f"spotify:track:{tid}",
        "id": tid,
        "name": f"Discog Track {artist_i}-{j}-{k}",
        "explicit": False,
        "is_local": False,
        "duration_ms": 180000 + 1000 * k,
        "type": "track",
        "href": f"{PUBLIC_BASE_URL}/v1/tracks/{tid}",
        "external_urls": {"spotify": f"https://open.spotify.com/track/{tid}"},
        "disc_number": 1,
        "track_number": k + 1,
        "artists": artists,
    }


def discog_album(artist_i, j):
    """A full album object, embedded track-list paging object included (what
    GET /v1/albums?ids= returns)."""
    alid = f"dal{artist_i:03d}{j:03d}"
    tracks = [discog_track(artist_i, j, k) for k in range(DISCOG_TRACKS_PER_ALBUM)]
    return {
        "uri": f"spotify:album:{alid}",
        "id": alid,
        "name": f"Discography Album {j} of Artist {artist_i}",
        "release_date": f"20{10 + (j % 15):02d}-06-01",
        "release_date_precision": "day",
        "total_tracks": len(tracks),
        "album_type": "single" if j % 3 == 2 else "album",
        "external_urls": {"spotify": f"https://open.spotify.com/album/{alid}"},
        "href": f"{PUBLIC_BASE_URL}/v1/albums/{alid}",
        "type": "album",
        "artists": [artist(artist_i)],
        "genres": [],
        "tracks": {
            "href": f"{PUBLIC_BASE_URL}/v1/albums/{alid}/tracks?offset=0&limit=50",
            "items": tracks,
            "limit": 50,
            "offset": 0,
            "next": None,  # DISCOG_TRACKS_PER_ALBUM < 50: always one embedded page
            "total": len(tracks),
        },
    }


def _parse_discog_album_id(identifier):
    n = _n("dal", identifier)
    if n is None:
        return None
    artist_i, j = n // 1000, n % 1000
    if artist_i < N_ARTISTS and j < n_discog_albums(artist_i):
        return artist_i, j
    return None


def _parse_discog_track_id(identifier):
    n = _n("dtk", identifier)
    if n is None:
        return None
    artist_i, j, k = n // 10000, (n // 100) % 100, n % 100
    if artist_i < N_ARTISTS and j < n_discog_albums(artist_i) and k < DISCOG_TRACKS_PER_ALBUM:
        return artist_i, j, k
    return None


def _discovery_get_by_id(resource_type, identifier):
    """get_by_id's delegate for the plan-01 namespaces (None = not ours)."""
    if resource_type == "tracks":
        parsed = _parse_discog_track_id(identifier)
        if parsed is not None:
            artist_i, j, k = parsed
            # The full track object: the simplified shape plus what the real
            # single/batch track endpoints add.
            return discog_track(artist_i, j, k) | {
                "album": discog_album(artist_i, j),
                "external_ids": {"isrc": f"USMCKD{artist_i:02d}{j:02d}{k:02d}"},
                "popularity": 25,
            }
    if resource_type == "albums":
        parsed = _parse_discog_album_id(identifier)
        if parsed is not None:
            return discog_album(*parsed)
    if resource_type == "artists":
        n = _n("fra", identifier)
        if n is not None and 0 <= n < N_FRONTIER_ARTISTS:
            return frontier_artist(n)
    return None


def _paging(items_all, offset, limit, href_base, extra_params=""):
    """Slice items_all into a Spotify paging object with a self-referential
    next link (or null at the end)."""
    page_items = items_all[offset:offset + limit]
    next_offset = offset + limit
    next_url = (
        f"{href_base}?offset={next_offset}&limit={limit}{extra_params}"
        if next_offset < len(items_all) else None
    )
    return {
        "href": f"{href_base}?offset={offset}&limit={limit}{extra_params}",
        "items": page_items,
        "limit": limit,
        "offset": offset,
        "next": next_url,
        "total": len(items_all),
    }


def artist_albums_page(artist_id, offset, limit, include_groups=None):
    """A page of GET /v1/artists/{id}/albums: simplified album objects (no
    embedded tracks — the real route doesn't send them; a handler that leaned
    on them here would break live). None for an unknown artist; frontier
    artists resolve with an EMPTY discography (the crawler must never ask —
    the E2E no-recursion assertion checks requested URLs — but a stray request
    shouldn't 404 the whole crawl)."""
    n = _n("art", artist_id)
    if n is not None and 0 <= n < N_ARTISTS:
        albums = [discog_album(n, j) for j in range(n_discog_albums(n))]
    elif _n("fra", artist_id) is not None and 0 <= _n("fra", artist_id) < N_FRONTIER_ARTISTS:
        albums = []
    else:
        return None

    if include_groups:
        groups = set(include_groups.split(","))
        albums = [al for al in albums if al["album_type"] in groups]

    simplified = [
        {key: value for key, value in al.items() if key not in ("tracks", "genres")}
        | {"album_group": al["album_type"]}
        for al in albums
    ]
    extra = f"&include_groups={include_groups}" if include_groups else ""
    return _paging(
        simplified, offset, limit,
        href_base=f"{PUBLIC_BASE_URL}/v1/artists/{artist_id}/albums",
        extra_params=extra,
    )


def album_tracks_page(album_id, offset, limit):
    """A page of GET /v1/albums/{id}/tracks (simplified track objects) for ANY
    album — discography or base catalog — or None if the album is unknown."""
    parsed = _parse_discog_album_id(album_id)
    if parsed is not None:
        artist_i, j = parsed
        items_all = [discog_track(artist_i, j, k) for k in range(DISCOG_TRACKS_PER_ALBUM)]
    else:
        n = _n("alb", album_id)
        if n is None or not (0 <= n < N_ALBUMS):
            return None
        # Base-catalog membership rule: track i lives on album (i % N_ALBUMS).
        simplify_keys = (
            "uri", "id", "name", "explicit", "is_local", "duration_ms",
            "type", "href", "external_urls", "artists",
        )
        items_all = [
            {key: track(i)[key] for key in simplify_keys}
            for i in range(n, N_TRACKS, N_ALBUMS)
        ]
    return _paging(
        items_all, offset, limit,
        href_base=f"{PUBLIC_BASE_URL}/v1/albums/{album_id}/tracks",
    )
