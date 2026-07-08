---
name: master-library
description: Run entity mastering — dedupe re-releases/remasters/radio edits into canonical Song nodes, review the ambiguity report, apply manual overrides. Use when asked to master the library, dedupe songs, merge track versions, or fix a wrong song merge/split.
---

# Run entity mastering

Full explanation: **[application/mastering/README.md](../../../application/mastering/README.md)**;
the graph shapes it writes: [docs/data-model.md](../../../docs/data-model.md#story-2-five-releases-one-song-mastering).

The loop:

```bash
# 0. only if tracks lack ISRCs (report will warn):
docker compose run --rm responses_write_to_neo4j python3 -m application.mastering.backfill

# 1. cluster (idempotent, safe to re-run after every crawl)
docker compose run --rm responses_write_to_neo4j python3 -m application.mastering.run

# 2. review — most ambiguous clusters listed first
cat data/mastering_review.md
```

3. Wrong merge or split? Add the track ids to
   `secrets/mastering_overrides.yaml` (format:
   `application/mastering/overrides.example.yaml` — `merge:` groups and
   `split:` groups; overrides always win) and re-run step 1.

Knows-before-you-ask: remixes never merge with their parent (they get
`REMIX_OF` edges); "Taylor's Version" re-recordings stay separate Songs on
purpose; re-runs re-point edges and never delete anything.
