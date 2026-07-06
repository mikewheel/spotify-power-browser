"""Stderr logging for the MCP server.

The stdio transport owns stdout (it carries the JSON-RPC frames), so unlike
application/loggers.py — which streams to stdout for container logs — every
log line emitted by this package must go to stderr, or it would corrupt the
protocol stream and kill the client session.
"""
from logging import getLogger, INFO, StreamHandler, Formatter
from sys import stderr


def get_logger(logger_name, log_level=INFO):
    logger = getLogger(logger_name)
    logger.setLevel(log_level)
    logger.propagate = False  # https://stackoverflow.com/a/50910770/8857601

    default_handler = StreamHandler(stream=stderr)
    default_handler.setFormatter(Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s'))
    logger.addHandler(default_handler)

    return logger
