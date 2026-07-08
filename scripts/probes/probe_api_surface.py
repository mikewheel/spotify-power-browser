"""One-off probe: which parts of the Spotify API surface does THIS app retain?

Spotify's 2024-11-27 change removed several endpoints for NEW apps (related
artists, recommendations, audio features/analysis, 30s previews, algorithmic /
Spotify-owned playlists); the 2026-02 changelog then listed the batch ?ids=
endpoints for removal (postponed). Existing apps (this one dates to 2023-04)
may be grandfathered — batch access was live-verified 2026-07-06. This probes
the rest of the surface the docs/plans/ feature plans depend on.

Runs inside the app image (Neo4j driver + requests), pulling real IDs from the
graph. Expected 403s on /me/player/* and /me/top/* are SCOPE gaps (the app's
token lacks those scopes today), not endpoint removals — the plans distinguish
the two. NOT part of the application; safe to delete.

    [ -f .env ] && set -a && . ./.env && set +a   # pick up a worktree's IMAGE_TAG
    docker run --rm --add-host host.docker.internal:host-gateway \
      -e NEO4J_HOSTNAME=host.docker.internal -e PYTHONPATH=/src -w /src \
      -v "$PWD/secrets:/src/secrets" -v "$PWD:/probe" \
      spotify-power-browser:${IMAGE_TAG:-latest} python3 /probe/scripts/probes/probe_api_surface.py
"""
import textwrap
import requests

from application.config import SECRETS_DIR
from application.graph_database.connect import connect_to_neo4j

TOKEN = (SECRETS_DIR / "spotify_api_token.secret").read_text().strip()
H = {"Authorization": f"Bearer {TOKEN}"}
API = "https://api.spotify.com"


def ids(label, n=3):
    d = connect_to_neo4j(SECRETS_DIR / "neo4j_credentials.yaml")
    rows, _, _ = d.execute_query(
        f"MATCH (n:{label}) WHERE n.id IS NOT NULL RETURN n.id AS id LIMIT {n}"
    )
    d.close()
    return [r["id"] for r in rows]


def probe(label, url):
    try:
        r = requests.get(url, headers=H, timeout=20)
    except Exception as e:
        print(f"[{label}] EXCEPTION: {e}\n")
        return None
    snippet = textwrap.shorten(r.text.replace("\n", " "), width=200)
    print(f"[{label}] -> HTTP {r.status_code}\n    {url}\n    {snippet}\n")
    return r.status_code


track_ids = ids("Track")
artist_ids = ids("Artist")

print(f"token: {len(TOKEN)} chars | tracks {track_ids} | artists {artist_ids}")
print("=" * 72)

results = {}
# Control + identity
results["control /v1/me"] = probe("control /v1/me", f"{API}/v1/me")
results["control single track"] = probe(
    "control single track", f"{API}/v1/tracks/{track_ids[0]}")

# 2024-11 removals (for new apps) — is this app grandfathered?
results["related-artists"] = probe(
    "related-artists", f"{API}/v1/artists/{artist_ids[0]}/related-artists")
results["recommendations"] = probe(
    "recommendations",
    f"{API}/v1/recommendations?seed_artists={artist_ids[0]}&limit=5")
results["audio-features (single)"] = probe(
    "audio-features (single)", f"{API}/v1/audio-features/{track_ids[0]}")
results["audio-features (batch)"] = probe(
    "audio-features (batch)",
    f"{API}/v1/audio-features?ids=" + ",".join(track_ids))
results["audio-analysis"] = probe(
    "audio-analysis", f"{API}/v1/audio-analysis/{track_ids[0]}")

# Discography + search (never deprecated; sanity checks for the plans)
results["artist albums"] = probe(
    "artist albums",
    f"{API}/v1/artists/{artist_ids[0]}/albums?include_groups=album,single&limit=5")
results["search"] = probe(
    "search", f"{API}/v1/search?q=daft%20punk&type=artist&limit=1")

# Scope-gated endpoints — expect 403 (missing scope), NOT 404/410 (removal)
results["recently-played (scope?)"] = probe(
    "recently-played (scope?)", f"{API}/v1/me/player/recently-played?limit=5")
results["top tracks (scope?)"] = probe(
    "top tracks (scope?)", f"{API}/v1/me/top/tracks?limit=5")

print("=" * 72)
for k, v in results.items():
    print(f"{str(v):>5}  {k}")
