"""Generate the Lucid Standard Import JSON for the Spotify Power Browser doc set.

Ten pages mirroring the Mermaid diagrams embedded in docs/. Hand-placed
layouts (no assisted layout) because logo images float next to their boxes.
"""
import json

ICONS = {
    "rabbitmq": "https://www.google.com/s2/favicons?domain=rabbitmq.com&sz=64",
    "redis": "https://www.google.com/s2/favicons?domain=redis.io&sz=64",
    "neo4j": "https://www.google.com/s2/favicons?domain=neo4j.com&sz=64",
    "spotify": "https://www.google.com/s2/favicons?domain=spotify.com&sz=64",
    "docker": "https://www.google.com/s2/favicons?domain=docker.com&sz=64",
    "python": "https://www.google.com/s2/favicons?domain=python.org&sz=64",
    "anthropic": "https://www.google.com/s2/favicons?domain=anthropic.com&sz=64",
    "pytest": "https://www.google.com/s2/favicons?domain=pytest.org&sz=64",
    "falcon": "https://www.google.com/s2/favicons?domain=falcon.readthedocs.io&sz=64",
}

# palette: (fill, stroke)
P = {
    "py":      ("#EEF5FB", "#3776AB"),
    "rabbit":  ("#FFE9D6", "#FF6600"),
    "redis":   ("#FFE3E0", "#FF4438"),
    "neo":     ("#E3EDF9", "#4581C3"),
    "spotify": ("#E2F7E9", "#1DB954"),
    "person":  ("#FDEBF3", "#C2185B"),
    "data":    ("#FFF7E0", "#D4A017"),
    "note":    ("#FFFDE7", "#B8A94A"),
    "ai":      ("#F3EFEA", "#D97757"),
    "plain":   ("#FFFFFF", "#555555"),
    "ghost":   ("#FAFAFA", "#999999"),
}

_id = [0]
def nid(prefix):
    _id[0] += 1
    return f"{prefix}{_id[0]}"

class Page:
    def __init__(self, pid, title):
        self.d = {"id": pid, "title": title, "shapes": [], "lines": []}

    def shape(self, typ, x, y, w, h, text=None, pal=None, dashed=False, **extra):
        s = {"id": nid("s"), "type": typ, "boundingBox": {"x": x, "y": y, "w": w, "h": h}}
        if text is not None:
            s["text"] = text
        if pal:
            fill, stroke = P[pal]
            s["style"] = {"fill": {"type": "color", "color": fill},
                          "stroke": {"color": stroke, "width": 2,
                                     "style": "dashed" if dashed else "solid"}}
        s.update(extra)
        self.d["shapes"].append(s)
        return s["id"]

    def box(self, x, y, w, h, text, pal="plain", icon=None, typ="rectangle", dashed=False):
        """A shape with an optional logo image floating above its top edge."""
        sid = self.shape(typ, x, y, w, h, text, pal, dashed)
        if icon:
            self.d["shapes"].append({
                "id": nid("i"), "type": "image",
                "boundingBox": {"x": x + w/2 - 16, "y": y - 40, "w": 32, "h": 32},
                "image": {"type": "image", "url": ICONS[icon]},
                "stroke": {"color": "#00000000", "width": 1, "style": "solid"},
            })
        return sid

    def container(self, x, y, w, h, title, pal="plain", icon=None, dashed=False):
        fill, stroke = P[pal]
        c = {"id": nid("c"), "type": "rectangleContainer",
             "boundingBox": {"x": x, "y": y, "w": w, "h": h},
             "containerTitle": {"text": title},
             "style": {"fill": {"type": "color", "color": fill + "55"},
                       "stroke": {"color": stroke, "width": 2,
                                  "style": "dashed" if dashed else "solid"}}}
        self.d["shapes"].insert(0, c)  # containers behind everything
        if icon:
            self.d["shapes"].append({
                "id": nid("i"), "type": "image",
                "boundingBox": {"x": x + w - 44, "y": y + 10, "w": 32, "h": 32},
                "image": {"type": "image", "url": ICONS[icon]},
                "stroke": {"color": "#00000000", "width": 1, "style": "solid"},
            })
        return c["id"]

    def note(self, x, y, w, h, text):
        return self.shape("note", x, y, w, h, text, "note")

    def line(self, a, b, label=None, dashed=False, color="#555555", both=False):
        l = {"id": nid("l"), "lineType": "elbow",
             "endpoint1": {"type": "shapeEndpoint",
                           "style": "arrow" if both else "none", "shapeId": a},
             "endpoint2": {"type": "shapeEndpoint", "style": "arrow", "shapeId": b},
             "stroke": {"color": color, "width": 2,
                        "style": "dashed" if dashed else "solid"}}
        if label:
            l["text"] = [{"text": label, "position": 0.5, "side": "middle"}]
        self.d["lines"].append(l)

pages = []

# ---------------------------------------------------------------- page 1
p = Page("p1", "1. System context (C4-1)")
you    = p.box(80, 80, 190, 90, "You\n(the tastemaker)", "person", typ="circle")
friend = p.box(320, 80, 190, 90, "A friend\n(second user)", "person", typ="circle")
ai     = p.box(1120, 80, 240, 80, "AI assistant\nClaude Desktop / Claude Code", "ai", icon="anthropic")
mach   = p.container(60, 300, 940, 460, "Your machine")
spb    = p.box(120, 380, 320, 130, "Spotify Power Browser\nDocker Compose stack:\ncrawler pipeline + OAuth service", "py", icon="docker")
neo    = p.box(620, 370, 300, 100, "Neo4j Desktop\nthe taste graph", "neo", icon="neo4j", typ="database")
mcp    = p.box(620, 560, 300, 100, "MCP server\nread-only graph access", "py", icon="python")
spot   = p.box(1120, 400, 260, 110, "Spotify Web API\napi.spotify.com\naccounts.spotify.com", "spotify", icon="spotify")
p.line(you, spb, "logs in once, watches the crawl")
p.line(friend, spb, "adds their library via /login")
p.line(spb, spot, "GET crawl + OAuth; guarded playlist writes")
p.line(spb, neo, "writes nodes and edges")
p.line(you, neo, "Cypher in the Neo4j browser", dashed=True)
p.line(ai, mcp, "questions via MCP tools")
p.line(mcp, neo, "read-only Cypher")
pages.append(p)

# ---------------------------------------------------------------- page 2
p = Page("p2", "2. Containers (C4-2): the Compose stack")
browser = p.box(90, 70, 200, 90, "You\n(browser)", "person", typ="circle")
spot    = p.box(1180, 70, 250, 90, "Spotify Web API", "spotify", icon="spotify")
dockerc = p.container(60, 260, 1010, 800, "Docker Compose project: spotify-power-browser", "py", icon="docker")
auth    = p.box(120, 350, 260, 110, "spotify_authentication\nFalcon web app :8000\nOAuth login + callback", "py", icon="falcon")
redis   = p.box(470, 350, 230, 100, "redis\ncrawled-URL memory\n+ login nonces", "redis", icon="redis", typ="database")
factory = p.box(120, 540, 260, 110, "requests_factory_start_crawls\nseeds the crawl, then exits", "py", icon="python")
rabbit  = p.box(470, 540, 230, 110, "rabbitmq\nmessage broker\nUI :15672", "rabbit", icon="rabbitmq")
engine  = p.box(790, 540, 250, 110, "api_call_engine\nevery Spotify GET:\nretry, backoff, refresh", "py", icon="python")
disk    = p.box(120, 750, 260, 100, "responses_write_to_disk\narchives raw JSON", "py", icon="python")
graphw  = p.box(430, 750, 260, 100, "responses_write_to_neo4j\ninserts nodes + edges", "py", icon="python")
follow  = p.box(750, 750, 260, 100, "responses_follow_links\nqueues neighbor URLs", "py", icon="python")
mock    = p.box(120, 930, 260, 90, "spotify_mock\n(profiles: test, mock)", "ghost", dashed=True)
tests   = p.box(430, 930, 260, 90, "tests\n(profile: test)", "ghost", dashed=True, icon="pytest")
hostc   = p.container(1130, 260, 360, 620, "Host machine")
neo     = p.box(1170, 340, 280, 110, "Neo4j Desktop\nbolt://host.docker.internal:7687", "neo", icon="neo4j", typ="database")
secrets = p.box(1170, 530, 280, 90, "./secrets\ntokens, credentials", "data", typ="storedData")
datad   = p.box(1170, 700, 280, 90, "./data\nresponses JSON archive", "data", typ="document")
p.line(browser, auth, "http://127.0.0.1:8000/login")
p.line(auth, redis, "single-use login nonces")
p.line(auth, secrets, "writes token files")
p.line(auth, engine, "healthcheck gates startup", dashed=True, color="#C2185B")
p.line(factory, rabbit, "publishes seed URLs")
p.line(factory, redis, "have we fetched this?", dashed=True)
p.line(rabbit, engine, "one request at a time")
p.line(engine, spot, "GET + bearer token")
p.line(engine, rabbit, "responses, fanned out x3")
p.line(rabbit, disk, "")
p.line(rabbit, graphw, "")
p.line(rabbit, follow, "")
p.line(follow, rabbit, "new URLs back on the queue")
p.line(follow, redis, "dedup check", dashed=True)
p.line(disk, datad, "")
p.line(graphw, neo, "MERGE nodes + edges")
p.line(factory, neo, "discography seed query", dashed=True)
p.line(mock, tests, "failure injection", dashed=True)
pages.append(p)

# ---------------------------------------------------------------- page 3
p = Page("p3", "3. Inside the pipeline (C4-3)")
env = p.note(60, 60, 360, 120,
             'Every message is a small JSON envelope:\n'
             '{ "request_url": "https://api.spotify.com/v1/me/tracks?offset=0",\n'
             '  "depth_of_search": 1, "user_id": "michael" }')
seeds  = p.box(60, 420, 220, 100, "requests_factory\nseed URLs", "py", icon="python")
redis  = p.box(330, 160, 220, 90, "Redis\nspb:crawled_urls", "redis", icon="redis", typ="database")
reqx   = p.box(330, 420, 230, 100, "spotify_api_requests\nqueue: make_api_call", "rabbit", icon="rabbitmq")
engine = p.box(650, 420, 250, 110, "api_call_engine\nGET - 429 backoff -\n500 retry - 401 refresh", "py", icon="python")
spot   = p.box(650, 150, 250, 100, "Spotify Web API", "spotify", icon="spotify")
respx  = p.box(990, 420, 240, 100, "spotify_api_responses\n3 bound queues", "rabbit", icon="rabbitmq")
disp   = p.box(1320, 420, 240, 110, "dispatcher\nURL pattern -> handler class\n(response_handlers/main.py)", "py")
disk   = p.box(1650, 260, 220, 90, "write_to_disk\ndata/responses/*.json", "data", typ="document")
graphw = p.box(1650, 430, 220, 90, "write_to_neo4j\nMERGE via Cypher", "neo", icon="neo4j", typ="database")
follow = p.box(1650, 600, 220, 90, "follow_links\nneighbors at depth - 1", "py")
p.line(seeds, redis, "url_is_new? (SADD)", dashed=True)
p.line(seeds, reqx, "publish")
p.line(reqx, engine, "consume")
p.line(engine, spot, "GET", both=True)
p.line(engine, respx, "response + envelope")
p.line(respx, disp, "consume x3 workers")
p.line(disp, disk, "")
p.line(disp, graphw, "")
p.line(disp, follow, "")
p.line(follow, reqx, "album/artist URLs at depth - 1")
p.line(follow, redis, "dedup check", dashed=True)
pages.append(p)

# ---------------------------------------------------------------- page 4
p = Page("p4", "4. The OAuth login flow")
steps = [
    ("You open http://127.0.0.1:8000/login\nand click Add a user", "person", None),
    ("/login/start mints a single-use state nonce\ninto Redis (TTL 10 min)", "redis", "redis"),
    ("303 redirect (never cached) to Spotify's\nconsent page - you log in, click Agree", "spotify", "spotify"),
    ("Spotify redirects back:\n/callback?code=...&state=...", "spotify", "spotify"),
    ("Callback consumes the nonce (GETDEL -\nvalid exactly once) or rejects with 400", "redis", "redis"),
    ("Exchanges the code for tokens\n(client id + secret)", "py", "falcon"),
    ("Asks GET /v1/me whose token this is -\nidentity is derived, never assumed", "spotify", "spotify"),
    ("Writes secrets/users/<their_id>/...\n(+ legacy mirror if primary user)", "data", None),
    ("Compose healthcheck sees the token file:\nthe gate opens, the crawl starts", "py", "docker"),
]
prev = None
for i, (txt, pal, icon) in enumerate(steps):
    col, row = i % 3, i // 3
    sid = p.box(80 + col * 480, 100 + row * 260, 380, 110, f"{i+1}. {txt}", pal, icon=icon)
    if prev:
        p.line(prev, sid)
    prev = sid
p.note(80, 880, 860, 90, "Full story, file layout, scopes table, and the primary-user mirror: docs/auth.md")
pages.append(p)

# ---------------------------------------------------------------- page 5
p = Page("p5", "5. The graph data model")
def circle(x, y, label, pal, w=150, h=150):
    return p.box(x, y, w, h, label, pal, typ="circle")
user  = circle(120, 400, "User\nid, display_name", "person")
track = circle(560, 400, "Track\nid, name, duration_ms,\nisrc, artist_ids", "spotify")
album = circle(560, 110, "Album\nid, name,\nrelease_date", "neo")
artist= circle(200, 110, "Artist\nid, name,\npopularity, followers", "neo")
genre = circle(900, 110, "Genre\nname", "ghost", w=120, h=120)
song  = circle(950, 400, "Song\nid (ISRC or hash),\ntitle", "py")
song2 = circle(1290, 400, "Song\n(remix parent)", "py", w=130, h=130)
note  = circle(430, 700, "Note\ntext, at_ms", "data", w=120, h=120)
cue   = circle(620, 700, "Cue\nat_ms, label", "data", w=120, h=120)
sect  = circle(810, 700, "Section\nkind, start_ms,\nend_ms", "data", w=130, h=130)
sect2 = circle(1060, 700, "Section\n(next)", "data", w=110, h=110)
mpl   = circle(120, 700, "ManagedPlaylist\nspotify_id, generator,\ntarget_snapshots", "ai", w=160, h=160)
p.line(user, track, "LIKED {added_at}")
p.line(user, mpl, "HAS_MANAGED")
p.line(album, track, "CONTAINS")
p.line(artist, track, "CREATED")
p.line(artist, album, "CREATED")
p.line(artist, genre, "SPOTIFY_CLASSIFIED_AS")
p.line(track, song, "VERSION_OF {kind, method, confidence}")
p.line(song, song2, "REMIX_OF {confidence}")
p.line(track, note, "HAS_NOTE")
p.line(track, cue, "HAS_CUE")
p.line(track, sect, "HAS_SECTION")
p.line(sect, sect2, "NEXT (time order)")
p.note(1180, 90, 300, 150, "Two layers:\nCatalog (Track/Album/Artist/Genre/Song) is shared - MERGEd on Spotify IDs.\nOwnership (User + LIKED / HAS_MANAGED) is per-person, on edges only.")
pages.append(p)

# ---------------------------------------------------------------- page 6
p = Page("p6", "6. One liked song's journey")
s1 = p.box(70, 300, 280, 120, 'Spotify answers\nGET /v1/me/tracks - one page,\n20 liked songs as JSON', "spotify", icon="spotify")
s2 = p.box(440, 300, 280, 120, "The envelope rides RabbitMQ\n{request_url, depth: 1,\nuser_id: michael}", "rabbit", icon="rabbitmq")
s3 = p.box(810, 300, 300, 120, "Handler:\nLikedSongsPlaylistResponseHandler\n(one class per endpoint)", "py", icon="python")
s4 = p.box(1210, 120, 300, 100, "Disk: data/responses/\nliked_songs/michael/0.json", "data", typ="document")
s5 = p.box(1210, 310, 300, 110, "Graph: MERGE Track, Album,\nArtist + LIKED, CONTAINS,\nCREATED edges", "neo", icon="neo4j", typ="database")
s6 = p.box(1210, 510, 300, 100, "Follow: album + artist URLs\nqueued at depth - 1", "py")
p.line(s1, s2); p.line(s2, s3)
p.line(s3, s4); p.line(s3, s5); p.line(s3, s6)
p.note(70, 520, 640, 200,
       'The fact "you liked it on 2023-10-15" lands on the LIKED edge (a fact about you).\n'
       '"The song is 3:20 long" lands on the Track (a fact about the world).\n\n'
       "MERGE on stable Spotify IDs means a re-crawl updates in place - nothing duplicates.\n"
       "x 12,547 tracks: the first full crawl took about 18 minutes.")
p.note(70, 90, 640, 150,
       '{ "added_at": "2023-10-15T14:22:00Z",\n'
       '  "track": { "id": "0VjIjW4GlUZAMYd2vXMwbk", "name": "Blinding Lights",\n'
       '             "external_ids": {"isrc": "USUG11904206"},\n'
       '             "album": {"name": "After Hours"}, "artists": [{"name": "The Weeknd"}] } }')
pages.append(p)

# ---------------------------------------------------------------- page 7
p = Page("p7", "7. Delivery paths")
src   = p.box(80, 340, 240, 100, "Source checkout\n(GitHub: source hosting only -\nno CI, no cloud)", "plain")
build = p.box(430, 340, 300, 110, "docker compose build\nONE image: spotify-power-browser\npython:3.13-slim + Poetry deps", "py", icon="docker")
live  = p.box(850, 90, 300, 100, "Live crawl\ndocker compose up\n(pauses at the OAuth gate)", "spotify", icon="spotify")
testr = p.box(850, 260, 300, 100, "Test suite\ndocker compose run --rm tests", "py", icon="pytest")
mockr = p.box(850, 430, 300, 110, "Offline mock crawl\ncompose -f compose.yaml\n-f docker-compose.mock.yml up", "ghost")
mcpr  = p.box(850, 620, 300, 100, "MCP server (on demand)\nscripts/mcp_server.sh\ndocker run --rm -i", "py", icon="anthropic")
wt    = p.note(430, 620, 340, 140, "Worktree isolation (SessionStart hook):\neach checkout gets its own IMAGE_TAG +\ncompose project, no host ports.\nLive crawls: primary checkout only.")
aws   = p.box(1290, 340, 280, 130, "AWS (planned, not built)\nmock service first on Fargate,\nthen the real pipeline\ndocs/mock-spotify-service.md", "ghost", dashed=True, typ="cloud")
p.line(src, build)
p.line(build, live); p.line(build, testr); p.line(build, mockr); p.line(build, mcpr)
p.line(build, aws, "someday", dashed=True)
pages.append(p)

# ---------------------------------------------------------------- page 8
p = Page("p8", "8. Monitoring map: which window answers which question")
qs = [
    ("Is it making progress?", 80),
    ("Is it done?", 380),
    ("Erroring or rate-limited?", 680),
    ("What has it fetched?", 980),
    ("Is data landing in the graph?", 1280),
]
qids = [p.box(x, 80, 260, 90, q, "note", typ="decision") for q, x in qs]
rmq  = p.box(80, 350, 260, 120, "RabbitMQ UI :15672\nQueues tab: backlog + rates.\nEmpty + zero rates = done", "rabbit", icon="rabbitmq")
logs = p.box(380, 350, 260, 120, "docker compose logs -f\napi_call_engine: GETs, 429s,\ntoken refreshes", "py", typ="document")
red  = p.box(680, 350, 260, 120, "Redis\nSCARD spb:crawled_urls\n= URLs fetched ever", "redis", icon="redis", typ="database")
disk = p.box(980, 350, 260, 120, "data/responses/\nfind ... | wc -l\none JSON per resource", "data", typ="document")
neo  = p.box(1280, 350, 260, 120, "Neo4j browser\nMATCH (t:Track)\nRETURN count(t)", "neo", icon="neo4j", typ="database")
for q, t in zip(qids, [rmq, logs, red, disk, neo]):
    p.line(q, t)
p.line(qids[0], logs, "", dashed=True)
p.line(qids[3], red, "", dashed=True)
p.note(80, 560, 700, 130, "Gaps to know about: no metrics/dashboards, no alerting, no completion\nsignal (queues empty IS done), plain-text logs lost on compose down.\nDetails + a healthy-crawl timeline: docs/observability.md")
pages.append(p)

# ---------------------------------------------------------------- page 9
p = Page("p9", "9. Test coverage map")
suite = p.container(60, 100, 700, 720, "Test suite: docker compose run --rm tests", "py", icon="pytest")
unit  = p.box(120, 180, 280, 110, "Pure unit tests\nconfig, dispatch, batching,\nnormalization, models", "py")
integ = p.box(120, 350, 280, 110, "Integration tests\noauth, refresh, dedup,\nqueues, MCP tools", "py")
e2e   = p.box(120, 520, 280, 110, "End-to-end tests\ncrawl -> handler -> graph\n(incl. two-user multiplayer)", "py")
resil = p.box(430, 350, 280, 110, "Resilience tests\n429 / 401 / 500 injection,\nconsumer reconnect", "py")
guard = p.note(430, 520, 290, 170, "Safety rails:\nsecrets mounted read-only;\nautouse fixture fails any test\nthat changes real secrets;\ntmp_path token stores")
mock  = p.box(880, 140, 260, 100, "spotify_mock\nfake Spotify +\nfailure injection", "ghost", icon="falcon")
red   = p.box(880, 310, 260, 90, "Redis", "redis", icon="redis", typ="database")
rmq   = p.box(880, 460, 260, 90, "RabbitMQ", "rabbit", icon="rabbitmq")
neo   = p.box(880, 610, 260, 100, "host Neo4j Desktop\n(tests skip politely if down)", "neo", icon="neo4j", typ="database")
p.line(integ, mock); p.line(integ, red); p.line(integ, rmq)
p.line(e2e, mock); p.line(e2e, neo); p.line(e2e, red)
p.line(resil, mock); p.line(resil, red)
pages.append(p)

# ---------------------------------------------------------------- page 10
p = Page("p10", "10. Exploring the graph through MCP")
you   = p.box(70, 300, 200, 90, "You:\n'who should I\nlisten to next?'", "person", typ="circle")
client= p.box(360, 300, 270, 100, "Claude Desktop / Claude Code\n(MCP client)", "ai", icon="anthropic")
sh    = p.box(720, 300, 260, 100, "scripts/mcp_server.sh\nregistered in .mcp.json /\ndesktop config", "plain", typ="document")
srv   = p.box(1070, 300, 270, 110, "mcp_server\ndocker run --rm -i\nstdio, read-only", "py", icon="docker")
neo   = p.box(1450, 300, 260, 110, "Neo4j Desktop\nhost.docker.internal:7687", "neo", icon="neo4j", typ="database")
p.line(you, client, "", both=True)
p.line(client, sh, "launches")
p.line(sh, srv, "")
p.line(client, srv, "MCP tools over stdio", both=True)
p.line(srv, neo, "read-only Cypher\nrow cap 200 - timeout 30s")
p.note(360, 520, 700, 170,
       "Tools: graph_schema - find_artist - find_track - collaborators_of -\n"
       "discover_adjacent - artist_completeness - run_cypher_readonly (escape hatch)\n"
       "Resources: schema://graph, queries://cookbook (incl. the two-user overlap pack)\n"
       "Guards: Neo4j READ_ACCESS sessions + write-keyword scan + row cap + timeout")
p.note(1070, 520, 340, 120,
       "ChatGPT Desktop: not supported -\nremote-HTTP-only client vs this local\nstdio server (mcp_server/README.md)")
pages.append(p)

doc = {"version": 1, "pages": [pg.d for pg in pages]}
out = json.dumps(doc, separators=(",", ":"))
with open("spb_lucid.json", "w") as f:
    f.write(out)
print(f"pages={len(pages)} shapes={sum(len(pg.d['shapes']) for pg in pages)} "
      f"lines={sum(len(pg.d['lines']) for pg in pages)} bytes={len(out)}")
