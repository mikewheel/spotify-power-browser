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
