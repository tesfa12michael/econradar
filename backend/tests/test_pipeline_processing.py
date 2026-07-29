"""Feature 1.2 — batch processing: nothing is dropped silently.

Every raw record must land in exactly one of three buckets: accepted, rejected (with
an etl_errors payload), or deliberately skipped. These tests pin that partition down.
"""

from __future__ import annotations

import datetime as dt

from connectors.base import BaseDataSourceConnector, NormalizationError, SkipRecord
from connectors.validation import ValueKind
from schemas import TimeSeriesRecord


class _Connector(BaseDataSourceConnector):
    """Raw record shape: {"code", "date", "value"} — value None means "no observation"."""

    source_name = "dummy"
    base_url = "http://example.test"

    async def fetch(self, **kwargs):  # pragma: no cover - not exercised here
        return []

    def value_kind(self, indicator_code: str) -> ValueKind | None:
        return ValueKind.PERCENT_SHARE if indicator_code == "SHARE" else None

    def normalize(self, raw_record: dict) -> TimeSeriesRecord:
        if "code" not in raw_record:
            raise NormalizationError("missing code")
        if raw_record["value"] is None:
            raise SkipRecord("no observation")
        return TimeSeriesRecord(
            country_code=raw_record.get("country", "NGA"),
            indicator_code=raw_record["code"],
            source_name=self.source_name,
            date=raw_record["date"],
            value=raw_record["value"],
        )


def _raw(code="X", value=1.0, date=dt.date(2020, 1, 1), **extra) -> dict:
    return {"code": code, "value": value, "date": date, **extra}


def test_every_record_lands_in_exactly_one_bucket() -> None:
    good, rejected, skipped = _Connector().process(
        [
            _raw(),  # accepted
            _raw(value=None),  # skipped
            {"date": dt.date(2020, 1, 1), "value": 1.0},  # rejected: no code
        ]
    )
    assert len(good) == 1
    assert len(rejected) == 1
    assert skipped == 1


def test_duplicate_within_a_batch_is_rejected_not_collapsed() -> None:
    """Upsert would silently swallow the second copy; it must be logged instead."""
    good, rejected, _ = _Connector().process([_raw(), _raw()])
    assert len(good) == 1
    assert len(rejected) == 1
    assert rejected[0].error_type == "DuplicateRecord"


def test_same_indicator_different_dates_is_not_a_duplicate() -> None:
    good, rejected, _ = _Connector().process(
        [_raw(date=dt.date(2020, 1, 1)), _raw(date=dt.date(2020, 2, 1))]
    )
    assert len(good) == 2
    assert rejected == []


def test_same_date_different_country_is_not_a_duplicate() -> None:
    good, rejected, _ = _Connector().process([_raw(country="NGA"), _raw(country="GHA")])
    assert len(good) == 2
    assert rejected == []


def test_rejected_records_carry_an_etl_errors_payload() -> None:
    """etl_errors needs raw_record, error_type and error_message on every row."""
    _, rejected, _ = _Connector().process([{"date": dt.date(2020, 1, 1), "value": 1.0}])
    reject = rejected[0]
    assert reject.error_type == "NormalizationError"
    assert reject.error_message
    assert reject.raw is not None


def test_implausible_value_is_rejected_with_a_validation_error() -> None:
    _, rejected, _ = _Connector().process([_raw(code="SHARE", value=1e12)])
    assert rejected[0].error_type == "ValidationError"


def test_one_bad_record_does_not_abort_the_batch() -> None:
    good, rejected, _ = _Connector().process(
        [_raw(code="A"), {"bad": True, "value": 1.0}, _raw(code="B")]
    )
    assert [r.indicator_code for r in good] == ["A", "B"]
    assert len(rejected) == 1


def test_status_reflects_error_count() -> None:
    c = _Connector()
    assert c._status(10, 10, 0) == "success"
    assert c._status(10, 8, 2) == "partial"
    assert c._status(10, 0, 3) == "failed"
