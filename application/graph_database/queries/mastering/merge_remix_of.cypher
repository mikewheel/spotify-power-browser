// Entity mastering (plan 03): a remix rolls up to its OWN Song, with a
// REMIX_OF edge to the parent Song when the parent was resolvable by
// (primary artist, base title with the remix credit removed).
UNWIND $edges AS edge

MATCH (remix:Song {id: edge.remix_song_id})
MATCH (parent:Song {id: edge.parent_song_id})

MERGE (remix)-[r:REMIX_OF]->(parent)
SET r.confidence = edge.confidence
;
