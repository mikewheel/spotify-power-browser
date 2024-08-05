from textwrap import dedent

import yaml
from neo4j import GraphDatabase

from application.config import NEO4J_HOSTNAME, NEO4J_PORT
from application.loggers import get_logger

logger = get_logger(__name__)


def connect_to_neo4j(neo4j_credentials_file):
    """Reads in credentials from a YAML file, initializes the Neo4J driver object, and tests connectivity."""
    with open(neo4j_credentials_file, "r") as yaml_stream:
        try:
            neo4j_credentials = yaml.safe_load(yaml_stream)
        except yaml.YAMLError as exc:
            raise exc

    URI = f'bolt://{NEO4J_HOSTNAME}:{NEO4J_PORT}'
    AUTH = (neo4j_credentials['username'], neo4j_credentials["password"])

    driver = GraphDatabase.driver(URI, auth=AUTH)
    driver.verify_connectivity()

    return driver


def execute_query_against_neo4j(query, driver, database="neo4j", **kwargs):
    summary = driver.execute_query(query, database_=database, **kwargs).summary
    logger.info(dedent(f'''
    Nodes Created: {summary.counters.nodes_created}
    Edges Created: {summary.counters.relationships_created}
    '''))


def execute_transaction_against_neo4j(queries, driver, database="neo4j"):

    with driver.session(database=database) as session:
        with session.begin_transaction() as tx:
            for query in queries:
                tx.run(query)
            tx.commit()
