// Entity mastering (plan 03): a remix rolls up to its OWN Song, with a
// REMIX_OF edge to the parent Song when the parent was resolvable by
// (primary artist, base title with the remix credit removed).
// Idempotent and re-runnable, mirroring VERSION_OF in
// merge_song_clusters.cypher: when the parent cluster's id changes between
// runs (e.g. a new variant flips it from a bare ISRC to a song:<hash>), the
// remix is RE-POINTED — the stale edge is deleted; the orphaned parent Song
// node itself is never deleted.
UNWIND $edges AS edge

MATCH (remix:Song {id: edge.remix_song_id})
MATCH (parent:Song {id: edge.parent_song_id})

// A remix points at exactly one parent: drop any edge to a different Song.
OPTIONAL MATCH (remix)-[stale:REMIX_OF]->(other:Song)
WHERE other.id <> edge.parent_song_id
DELETE stale

MERGE (remix)-[r:REMIX_OF]->(parent)
SET r.confidence = edge.confidence
;
