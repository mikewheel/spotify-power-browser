// Exploration queue for one artist (plan 02's unheard-albums queue, flattened
// — the plan 08 v1 approximation): albums by $artist_name containing ZERO
// liked tracks, flattened to track ids in album release-date order. Until
// plan 02's Play/LISTENED_TO history lands, "liked" is the best available
// proxy for "heard" — unify with plan 02's completeness model then.
//
// Artist.popularity plays no filtering role here, so a null value degrades to
// "unknown -> include, flag" via popularity_unknown. Track order within an
// album falls back to Track.id (track_number is not persisted on Track nodes).
MATCH (a:Artist)
WHERE toLower(a.name) = toLower($artist_name)

MATCH (a)-[:CREATED]->(al:Album)
WHERE NOT EXISTS {
    MATCH (al)-[:CONTAINS]->(:Track {liked_songs: true})
}

MATCH (al)-[:CONTAINS]->(t:Track)

RETURN
    t.id AS track_id,
    a.name AS artist_name,
    al.name AS album_name,
    al.release_date AS release_date,
    (a.popularity IS NULL) AS popularity_unknown
ORDER BY al.release_date ASC, al.id ASC, t.id ASC
;
