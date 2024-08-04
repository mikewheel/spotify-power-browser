import yaml

from textwrap import indent, dedent

from neo4j import GraphDatabase

from application.loggers import get_logger

logger = get_logger(__name__)


def connect_to_neo4j(neo4j_credentials_file):
    """Reads in credentials from a YAML file, initializes the Neo4J driver object, and tests connectivity."""
    with open(neo4j_credentials_file, "r") as yaml_stream:
        try:
            neo4j_credentials = yaml.safe_load(yaml_stream)
        except yaml.YAMLError as exc:
            raise exc

    URI = neo4j_credentials['url']
    AUTH = (neo4j_credentials['username'], neo4j_credentials["password"])

    driver = GraphDatabase.driver(URI, auth=AUTH)
    driver.verify_connectivity()

    return driver


def execute_query_against_neo4j(query, driver, database="neo4j", **kwargs):
    summary = driver.execute_query(query, database_=database, **kwargs).summary
    logger.info(dedent(f'''
    Query: {indent(summary.query, '        ')}
    Time: {round(summary.result_available_after / 1000, 3)} seconds
    Nodes Created: {summary.counters.nodes_created}
    Nodes Deleted: {summary.counters.nodes_deleted}
    Edges Created: {summary.counters.relationships_created}
    Edges Deleted: {summary.counters.relationships_deleted}
    '''))


def execute_transaction_against_neo4j(queries, driver, database="neo4j"):

    with driver.session(database=database) as session:
        with session.begin_transaction() as tx:
            for query in queries:
                tx.run(query)
            tx.commit()
