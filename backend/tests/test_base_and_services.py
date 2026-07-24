"""Base-connector orchestration helpers + AI-service fallback-order guards."""

from __future__ import annotations

from connectors.base import BaseDataSourceConnector
from schemas import TimeSeriesRecord
from services import ForecastingService, LLMService, VLMService


class _Dummy(BaseDataSourceConnector):
    source_name = "dummy"
    base_url = "http://example.test"

    async def fetch(self, **kwargs):  # pragma: no cover - not exercised here
        return []

    def normalize(self, raw_record):  # pragma: no cover - not exercised here
        raise NotImplementedError


def test_run_status_classification() -> None:
    d = _Dummy()
    assert d._status(10, 10, 0) == "success"
    assert d._status(10, 8, 2) == "partial"
    assert d._status(10, 0, 3) == "failed"
    assert d._status(0, 0, 0) == "success"


def test_validate_sets_is_validated() -> None:
    import datetime as dt

    d = _Dummy()
    rec = TimeSeriesRecord(
        country_code="usa",
        indicator_code="X",
        source_name="dummy",
        date=dt.date(2020, 1, 1),
        value=2.5,
    )
    out = d.validate(rec)
    assert out.is_validated is True
    assert out.country_code == "USA"  # TimeSeriesRecord upper-cases ISO-3


def test_fallback_orders_are_pinned() -> None:
    # Guards the CLAUDE.md hard rule: this order is authoritative.
    assert ForecastingService.MODEL_CASCADE == ("chronos2", "timesfm", "statsforecast")
    assert LLMService.PROVIDER_ORDER == ("mistral", "groq", "openrouter")
    assert VLMService.PROVIDER_ORDER == ("gemini_flash", "qwen3_vl_openrouter")
