// Undo for Sections: if the previous section's end_ms was closed by this
// boundary (insert_section sets prev.end_ms = new start_ms), reopen it so the
// chain returns to its pre-insert state. FOREACH-guard because prev may not
// exist (undoing the first section) and SET on a null node is an error.
MATCH (s:Section {id: $section_id})
OPTIONAL MATCH (prev:Section)-[:NEXT]->(s)
FOREACH (p IN CASE WHEN prev IS NOT NULL AND prev.end_ms = s.start_ms THEN [prev] ELSE [] END |
    SET p.end_ms = null
)
DETACH DELETE s
;
