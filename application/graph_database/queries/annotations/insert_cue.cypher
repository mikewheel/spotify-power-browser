WITH $cue as cue

MATCH (t:Track {id: cue.track_id})

CREATE (c:Cue {
    id: cue.id,
    at_ms: cue.at_ms,
    label: cue.label,
    created_at: cue.created_at
})

CREATE (t)-[:HAS_CUE]->(c)
;
