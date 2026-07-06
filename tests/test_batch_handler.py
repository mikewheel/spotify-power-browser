from application.response_handlers.tracks.several_tracks import GetSeveralTracksResponseHandler


def test_items_filters_null_entries(make):
    # Spotify's Get Several X endpoints return null for ids that don't resolve.
    handler = GetSeveralTracksResponseHandler(None, 0, {"tracks": [make.track(1), None, make.track(2)]})
    assert len(handler.items) == 2
    assert all(item is not None for item in handler.items)


def test_write_to_disk_uses_id_and_tolerates_a_bad_item(make, tmp_path, monkeypatch):
    monkeypatch.setattr(GetSeveralTracksResponseHandler, "DISK_LOCATION", tmp_path)
    good = make.track(1)
    bad = {"id": "noname"}  # no "name" -> falls back to id, still written, not aborting the batch
    GetSeveralTracksResponseHandler(None, 0, {"tracks": [good, bad]}).write_to_disk()

    files = [p.name for p in tmp_path.iterdir()]
    assert len(files) == 2  # one bad item did not abort the other write
    # the unique id is in the filename so same-named items can't collide
    assert any(good["id"] in name for name in files)


def _patch_request_batch(monkeypatch):
    calls = []
    monkeypatch.setattr(
        "application.requests_factory.SpotifyRequestFactory.request_batch",
        classmethod(lambda cls, rtype, ids, depth_of_search=0, user_id=None: calls.append((rtype, list(ids), depth_of_search))),
    )
    return calls


def test_follow_links_terminates_at_depth_zero(make, monkeypatch):
    calls = _patch_request_batch(monkeypatch)
    GetSeveralTracksResponseHandler(None, 0, {"tracks": [make.track(1)]}).follow_links()
    assert calls == []


def test_follow_links_batches_neighbors_at_depth(make, monkeypatch):
    calls = _patch_request_batch(monkeypatch)
    GetSeveralTracksResponseHandler(None, 1, {"tracks": [make.track(1)]}).follow_links()
    assert {rtype for rtype, _, _ in calls} == {"albums", "artists"}
    assert all(depth == 0 for _, _, depth in calls)  # depth decremented from 1
