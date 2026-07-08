# Exploring the graph: a field guide

The crawl is done. There are twelve thousand tracks in Neo4j. **Now what?**

This is the guide for that moment. It assumes you know a little Cypher (or are
willing to paste queries and tweak numbers) and nothing else. Two ways to
explore: hand-written queries in the Neo4j browser (this page), or
conversationally through an AI assistant
([mcp_server/README.md](../mcp_server/README.md) — same graph, natural
language instead of Cypher).

## Getting your bearings (5 minutes)

Open the Neo4j browser (Neo4j Desktop → your database → Open). First, see
what exists:

```cypher
CALL db.labels();            // the node types
CALL db.relationshipTypes(); // the edge types
```

Then size it up:

```cypher
MATCH (t:Track)  WITH count(t) AS tracks
MATCH (al:Album) WITH tracks, count(al) AS albums
MATCH (ar:Artist) WITH tracks, albums, count(ar) AS artists
MATCH (u:User)
RETURN tracks, albums, artists, collect(u.id) AS users;
```

And look at one familiar corner — pick any artist you love:

```cypher
MATCH (a:Artist {name: "Caribou"})-[:CREATED]->(t:Track)
RETURN a, t LIMIT 50;
```

The browser draws the neighborhood. Click nodes, expand relationships, get a
feel for the shape: Artists point at Tracks and Albums via `CREATED`, Albums
point at Tracks via `CONTAINS`, you point at Tracks via `LIKED`. (The full
model, with stories: [data-model.md](data-model.md).)

**The one mental shift from tables to graphs:** you don't join — you draw the
shape you're looking for. "Artists I like who share a genre with Caribou" is
literally the path `(me)-[:LIKED]->()<-[:CREATED]-(artist)-[:SPOTIFY_CLASSIFIED_AS]->(genre)<-[:SPOTIFY_CLASSIFIED_AS]-(caribou)`.

## Ten questions worth asking your own library

Each of these is copy-pasteable. Replace names and numbers freely — breaking
these queries is the tutorial.

**1. Who do I actually listen to?** (by liked-track count)

```cypher
MATCH (u:User {id: "YOUR_ID"})-[:LIKED]->(t:Track)<-[:CREATED]-(a:Artist)
RETURN a.name, count(t) AS liked_tracks
ORDER BY liked_tracks DESC LIMIT 25;
```

**2. What do I sound like?** (genre profile)

```cypher
MATCH (u:User {id: "YOUR_ID"})-[:LIKED]->(t)<-[:CREATED]-(a:Artist)
      -[:SPOTIFY_CLASSIFIED_AS]->(g:Genre)
RETURN g.name, count(DISTINCT t) AS tracks
ORDER BY tracks DESC LIMIT 30;
```

**3. How has my taste moved over time?** (`added_at` lives on the LIKED edge)

```cypher
MATCH (u:User {id: "YOUR_ID"})-[l:LIKED]->(t)
RETURN substring(l.added_at, 0, 4) AS year, count(t) AS songs_liked
ORDER BY year;
```

**4. My deep cuts** — liked artists almost nobody follows:

```cypher
MATCH (u:User {id: "YOUR_ID"})-[:LIKED]->(t)<-[:CREATED]-(a:Artist)
WHERE a.popularity IS NOT NULL AND a.popularity < 25
RETURN a.name, a.popularity, count(t) AS my_likes
ORDER BY my_likes DESC LIMIT 25;
```

(If `popularity` is null everywhere, run the enrichment first:
`python -m application.discovery.backfill_artists` — see
[application/discovery/README.md](../application/discovery/README.md).)

**5. Who's hiding one hop away?** Artists you've *never* liked who
collaborated with several artists you love — your discovery frontier:

```cypher
MATCH (u:User {id: "YOUR_ID"})-[:LIKED]->()<-[:CREATED]-(mine:Artist)
WITH u, collect(DISTINCT mine) AS my_artists
UNWIND my_artists AS m
MATCH (m)-[:CREATED]->(t:Track)<-[:CREATED]-(candidate:Artist)
WHERE NOT candidate IN my_artists
WITH candidate, count(DISTINCT m) AS bridges, collect(DISTINCT m.name)[0..3] AS via
WHERE bridges >= 2
RETURN candidate.name, candidate.popularity, bridges, via
ORDER BY bridges DESC, candidate.popularity ASC LIMIT 25;
```

This is the query behind the whole discovery feature; the polished versions
live in [queries/discovery/](../application/graph_database/queries/discovery/)
and power the `adjacent-discoveries` playlist.

**6. Same song, how many times?** (after a mastering run — see
[application/mastering/README.md](../application/mastering/README.md))

```cypher
MATCH (s:Song)<-[v:VERSION_OF]-(t:Track)
WITH s, count(t) AS versions, collect(t.name) AS names
WHERE versions > 1
RETURN s.title, versions, names
ORDER BY versions DESC LIMIT 20;
```

**7. Which albums do I love whole vs. cherry-pick?**

```cypher
MATCH (u:User {id: "YOUR_ID"})-[:LIKED]->(t)<-[:CONTAINS]-(al:Album)
WITH al, count(t) AS liked, al.total_tracks AS total
WHERE total > 4
RETURN al.name, liked, total, toFloat(liked)/total AS ratio
ORDER BY ratio DESC, liked DESC LIMIT 25;
```

**8–10.** Longest liked tracks; remixes and their parents
(`MATCH (r:Song)-[:REMIX_OF]->(p:Song) RETURN r.title, p.title`); everything
you annotated (`MATCH (t:Track)-[:HAS_CUE|HAS_NOTE|HAS_SECTION]->(x) RETURN t.name, x`).

## The shared music space (when a friend's library is loaded)

Once a second user is crawled ([multiplayer-runbook.md](multiplayer-runbook.md)),
the interesting object is the *overlap*. Five ready-made queries live in
[queries/overlap/](../application/graph_database/queries/overlap/) — they use
parameters, so set them once in the browser:

```
:param a => "YOUR_ID"
:param b => "THEIR_ID"
:param min_likes => 3
:param min_bridges => 2
```

Then open any file from that directory, paste, run:

| Query file | The question it answers |
|---|---|
| `shared_artists_weighted.cypher` | *Which artists do we both like — and both actually keep coming back to?* Ranked by the smaller of the two like-counts, so one-sided obsessions sink. |
| `liked_artist_jaccard.cypher` | *How similar are we, as one number?* 0 = nothing in common, 1 = identical artist sets. Library-size-normalized, so a huge library vs a small one is compared fairly. |
| `genre_radar_diff.cypher` | *Where do our genre profiles diverge most?* Shares, not raw counts. |
| `a_loves_b_never_heard.cypher` | *What do I love that you've never touched?* The "here's your homework" query — swap `$a`/`$b` to get homework in the other direction. |
| `bridge_playlist.cypher` | *What's new to __both__ of us but adjacent to __both__ our tastes?* Finds artists neither of you knows who collaborated with several artists each of you loves. The best first-date query in the pack. |

A nice session structure for exploring with the friend in the room:
**jaccard** first (one number to react to), **shared_artists_weighted** second
(the "obviously" and the "wait, you too?!" moments), **genre_radar_diff**
third (why you feel different), then **a_loves_b_never_heard** both directions
(exchange homework), and **bridge_playlist** last — pipe its output into a
real playlist with the `blend` generator
([application/playlists/README.md](../application/playlists/README.md)).

## Escalation paths when a question outgrows the browser

- **Repeatable analysis** → the query packs under
  [application/graph_database/queries/](../application/graph_database/queries/)
  are the curated, tested versions of everything above. Steal from them.
- **Conversational exploration** → the MCP server exposes `run_cypher_readonly`
  plus purpose-built tools (`find_artist`, `collaborators_of`,
  `discover_adjacent`) to Claude. You ask in English; it writes the Cypher.
- **Acting on findings** → the playlist generators turn queries into actual
  Spotify playlists, safely (dry-run default, managed-only writes).
