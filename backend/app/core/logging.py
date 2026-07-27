"""Structured logging configuration.

Uses ``structlog`` so every log line carries the request id and other bound
context. In production the renderer emits JSON for log shippers; locally it
emits colourised key/value pairs.
"""

from __future__ import annotations

import logging
import sys
from typing import Any

import structlog

from app.core.config import Settings

#: Loggers whose records are routed through structlog's formatter.
_THIRD_PARTY_LOGGERS = ("uvicorn", "uvicorn.error", "uvicorn.access", "sqlalchemy.engine")


def configure_logging(settings: Settings) -> None:
    """Configure stdlib logging + structlog. Safe to call more than once."""
    level = getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO)

    shared_processors: list[Any] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.UnicodeDecoder(),
    ]

    renderer: Any = (
        structlog.processors.JSONRenderer()
        if settings.LOG_JSON
        else structlog.dev.ConsoleRenderer(colors=True)
    )

    # structlog hands the event dict to the stdlib logger, and the handler's
    # ProcessorFormatter below does the rendering. Rendering here as well would
    # emit every line twice, once nested inside the other.
    structlog.configure(
        processors=[
            *shared_processors,
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        wrapper_class=structlog.make_filtering_bound_logger(level),
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(
        structlog.stdlib.ProcessorFormatter(
            foreign_pre_chain=shared_processors,
            processors=[
                structlog.stdlib.ProcessorFormatter.remove_processors_meta,
                structlog.processors.format_exc_info,
                renderer,
            ],
        )
    )

    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level)

    for name in _THIRD_PARTY_LOGGERS:
        logger = logging.getLogger(name)
        logger.handlers = []
        logger.propagate = True

    # SQLAlchemy is noisy at INFO when echo is on; keep it at WARNING otherwise.
    logging.getLogger("sqlalchemy.engine").setLevel(
        logging.INFO if settings.DB_ECHO else logging.WARNING
    )


def get_logger(name: str | None = None) -> structlog.stdlib.BoundLogger:
    """Return a structlog logger bound to ``name``."""
    return structlog.stdlib.get_logger(name)
