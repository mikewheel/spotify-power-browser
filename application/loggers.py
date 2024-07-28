from logging import getLogger, INFO, StreamHandler, Formatter
from json import dumps
from sys import stdout


class StructuredLoggingFormatter(Formatter):
    """Constructs a JSON object from the log record, in order to enable structured logging."""
    def usesTime(self) -> bool:
        return True

    def format(self, record):
        # The call to the default implementation appends additional info, like well-formatted timestamps and tracebacks
        # So discard the string output, but keep the modifications to the LogRecord
        super().format(record)

        if record.stack_info:  # Not appended to the LogRecord default implementation, so add it here
            record.stack_text = self.formatStack(record.stack_info)

        # Skip serialization of certain JSON-unfriendly objects, such as Exception classes
        # https://stackoverflow.com/a/56138540/8857601
        default_serialize = lambda o: f"<<non-serializable: {type(o).__qualname__}>>"
        return dumps(record.__dict__, default=default_serialize)


def get_logger(logger_name, log_level=INFO):
    logger = getLogger(logger_name)
    logger.setLevel(log_level)
    logger.propagate = False  # https://stackoverflow.com/a/50910770/8857601

    default_handler = StreamHandler(stream=stdout)
    default_handler.setFormatter(Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s'))
    # structured_logging_formatter = StructuredLoggingFormatter()
    # default_handler.setFormatter(fmt=structured_logging_formatter)
    logger.addHandler(default_handler)

    return logger
