// Fine-tune a captured timestamp (the +/- 500ms nudge keys in `listen`).
//
// Section moves are validated against the chain invariant BEFORE anything is
// written; an out-of-bounds move is rejected wholesale (applied = false) so
// the caller tells the user instead of corrupting the chain:
//   - strictly after the previous section's start (dragging the chained
//     prev.end_ms to or below prev.start_ms would invert the predecessor);
//   - strictly before the next section's start (NEXT is strictly increasing
//     in start_ms);
//   - at most the section's own end_ms (never end_ms < start_ms).
// Notes and Cues have no chain constraints (callers floor them at 0).
//
// FOREACH order is load-bearing for Sections: the previous section's chained
// end_ms must be re-pointed while it still equals the OLD start_ms, before the
// new start_ms is written. Notes are only nudged if they carry a position.
MATCH (a)
WHERE a.id = $annotation_id AND (a:Note OR a:Cue OR a:Section)
OPTIONAL MATCH (prev:Section)-[:NEXT]->(a)
OPTIONAL MATCH (a)-[:NEXT]->(next:Section)
WITH a, prev, next,
     ((NOT a:Section) OR (
         (prev IS NULL OR $at_ms > prev.start_ms)
         AND (next IS NULL OR $at_ms < next.start_ms)
         AND (a.end_ms IS NULL OR $at_ms <= a.end_ms)
     )) AS applied
FOREACH (n IN CASE WHEN applied AND a:Note AND a.at_ms IS NOT NULL THEN [a] ELSE [] END |
    SET n.at_ms = $at_ms
)
FOREACH (c IN CASE WHEN applied AND a:Cue THEN [a] ELSE [] END |
    SET c.at_ms = $at_ms
)
// Only chain-derived previous ends move with the boundary: an explicit
// prev.end_ms that happens to equal this start (contiguous entry) must not
// be dragged. Legacy nodes without the flag are treated as explicit (safe).
FOREACH (p IN CASE WHEN applied AND prev IS NOT NULL AND a:Section AND prev.end_ms = a.start_ms
                        AND coalesce(prev.end_ms_explicit, prev.end_ms IS NOT NULL) = false
              THEN [prev] ELSE [] END |
    SET p.end_ms = $at_ms
)
FOREACH (s IN CASE WHEN applied AND a:Section THEN [a] ELSE [] END |
    SET s.start_ms = $at_ms
)
RETURN applied
;
