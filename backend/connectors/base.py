"""BaseDataSourceConnector — the abstract ETL contract every data source implements.

Design goals:
  * `fetch()` and `normalize()` are provider-specific and DB-free, so they can be
    unit-tested against fixtures (and the live API) without a database.
  * `run()` is the shared template method: it fetches, normalizes, validates, and
    persists, recording a pipeline_runs row and logging every rejected record to
    etl_errors — never dropping a bad record silently (feature 1.2).
  * The pipeline is self-seeding: it upserts its data_sources row and the
    indicators_catalog rows it touches, so ingestion works on a freshly-migrated DB.
"""

from __future__ import annotations

import datetime as dt
import math
import uuid
from abc import ABC, abstractmethod
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, ClassVar

from sqlalchemy import text, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from db import get_session_factory
from logging_config import get_logger
from models import DataSource, EtlError, IndicatorCatalog, PipelineRun, TimeSeries
from schemas import TimeSeriesRecord

logger = get_logger(__name__)

_UPSERT_CHUNK = 500


class NormalizationError(Exception):
    """A raw record could not be converted to a TimeSeriesRecord."""


class ValidationError(Exception):
    """A normalized record failed a validation rule."""


class SkipRecord(Exception):
    """A raw record is legitimately empty (e.g. a null value for a year) — skip,
    don't count as a failure."""


@dataclass(slots=True)
class PipelineRunResult:
    run_id: uuid.UUID | None
    status: str
    records_fetched: int
    records_inserted: int
    records_failed: int
    records_skipped: int = 0


@dataclass(slots=True)
class _RejectedRecord:
    raw: Any
    error_type: str
    error_message: str


class BaseDataSourceConnector(ABC):
    #: data_sources.name — must match a row in that table.
    source_name: ClassVar[str]
    #: default base URL registered for the source.
    base_url: ClassVar[str]

    def __init__(self, session_factory: async_sessionmaker[AsyncSession] | None = None) -> None:
        self._session_factory = session_factory
        # code -> human-readable name, populated during fetch/normalize for catalog upsert.
        self._indicator_names: dict[str, str] = {}

    # ── provider-specific, DB-free (implement in subclasses) ──

    @abstractmethod
    async def fetch(self, **kwargs: Any) -> list[Any]:
        """Return raw provider records (already de-paginated)."""

    @abstractmethod
    def normalize(self, raw_record: Any) -> TimeSeriesRecord:
        """Convert one raw record to a TimeSeriesRecord.

        Raise NormalizationError for malformed input, or SkipRecord for a record
        that is valid but carries no observation (e.g. a null value).
        """

    def indicator_display_name(self, code: str) -> str:
        return self._indicator_names.get(code, code)

    # ── shared validation ──

    def validate(self, record: TimeSeriesRecord) -> TimeSeriesRecord:
        """Baseline validation (feature 1.2 hardens this in Phase 2). Raises ValidationError.

        Null values never reach here — normalize() raises SkipRecord for them and
        TimeSeriesRecord.value is a required float — so this guards the remaining
        numeric hazards: NaN/inf and implausible future dates.
        """
        if math.isnan(record.value) or math.isinf(record.value):
            raise ValidationError(f"value is not finite: {record.value!r}")
        if record.date.year > dt.date.today().year + 1:
            raise ValidationError(f"date is implausibly far in the future: {record.date}")
        return record.model_copy(update={"is_validated": True})

    # ── orchestration (DB-backed) ──

    async def run(self, **fetch_kwargs: Any) -> PipelineRunResult:
        """Fetch → normalize → validate → persist, with full run/error logging."""
        factory = self._session_factory or get_session_factory()
        run_id = await self._start_run(factory)
        logger.info("[%s] pipeline run %s started", self.source_name, run_id)

        fetched = 0
        good: list[TimeSeriesRecord] = []
        rejected: list[_RejectedRecord] = []
        skipped = 0

        try:
            raw_records = await self.fetch(**fetch_kwargs)
            fetched = len(raw_records)
            for raw in raw_records:
                try:
                    record = self.validate(self.normalize(raw))
                except SkipRecord:
                    skipped += 1
                except (NormalizationError, ValidationError) as exc:
                    rejected.append(_RejectedRecord(raw, type(exc).__name__, str(exc)))
                else:
                    good.append(record)

            inserted = await self._persist(factory, good)
            await self._log_errors(factory, run_id, rejected)
            status = self._status(fetched, inserted, len(rejected))
            await self._finish_run(factory, run_id, fetched, inserted, len(rejected), status)
        except Exception as exc:
            logger.exception("[%s] pipeline run %s failed hard", self.source_name, run_id)
            await self._log_errors(
                factory, run_id, [_RejectedRecord(None, type(exc).__name__, str(exc))]
            )
            await self._finish_run(factory, run_id, fetched, 0, len(rejected) + 1, "failed")
            return PipelineRunResult(run_id, "failed", fetched, 0, len(rejected) + 1, skipped)

        logger.info(
            "[%s] run %s done: status=%s fetched=%d inserted=%d failed=%d skipped=%d",
            self.source_name,
            run_id,
            status,
            fetched,
            inserted,
            len(rejected),
            skipped,
        )
        return PipelineRunResult(run_id, status, fetched, inserted, len(rejected), skipped)

    # ── internal helpers ──

    @staticmethod
    def _status(fetched: int, inserted: int, failed: int) -> str:
        if inserted == 0 and failed > 0:
            return "failed"
        if failed > 0:
            return "partial"
        return "success"

    async def _start_run(self, factory: async_sessionmaker[AsyncSession]) -> uuid.UUID:
        async with factory() as session:
            source_id = await self._ensure_source(session)
            run_id = (
                await session.execute(
                    pg_insert(PipelineRun)
                    .values(source_id=source_id, status="running")
                    .returning(PipelineRun.id)
                )
            ).scalar_one()
            await session.commit()
            return run_id

    async def _ensure_source(self, session: AsyncSession) -> uuid.UUID:
        stmt = (
            pg_insert(DataSource)
            .values(name=self.source_name, base_url=self.base_url)
            .on_conflict_do_update(
                index_elements=[DataSource.name], set_={"base_url": self.base_url}
            )
            .returning(DataSource.id)
        )
        return (await session.execute(stmt)).scalar_one()

    async def _ensure_indicators(
        self, session: AsyncSession, source_id: uuid.UUID, codes: Sequence[str]
    ) -> dict[str, uuid.UUID]:
        rows = [
            {
                "source_id": source_id,
                "indicator_code": code,
                "indicator_name": self.indicator_display_name(code),
            }
            for code in dict.fromkeys(codes)  # de-dupe, preserve order
        ]
        if not rows:
            return {}
        ins = pg_insert(IndicatorCatalog).values(rows)
        stmt = ins.on_conflict_do_update(
            index_elements=[IndicatorCatalog.source_id, IndicatorCatalog.indicator_code],
            set_={"indicator_name": ins.excluded.indicator_name},
        ).returning(IndicatorCatalog.id, IndicatorCatalog.indicator_code)
        result = await session.execute(stmt)
        return {code: id_ for id_, code in result.all()}

    async def _persist(
        self, factory: async_sessionmaker[AsyncSession], records: list[TimeSeriesRecord]
    ) -> int:
        if not records:
            return 0
        async with factory() as session:
            source_id = await self._ensure_source(session)
            id_by_code = await self._ensure_indicators(
                session, source_id, [r.indicator_code for r in records]
            )
            payload = [
                {
                    "country_code": r.country_code,
                    "indicator_id": id_by_code[r.indicator_code],
                    "source_id": source_id,
                    "date": r.date,
                    "value": r.value,
                    "is_validated": r.is_validated,
                }
                for r in records
            ]
            for start in range(0, len(payload), _UPSERT_CHUNK):
                chunk = payload[start : start + _UPSERT_CHUNK]
                ins = pg_insert(TimeSeries).values(chunk)
                await session.execute(
                    ins.on_conflict_do_update(
                        constraint="time_series_natural_key",
                        set_={
                            "value": ins.excluded.value,
                            "is_validated": ins.excluded.is_validated,
                            "ingested_at": text("now()"),
                        },
                    )
                )
            await session.commit()
            return len(payload)

    async def _log_errors(
        self,
        factory: async_sessionmaker[AsyncSession],
        run_id: uuid.UUID,
        rejected: list[_RejectedRecord],
    ) -> None:
        if not rejected:
            return
        async with factory() as session:
            await session.execute(
                pg_insert(EtlError),
                [
                    {
                        "pipeline_run_id": run_id,
                        "raw_record": _json_safe(r.raw),
                        "error_type": r.error_type,
                        "error_message": r.error_message,
                    }
                    for r in rejected
                ],
            )
            await session.commit()

    async def _finish_run(
        self,
        factory: async_sessionmaker[AsyncSession],
        run_id: uuid.UUID,
        fetched: int,
        inserted: int,
        failed: int,
        status: str,
    ) -> None:
        async with factory() as session:
            await session.execute(
                update(PipelineRun)
                .where(PipelineRun.id == run_id)
                .values(
                    completed_at=text("now()"),
                    records_fetched=fetched,
                    records_inserted=inserted,
                    records_failed=failed,
                    status=status,
                )
            )
            if status in ("success", "partial"):
                await session.execute(
                    update(DataSource)
                    .where(DataSource.name == self.source_name)
                    .values(last_successful_run=text("now()"))
                )
            await session.commit()


def _json_safe(raw: Any) -> dict | None:
    """etl_errors.raw_record is jsonb; coerce arbitrary raw payloads to something storable."""
    if raw is None:
        return None
    if isinstance(raw, dict):
        return raw
    return {"value": repr(raw)}
