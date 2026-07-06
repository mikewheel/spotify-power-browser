"""One-off Cypher migration runner (plan 06 T1).

    python3 -m application.graph_database.migrations.run <migration> \
        [--me <spotify_user_id>] [--display-name <name>] [--param key=value ...]

<migration> is a file stem under this directory (e.g.
``0001_multiplayer_ownership``; the ``.cypher`` suffix is optional). The file
is split on ``;`` into statements (the query-pack convention: no literal
semicolons in comments) and executed in ONE transaction, so a migration either
fully applies or fully rolls back.

Standard params injected for every migration (extra params are harmless when a
statement doesn't reference them):
  $me            --me, defaulting to the primary user recorded by the
                 multi-user OAuth flow (secrets/users/.primary_user)
  $display_name  --display-name (null when omitted)
  $added_at      the current UTC time, ISO 8601
Arbitrary extras ride along via repeated --param key=value (values are strings).

Safety: a migration whose header marks it as a stub (the string
``DO NOT RUN`` — e.g. 0002, the deferred legacy-property cleanup) is refused
unless --force is passed.
"""
import argparse
from datetime import datetime, timezone
from pathlib import Path

from application.config import SECRETS_DIR
from application.graph_database.connect import connect_to_neo4j
from application.loggers import get_logger

logger = get_logger(__name__)

MIGRATIONS_DIR = Path(__file__).absolute().parent
NEO4J_CREDENTIALS_FILE = SECRETS_DIR / "neo4j_credentials.yaml"


def load_migration_statements(name, migrations_dir=MIGRATIONS_DIR):
    """Resolve a migration name to its non-empty Cypher statements."""
    stem = name[:-len(".cypher")] if name.endswith(".cypher") else name
    path = migrations_dir / f"{stem}.cypher"
    if not path.is_file():
        available = sorted(p.stem for p in migrations_dir.glob("*.cypher"))
        raise FileNotFoundError(
            f"No migration named {stem!r} in {migrations_dir} (available: {available})"
        )
    text = path.read_text()
    statements = [s.strip() for s in text.split(";") if s.strip()]
    return path, text, statements


def build_standard_params(me=None, display_name=None):
    """The params every migration receives (see module docstring)."""
    if me is None:
        # Lazy import: the token store belongs to the auth layer and needs no
        # secrets to import, but keeping the dependency out of module scope
        # lets this runner work standalone.
        from application.spotify_authentication.token_store import get_primary_user_id
        me = get_primary_user_id()
    return {
        "me": me,
        "display_name": display_name,
        "added_at": datetime.now(timezone.utc).isoformat(),
    }


def run_migration(driver, name, params, database="neo4j", force=False):
    """Execute one migration file transactionally. Returns per-statement
    (nodes_created, relationships_created, properties_set) counter tuples."""
    path, text, statements = load_migration_statements(name)
    if "DO NOT RUN" in text and not force:
        raise RuntimeError(
            f"{path.name} is marked as a deferred stub (DO NOT RUN). "
            f"Read its header; pass --force only when its preconditions hold."
        )

    logger.info(f"Running migration {path.name}: {len(statements)} statement(s)")
    counters = []
    with driver.session(database=database) as session:
        with session.begin_transaction() as tx:
            for i, statement in enumerate(statements, start=1):
                summary = tx.run(statement, params).consume()
                c = summary.counters
                counters.append((c.nodes_created, c.relationships_created, c.properties_set))
                logger.info(
                    f"  [{i}/{len(statements)}] nodes +{c.nodes_created}, "
                    f"rels +{c.relationships_created}, props {c.properties_set}"
                )
            tx.commit()
    logger.info(f"Migration {path.name} committed.")
    return counters


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="python3 -m application.graph_database.migrations.run",
        description="Run a one-off Cypher migration transactionally.",
    )
    parser.add_argument("migration", help="migration file stem, e.g. 0001_multiplayer_ownership")
    parser.add_argument("--me", default=None,
                        help="Spotify user id for $me (default: the recorded primary user)")
    parser.add_argument("--display-name", default=None, help="display name for $display_name")
    parser.add_argument("--param", action="append", default=[], metavar="KEY=VALUE",
                        help="extra migration param (repeatable)")
    parser.add_argument("--force", action="store_true",
                        help="run a migration marked as a deferred stub")
    args = parser.parse_args(argv)

    params = build_standard_params(me=args.me, display_name=args.display_name)
    for pair in args.param:
        key, sep, value = pair.partition("=")
        if not sep:
            parser.error(f"--param expects KEY=VALUE, got {pair!r}")
        params[key] = value

    if params["me"] is None and args.migration.startswith("0001"):
        parser.error(
            "0001 needs the user id the existing data belongs to: pass --me "
            "<spotify_user_id> (no primary user is recorded yet)."
        )

    driver = connect_to_neo4j(NEO4J_CREDENTIALS_FILE)
    try:
        run_migration(driver, args.migration, params, force=args.force)
    finally:
        driver.close()


if __name__ == "__main__":
    main()
