"""One-off probe: do the now-'removed' batch endpoints still work for this app?

Reads the live token + real IDs from saved crawl data, then compares a
single-resource call (control) against the batch variants.
NOT part of the application; safe to delete.
"""
import json
import glob
import textwrap
from pathlib import Path

import requests

ROOT = Path(__file__).absolute().parents[2]  # repo root (this file lives in scripts/probes/)
TOKEN = (ROOT / "secrets" / "spotify_api_token.secret").read_text().strip()

def ids_from_liked(n=3):
    f = sorted(glob.glob(str(ROOT / "data/responses/liked_songs/**/*.json"), recursive=True))[0]
    items = json.loads(Path(f).read_text())["items"]
    return [it["track"]["id"] for it in items[:n]]

def ids_from_dir(subdir, n=3):
    out = []
    for f in sorted(glob.glob(str(ROOT / f"data/responses/{subdir}/*.json")))[:n]:
        obj = json.loads(Path(f).read_text())
        if "id" in obj:
            out.append(obj["id"])
    return out

track_ids = ids_from_liked(3)
artist_ids = ids_from_dir("artists", 3)
album_ids = ids_from_dir("albums", 3)

print(f"token length: {len(TOKEN)} chars")
print(f"track_ids:  {track_ids}")
print(f"artist_ids: {artist_ids}")
print(f"album_ids:  {album_ids}")
print("=" * 70)

H = {"Authorization": f"Bearer {TOKEN}"}

def probe(label, url):
    try:
        r = requests.get(url, headers=H, timeout=20)
    except Exception as e:
        print(f"[{label}] EXCEPTION: {e}\n")
        return
    body = r.text
    snippet = textwrap.shorten(body.replace("\n", " "), width=280)
    print(f"[{label}] {url}")
    print(f"    -> HTTP {r.status_code}")
    print(f"    -> {snippet}\n")

# Control: does the token work at all, on a surviving single-resource endpoint?
if track_ids:
    probe("CONTROL single /v1/tracks/{id}",
          f"https://api.spotify.com/v1/tracks/{track_ids[0]}")

# The batch endpoints the Feb-2026 changelog lists as removed:
if track_ids:
    probe("BATCH /v1/tracks?ids=",
          "https://api.spotify.com/v1/tracks?ids=" + ",".join(track_ids))
if artist_ids:
    probe("BATCH /v1/artists?ids=",
          "https://api.spotify.com/v1/artists?ids=" + ",".join(artist_ids))
if album_ids:
    probe("BATCH /v1/albums?ids=",
          "https://api.spotify.com/v1/albums?ids=" + ",".join(album_ids))
