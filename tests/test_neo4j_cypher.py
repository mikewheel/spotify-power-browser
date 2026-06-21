import pytest

from application.response_handlers.tracks.several_tracks import GetSeveralTracksResponseHandler


@pytest.fixture(autouse=True)
def _cleanup(neo4j_driver):
    # neo4j_driver skips the module if Neo4j isn't reachable. Remove any nodes
    # this module created (distinctive CYTEST uris) before and after each test.
    purge = "MATCH (n) WHERE n.uri CONTAINS 'CYTEST' DETACH DELETE n"
    neo4j_driver.execute_query(purge)
    yield
    neo4j_driver.execute_query(purge)


def test_batch_insert_creates_track_album_artist(neo4j_driver, make):
    artist = make.artist("CYTEST1")
    album = make.album("CYTEST1", artists=[artist])
    track = make.track("CYTEST1", album=album, artists=[artist])

    GetSeveralTracksResponseHandler(None, 0, {"tracks": [track]}).write_to_neo4j(driver=neo4j_driver)

    recs, _, _ = neo4j_driver.execute_query(
        "MATCH (t:Track {uri: $uri}) "
        "OPTIONAL MATCH (t)<-[:CONTAINS]-(al:Album) "
        "OPTIONAL MATCH (t)<-[:CREATED]-(ar:Artist) "
        "RETURN t.name AS name, al.uri AS album_uri, count(DISTINCT ar) AS artist_count",
        uri=track["uri"],
    )
    row = recs[0]
    assert row["name"] == track["name"]
    assert row["album_uri"] == album["uri"]
    assert row["artist_count"] >= 1


def test_empty_album_artists_still_links_track_artists(neo4j_driver, make):
    # Review #4: the chained-UNWIND bug dropped a track's own artists when its
    # album had no artists. The CALL-subquery fix must keep them linked.
    artist = make.artist("CYTEST2")
    album = make.album("CYTEST2", artists=[])  # pathological empty album-artists
    track = make.track("CYTEST2", album=album, artists=[artist])

    GetSeveralTracksResponseHandler(None, 0, {"tracks": [track]}).write_to_neo4j(driver=neo4j_driver)

    recs, _, _ = neo4j_driver.execute_query(
        "MATCH (t:Track {uri: $uri})<-[:CREATED]-(ar:Artist) RETURN count(ar) AS c",
        uri=track["uri"],
    )
    assert recs[0]["c"] >= 1
