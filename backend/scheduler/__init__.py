"""APScheduler wiring: an AsyncIOScheduler backed by a SQLAlchemyJobStore so jobs
survive restarts (architecture.md decision #5)."""

from scheduler.scheduler import (
    WORLD_BANK_JOB_ID,
    scheduled_job_ids,
    scheduler_status,
    shutdown_scheduler,
    start_scheduler,
)

__all__ = [
    "WORLD_BANK_JOB_ID",
    "scheduled_job_ids",
    "scheduler_status",
    "shutdown_scheduler",
    "start_scheduler",
]
