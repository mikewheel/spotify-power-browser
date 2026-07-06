// Undo for Sections: if the previous section's end_ms was closed by this
// boundary (insert_section sets prev.end_ms = new start_ms and leaves
// prev.end_ms_explicit false), reopen it so the chain returns to its
// pre-insert state. Value equality alone can't distinguish a chain-derived
// end from a user-provided end that happens to equal this boundary's start
// (the natural contiguous case), so the end_ms_explicit provenance flag
// gates the reopen: explicit ends are NEVER erased. For pre-flag legacy
// nodes coalesce treats any set end_ms as explicit — the safe direction
// (keep data rather than null it). FOREACH-guard because prev may not exist
// (undoing the first section) and SET on a null node is an error.
MATCH (s:Section {id: $section_id})
OPTIONAL MATCH (prev:Section)-[:NEXT]->(s)
FOREACH (p IN CASE WHEN prev IS NOT NULL AND prev.end_ms = s.start_ms
                        AND coalesce(prev.end_ms_explicit, prev.end_ms IS NOT NULL) = false
              THEN [prev] ELSE [] END |
    SET p.end_ms = null
)
DETACH DELETE s
;
