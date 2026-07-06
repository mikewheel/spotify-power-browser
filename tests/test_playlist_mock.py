"""Tests for the mock's playlist CRUD routes (plan 08 T3).

Unlike the compose-network mock tests (test_mock_service.py), these serve the
mock app in-process on an ephemeral localhost port so they run fully offline —
no compose network required. catalog.PUBLIC_BASE_URL is patched to that base
for the duration so hrefs and `next` links stay self-referential.
"""
import threading
from wsgiref.simple_server import make_server

import pytest
import requests

from mock_spotify import catalog
from mock_spotify.app import create_app, _ThreadingWSGIServer


@pytest.fixture
def mock_url():
    server = make_server("127.0.0.1", 0, create_app(), server_class=_ThreadingWSGIServer)
    base = f"http://127.0.0.1:{server.server_port}"
    original_base = catalog.PUBLIC_BASE_URL
    catalog.PUBLIC_BASE_URL = base
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    requests.post(f"{base}/_control/reset", timeout=3).raise_for_status()
    yield base
    requests.post(f"{base}/_control/reset", timeout=3)
    server.shutdown()
    catalog.PUBLIC_BASE_URL = original_base


def _uri(track_id):
    return f"spotify:track:{track_id}"


def _create(mock_url, name="[SPB] Test", description="stamped", user_id="mockuser"):
    response = requests.post(
        f"{mock_url}/v1/users/{user_id}/playlists",
        json={"name": name, "public": False, "description": description},
    )
    response.raise_for_status()
    return response.json()


def test_me_returns_the_fake_user(mock_url):
    me = requests.get(f"{mock_url}/v1/me").json()
    assert me["id"] == "mockuser"
    assert me["type"] == "user"


def test_create_playlist_returns_a_playlist_object(mock_url):
    created = _create(mock_url)
    assert created["id"].startswith("pl")
    assert created["name"] == "[SPB] Test"
    assert created["description"] == "stamped"
    assert created["owner"]["id"] == "mockuser"
    assert created["public"] is False
    assert created["tracks"]["total"] == 0
    assert created["snapshot_id"]
    assert created["href"].startswith(mock_url)  # self-referential


def test_get_unknown_playlist_is_404(mock_url):
    assert requests.get(f"{mock_url}/v1/playlists/pl999999").status_code == 404


def test_add_tracks_then_paginate_through_items(mock_url):
    playlist_id = _create(mock_url)["id"]
    ids = [f"trk{i:06d}" for i in range(5)]
    response = requests.post(
        f"{mock_url}/v1/playlists/{playlist_id}/tracks",
        json={"uris": [_uri(i) for i in ids]},
    )
    assert response.status_code == 201
    assert response.json()["snapshot_id"]

    seen, url = [], f"{mock_url}/v1/playlists/{playlist_id}/tracks?offset=0&limit=2"
    while url:
        page = requests.get(url).json()
        assert page["total"] == 5
        seen += [item["track"]["id"] for item in page["items"]]
        if page["next"]:
            assert page["next"].startswith(mock_url)  # self-referential
        url = page["next"]
    assert seen == ids  # order preserved across pages


def test_add_more_than_100_per_call_is_400_like_spotify(mock_url):
    playlist_id = _create(mock_url)["id"]
    uris = [_uri("trk000000")] * 101
    response = requests.post(
        f"{mock_url}/v1/playlists/{playlist_id}/tracks", json={"uris": uris}
    )
    assert response.status_code == 400


def test_remove_more_than_100_per_call_is_400_like_spotify(mock_url):
    playlist_id = _create(mock_url)["id"]
    tracks = [{"uri": _uri("trk000000")}] * 101
    response = requests.delete(
        f"{mock_url}/v1/playlists/{playlist_id}/tracks", json={"tracks": tracks}
    )
    assert response.status_code == 400


def test_unknown_or_malformed_uri_is_400(mock_url):
    playlist_id = _create(mock_url)["id"]
    for bad in ("spotify:track:does-not-exist", "trk000001", "spotify:album:alb000001"):
        response = requests.post(
            f"{mock_url}/v1/playlists/{playlist_id}/tracks", json={"uris": [bad]}
        )
        assert response.status_code == 400, bad


def test_remove_deletes_all_occurrences_of_a_uri(mock_url):
    playlist_id = _create(mock_url)["id"]
    uris = [_uri("trk000001"), _uri("trk000002"), _uri("trk000001")]
    requests.post(f"{mock_url}/v1/playlists/{playlist_id}/tracks", json={"uris": uris})
    response = requests.delete(
        f"{mock_url}/v1/playlists/{playlist_id}/tracks",
        json={"tracks": [{"uri": _uri("trk000001")}]},
    )
    assert response.status_code == 200
    page = requests.get(f"{mock_url}/v1/playlists/{playlist_id}/tracks").json()
    assert [item["track"]["id"] for item in page["items"]] == ["trk000002"]


def test_put_updates_name_and_description(mock_url):
    playlist_id = _create(mock_url)["id"]
    response = requests.put(
        f"{mock_url}/v1/playlists/{playlist_id}",
        json={"name": "[SPB] Renamed", "description": "restamped"},
    )
    assert response.status_code == 200
    obj = requests.get(f"{mock_url}/v1/playlists/{playlist_id}").json()
    assert obj["name"] == "[SPB] Renamed"
    assert obj["description"] == "restamped"


def test_snapshot_id_changes_on_every_mutation(mock_url):
    playlist_id = _create(mock_url)["id"]
    first = requests.get(f"{mock_url}/v1/playlists/{playlist_id}").json()["snapshot_id"]
    requests.post(
        f"{mock_url}/v1/playlists/{playlist_id}/tracks", json={"uris": [_uri("trk000001")]}
    )
    second = requests.get(f"{mock_url}/v1/playlists/{playlist_id}").json()["snapshot_id"]
    assert first != second


def test_control_reset_clears_playlist_state(mock_url):
    playlist_id = _create(mock_url)["id"]
    requests.post(f"{mock_url}/_control/reset")
    assert requests.get(f"{mock_url}/v1/playlists/{playlist_id}").status_code == 404


def test_failure_injection_applies_to_playlist_routes_too(mock_url):
    playlist_id = _create(mock_url)["id"]
    requests.post(f"{mock_url}/_control/config", json={"fail_next_n": 1, "fail_status": 429, "retry_after": 3})
    first = requests.get(f"{mock_url}/v1/playlists/{playlist_id}")
    assert first.status_code == 429 and first.headers.get("Retry-After") == "3"
    assert requests.get(f"{mock_url}/v1/playlists/{playlist_id}").status_code == 200  # resumed
