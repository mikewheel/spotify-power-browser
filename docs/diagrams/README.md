# System diagrams: Lucid vs Mermaid, side by side

Every diagram in this project exists twice, with the same content and
structure, so the two tools can be compared and the better one kept:

- **Lucid** — one document, ten pages, with real product logos:
  **[Spotify Power Browser — System Diagrams (C4)](https://lucid.app/lucidchart/092eb27a-7dda-48c1-9302-dcb6ab8ddde5/edit)**
- **Mermaid** — embedded in the docs, rendered by GitHub, using emoji as
  icons (GitHub's Mermaid can't load image icons).

| # | Diagram | Lucid page | Mermaid twin lives in |
|---|---|---|---|
| 1 | System context (C4 level 1) | 1 | [architecture.md](../architecture.md#level-1-the-system-in-its-world) |
| 2 | Containers — the Compose stack (C4 level 2) | 2 | [architecture.md](../architecture.md#level-2-the-containers) |
| 3 | Inside the pipeline (C4 level 3) | 3 | [architecture.md](../architecture.md#level-3-inside-the-pipeline) |
| 4 | The OAuth login flow | 4 | [auth.md](../auth.md#the-login-flow-step-by-step) |
| 5 | The graph data model | 5 | [data-model.md](../data-model.md#the-cast-of-characters) |
| 6 | One liked song's journey | 6 | [data-model.md](../data-model.md#story-1-one-liked-songs-journey-into-the-graph) |
| 7 | Delivery paths | 7 | [delivery.md](../delivery.md) |
| 8 | Monitoring map | 8 | [observability.md](../observability.md) |
| 9 | Test coverage map | 9 | [testing.md](../testing.md) |
| 10 | Exploring the graph through MCP | 10 | [mcp_server/README.md](../../mcp_server/README.md) |

## How to judge the comparison

Things to weigh while flipping between the two:

- **Fidelity:** Lucid pages carry real logos and precise layout; Mermaid gets
  emoji and auto-layout. For a portfolio page viewed on GitHub, Mermaid wins
  on zero-friction rendering; for a presentation or wiki, Lucid looks better.
- **Maintenance:** the Mermaid sources live *inside* the docs they
  illustrate — edit the doc, the diagram updates in the same PR, and it
  diffs like code. The Lucid document is regenerated from
  [gen_lucid.py](gen_lucid.py) (see below) or edited by hand in the app —
  either way it lives outside version control.
- **Linkability:** Mermaid diagrams appear inline where you're already
  reading; Lucid needs a click out (and a Lucid account for editing).

## Regenerating the Lucid document

[gen_lucid.py](gen_lucid.py) builds the entire ten-page document as Lucid
Standard Import JSON — layout coordinates, colors, logo URLs, every line and
label:

```bash
python3 docs/diagrams/gen_lucid.py     # writes spb_lucid.json next to cwd
```

Then import `spb_lucid.json` via Lucid's MCP tool
(`lucid_create_diagram_from_specification`, with assisted layout off) or the
Lucid Standard Import API. Note the logo icons use Google's favicon service
(`google.com/s2/favicons?domain=…`) because Lucid's importer renders raster
images reliably but silently drops SVG URLs.
