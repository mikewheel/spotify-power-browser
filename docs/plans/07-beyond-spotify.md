# 07 — Beyond Spotify (local files, SoundCloud, platform-agnostic core)

> One taste graph over every place your music lives: the MP3s you own, the
> indie-EDM world on SoundCloud, and Spotify — joined where identity can be
> established, honest about where it can't. **Effort: XL — three independent
> phases (local → identity → SoundCloud).** Depends on: 03 (the Song layer is
> the join point). Feeds: 04 (BPM/key/cues from files + Rekordbox!).

## Vision & the honest identity problem

Platform-agnostic means the graph's *anchor* can't be a Spotify ID. Plan 03's
`(:Song)` is that anchor. Each platform contributes **platform-native track
nodes** linked to Songs when identity is provable — and standing alone when
not. Critically for the DJ use-case: a huge share of indie-EDM SoundCloud
content (bootlegs, edits, unreleased VIPs, mixes) **has no canonical identity
anywhere** — those aren't matching failures; they're first-class citizens that
only exist there.

### The identity ladder (extends plan 03's)

1. **ISRC** — Spotify has it (post plan-03 backfill); local files sometimes
   carry it (ID3 `TSRC` frame); SoundCloud rarely exposes it.
2. **MusicBrainz Recording ID** — the neutral hub. Local files:
   **AcoustID/Chromaprint** audio fingerprint → MusicBrainz recording → ISRC(s).
   This is how untagged/mistagged files get real identity.
3. **Tag/metadata match** — normalized (title, artist, duration±3s) per plan 03.
4. **Manual link / no link** — override YAML; unlinked stays platform-native.

## Design

### Phase L — local files (do this first; it unblocks plan 04's data needs)

```
(:LocalFile {path, filename, format, bitrate, duration_ms, mtime, content_hash})
(:LocalFile)-[:VERSION_OF {method, confidence}]->(:Song)
```
- **Scanner** `python -m application.ingest.local_library <root>`:
  walk → hash (xxhash of audio stream, not file — tags change) →
  **mutagen** for tags (title/artist/album/`TSRC`/`TBPM`/`TKEY`, artwork
  presence) → MERGE LocalFile; incremental by (path, mtime).
- **Resolver pass**: ISRC direct → else AcoustID (pyacoustid + Chromaprint,
  free API key) → MusicBrainz recording → match/mint Song. Rate-limit MB to
  1 req/s (their policy) — a 5k-file library resolves overnight; cache
  responses on disk.
- **Consider [beets](https://beets.io)** as the tagging workhorse *upstream* of
  the graph (it already does fingerprint-autotag-organize superbly; we ingest
  its clean library DB) — evaluate in a spike (T-L5) before writing a worse
  version of it.
- **DJ metadata joins plan 04 here**: `TBPM`/`TKEY` tags, and **Rekordbox XML
  export** (contains per-track BPM, key, and **cue points/memory cues with
  positions**) → import as `Track/LocalFile` props + `(:Cue)` nodes. Serato
  crates similar (via `serato-tools`). This is the richest source of DJ truth
  we control — Spotify's analysis being dead (403) makes it the *only* one.

### Phase S — SoundCloud

```
(:SoundCloudTrack {id, urn, title, permalink, duration_ms, playback_count, …})
(:SoundCloudUser {id, username})-[:POSTED]->(:SoundCloudTrack)
(:User)-[:SC_LIKED {liked_at?}]->(:SoundCloudTrack)
(:SoundCloudTrack)-[:VERSION_OF]->(:Song)     // when provable — expect a low hit rate, by design
```
- **Access reality (verify first, build second):** SoundCloud's public API has
  had *closed/waitlisted client registration* for long stretches; policies have
  shifted repeatedly. T-S1 is a spike: register an app at
  developers.soundcloud.com, confirm OAuth works and which endpoints your
  account tier gets (`/me/likes/tracks`, `/me/followings`, `/users/{id}/tracks`,
  `/resolve`). **No code before that answer.** Fallbacks if registration is
  blocked: (a) SoundCloud's GDPR data export of your own account (likes list),
  (b) the "unofficial" api-v2 (fragile ToS-gray — flag, prefer not).
- If API access lands: the crawler generalizes beautifully — a second
  `SPOTIFY_API_BASE_URL`-style config, new handlers for SC response shapes,
  same queue/dedup/Neo4j spine (the mock/base-URL work of Phase 0 was
  accidentally the multi-platform foundation).
- SC is *the* source for: unreleased edits (DJ gold), who-reposts-whom
  (a social adjacency signal Spotify lost with related-artists!), and the
  indie-artist frontier plan 01 can't see.

### Phase X — cross-platform synthesis

- "Owned vs streamed" coverage: which liked Songs do I own as files (DJ-able)?
- Discovery reinforcement: an artist adjacent on Spotify (plan 01) whose SC
  account you already follow = strong signal.
- The platform-agnostic altitude in Bloom: Song-level, platform-colored.

## Task breakdown

| # | Task | Phase | Done when |
|---|------|-------|-----------|
| T-L1 | LocalFile model + scanner (hash, mutagen tags, incremental) | L | Library scanned; re-scan is a no-op |
| T-L2 | ISRC/tag-match resolver → Song links | L | Coverage report: % linked by method |
| T-L3 | AcoustID/Chromaprint + MusicBrainz resolver (rate-limited, cached) | L | Untagged files gain identity |
| T-L4 | Rekordbox XML import: BPM/key/cues → graph (feeds plan 04) | L | Cues visible on tracks you've already gridded |
| T-L5 | beets spike: evaluate as upstream tagger vs bespoke | L | Decision doc |
| T-S1 | **SoundCloud API access spike** — register, OAuth, endpoint inventory | S | Written verdict + working token or documented fallback |
| T-S2 | SC models + likes/followings crawler via the generalized pipeline | S | Your SC likes in the graph |
| T-S3 | SC↔Song matcher (expect low rates; report don't force) | S | Match report with confidence bands |
| T-X1 | Owned-vs-streamed + cross-platform discovery queries + MCP tools | X | "What should I buy/download next?" answerable |

## Risks & open questions

- **SoundCloud API access is the single biggest unknown** — hence spike-first,
  zero code before the verdict.
- Fingerprinting mixes/sets (60-min files) is meaningless — skip by duration
  gate; model mixes separately later if wanted (tracklist parsing is its own
  deep rabbit hole; explicitly out of scope).
- MusicBrainz coverage of deep indie EDM is thin — expected; the ladder
  degrades gracefully to platform-native nodes, which is the honest answer.
- File paths are machine-specific — store a `library_root` config and relative
  paths so the NAS move (or AWS sync) doesn't orphan 5k nodes.
