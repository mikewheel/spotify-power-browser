# docs/ — start here

Reading order for someone new to the project:

1. **[architecture.md](architecture.md)** — how the pieces fit together
   (C4-style, widest view first). Read this one first.
2. **[data-model.md](data-model.md)** — what's in the graph, told through
   five stories (a liked song's journey, mastering, multiplayer, annotations,
   playlists).
3. **[exploring-the-graph.md](exploring-the-graph.md)** — the hands-on
   tutorial for when the crawl is done and you're staring at 12k tracks.

Then, by topic:

| Doc | Covers |
|---|---|
| [auth.md](auth.md) | The Spotify OAuth flow, token storage, refresh, scopes — and how it could be extracted as a standalone module |
| [delivery.md](delivery.md) | The four ways to run the software, the one-image build, worktree isolation, the (absent) CI, the (planned) AWS path |
| [observability.md](observability.md) | The five windows into a running crawl and how to interpret them; honest gaps |
| [testing.md](testing.md) | The four test layers, safety rails, coverage gaps |
| [multiplayer-runbook.md](multiplayer-runbook.md) | Step-by-step: adding a second person's library |
| [mock-spotify-service.md](mock-spotify-service.md) | Design doc for the mock + the AWS strategy |
| [diagrams/README.md](diagrams/README.md) | Index of every system diagram — Lucid and Mermaid twins, side by side |
| [plans/](plans/README.md) | The nine feature plans (six shipped, three pending) and the verified Spotify API surface |

Component-level detail lives next to the code — every folder has a README
(indexed in [architecture.md](architecture.md#where-the-code-lives)).
