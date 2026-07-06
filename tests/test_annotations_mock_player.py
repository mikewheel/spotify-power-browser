"""Tests for the mock's GET /v1/me/player route (plan 04 T5), hit over HTTP via
the `spotify_mock` compose service. The mock_base fixture resets the control
plane (including player state) before and after each test."""
import time

import requests


def _configure(mock_base, **player_keys):
    response = requests.post(f"{mock_base}/_control/config", json=player_keys)
    response.raise_for_status()
    return response.json()


def test_default_player_state_is_track_zero_playing(mock_base):
    response = requests.get(f"{mock_base}/v1/me/player")
    assert response.status_code == 200
    state = response.json()
    assert state["is_playing"] is True
    assert state["progress_ms"] == 0  # advance defaults off: deterministic
    assert state["item"]["id"] == "trk000000"
    assert state["item"]["href"].startswith(mock_base)  # self-referential
    assert state["currently_playing_type"] == "track"


def test_configure_exact_track_and_position(mock_base):
    body = _configure(
        mock_base, player_track_id="trk000003", player_progress_ms=41000
    )
    assert body["player_track_id"] == "trk000003"  # control echoes player state
    state = requests.get(f"{mock_base}/v1/me/player").json()
    assert state["item"]["id"] == "trk000003"
    assert state["progress_ms"] == 41000  # frozen without player_advance
    time.sleep(1.1)
    assert requests.get(f"{mock_base}/v1/me/player").json()["progress_ms"] == 41000


def test_progress_advances_with_wallclock_when_enabled(mock_base):
    _configure(mock_base, player_progress_ms=1000, player_advance=True)
    first = requests.get(f"{mock_base}/v1/me/player").json()["progress_ms"]
    time.sleep(1.1)
    second = requests.get(f"{mock_base}/v1/me/player").json()["progress_ms"]
    assert second > first >= 1000
    assert second - first >= 1000  # ~wall-clock ms elapsed between the polls


def test_paused_player_does_not_advance(mock_base):
    _configure(
        mock_base, player_progress_ms=5000, player_advance=True, player_is_playing=False
    )
    state = requests.get(f"{mock_base}/v1/me/player").json()
    assert state["is_playing"] is False
    assert state["progress_ms"] == 5000


def test_advance_flows_across_track_boundary_like_an_album(mock_base):
    # Catalog tracks are 200000ms; park 100ms before the end of track 0 and
    # let wall-clock advance carry playback into track 1.
    _configure(mock_base, player_track_id="trk000000", player_progress_ms=199900, player_advance=True)
    time.sleep(1.2)
    state = requests.get(f"{mock_base}/v1/me/player").json()
    assert state["item"]["id"] == "trk000001"
    assert 0 <= state["progress_ms"] < 10000


def test_no_active_device_is_204(mock_base):
    _configure(mock_base, player_track_id=None)
    assert requests.get(f"{mock_base}/v1/me/player").status_code == 204


def test_control_reset_restores_default_player(mock_base):
    _configure(mock_base, player_track_id="trk000007", player_progress_ms=12345)
    requests.post(f"{mock_base}/_control/reset")
    state = requests.get(f"{mock_base}/v1/me/player").json()
    assert state["item"]["id"] == "trk000000" and state["progress_ms"] == 0


def test_player_payload_shape_matches_what_listen_consumes(mock_base):
    # PlaybackTracker reads is_playing, progress_ms, and item{id,name,
    # duration_ms,artists[].name} — pin them so the mock stays load-bearing.
    state = requests.get(f"{mock_base}/v1/me/player").json()
    assert {"is_playing", "progress_ms", "item"} <= set(state)
    item = state["item"]
    assert {"id", "name", "duration_ms", "artists"} <= set(item)
    assert all("name" in artist for artist in item["artists"])


def test_failure_injection_applies_to_player_route_too(mock_base):
    requests.post(f"{mock_base}/_control/config", json={"fail_next_n": 1, "fail_status": 429, "retry_after": 3})
    first = requests.get(f"{mock_base}/v1/me/player")
    assert first.status_code == 429 and first.headers.get("Retry-After") == "3"
    assert requests.get(f"{mock_base}/v1/me/player").status_code == 200  # resumed
