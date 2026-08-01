"""Scheduled job callables (feature 2.4).

These MUST be module-level, importable functions: the SQLAlchemyJobStore persists
a job by its ``module:qualname`` reference, so a closure or a bound method would not
survive a restart.

Every job follows the same shape — ingest one source, then re-score that source's
series for anomalies (feature 1.8's "detected automatically as new data is ingested").
A source being unreachable must never crash the scheduler, so each job catches and
reports rather than propagating; APScheduler would otherwise keep firing into an
error and the run history would lose the detail of what actually failed.
"""

from __future__ import annotations

from typing import Any

from config import settings
from connectors import (
    BISConnector,
    FREDConnector,
    IMFConnector,
    WBDataBankConnector,
    WorldBankConnector,
)
from connectors.base import BaseDataSourceConnector
from db import get_session_factory
from logging_config import get_logger
from services import refresh_anomalies
from services.cache import prune_expired
from services.forecast_store import refresh_forecasts

logger = get_logger(__name__)


async def _ingest(
    connector: BaseDataSourceConnector, *, detect_anomalies: bool = True, **fetch_kwargs: Any
) -> dict:
    """Run one connector, then refresh anomalies for the source it just loaded."""
    source = connector.source_name
    try:
        result = await connector.run(**fetch_kwargs)
    except Exception as exc:
        # An unreachable source degrades one job, not the scheduler.
        logger.exception("[%s] scheduled ingestion failed", source)
        return {"source": source, "status": "failed", "error": f"{type(exc).__name__}: {exc}"}

    summary = {
        "source": source,
        "status": result.status,
        "fetched": result.records_fetched,
        "inserted": result.records_inserted,
        "failed": result.records_failed,
        "skipped": result.records_skipped,
    }

    if detect_anomalies and result.records_inserted:
        try:
            summary["anomalies"] = await refresh_anomalies(
                get_session_factory(), source_name=source
            )
        except Exception as exc:
            # Ingestion succeeded; losing the anomaly pass must not mark it failed.
            logger.exception("[%s] anomaly refresh failed after ingestion", source)
            summary["anomaly_error"] = f"{type(exc).__name__}: {exc}"

    logger.info("[%s] scheduled refresh complete: %s", source, summary)
    return summary


async def run_world_bank_refresh() -> dict:
    """World Bank WDI — weekly. Annual data, revised on a slow cadence."""
    return await _ingest(WorldBankConnector(), countries=settings.world_bank_countries)


async def run_imf_refresh() -> dict:
    """IMF WEO — weekly. Published twice yearly, so weekly is ample."""
    return await _ingest(IMFConnector())


async def run_fred_refresh() -> dict:
    """FRED — daily. Highest-frequency source; no-ops cleanly without an API key."""
    return await _ingest(FREDConnector())


async def run_bis_refresh() -> dict:
    """BIS policy rates — monthly, matching the publication frequency."""
    return await _ingest(BISConnector())


async def run_wb_databank_refresh() -> dict:
    """World Bank Global Economic Monitor — monthly."""
    return await _ingest(
        WBDataBankConnector(),
        countries=settings.world_bank_countries,
        start_period=settings.gem_start_period,
        end_period=settings.gem_end_period,
    )


async def run_forecast_refresh() -> dict:
    """Pre-compute forecasts for the covered countries (feature 1.4) — weekly.

    The sixth and last job, and the only one that is not an ingestion. It runs after
    the weekly ingestions so it forecasts the freshest history, and it is what keeps
    the Modal round trip off the request path: by the time anyone opens a profile
    page, the forecast is already in `forecast_cache`.

    Like the ingestion jobs it reports rather than raises — a Modal outage must
    leave the scheduler running and the site serving cached forecasts.

    It also carries the cache sweep, which it inherited from the RAG corpus job that
    decision #40 retired. Attaching it to an existing weekly job rather than adding
    a seventh is the same reasoning the corpus job carried it under; this is now the
    last job of the week, which is where a sweep belongs.
    """
    try:
        summary = await refresh_forecasts(get_session_factory())
    except Exception as exc:
        logger.exception("scheduled forecast refresh failed")
        return {"job": "forecast", "status": "failed", "error": f"{type(exc).__name__}: {exc}"}

    # Reclaim superseded AI responses while we are already here (decision #31).
    # Content-addressed keys mean a stale entry is never served again, but nothing
    # deletes it either; this is the only sweep in the system.
    pruned = 0
    try:
        async with get_session_factory()() as session:
            pruned = await prune_expired(session)
    except Exception:
        # A failed sweep is a housekeeping problem, not a forecasting problem: the
        # refresh above already succeeded and must still be reported as such.
        logger.exception("cache prune failed after the forecast refresh")

    logger.info("scheduled forecast refresh complete: %s (pruned %d cache rows)", summary, pruned)
    return {"job": "forecast", "status": "success", **summary, "cache_rows_pruned": pruned}
