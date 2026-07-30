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

import uuid
from abc import ABC, abstractmethod
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, ClassVar

from sqlalchemy import text, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from connectors.validation import (
    DuplicateRecord,
    ValidationError,
    ValueKind,
    validate_record,
)
from db import get_session_factory
from logging_config import get_logger
from models import DataSource, EtlError, IndicatorCatalog, PipelineRun, TimeSeries
from schemas import TimeSeriesRecord

logger = get_logger(__name__)

_UPSERT_CHUNK = 500

__all__ = [
    "BaseDataSourceConnector",
    "DuplicateRecord",
    "NormalizationError",
    "PipelineRunResult",
    "SkipRecord",
    "ValidationError",
]


class NormalizationError(Exception):
    """A raw record could not be converted to a TimeSeriesRecord."""


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
        # Partial fetch failures (e.g. one indicator of eight). Drained by run() into
        # etl_errors so a partial fetch is visible rather than looking like thin data.
        self._fetch_errors: list[_RejectedRecord] = []

    def record_fetch_error(self, context: str, exc: Exception) -> None:
        """Note that part of a fetch failed without abandoning the rest of it.

        Losing one indicator should degrade a run to "partial", not discard the seven
        that succeeded — but it must never pass silently as a short result either.
        """
        logger.warning("[%s] partial fetch failure (%s): %s", self.source_name, context, exc)
        self._fetch_errors.append(
            _RejectedRecord({"fetch_context": context}, type(exc).__name__, str(exc))
        )

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

    @property
    def is_configured(self) -> bool:
        """Whether this source has everything it needs to run (e.g. an API key).

        Overridden by FRED, the only keyed source. A connector that cannot run must not
        record a pipeline run at all: a "success" with zero rows would set
        `last_successful_run` and make /status claim a source is healthy when it has in
        fact never once been reached.
        """
        return True

    def value_kind(self, indicator_code: str) -> ValueKind | None:
        """Semantic kind of an indicator's values, enabling plausibility bounds.

        Returning None (the default) means "unknown units" — the record still gets the
        universal finite/date checks, but no bounds are asserted. Subclasses override
        this for indicators whose units they actually know; see connectors/validation.py
        for why guessing here would be worse than not bounding at all.
        """
        return None

    # ── shared validation (feature 1.2) ──

    def validate(self, record: TimeSeriesRecord) -> TimeSeriesRecord:
        """Per-record rules. Raises ValidationError; the caller logs it to etl_errors."""
        return validate_record(record, self.value_kind(record.indicator_code))

    # ── batch processing (pure — no database, no network) ──

    def process(
        self, raw_records: Sequence[Any]
    ) -> tuple[list[TimeSeriesRecord], list[_RejectedRecord], int]:
        """Normalize + validate a raw batch into ``(accepted, rejected, skipped)``.

        Deliberately DB-free so the whole accept/reject/skip decision surface — the part
        that decides what silently disappears and what is logged — can be unit-tested
        against fixtures without a database.
        """
        good: list[TimeSeriesRecord] = []
        rejected: list[_RejectedRecord] = []
        skipped = 0

        # Natural keys already accepted this run. A provider paging bug or an
        # overlapping re-run would otherwise collapse silently during upsert; here the
        # second copy is rejected loudly and lands in etl_errors like any other reject.
        seen: set[tuple[str, str, Any]] = set()

        for raw in raw_records:
            try:
                record = self.validate(self.normalize(raw))
                key = (record.country_code, record.indicator_code, record.date)
                if key in seen:
                    raise DuplicateRecord(f"duplicate observation for {key[0]}/{key[1]}/{key[2]}")
                seen.add(key)
            except SkipRecord:
                skipped += 1
            except (NormalizationError, ValidationError) as exc:
                rejected.append(_RejectedRecord(raw, type(exc).__name__, str(exc)))
            else:
                good.append(record)

        return good, rejected, skipped

    # ── orchestration (DB-backed) ──

    async def run(self, **fetch_kwargs: Any) -> PipelineRunResult:
        """Fetch → normalize → validate → persist, with full run/error logging."""
        # Checked before the session factory is built, not after: `get_session_factory()`
        # constructs the engine and raises without DATABASE_URL, so acquiring it first
        # made "skips without touching the database" false — an unconfigured source
        # failed on a machine that had no database rather than skipping cleanly. CI
        # caught it; every developer machine has a DATABASE_URL and hid it.
        if not self.is_configured:
            logger.warning(
                "[%s] not configured — skipping. No pipeline run recorded, so /status "
                "will not report this source as having succeeded.",
                self.source_name,
            )
            return PipelineRunResult(None, "skipped", 0, 0, 0, 0)

        factory = self._session_factory or get_session_factory()
        run_id = await self._start_run(factory)
        logger.info("[%s] pipeline run %s started", self.source_name, run_id)

        fetched = 0
        rejected: list[_RejectedRecord] = []
        self._fetch_errors = []

        try:
            raw_records = await self.fetch(**fetch_kwargs)
            fetched = len(raw_records)
            good, rejected, skipped = self.process(raw_records)
            # Partial fetch failures count as errors too, so status reflects them.
            rejected = [*self._fetch_errors, *rejected]
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
            return PipelineRunResult(run_id, "failed", fetched, 0, len(rejected) + 1, 0)

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
        self, session: AsyncSession, source_id: uuid.UUID, records: Sequence[TimeSeriesRecord]
    ) -> dict[str, uuid.UUID]:
        """Upsert the catalog rows for every indicator in this batch.

        Unit and frequency are carried on the observations themselves, so the catalog
        learns them from the data rather than needing a hand-maintained table per source.
        COALESCE keeps a previously-known unit/frequency when a later batch omits it.
        """
        by_code: dict[str, TimeSeriesRecord] = {}
        for record in records:  # first occurrence wins; preserves order
            by_code.setdefault(record.indicator_code, record)

        rows = [
            {
                "source_id": source_id,
                "indicator_code": code,
                "indicator_name": self.indicator_display_name(code),
                "unit": sample.unit,
                "frequency": sample.frequency,
            }
            for code, sample in by_code.items()
        ]
        if not rows:
            return {}
        ins = pg_insert(IndicatorCatalog).values(rows)
        stmt = ins.on_conflict_do_update(
            index_elements=[IndicatorCatalog.source_id, IndicatorCatalog.indicator_code],
            set_={
                "indicator_name": ins.excluded.indicator_name,
                "unit": text("coalesce(excluded.unit, indicators_catalog.unit)"),
                "frequency": text("coalesce(excluded.frequency, indicators_catalog.frequency)"),
            },
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
            id_by_code = await self._ensure_indicators(session, source_id, records)
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
                # Also flip is_active: the seed registers the non-Phase-1 sources as
                # inactive, so a source that is demonstrably ingesting would otherwise
                # keep reporting itself inactive on /status.
                await session.execute(
                    update(DataSource)
                    .where(DataSource.name == self.source_name)
                    .values(last_successful_run=text("now()"), is_active=True)
                )
            await session.commit()


def _json_safe(raw: Any) -> dict | None:
    """etl_errors.raw_record is jsonb; coerce arbitrary raw payloads to something storable."""
    if raw is None:
        return None
    if isinstance(raw, dict):
        return raw
    return {"value": repr(raw)}
