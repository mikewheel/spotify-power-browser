WITH $section as section

MATCH (t:Track {id: section.track_id})

// Chain invariant: NEXT is strictly increasing in start_ms, so two sections
// of one track can never share a boundary. A duplicate start makes the whole
// query match nothing (zero writes) — the writer turns the zero-created
// counter into a loud SectionBoundaryError instead of corrupting the chain.
WHERE NOT EXISTS {
    MATCH (t)-[:HAS_SECTION]->(dup:Section)
    WHERE dup.start_ms = section.start_ms
}

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

// The chain is ordered by TIME (start_ms), not by insertion order: `order` is
// only a capture-sequence id for undo bookkeeping. A boundary remembered late
// ("intro at 0:00" entered after "drop at 2:10") slots into place instead of
// chaining backwards in time. Independent CALL subqueries so a missing
// predecessor/successor doesn't drop the row.

// Predecessor = latest section strictly before the new boundary. Its NEXT
// edge (if any) now belongs to the new section, and its chain-derived end
// closes at this boundary; explicit ends are never overwritten.
WITH t, s
CALL (t, s) {
    MATCH (t)-[:HAS_SECTION]->(prev:Section)
    WHERE prev <> s AND prev.start_ms < s.start_ms
    WITH prev, s
    ORDER BY prev.start_ms DESC
    LIMIT 1
    OPTIONAL MATCH (prev)-[old:NEXT]->(:Section)
    DELETE old
    MERGE (prev)-[:NEXT]->(s)
    FOREACH (p IN CASE WHEN coalesce(prev.end_ms_explicit, prev.end_ms IS NOT NULL) = false
                  THEN [prev] ELSE [] END |
        SET p.end_ms = s.start_ms
    )
}

// Successor = earliest section strictly after the new boundary: the new
// section chains into it and (unless explicitly ended) closes there, keeping
// end_ms >= start_ms by construction.
WITH t, s
CALL (t, s) {
    MATCH (t)-[:HAS_SECTION]->(next:Section)
    WHERE next <> s AND next.start_ms > s.start_ms
    WITH next, s
    ORDER BY next.start_ms ASC
    LIMIT 1
    MERGE (s)-[:NEXT]->(next)
    FOREACH (x IN CASE WHEN coalesce(s.end_ms_explicit, false) = false THEN [s] ELSE [] END |
        SET x.end_ms = next.start_ms
    )
}
;
