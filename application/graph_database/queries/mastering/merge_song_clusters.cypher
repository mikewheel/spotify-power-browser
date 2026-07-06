// Entity mastering (plan 03): MERGE canonical (:Song) nodes and point each
// member (:Track) at its Song with exactly ONE VERSION_OF edge. Idempotent and
// re-runnable: a track whose cluster changed is RE-POINTED (the stale edge is
// deleted), but Songs are never deleted — an orphaned Song is harmless and a
// later run may repopulate it.
UNWIND $clusters AS cluster

MERGE (s:Song {id: cluster.song_id})
SET s.title = cluster.title

WITH cluster, s
UNWIND cluster.members AS member

MATCH (t:Track {id: member.track_id})

// A Track has exactly one VERSION_OF: drop any edge to a different Song.
OPTIONAL MATCH (t)-[stale:VERSION_OF]->(other:Song)
WHERE other.id <> cluster.song_id
DELETE stale

MERGE (t)-[v:VERSION_OF]->(s)
SET
    v.kind = member.kind,
    v.method = member.method,
    v.confidence = member.confidence
;
