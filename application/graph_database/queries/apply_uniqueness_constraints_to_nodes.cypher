CREATE CONSTRAINT album_id_uniqueness IF NOT EXISTS
FOR (album:Album)
REQUIRE album.id IS UNIQUE;

CREATE CONSTRAINT artist_id_uniqueness IF NOT EXISTS
FOR (artist:Artist)
REQUIRE artist.id IS UNIQUE;

CREATE CONSTRAINT track_id_uniqueness IF NOT EXISTS
FOR (track:Track)
REQUIRE track.id IS UNIQUE;

// --- Entity mastering (plan 03): canonical Song masters ---
CREATE CONSTRAINT song_id_uniqueness IF NOT EXISTS
FOR (song:Song)
REQUIRE song.id IS UNIQUE;

// --- 04 annotations & DJ sets (phases A-B): Note / Cue / Section ---
// Annotation ids are app-side uuid4 (application/annotations/model.py).

CREATE CONSTRAINT note_id_uniqueness IF NOT EXISTS
FOR (note:Note)
REQUIRE note.id IS UNIQUE;

CREATE CONSTRAINT cue_id_uniqueness IF NOT EXISTS
FOR (cue:Cue)
REQUIRE cue.id IS UNIQUE;

CREATE CONSTRAINT section_id_uniqueness IF NOT EXISTS
FOR (section:Section)
REQUIRE section.id IS UNIQUE;

// --- 08 playlist write-back: ManagedPlaylist (application/playlists/) ---
CREATE CONSTRAINT managed_playlist_spotify_id_uniqueness IF NOT EXISTS
FOR (playlist:ManagedPlaylist)
REQUIRE playlist.spotify_id IS UNIQUE;

// --- 06 multiplayer: (:User) ownership layer ---
// User.id is the Spotify user id (GET /v1/me "id"); every per-user
// relationship ((:User)-[:LIKED]->, -[:HAS_MANAGED]->, later -[:FOLLOWS]->
// and plan 02's -[:DID]->(:Play)) anchors on it.
CREATE CONSTRAINT user_id_uniqueness IF NOT EXISTS
FOR (user:User)
REQUIRE user.id IS UNIQUE;
