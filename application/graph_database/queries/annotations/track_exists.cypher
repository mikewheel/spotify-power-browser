// Graph-membership probe for the live-capture UI (`listen`): unlike
// `annotate`, which only offers tracks already in the graph, `listen` takes
// its track id straight from /v1/me/player — the track may not be crawled
// yet, and every insert query MATCHes the Track (never MERGE: annotations
// must not create placeholder Track nodes). count() aggregates over zero
// rows, so this always returns exactly one row.
MATCH (t:Track {id: $track_id})
RETURN count(t) > 0 AS present
;
