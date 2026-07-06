"""Entity mastering (plan 03): fold re-released track variants into canonical
(:Song) masters without ever destroying release-level (:Track) truth.

Layout:
    normalize.py  title normalization + variant-kind extraction (pure)
    cluster.py    the identity ladder on plain dicts (pure, no Neo4j)
    overrides.py  manual forced merge/split YAML loading
    report.py     human review report (markdown, ambiguity-sorted)
    run.py        the offline batch job: Neo4j read -> cluster -> Neo4j write
    backfill.py   batch refetch of tracks missing an ISRC (live API)
"""
