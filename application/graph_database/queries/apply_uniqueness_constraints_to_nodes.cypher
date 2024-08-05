CREATE CONSTRAINT album_id_uniqueness IF NOT EXISTS
FOR (album:Album)
REQUIRE album.id IS UNIQUE;

CREATE CONSTRAINT artist_id_uniqueness IF NOT EXISTS
FOR (artist:Artist)
REQUIRE artist.id IS UNIQUE;

CREATE CONSTRAINT track_id_uniqueness IF NOT EXISTS
FOR (track:Track)
REQUIRE track.id IS UNIQUE;
