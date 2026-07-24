"""AsyncIOScheduler + persistent SQLAlchemyJobStore.

Persistence demonstration (Phase 1 checkpoint): the World Bank job is added only
if it is not already present in the store. On the first boot it is created; on every
subsequent boot it is loaded from Postgres and the "already present" branch logs —
proving the schedule survived the restart rather than being recreated from scratch.
"""

from __future__ import annotations

from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from config import settings
from db import normalize_db_url
from logging_config import get_logger
from scheduler.jobs import run_world_bank_refresh

logger = get_logger(__name__)

WORLD_BANK_JOB_ID = "world_bank_refresh"

_scheduler: AsyncIOScheduler | None = None


def start_scheduler() -> AsyncIOScheduler | None:
    """Start the scheduler and ensure the World Bank job exists. Returns None if
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
        job_defaults={"coalesce": True, "max_instances": 1, "misfire_grace_time": 3600},
    )
    scheduler.start()  # loads any persisted jobs from Postgres into memory

    if scheduler.get_job(WORLD_BANK_JOB_ID) is None:
        scheduler.add_job(
            run_world_bank_refresh,
            trigger="cron",
            day_of_week=settings.world_bank_refresh_cron_day_of_week,
            hour=settings.world_bank_refresh_cron_hour,
            id=WORLD_BANK_JOB_ID,
            name="World Bank weekly refresh",
            replace_existing=False,
        )
        logger.info("Registered new scheduled job %r.", WORLD_BANK_JOB_ID)
    else:
        logger.info(
            "Scheduled job %r already present in persistent store — survived restart.",
            WORLD_BANK_JOB_ID,
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
