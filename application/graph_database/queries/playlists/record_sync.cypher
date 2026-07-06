// Stamp a completed sync: last_synced plus a rolling window of the LAST THREE
// target snapshots (JSON strings, newest first). Each snapshot is
// {"at": <iso>, "track_ids": [...]} — serialized because Neo4j properties
// cannot hold nested lists.
//
// Restore path: read p.target_snapshots[i], json-decode it, and feed its
// track_ids back through the sync module as the target list (see
// application/playlists/sync.py module docstring).
WITH $sync AS sync

MATCH (p:ManagedPlaylist {spotify_id: sync.spotify_id})
SET p.last_synced = sync.last_synced,
    p.target_snapshots = ([sync.snapshot] + coalesce(p.target_snapshots, []))[0..3]
;
