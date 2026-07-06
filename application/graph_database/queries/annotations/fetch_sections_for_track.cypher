MATCH (t:Track {id: $track_id})-[:HAS_SECTION]->(s:Section)
RETURN s.id AS id,
       s.order AS `order`,
       s.start_ms AS start_ms,
       s.end_ms AS end_ms,
       s.label AS label,
       s.kind AS kind,
       s.created_at AS created_at
ORDER BY s.order
;
