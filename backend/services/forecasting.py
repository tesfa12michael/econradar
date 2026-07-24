"""ForecastingService — zero-shot forecasting cascade (feature 1.4, Phase 3).

Fallback cascade (authoritative — see architecture.md decision #4):
    Chronos-2 (mini, CPU)  →  TimesFM  →  Nixtla StatsForecast
Do NOT reorder without updating docs/architecture.md.
"""

from __future__ import annotations

from typing import ClassVar


class ForecastingService:
    MODEL_CASCADE: ClassVar[tuple[str, ...]] = ("chronos2", "timesfm", "statsforecast")

    async def predict(self, *args: object, **kwargs: object) -> None:
        raise NotImplementedError(
            "Forecasting lands in Phase 3 (feature 1.4). "
            "Cascade order is fixed here: " + " -> ".join(self.MODEL_CASCADE)
        )
