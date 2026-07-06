// Entity mastering (plan 03): pull every non-local Track with the fields the
// clustering job needs. CREATED edges are unordered, so artist ids/names come
// back sorted and run.py treats the lexicographically smallest id as a stable
// primary-artist proxy for the heuristic blocking key.
MATCH (t:Track)
WHERE coalesce(t.is_local, false) = false
OPTIONAL MATCH (t)<-[:CREATED]-(ar:Artist)
WITH t, ar ORDER BY ar.id
WITH t, collect(ar.id) AS artist_ids, collect(ar.name) AS artist_names
RETURN
    t.id AS id,
    t.name AS name,
    t.isrc AS isrc,
    t.linked_from_id AS linked_from_id,
    t.duration_ms AS duration_ms,
    t.explicit AS explicit,
    artist_ids,
    artist_names
;
