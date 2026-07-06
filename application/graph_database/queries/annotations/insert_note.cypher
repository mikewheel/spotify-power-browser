WITH $note as note

MATCH (t:Track {id: note.track_id})

CREATE (n:Note {
    id: note.id,
    text: note.text,
    created_at: note.created_at
})
// Optional playback position: present for live capture (`listen`), null for
// cold entry — setting a property to null is a no-op, so it simply isn't stored.
SET n.at_ms = note.at_ms

CREATE (t)-[:HAS_NOTE]->(n)
;
