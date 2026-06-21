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
    return {
        "uri": f"spotify:track:{tid}",
        "id": tid,
        "name": f"Track {i}",
        "explicit": False,
        "is_local": False,
        "duration_ms": 200000,
        "popularity": 50,
        "type": "track",
        "href": f"{PUBLIC_BASE_URL}/v1/tracks/{tid}",
        "external_urls": {"spotify": f"https://open.spotify.com/track/{tid}"},
        "album": album(i),          # track i lives on album (i % N_ALBUMS)
        "artists": [artist(i)],     # plus its own performing artist
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
