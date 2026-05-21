import logging
import logging.config
import os


def configure_logging() -> None:
    level = os.getenv("LOG_LEVEL", "INFO").upper()
    log_file = os.getenv("LOG_FILE")
    log_format = os.getenv("LOG_FORMAT", "text")

    formatters: dict = {
        "text": {
            "format": "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
            "datefmt": "%Y-%m-%d %H:%M:%S",
        },
        "json": {
            "()": "_JsonFormatter",
        },
    }

    handlers: dict = {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": log_format if log_format in ("text", "json") else "text",
        },
    }

    if log_file:
        handlers["file"] = {
            "class": "logging.handlers.RotatingFileHandler",
            "filename": log_file,
            "maxBytes": 50 * 1024 * 1024,  # 50 MB
            "backupCount": 5,
            "formatter": log_format if log_format in ("text", "json") else "text",
            "encoding": "utf-8",
        }

    active_handlers = list(handlers.keys())

    logging.config.dictConfig(
        {
            "version": 1,
            "disable_existing_loggers": False,
            "formatters": {k: v for k, v in formatters.items() if k != "json"},
            "handlers": handlers,
            "root": {
                "level": level,
                "handlers": active_handlers,
            },
            "loggers": {
                "sqlalchemy.engine": {"level": "WARNING"},
                "httpx": {"level": "WARNING"},
                "httpcore": {"level": "WARNING"},
            },
        }
    )
