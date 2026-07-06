// Iterate over a batch of full artist objects (Get Several Artists response)
UNWIND $artists as artist

MERGE (ar:Artist {uri: artist.uri})
ON CREATE SET
    ar.uri = artist.uri,
    ar.id = artist.id,
    ar.name = artist.name,
    ar.spotify_url = artist.external_urls.spotify,
    ar.type = artist.type,
    ar.popularity = artist.popularity,
    ar.followers = artist.followers.total
// Adjacent-artist discovery (plan 01): refresh the ranking fields on re-insert
// so the popularity backfill updates existing nodes; coalesce so a payload
// that lacks a field (e.g. a simplified artist object) can't erase a
// previously stored value.
ON MATCH SET
    ar.popularity = coalesce(artist.popularity, ar.popularity),
    ar.followers = coalesce(artist.followers.total, ar.followers)

// Inner loop over artist's genres
WITH artist UNWIND artist.genres as genre

MATCH (ar:Artist {uri: artist.uri})

MERGE (g:Genre {name: genre})

MERGE (ar)-[:SPOTIFY_CLASSIFIED_AS]->(g)
