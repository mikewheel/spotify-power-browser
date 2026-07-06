// Undo for Sections: restore the chain to its pre-insert state.
//
// - If the deleted section sat between two others (a position-aware middle
//   insert), bridge prev-[:NEXT]->next so the chain stays connected.
// - If the previous section's end_ms was closed by this boundary
//   (insert_section sets prev.end_ms = new start_ms and leaves
//   prev.end_ms_explicit false), re-derive it: back to the successor's start
//   when one exists, otherwise reopen (null = runs to track end). Value
//   equality alone can't distinguish a chain-derived end from a user-provided
//   end that happens to equal this boundary's start (the natural contiguous
//   case), so the end_ms_explicit provenance flag gates this: explicit ends
//   are NEVER erased. Pre-flag legacy nodes with a set end_ms are treated as
//   explicit — the safe direction (keep data rather than null it).
// FOREACH-guards because prev/next may not exist and SET/MERGE on a null
// node is an error.
MATCH (s:Section {id: $section_id})
OPTIONAL MATCH (prev:Section)-[:NEXT]->(s)
OPTIONAL MATCH (s)-[:NEXT]->(next:Section)
FOREACH (_ IN CASE WHEN prev IS NOT NULL AND next IS NOT NULL THEN [1] ELSE [] END |
    MERGE (prev)-[:NEXT]->(next)
)
FOREACH (p IN CASE WHEN prev IS NOT NULL AND prev.end_ms = s.start_ms
                        AND coalesce(prev.end_ms_explicit, prev.end_ms IS NOT NULL) = false
              THEN [prev] ELSE [] END |
    SET p.end_ms = CASE WHEN next IS NULL THEN null ELSE next.start_ms END
)
DETACH DELETE s
;
