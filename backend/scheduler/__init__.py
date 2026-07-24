"""APScheduler wiring: an AsyncIOScheduler backed by a SQLAlchemyJobStore so jobs
survive Render restarts (architecture.md decision #5)."""

from scheduler.scheduler import (
    WORLD_BANK_JOB_ID,
    scheduler_status,
    start_scheduler,
    shutdown_scheduler,
)

__all__ = [
    "WORLD_BANK_JOB_ID",
    "scheduler_status",
    "start_scheduler",
    "shutdown_scheduler",
]
