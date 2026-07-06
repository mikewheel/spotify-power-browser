// max(order)+1 rather than count(*): deleted sections must not make orders
// collide with survivors.
MATCH (t:Track {id: $track_id})
OPTIONAL MATCH (t)-[:HAS_SECTION]->(s:Section)
RETURN coalesce(max(s.order), -1) + 1 AS next_order
;
