// Adjacent-artist discovery (plan 01): the popularity-backfill worklist —
// every Artist not yet enriched with popularity/followers (nodes created by
// the pre-plan-01 crawl Cyphers, or frontier stubs whose enrichment sweep
// was interrupted).
MATCH (ar:Artist)
WHERE ar.popularity IS NULL
  AND ar.id IS NOT NULL
RETURN ar.id AS id
ORDER BY id
;
