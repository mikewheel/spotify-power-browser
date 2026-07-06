// Iterate over a batch of full album objects (Get Several Albums response)
UNWIND $albums as album

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
    al.href = album.href
// A stub Album {uri, id, crawl_source} can pre-exist this insert: the
// tracks-page handler (insert_tracks_of_album_page.cypher) MERGEs one to
// tolerate out-of-order queue consumption, and an auto-ack'd batch write can
// be lost outright while the crawled-URL dedup set blocks any refetch of the
// /v1/albums?ids= URL. Upgrade it here with the chain's established
// coalesce(payload, existing) ON MATCH pattern so a later full payload always
// lands; a payload that lacks a field never erases a stored value.
ON MATCH SET
    al.name = coalesce(album.name, al.name),
    al.release_date = coalesce(album.release_date, al.release_date),
    al.release_date_precision = coalesce(album.release_date_precision, al.release_date_precision),
    al.total_tracks = coalesce(album.total_tracks, al.total_tracks),
    al.album_type = coalesce(album.album_type, al.album_type),
    al.spotify_url = coalesce(album.external_urls.spotify, al.spotify_url),
    al.type = coalesce(album.type, al.type),
    al.href = coalesce(album.href, al.href)

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

// Inner loop over album's genres (currently blank)
WITH album UNWIND album.genres as genre

MATCH (al:Album {uri: album.uri})

MERGE (g:Genre {name: genre})

MERGE (al)-[:SPOTIFY_CLASSIFIED_AS]->(g)
