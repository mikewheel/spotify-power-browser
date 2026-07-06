// Fine-tune a captured timestamp (the +/- 500ms nudge keys in `listen`).
// FOREACH order is load-bearing for Sections: the previous section's chained
// end_ms must be re-pointed while it still equals the OLD start_ms, before the
// new start_ms is written. Notes are only nudged if they carry a position.
MATCH (a)
WHERE a.id = $annotation_id AND (a:Note OR a:Cue OR a:Section)
OPTIONAL MATCH (prev:Section)-[:NEXT]->(a)
FOREACH (n IN CASE WHEN a:Note AND a.at_ms IS NOT NULL THEN [a] ELSE [] END |
    SET n.at_ms = $at_ms
)
FOREACH (c IN CASE WHEN a:Cue THEN [a] ELSE [] END |
    SET c.at_ms = $at_ms
)
FOREACH (p IN CASE WHEN prev IS NOT NULL AND a:Section AND prev.end_ms = a.start_ms THEN [prev] ELSE [] END |
    SET p.end_ms = $at_ms
)
FOREACH (s IN CASE WHEN a:Section THEN [a] ELSE [] END |
    SET s.start_ms = $at_ms
)
;
