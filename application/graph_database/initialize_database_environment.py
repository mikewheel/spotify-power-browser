from pathlib import Path

from application.graph_database.connect import connect_to_neo4j, execute_transaction_against_neo4j

PROJECT_ROOT_DIR = Path(__file__).parent.parent.parent
QUERIES_DIR = PROJECT_ROOT_DIR / "application" / "graph_database" / "queries"
NEO4J_CREDENTIALS_FILE = PROJECT_ROOT_DIR / "secrets" / "neo4j_credentials.yaml"


def apply_uniqueness_constraints(driver, database="neo4j"):

    with open(QUERIES_DIR / "apply_uniqueness_constraints_to_nodes.cypher", "r") as f:
        query = f.read()

    queries = [q.strip() for q in query.split(";") if q.strip()]

    execute_transaction_against_neo4j(
        queries=queries,
        driver=driver,
        database=database,
    )


def initialize_database_environment(driver, database="neo4j"):
    apply_uniqueness_constraints(driver=driver, database=database)


if __name__ == "__main__":
    neo4j_driver = connect_to_neo4j(NEO4J_CREDENTIALS_FILE)
    apply_uniqueness_constraints(neo4j_driver)
