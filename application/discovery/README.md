# discovery/ — artist enrichment backfill

One job: fill in `popularity` and `followers` on Artist nodes after a crawl,
because discovery ranking ("show me *obscure* adjacent artists") needs those
numbers and the crawl's simplified artist objects don't carry them.

```bash
docker compose run --rm responses_write_to_neo4j \
    python3 -m application.discovery.backfill_artists
```

[backfill_artists.py](backfill_artists.py) finds Artists missing `popularity`,
batch-fetches them 50 at a time via `/v1/artists?ids=` (with the same
429/500 patience as the crawl engine), and updates the nodes in place.
~7,600 artists ≈ 152 API calls, a few minutes.

Note the *seeding* side of discovery — deciding which artists deserve a
discography crawl — lives in
[requests_factory.py](../requests_factory.py) behind the
`CRAWL_ARTIST_DISCOGRAPHIES` flag, and the crawl itself is ordinary pipeline
work. This folder is only the enrichment step. The end-to-end feature is
described in [docs/plans/01-adjacent-artist-discovery.md](../../docs/plans/01-adjacent-artist-discovery.md).
