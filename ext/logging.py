import logging.config
from typing import Any, Union

LoggerConfig = Union[str, dict[str, Any]]


def setup_logging(log_file: str, loggers: dict[str, LoggerConfig] | None = None):
    config = {
        "version": 1,
        "disable_existing_loggers": False,
        "formatters": {
            "default": {
                "format": "{asctime} {levelname:<7} {name:<30} {message}",
                "style": "{",
            },
        },
        "handlers": {
            "file": {
                "class": "logging.FileHandler",
                "formatter": "default",
                "filename": log_file,
                "mode": "a",
            },
        },
        "loggers": {
            "": {
                "handlers": ["file"],
                "level": "DEBUG",
                "propagate": True,
            },
        },
    }

    if loggers is not None:
        for name, logger_config in loggers.items():
            match logger_config:
                case str(level):
                    config["loggers"][name] = {"level": level}
                case dict():
                    config["loggers"][name] = logger_config

    logging.config.dictConfig(config)
