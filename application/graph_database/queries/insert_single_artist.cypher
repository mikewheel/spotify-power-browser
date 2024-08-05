WITH $artist as artist

MERGE (ar:Artist {uri: artist.uri})
ON CREATE SET
    ar.uri = artist.uri,
    ar.id = artist.id,
    ar.name = artist.name,
    ar.spotify_url = artist.external_urls.spotify,
    ar.type = artist.type,
    ar.popularity = artist.popularity,
    ar.followers_count = artist.followers.total
ON MATCH SET
    ar.popularity = artist.popularity,
    ar.followers_count = artist.followers.total

// Inner loop over artist's genres
WITH artist UNWIND artist.genres as genre

MATCH (ar:Artist {uri: artist.uri})

MERGE (g:Genre {name: genre})

MERGE (ar)-[:SPOTIFY_CLASSIFIED_AS]->(g)