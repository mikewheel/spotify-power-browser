// Entity mastering (plan 03): pull every non-local Track with the fields the
// clustering job needs.
//
// artist_ids: prefer t.artist_ids — the track's OWN performing artists in
// credit order, persisted by the insert Cyphers (first = primary artist).
// Legacy nodes crawled before that field existed fall back to the CREATED
// edges, which are unordered AND include album artists — a weaker proxy
// (smallest id as pseudo-primary). The ISRC backfill refreshes t.artist_ids
// on every node it touches, so the fallback disappears after one backfill.
//
// artist_names: collected from CREATED edges; only used as a set to decide
// whether a "feat. X" clause is redundant, so order doesn't matter.
MATCH (t:Track)
WHERE coalesce(t.is_local, false) = false
OPTIONAL MATCH (t)<-[:CREATED]-(ar:Artist)
WITH t, ar ORDER BY ar.id
WITH t, collect(ar.id) AS edge_artist_ids, collect(ar.name) AS artist_names
RETURN
    t.id AS id,
    t.name AS name,
    t.isrc AS isrc,
    t.linked_from_id AS linked_from_id,
    t.duration_ms AS duration_ms,
    t.explicit AS explicit,
    coalesce(t.artist_ids, edge_artist_ids) AS artist_ids,
    artist_names
;
