"""The entity-mastering batch job (plan 03 T5/T6): offline, idempotent,
re-runnable after every crawl.

    python -m application.mastering.run

1. Read every non-local (:Track) (with sorted artist ids/names) from Neo4j.
2. Run the identity ladder (see cluster.py) with manual overrides applied
   last — overrides load from MASTERING_OVERRIDES_PATH (default:
   secrets/mastering_overrides.yaml; missing file = no overrides).
3. MERGE (:Song) + (:Track)-[:VERSION_OF {kind, confidence, method}]->(:Song)
   (exactly one per Track — reassignment re-points the edge, never deletes a
   Song) and (:Song)-[:REMIX_OF {confidence}]->(:Song).
4. Emit the ambiguity-sorted review report to data/mastering_review.md.

Not in the crawl path: run it by hand (or a one-off container) whenever the
graph has grown. Requires tracks to carry `isrc` — run
`python -m application.mastering.backfill` first after upgrading old graphs.
"""
import os

from application.config import APPLICATION_DIR, SECRETS_DIR
from application.graph_database.connect import connect_to_neo4j, execute_query_against_neo4j
from application.graph_database.initialize_database_environment import initialize_database_environment
from application.loggers import get_logger
from application.mastering.cluster import cluster_tracks
from application.mastering.overrides import load_overrides
from application.mastering.report import write_review_report

logger = get_logger(__name__)

MASTERING_QUERIES_DIR = APPLICATION_DIR / "graph_database" / "queries" / "mastering"
NEO4J_CREDENTIALS_FILE = SECRETS_DIR / "neo4j_credentials.yaml"
DEFAULT_OVERRIDES_PATH = SECRETS_DIR / "mastering_overrides.yaml"

# Keep UNWIND payloads a sane size for one transaction.
CLUSTER_WRITE_BATCH_SIZE = 500


def _read_query(filename):
    with open(MASTERING_QUERIES_DIR / filename, "r") as f:
        return f.read()


def overrides_path_from_env():
    return os.environ.get("MASTERING_OVERRIDES_PATH", str(DEFAULT_OVERRIDES_PATH))


def fetch_track_records(driver, database="neo4j"):
    """Read the clustering input records out of the graph."""
    records, _, _ = driver.execute_query(
        _read_query("fetch_tracks_for_mastering.cypher"), database_=database
    )
    return [record.data() for record in records]


def write_mastering_result(result, driver, database="neo4j"):
    """MERGE Songs + VERSION_OF (batched), then REMIX_OF edges."""
    clusters_param = [
        {
            "song_id": c.song_id,
            "title": c.title,
            "members": [
                {
                    "track_id": m.track_id,
                    "kind": m.kind,
                    "method": m.method,
                    "confidence": m.confidence,
                }
                for m in c.members
            ],
        }
        for c in result.clusters
    ]

    merge_clusters = _read_query("merge_song_clusters.cypher")
    for start in range(0, len(clusters_param), CLUSTER_WRITE_BATCH_SIZE):
        batch = clusters_param[start:start + CLUSTER_WRITE_BATCH_SIZE]
        logger.info(f"Writing Song clusters {start + 1}..{start + len(batch)} of {len(clusters_param)}")
        execute_query_against_neo4j(
            query=merge_clusters, driver=driver, database=database, clusters=batch
        )

    edges_param = [
        {
            "remix_song_id": e.remix_song_id,
            "parent_song_id": e.parent_song_id,
            "confidence": e.confidence,
        }
        for e in result.remix_edges
    ]
    if edges_param:
        execute_query_against_neo4j(
            query=_read_query("merge_remix_of.cypher"),
            driver=driver, database=database, edges=edges_param,
        )


def run_mastering(driver, database="neo4j", overrides_path=None, report_path=None):
    """The whole batch against an existing driver; returns the MasteringResult."""
    overrides = load_overrides(overrides_path or overrides_path_from_env())

    records = fetch_track_records(driver, database=database)
    logger.info(f"Fetched {len(records)} track records for mastering.")
    without_isrc = sum(1 for r in records if not r.get("isrc"))
    if without_isrc:
        logger.warning(
            f"{without_isrc}/{len(records)} tracks have no isrc — consider running "
            f"`python -m application.mastering.backfill` first."
        )

    result = cluster_tracks(records, overrides)
    for warning in result.warnings:
        logger.warning(warning)
    logger.info(
        f"Formed {len(result.clusters)} Songs "
        f"({len(result.multi_member_clusters)} multi-version) and "
        f"{len(result.remix_edges)} REMIX_OF edges."
    )

    write_mastering_result(result, driver, database=database)
    report_file = write_review_report(result, output_path=report_path)
    logger.info(f"Done. Review report: {report_file}")
    return result


def main():
    driver = connect_to_neo4j(NEO4J_CREDENTIALS_FILE)
    try:
        initialize_database_environment(driver=driver)  # Song.id uniqueness
        run_mastering(driver)
    finally:
        driver.close()


if __name__ == "__main__":
    main()
