"""Lazy, process-wide Neo4j driver for the MCP server.

The driver is created on first use, not at import — the server must start (and
list its tools) even when Neo4j Desktop isn't running yet; only the first tool
call fails, with the driver's own connectivity error.
"""
from application.config import SECRETS_DIR
from application.graph_database.connect import connect_to_neo4j

_driver = None


def get_driver():
    global _driver
    if _driver is None:
        _driver = connect_to_neo4j(SECRETS_DIR / 'neo4j_credentials.yaml')
    return _driver


def close_driver():
    global _driver
    if _driver is not None:
        _driver.close()
        _driver = None
