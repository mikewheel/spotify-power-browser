MATCH (t:Track {id: $track_id})-[:HAS_CUE]->(c:Cue)
RETURN c.id AS id,
       c.at_ms AS at_ms,
       c.label AS label,
       c.created_at AS created_at
ORDER BY c.at_ms
;
