"""Tests for the mock Spotify service itself (hit over HTTP via the
`spotify_mock` compose service)."""
import requests


def test_health(mock_base):
    assert requests.get(f"{mock_base}/_control/health").json()["status"] == "ok"


def test_liked_songs_pagination_traverses_whole_catalog(mock_base):
    seen, total = 0, None
    url = f"{mock_base}/v1/me/tracks?offset=0&limit=20"
    while url:
        page = requests.get(url).json()
        total = page["total"]
        seen += len(page["items"])
        assert page["items"][0]["track"]["href"].startswith(mock_base)  # self-referential
        url = page["next"]
    assert seen == total  # the whole catalog was reachable via `next`


def test_single_resources_resolve(mock_base):
    for rtype, prefix in [("tracks", "trk"), ("albums", "alb"), ("artists", "art")]:
        obj = requests.get(f"{mock_base}/v1/{rtype}/{prefix}000000").json()
        assert obj["id"] == f"{prefix}000000"
        assert obj["href"].startswith(mock_base)


def test_unknown_single_is_404(mock_base):
    assert requests.get(f"{mock_base}/v1/tracks/does-not-exist").status_code == 404


def test_batch_returns_objects_and_nulls_for_unknown(mock_base):
    tracks = requests.get(f"{mock_base}/v1/tracks?ids=trk000000,unknownid,trk000001").json()["tracks"]
    assert [t and t["id"] for t in tracks] == ["trk000000", None, "trk000001"]


def test_token_endpoint(mock_base):
    # Authenticated code exchange includes a refresh_token...
    body = requests.post(
        f"{mock_base}/api/token",
        data={"grant_type": "authorization_code", "code": "mock-auth-code"},
        auth=("mock-client-id", "mock-client-secret"),
    ).json()
    assert body["token_type"] == "Bearer" and body["access_token"] and body["refresh_token"]
    # ...while a refresh grant omits it (as Spotify commonly does).
    body = requests.post(
        f"{mock_base}/api/token",
        data={"grant_type": "refresh_token", "refresh_token": "mock-refresh-token"},
        auth=("mock-client-id", "mock-client-secret"),
    ).json()
    assert body["access_token"] and "refresh_token" not in body


def test_inject_429_with_retry_after_then_resumes(mock_base):
    requests.post(f"{mock_base}/_control/config", json={"fail_next_n": 1, "fail_status": 429, "retry_after": 7})
    r1 = requests.get(f"{mock_base}/v1/tracks/trk000000")
    assert r1.status_code == 429 and r1.headers.get("Retry-After") == "7"
    assert requests.get(f"{mock_base}/v1/tracks/trk000000").status_code == 200  # resumed


def test_inject_401(mock_base):
    requests.post(f"{mock_base}/_control/config", json={"fail_next_n": 1, "fail_status": 401})
    assert requests.get(f"{mock_base}/v1/tracks/trk000000").status_code == 401


def test_inject_500_for_a_specific_url_only(mock_base):
    requests.post(f"{mock_base}/_control/config", json={"fail_url_substring": "trk000005", "fail_status": 500})
    assert requests.get(f"{mock_base}/v1/tracks/trk000005").status_code == 500
    assert requests.get(f"{mock_base}/v1/tracks/trk000000").status_code == 200  # others unaffected
