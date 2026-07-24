"""Minimal, dependency-free structured-ish logging setup.

Kept simple for Phase 1: a single console handler at the configured level, with a
consistent format across the API, connectors, and scheduler. Swapping in JSON logs
for production observability (Phase 4) is a one-function change here.
"""

from __future__ import annotations

import logging

from config import settings

_CONFIGURED = False

_FORMAT = "%(asctime)s %(levelname)-8s [%(name)s] %(message)s"


def configure_logging() -> None:
    """Idempotently configure the root logger from settings.log_level."""
    global _CONFIGURED
    if _CONFIGURED:
        return
    level = getattr(logging, settings.log_level.upper(), logging.INFO)
    logging.basicConfig(level=level, format=_FORMAT)
    # APScheduler is chatty at INFO; keep it at WARNING unless we're debugging.
    logging.getLogger("apscheduler").setLevel(
        logging.DEBUG if level <= logging.DEBUG else logging.WARNING
    )
    _CONFIGURED = True


def get_logger(name: str) -> logging.Logger:
    configure_logging()
    return logging.getLogger(name)
