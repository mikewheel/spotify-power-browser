// Cold-entry track picker for `annotate`: case-insensitive substring search
// over tracks already in the graph, with enough context to disambiguate.
MATCH (t:Track)
WHERE toLower(t.name) CONTAINS toLower($search_term)
OPTIONAL MATCH (t)<-[:CREATED]-(ar:Artist)
OPTIONAL MATCH (t)<-[:CONTAINS]-(al:Album)
RETURN t.id AS id,
       t.name AS name,
       t.duration_ms AS duration_ms,
       collect(DISTINCT ar.name) AS artists,
       head(collect(DISTINCT al.name)) AS album
ORDER BY t.name
LIMIT 25
;
