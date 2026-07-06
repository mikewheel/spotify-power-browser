// Entity mastering (plan 03): the backfill worklist — every non-local Track
// that has not yet been enriched with its ISRC. (Local files have no Spotify
// catalog entry to refetch, so they are excluded — the plan's "0 tracks
// without isrc (minus is_local)" done-condition.)
MATCH (t:Track)
WHERE t.isrc IS NULL
  AND coalesce(t.is_local, false) = false
  AND t.id IS NOT NULL
RETURN t.id AS id
ORDER BY id
;
