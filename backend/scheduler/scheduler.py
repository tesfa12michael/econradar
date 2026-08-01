"""AsyncIOScheduler + persistent SQLAlchemyJobStore (features 2.4 and 1.8).

Persistence demonstration (carried over from the Phase 1 checkpoint): a job is added
only if it is not already present in the store. On first boot it is created; on every
subsequent boot it is loaded from Postgres and the "already present" branch logs —
proving the schedule survived the restart rather than being recreated from scratch.

Per-source cadence follows each provider's own publication rhythm, so the pipeline
does not repeatedly re-fetch data that cannot have changed.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from config import settings
from db import normalize_db_url
from logging_config import get_logger
from scheduler.jobs import (
    run_bis_refresh,
    run_forecast_refresh,
    run_fred_refresh,
    run_imf_refresh,
    run_wb_databank_refresh,
    run_world_bank_refresh,
)

logger = get_logger(__name__)

WORLD_BANK_JOB_ID = "world_bank_refresh"
FORECAST_JOB_ID = "forecast_refresh"

#: Jobs that used to exist and no longer do. The store persists a job by its
#: ``module:qualname`` reference, so deleting the callable is not enough — the row
#: outlives the code. APScheduler would eventually drop such a job itself, on the
#: first attempt to reconstitute it, with a warning nobody reads; that is a silent
#: failure wearing a log line. Retiring it here is explicit, happens on the first
#: boot after deploy, and says why in the log.
RETIRED_JOB_IDS: frozenset[str] = frozenset(
    {
        # The weekly pgvector corpus rebuild. Decision #40 removed the corpus it
        # rebuilt; the cache sweep it carried moved to the forecast job.
        "embeddings_refresh",
    }
)


@dataclass(frozen=True, slots=True)
class ScheduledSource:
    job_id: str
    name: str
    func: Any
    trigger_kwargs: dict[str, Any]


def _schedule() -> list[ScheduledSource]:
    """Six jobs: five ingestions plus forecasting.

    Hours are staggered so a 1 vCPU box never runs two of them at once. The derived
    job comes last on Monday, after the weekly World Bank and IMF ingestions, so it
    projects from the freshest history.
    """
    return [
        ScheduledSource(
            WORLD_BANK_JOB_ID,
            "World Bank weekly refresh",
            run_world_bank_refresh,
            {
                "trigger": "cron",
                "day_of_week": settings.world_bank_refresh_cron_day_of_week,
                "hour": settings.world_bank_refresh_cron_hour,
            },
        ),
        ScheduledSource(
            "imf_refresh",
            "IMF WEO weekly refresh",
            run_imf_refresh,
            {"trigger": "cron", "day_of_week": "mon", "hour": 5},
        ),
        ScheduledSource(
            "fred_refresh",
            "FRED daily refresh",
            run_fred_refresh,
            {"trigger": "cron", "hour": 6},
        ),
        ScheduledSource(
            "bis_refresh",
            "BIS policy rates monthly refresh",
            run_bis_refresh,
            {"trigger": "cron", "day": 2, "hour": 7},
        ),
        ScheduledSource(
            "wb_databank_refresh",
            "World Bank GEM monthly refresh",
            run_wb_databank_refresh,
            {"trigger": "cron", "day": 3, "hour": 7},
        ),
        ScheduledSource(
            FORECAST_JOB_ID,
            "Forecast pre-computation (Chronos-2 via Modal)",
            run_forecast_refresh,
            {"trigger": "cron", "day_of_week": "mon", "hour": 9},
        ),
    ]


_scheduler: AsyncIOScheduler | None = None


def _retire_removed_jobs(scheduler: AsyncIOScheduler) -> list[str]:
    """Delete persisted jobs whose callable no longer exists. Returns what it removed.

    The mirror image of the add-only-if-absent rule above: persistence is the point
    of this job store, and persistence cuts both ways. A job added on one deploy
    outlives the code that defined it, so removing the function is only half of
    removing the job.
    """
    removed: list[str] = []
    for job_id in sorted(RETIRED_JOB_IDS):
        try:
            scheduler.remove_job(job_id)
        except Exception:
            continue  # not in the store: already retired, or never ran here
        removed.append(job_id)
        logger.info("Removed retired scheduled job %r from the persistent store.", job_id)
    return removed


def start_scheduler() -> AsyncIOScheduler | None:
    """Start the scheduler and ensure every source job exists. Returns None if
    scheduling is disabled or no database is configured (both are non-fatal)."""
    global _scheduler
    if _scheduler is not None:
        return _scheduler

    if not settings.scheduler_enabled:
        logger.info("Scheduler disabled (SCHEDULER_ENABLED=false).")
        return None
    if not settings.database_url:
        logger.warning("No DATABASE_URL — scheduler not started (jobs need a persistent store).")
        return None

    jobstore = SQLAlchemyJobStore(url=normalize_db_url(settings.database_url))
    scheduler = AsyncIOScheduler(
        jobstores={"default": jobstore},
        timezone="UTC",
        # max_instances=1 is what stops a slow run overlapping its own next trigger;
        # coalesce collapses a backlog of missed fires into a single catch-up run.
        job_defaults={"coalesce": True, "max_instances": 1, "misfire_grace_time": 3600},
    )
    scheduler.start()  # loads any persisted jobs from Postgres into memory

    _retire_removed_jobs(scheduler)

    for source in _schedule():
        if scheduler.get_job(source.job_id) is None:
            scheduler.add_job(
                source.func,
                id=source.job_id,
                name=source.name,
                replace_existing=False,
                **source.trigger_kwargs,
            )
            logger.info("Registered new scheduled job %r.", source.job_id)
        else:
            logger.info(
                "Scheduled job %r already present in persistent store — survived restart.",
                source.job_id,
            )

    _scheduler = scheduler
    return scheduler


def shutdown_scheduler() -> None:
    global _scheduler
    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
        _scheduler = None


def scheduler_status() -> str:
    if not settings.scheduler_enabled:
        return "disabled"
    if _scheduler is not None and _scheduler.running:
        return "running"
    return "stopped"


def scheduled_job_ids() -> list[str]:
    """Job ids currently registered — used by /status to report scheduler coverage."""
    if _scheduler is None:
        return []
    return sorted(job.id for job in _scheduler.get_jobs())
