"""Scheduled job callables.

These MUST be module-level, importable functions: the SQLAlchemyJobStore persists
a job by its ``module:qualname`` reference, so a closure or a bound method would not
survive a restart.
"""

from __future__ import annotations

from connectors import WorldBankConnector
from logging_config import get_logger

logger = get_logger(__name__)


async def run_world_bank_refresh() -> dict:
    """Ingest the configured World Bank indicators for the focus countries.

    Returns a small dict (JSON-friendly) so job execution history is legible.
    """
    connector = WorldBankConnector()
    result = await connector.run()
    logger.info(
        "world_bank_refresh complete: status=%s fetched=%d inserted=%d failed=%d skipped=%d",
        result.status,
        result.records_fetched,
        result.records_inserted,
        result.records_failed,
        result.records_skipped,
    )
    return {
        "status": result.status,
        "fetched": result.records_fetched,
        "inserted": result.records_inserted,
        "failed": result.records_failed,
        "skipped": result.records_skipped,
    }
