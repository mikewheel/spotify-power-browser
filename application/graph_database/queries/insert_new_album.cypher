WITH $album as album

MERGE (al:Album {uri: album.uri})
ON CREATE SET
    al.uri = album.uri,
    al.id = album.id,
    al.name = album.name,
    al.release_date = album.release_date,
    al.release_date_precision = album.release_date_precision,
    al.total_tracks = album.total_tracks,
    al.album_type = album.album_type,
    al.spotify_url = album.external_urls.spotify,
    al.type = album.type,
    al.href = album.href,
    al.label = album.label,
    al.popularity = album.popularity
ON MATCH SET
    al.label = album.label,
    al.popularity = album.popularity

// Skip tracks because it's paginated

// Inner loop over album's own artists
WITH album UNWIND album.artists as artist
MATCH (al:Album {uri: album.uri})

MERGE (ar:Artist {uri: artist.uri})
ON CREATE SET
    ar.uri = artist.uri,
    ar.id = artist.id,
    ar.name = artist.name,
    ar.spotify_url = artist.external_urls.spotify,
    ar.type = artist.type

MERGE (al)<-[:CREATED]-(ar)
