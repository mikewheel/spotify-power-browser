"""End-to-end (data path): a real mock response → the real handler + Cypher →
Neo4j. Needs both the mock service and Neo4j (skips otherwise)."""
import requests

from application.response_handlers.me.my_liked_songs import LikedSongsPlaylistResponseHandler


def _all_uris(page):
    uris = set()
    for item in page["items"]:
        track = item["track"]
        uris.add(track["uri"])
        uris.add(track["album"]["uri"])
        for artist in track["album"]["artists"] + track["artists"]:
            uris.add(artist["uri"])
    return uris


def test_mock_liked_songs_page_builds_the_graph(mock_base, neo4j_driver):
    page = requests.get(f"{mock_base}/v1/me/tracks?offset=0&limit=5").json()
    uris = _all_uris(page)
    try:
        LikedSongsPlaylistResponseHandler(f"{mock_base}/v1/me/tracks", 1, page).write_to_neo4j(driver=neo4j_driver)

        # every track/album/artist the page referenced is now a node
        recs, _, _ = neo4j_driver.execute_query(
            "MATCH (n) WHERE n.uri IN $uris RETURN count(n) AS c", uris=list(uris))
        assert recs[0]["c"] == len(uris)

        # the Album-CONTAINS->Track edges exist
        track_uris = [item["track"]["uri"] for item in page["items"]]
        recs, _, _ = neo4j_driver.execute_query(
            "MATCH (:Album)-[:CONTAINS]->(t:Track) WHERE t.uri IN $u RETURN count(DISTINCT t) AS c", u=track_uris)
        assert recs[0]["c"] == len(track_uris)
    finally:
        neo4j_driver.execute_query("MATCH (n) WHERE n.uri IN $uris DETACH DELETE n", uris=list(uris))


def test_follow_links_from_a_mock_page_points_back_at_the_mock(mock_base, monkeypatch):
    page = requests.get(f"{mock_base}/v1/me/tracks?offset=0&limit=3").json()
    captured = []
    monkeypatch.setattr(
        "application.requests_factory.SpotifyRequestFactory.request_url",
        staticmethod(lambda url, depth_of_search=0, user_id=None: captured.append(url)),
    )
    LikedSongsPlaylistResponseHandler(f"{mock_base}/v1/me/tracks", 1, page).follow_links()
    assert captured  # it followed track/album/artist hrefs
    assert all(url.startswith(mock_base) for url in captured)  # self-referential, stays on the mock
