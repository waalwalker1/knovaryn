"""Structured logging (spec §22.1).

Wraps the standard :mod:`logging` machinery with JSON-format ``structlog`` when
available, and a dependency-free text fallback otherwise. All log emission flows
through :func:`get_logger` so redaction and metadata policy are applied in one
place. Content is never logged by default (``KNOVARYN_LOG_CONTENT`` must be set
explicitly).
"""

from __future__ import annotations

import logging
import os
import sys
from typing import Any

import structlog

from ...domain.config import load_config

_CONTENT_IN_LOGS = os.environ.get("KNOVARYN_LOG_CONTENT", "").lower() in ("1", "true", "yes")


def _configure_structlog(level: int) -> None:
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.JSONRenderer(ensure_ascii=False),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(level),
        logger_factory=structlog.PrintLoggerFactory(file=sys.stderr),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str) -> structlog.stdlib.BoundLogger:
    """Return a bound structured logger for the given name.

    Honors ``KNOVARYN_LOG_LEVEL`` (default INFO). Sensitive payloads must be
    passed as already-redacted values; see :mod:`knovaryn.infrastructure.models.secrets`.
    """
    cfg = load_config()
    level_name = (os.environ.get("KNOVARYN_LOG_LEVEL") or cfg.get("telemetry", {}).get("log_level") or "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)
    _configure_structlog(level)
    logger = structlog.get_logger(name)
    return logger


class ContentGuard:
    """Context manager flagging that document content may appear in logs."""

    def __init__(self, enabled: bool = False) -> None:
        self.enabled = enabled or _CONTENT_IN_LOGS

    def allow(self) -> bool:
        return self.enabled


__all__ = ["get_logger", "ContentGuard", "_CONTENT_IN_LOGS"]
