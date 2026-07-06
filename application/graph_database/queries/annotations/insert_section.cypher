WITH $section as section

MATCH (t:Track {id: section.track_id})

CREATE (s:Section {
    id: section.id,
    order: section.order,
    start_ms: section.start_ms,
    label: section.label,
    kind: section.kind,
    created_at: section.created_at
})
// end_ms may be null: an open section runs until the next boundary (which
// closes it below on its own insert) or the track end.
SET s.end_ms = section.end_ms
// Provenance: true only when the caller supplied end_ms explicitly.
// Chain-derived ends (set by a later boundary's insert) keep this false, so
// undo/nudge can re-derive or reopen them WITHOUT ever destroying a
// user-provided end that merely coincides with the next boundary's start.
SET s.end_ms_explicit = section.end_ms IS NOT NULL

CREATE (t)-[:HAS_SECTION]->(s)

// Chain NEXT from the immediately-preceding section of the same track (the
// highest order below this one) and close its open end at this boundary.
// Independent CALL subquery so a first section (no predecessor) doesn't drop
// the row.
WITH t, s
CALL (t, s) {
    MATCH (t)-[:HAS_SECTION]->(prev:Section)
    WHERE prev.order < s.order
    WITH prev, s
    ORDER BY prev.order DESC
    LIMIT 1
    MERGE (prev)-[:NEXT]->(s)
    SET prev.end_ms = coalesce(prev.end_ms, s.start_ms)
}
;
