"""End-to-end tests for the adjacent-artist discovery crawl (plan 01 T8),
against the mock Spotify service.

The full-crawl test drives the pipeline synchronously: the real
SpotifyRequestFactory publishes into a local in-test queue instead of RabbitMQ
(so the real Redis dedup choke point still runs), and the test consumes
messages exactly like api_call_engine does — GET the URL, re-queue `next` at
the same depth, then dispatch the response through the real handler classes
for write_to_neo4j + follow_links. Needs the mock, Neo4j, and Redis (each
fixture skips when its service isn't reachable).

Mock catalog literals are mirrored here on purpose (the tests container
doesn't mount mock_spotify/, and drift fails loudly): 15 liked artists
art000000..art000014, discography albums dal..., their tracks dtk..., and 5
frontier collaborators fra000000..fra000004 that exist nowhere else.
"""
from collections import deque
from json import loads
import re

import pytest
import requests

from application.config import APPLICATION_DIR
from application.requests_factory import SpotifyRequestFactory
from application.response_handlers import (
    GetSeveralArtistsResponseHandler,
    GetTracksOfAlbumResponseHandler,
    LikedSongsPlaylistResponseHandler,
)
from application.response_handlers.main import SpotifyResponseController

DISCOVERY_QUERIES_DIR = APPLICATION_DIR / "graph_database" / "queries" / "discovery"

N_MOCK_ARTISTS = 15
MOCK_ARTIST_IDS = [f"art{i:06d}" for i in range(N_MOCK_ARTISTS)]
FRONTIER_ARTIST_IDS = [f"fra{i:06d}" for i in range(5)]

# Every node the mock catalog can produce, precisely (6-digit functional ids),
# so purging can't touch real data in a shared graph.
PURGE_MOCK_NODES = (
    "MATCH (n) WHERE n.uri =~ "
    "'spotify:(track:(trk|dtk)|album:(alb|dal)|artist:(art|fra))[0-9]{6}' "
    "DETACH DELETE n"
)
PURGE_MOCK_GENRES = "MATCH (g:Genre) WHERE g.name =~ 'genre-[0-9]' DETACH DELETE g"
# plan 06: the liked-songs seeding writes a (:User {id: 'mockuser'}) anchor
PURGE_MOCK_USERS = "MATCH (u:User) WHERE u.id IN ['mockuser', 'mockuser2'] DETACH DELETE u"

FLAG = "application.response_handlers.albums.several_albums.CRAWL_ARTIST_DISCOGRAPHIES"


# ---------------------------------------------------------------------------
# mock service: the new discography routes (no Neo4j needed)
# ---------------------------------------------------------------------------

def test_mock_artist_albums_paginates_with_self_referential_next(mock_base):
    seen, url = 0, f"{mock_base}/v1/artists/art000000/albums?include_groups=album,single&limit=50"
    pages = 0
    while url:
        page = requests.get(url).json()
        pages += 1
        seen += len(page["items"])
        assert page["href"].startswith(mock_base)
        url = page["next"]
        if url:
            assert url.startswith(mock_base)  # self-referential, stays on the mock
    assert pages >= 2  # artist 0's discography paginates past limit=50
    assert seen == page["total"]


def test_mock_artist_albums_returns_simplified_objects(mock_base):
    page = requests.get(f"{mock_base}/v1/artists/art000001/albums?limit=50").json()
    assert page["items"]
    # No embedded track lists on the list route (matching the real API): a
    # handler must batch-fetch the full albums to see tracks.
    assert all("tracks" not in album for album in page["items"])


def test_mock_unknown_artist_albums_is_404(mock_base):
    assert requests.get(f"{mock_base}/v1/artists/does-not-exist/albums").status_code == 404


def test_mock_batch_albums_embed_tracks_with_frontier_credits(mock_base):
    albums = requests.get(f"{mock_base}/v1/albums?ids=dal000000,dal003001").json()["albums"]
    assert all(albums)
    for album in albums:
        credits = {
            artist["id"] for track in album["tracks"]["items"] for artist in track["artists"]
        }
        assert any(artist_id.startswith("fra") for artist_id in credits)  # the collab track


def test_mock_frontier_artists_resolve_enriched_and_are_absent_from_liked_pages(mock_base):
    artists = requests.get(
        f"{mock_base}/v1/artists?ids={','.join(FRONTIER_ARTIST_IDS)}"
    ).json()["artists"]
    assert all(artists)
    assert all(a["popularity"] is not None and a["followers"]["total"] is not None for a in artists)

    # The frontier property: crawl every liked page and confirm no frontier id
    # is reachable there (they exist ONLY via discography collab credits).
    liked_credit_ids, url = set(), f"{mock_base}/v1/me/tracks?offset=0&limit=50"
    while url:
        page = requests.get(url).json()
        for item in page["items"]:
            track = item["track"]
            liked_credit_ids |= {a["id"] for a in track["artists"]}
            liked_credit_ids |= {a["id"] for a in track["album"]["artists"]}
        url = page["next"]
    assert not any(artist_id.startswith("fra") for artist_id in liked_credit_ids)


def test_mock_album_tracks_route_paginates(mock_base):
    page = requests.get(f"{mock_base}/v1/albums/dal000000/tracks?offset=0&limit=2").json()
    assert page["total"] == 4 and len(page["items"]) == 2
    tail = requests.get(page["next"]).json()
    assert len(tail["items"]) == 2 and tail["next"] is None


# ---------------------------------------------------------------------------
# Neo4j write layer (skips when Neo4j isn't reachable)
# ---------------------------------------------------------------------------

@pytest.fixture
def graph(neo4j_driver):
    """Purge this module's marked + mock-catalog-shaped nodes before/after."""
    def purge():
        neo4j_driver.execute_query("MATCH (n) WHERE n.uri CONTAINS 'DISCTEST' DETACH DELETE n")
        neo4j_driver.execute_query(PURGE_MOCK_NODES)
        neo4j_driver.execute_query(PURGE_MOCK_GENRES)
        neo4j_driver.execute_query(PURGE_MOCK_USERS)
    purge()
    yield neo4j_driver
    purge()


def test_artist_insert_persists_and_refreshes_popularity(graph, make):
    def stored():
        recs, _, _ = graph.execute_query(
            "MATCH (a:Artist {uri: $uri}) RETURN a.popularity AS pop, a.followers AS followers",
            uri="spotify:artist:DISCTEST1")
        return recs[0]["pop"], recs[0]["followers"]

    artist = make.artist("DISCTEST1", popularity=41, followers=1234)
    GetSeveralArtistsResponseHandler(None, 0, {"artists": [artist]}).write_to_neo4j(driver=graph)
    assert stored() == (41, 1234)

    # A payload WITHOUT the fields (simplified object) must not erase them.
    bare = make.artist("DISCTEST1", popularity="", followers="")
    GetSeveralArtistsResponseHandler(None, 0, {"artists": [bare]}).write_to_neo4j(driver=graph)
    assert stored() == (41, 1234)

    # A payload WITH fresh values refreshes them (the backfill path).
    refreshed = make.artist("DISCTEST1", popularity=64, followers=9999)
    GetSeveralArtistsResponseHandler(None, 0, {"artists": [refreshed]}).write_to_neo4j(driver=graph)
    assert stored() == (64, 9999)


def test_tracks_of_album_page_writes_tracks_and_frontier_stubs(mock_base, graph):
    url = f"{mock_base}/v1/albums/dal000000/tracks?offset=0&limit=50"
    page = requests.get(url).json()
    GetTracksOfAlbumResponseHandler(url, 1, page).write_to_neo4j(driver=graph)

    recs, _, _ = graph.execute_query(
        "MATCH (al:Album {uri: 'spotify:album:dal000000'})-[:CONTAINS]->(t:Track) "
        "RETURN count(t) AS tracks, al.crawl_source AS src")
    assert recs[0]["tracks"] == 4
    assert recs[0]["src"] == "discography"  # album stub tolerates out-of-order arrival

    # The collab track's frontier credit exists as a stub with provenance.
    recs, _, _ = graph.execute_query(
        "MATCH (a:Artist {id: 'fra000000'})-[:CREATED]->(t:Track) "
        "RETURN a.crawl_source AS src, a.liked_songs AS liked, count(t) AS c")
    assert recs and recs[0]["src"] == "discography" and recs[0]["liked"] is None
    assert recs[0]["c"] >= 1


# ---------------------------------------------------------------------------
# The full discography crawl (mock + Neo4j + Redis)
# ---------------------------------------------------------------------------

@pytest.fixture
def crawl(mock_base, graph, redis_client, monkeypatch):
    """A synchronous crawl driver wired to the mock: real request factory +
    real Redis dedup, local queue instead of RabbitMQ."""
    from application.cache.redis_client import reset_crawled_set

    queue = deque()
    requested = []

    monkeypatch.setattr(
        "application.requests_factory.connect_to_rabbitmq_exchange",
        lambda exchange_name, exchange_type: (None, None),
    )
    monkeypatch.setattr(
        "application.requests_factory.publish_message_to_exchange",
        lambda channel, exchange, routing_key, body: queue.append(loads(body)),
    )
    monkeypatch.setattr("application.requests_factory.SPOTIFY_API_BASE_URL", mock_base)
    monkeypatch.setattr(FLAG, True)  # the discography crawl kind is ON

    reset_crawled_set()

    def drive(max_steps=400):
        """Consume the queue like api_call_engine until the crawl terminates."""
        steps = 0
        while queue:
            steps += 1
            assert steps <= max_steps, "crawl did not terminate (unbounded recursion?)"
            message = queue.popleft()
            url, depth = message["request_url"], message["depth_of_search"]
            requested.append(url)

            response = requests.get(url)
            assert response.status_code == 200, f"HTTP {response.status_code} for {url}"
            payload = response.json()

            # the engine re-queues pagination at the SAME depth
            if payload.get("next"):
                SpotifyRequestFactory.request_url(payload["next"], depth_of_search=depth)

            handler_class = SpotifyResponseController.resolve_handler(url)
            handler = handler_class(url, depth, payload)
            handler.write_to_neo4j(driver=graph)
            handler.follow_links()
        return steps

    return type("CrawlEnv", (), {
        "queue": queue, "requested": requested, "drive": staticmethod(drive),
        "graph": graph, "mock_base": mock_base,
    })


def _seed_liked_songs(mock_base, graph):
    """Write the mock liked-songs catalog to Neo4j (the affinity source).
    Seeded WITH a user (plan 06): 'liked' is now the (:User)-[:LIKED]
    relationship the seed worklist query traverses."""
    url = f"{mock_base}/v1/me/tracks?offset=0&limit=50"
    while url:
        page = requests.get(url).json()
        LikedSongsPlaylistResponseHandler(
            url, 0, page, user_id="mockuser"
        ).write_to_neo4j(driver=graph)
        url = page["next"]


def _seed_url(mock_base, artist_id):
    return f"{mock_base}/v1/artists/{artist_id}/albums?include_groups=album,single&limit=50"


def test_discography_crawl_enriches_frontier_without_recursion(crawl):
    _seed_liked_songs(crawl.mock_base, crawl.graph)

    # --- the seeder's worklist query finds the liked artists (T4) ---
    with open(DISCOVERY_QUERIES_DIR / "fetch_discography_seed_artist_ids.cypher") as f:
        worklist_query = f.read()
    # user_id=None -> 'any user' (the legacy factory default)
    records, _, _ = crawl.graph.execute_query(worklist_query, affinity_min=3, user_id=None)
    worklist = [record["id"] for record in records]
    assert set(MOCK_ARTIST_IDS) <= set(worklist)

    # --- seed + run (seed URLs published through the real dedup choke point;
    # the production seeder is worklist-query + request_url, both under test —
    # it isn't invoked directly because a shared graph may hold non-mock
    # artists whose ids the mock can't resolve) ---
    published = [
        SpotifyRequestFactory.request_url(
            _seed_url(crawl.mock_base, artist_id),
            depth_of_search=SpotifyRequestFactory.DISCOGRAPHY_SEED_DEPTH,
        )
        for artist_id in MOCK_ARTIST_IDS
    ]
    assert all(published)
    crawl.drive()

    # --- frontier artists exist, enriched, with no liked provenance (T8) ---
    recs, _, _ = crawl.graph.execute_query(
        "MATCH (a:Artist) WHERE a.id IN $ids "
        "RETURN a.id AS id, a.popularity AS pop, a.followers AS followers, "
        "a.liked_songs AS liked, a.crawl_source AS src ORDER BY id",
        ids=FRONTIER_ARTIST_IDS)
    assert [r["id"] for r in recs] == FRONTIER_ARTIST_IDS
    assert all(r["pop"] is not None and r["followers"] is not None for r in recs)
    assert all(r["liked"] is None for r in recs)          # never a liked-songs artist
    assert all(r["src"] == "discography" for r in recs)   # provenance tag

    # ...and they're CONNECTED: collab tracks bridge them to liked artists.
    recs, _, _ = crawl.graph.execute_query(
        "MATCH (f:Artist {id: 'fra000000'})-[:CREATED]->(t:Track)<-[:CREATED]-(m:Artist) "
        "WHERE m.id STARTS WITH 'art' RETURN count(DISTINCT m) AS bridges")
    assert recs[0]["bridges"] >= 2

    # --- liked artists got their popularity refreshed by the sweep (T2) ---
    recs, _, _ = crawl.graph.execute_query(
        "MATCH (a:Artist {id: 'art000003'}) RETURN a.popularity AS pop")
    assert recs[0]["pop"] == 63  # 60 + 3, the mock's deterministic value

    # --- no recursion: the only discography lists ever requested are the
    # seeds (frontier artists' own discographies are depth-3 territory) ---
    listed_artists = {
        match.group(1)
        for url in crawl.requested
        if (match := re.search(r"/v1/artists/([^/?]+)/albums", url))
    }
    assert listed_artists == set(MOCK_ARTIST_IDS)

    # --- the crawl's writes satisfy the deliverable ranking query (T10) ---
    with open(DISCOVERY_QUERIES_DIR / "adjacent_artist_discovery.cypher") as f:
        pack = [q.strip() for q in f.read().split(";") if q.strip()]
    affinity_query, track_altitude_query = pack[0], pack[1]

    recs, _, _ = crawl.graph.execute_query(
        track_altitude_query, max_popularity=40, min_bridges=2)
    frontier_rows = [r for r in recs if r["artist"].startswith("Frontier Collaborator")]
    assert frontier_rows, "the ranked frontier must surface the mock's collaborators"
    assert all(r["bridges"] >= 2 and r["popularity"] <= 40 for r in frontier_rows)
    assert all(r["via"] for r in frontier_rows)  # explainability: bridged via whom

    recs, _, _ = crawl.graph.execute_query(affinity_query)
    counts = [r["qualifying_artists"] for r in recs]
    assert len(counts) == 20 and counts == sorted(counts, reverse=True)

    # --- frontier artists never qualify as seeds themselves (T4 gating) ---
    # user_id=None -> 'any user' (the legacy factory default)
    records, _, _ = crawl.graph.execute_query(worklist_query, affinity_min=3, user_id=None)
    assert not any(record["id"].startswith("fra") for record in records)

    # --- dedup: a second run re-publishes nothing (T8) ---
    republished = [
        SpotifyRequestFactory.request_url(
            _seed_url(crawl.mock_base, artist_id),
            depth_of_search=SpotifyRequestFactory.DISCOGRAPHY_SEED_DEPTH,
        )
        for artist_id in MOCK_ARTIST_IDS
    ]
    assert not any(republished)
    assert not crawl.queue  # nothing even entered the queue
