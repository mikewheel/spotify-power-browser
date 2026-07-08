# mastering/ — one Song, many releases

Your library contains the same recording under several names — album cut,
radio edit, deluxe re-release, "2011 Remaster". Mastering rolls those up into
canonical `(:Song)` nodes so counting and exploring work at the level you
actually think in, without deleting any release-level truth.

## The workflow

```bash
# 1. (first time only) fetch missing ISRCs — the recording industry's serial numbers
python -m application.mastering.backfill

# 2. run the clustering job (idempotent; re-run after every crawl)
python -m application.mastering.run

# 3. read the review report
open data/mastering_review.md

# 4. fix any wrong merges/splits, then re-run step 2
$EDITOR secrets/mastering_overrides.yaml     # format: overrides.example.yaml
```

## How it decides two Tracks are the same Song

Strongest evidence wins, and your overrides beat everything:

1. **ISRC match** ([cluster.py](cluster.py)) — same serial number, same
   recording. Confidence 1.0.
2. **Spotify `linked_from`** — Spotify's own market-relinking. 0.95.
3. **Heuristic** — same normalized title + same primary artist + duration
   within 3 s. 0.85. Title normalization ([normalize.py](normalize.py)) strips
   suffixes like "– 2011 Remaster" / "(Deluxe)" and records what it stripped
   as the version `kind`.
4. **Manual overrides** ([overrides.py](overrides.py)) — forced merges and
   splits from `secrets/mastering_overrides.yaml`.

Two deliberate stances: **remix credits are never stripped** — a remix is a
different song, so it becomes its own Song with a `REMIX_OF` edge to the
parent; and **re-recordings ("Taylor's Version") stay separate Songs** — they
are different recordings, and that's the point of them.

## What it writes

`(:Song {id, title})` nodes (id = ISRC when unambiguous, else a stable hash),
exactly one `(:Track)-[:VERSION_OF {kind, method, confidence}]->(:Song)` per
Track, and `(:Song)-[:REMIX_OF]->(:Song)` edges. Re-runs re-point edges;
nothing is ever deleted. The graph shape is illustrated in
[docs/data-model.md](../../docs/data-model.md#story-2-five-releases-one-song-mastering).

[report.py](report.py) writes `data/mastering_review.md` after every run,
most-ambiguous clusters first — the human feedback loop that keeps the
heuristics honest.

Tests: `test_mastering_normalize.py` (the suffix rules, effectively the
spec), `test_mastering_clustering.py`, `test_mastering_overrides.py`,
`test_mastering_e2e.py`.
