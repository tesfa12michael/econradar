"""World Bank DataBank connector — the Global Economic Monitor (source 15).

The World Bank v2 API fronts ~71 distinct collections behind one host, selected with
`?source=N`. `world_bank` reads source 2 (World Development Indicators, annual);
this connector reads **source 15, the Global Economic Monitor**, which is *monthly*
(docs/architecture.md decision #17).

That makes `wb_databank` a genuinely different dataset rather than a duplicate of
`world_bank`, and it is the connector that exercises sub-annual date handling against
a real provider. It reuses WorldBankConnector's pagination, retry and normalization —
including the `country.id` fallback that source 15 requires, since it leaves
`countryiso3code` empty.
"""

from __future__ import annotations

from typing import Any

from connectors.validation import ValueKind
from connectors.world_bank import WorldBankConnector
from logging_config import get_logger

logger = get_logger(__name__)

#: World Bank source id for the Global Economic Monitor.
GEM_SOURCE_ID = 15

#: Curated monthly GEM indicators, verified against the live API on 2026-07-29.
GEM_INDICATORS: dict[str, tuple[str, str, ValueKind]] = {
    "DPANUSSPB": (
        "Exchange rate, LCU per US$, period average",
        "LCU/US$",
        ValueKind.CURRENCY,
    ),
    # The N is *nominal*, distinguishing this from CPTOTSAXMZGY, the median-weighted
    # variant the World Bank computes for geographic aggregates and which is null for
    # most individual countries. Both are seasonally adjusted — the name the catalog
    # picked up at first ingestion says "not seas. adj.", which is an older World Bank
    # label the API no longer returns. Checked against the live indicator metadata on
    # 2026-08-01; migration 0011 records the corrected classification.
    "CPTOTSAXNZGY": (
        "CPI Price, % y-o-y, nominal, seas. adj.",
        "%",
        ValueKind.PERCENT_CHANGE,
    ),
    "IPTOTSAKD": (
        "Industrial production, constant US$, seasonally adjusted",
        "US$",
        ValueKind.CURRENCY,
    ),
    "DSTKMKTXD": ("Stock market index, US$", "index", ValueKind.INDEX),
}


class WBDataBankConnector(WorldBankConnector):
    source_name = "wb_databank"
    base_url = "https://api.worldbank.org/v2"

    def __init__(self, *args: Any, source_id: int = GEM_SOURCE_ID, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._source_id = source_id
        for code, (name, _unit, _kind) in GEM_INDICATORS.items():
            self._indicator_names[code] = name

    def value_kind(self, indicator_code: str) -> ValueKind | None:
        entry = GEM_INDICATORS.get(indicator_code)
        return entry[2] if entry else None

    async def fetch(
        self,
        indicator_codes: list[str] | None = None,
        countries: list[str] | str | None = None,
        start_period: str | None = None,
        end_period: str | None = None,
        **kwargs: Any,
    ) -> list[dict]:
        """Fetch monthly GEM series.

        GEM defaults to annual aggregates unless an explicit monthly date range is
        given, so `start_period`/`end_period` use the World Bank's own `YYYYMnn`
        spelling (e.g. `2015M01:2026M12`) to pin the request to monthly data.
        """
        codes = list(indicator_codes or GEM_INDICATORS)
        if start_period and end_period:
            kwargs["date_range"] = f"{start_period}:{end_period}"
        return await super().fetch(indicator_codes=codes, countries=countries, **kwargs)

    def _extra_params(self) -> dict[str, Any]:
        return {"source": self._source_id}

    def normalize(self, raw_record: dict):
        record = super().normalize(raw_record)
        entry = GEM_INDICATORS.get(record.indicator_code)
        if entry and record.unit is None:
            return record.model_copy(update={"unit": entry[1]})
        return record
