"""ForecastingService — zero-shot forecasting cascade (feature 1.4, Phase 3).

Fallback cascade (authoritative — see architecture.md decisions #4 and #21):
    Chronos-2  →  TimesFM  →  Nixtla StatsForecast
Do NOT reorder without updating docs/architecture.md.

**Where each step runs** (decision #22). Chronos-2 and TimesFM execute on Modal —
model weights never touch the 1 vCPU / 2 GB VPS. StatsForecast runs *here*, in
process, and that placement is the point rather than a convenience: it is the only
step that survives a Modal outage, so the documented "guaranteed last resort" is
actually guaranteed. Its import is deferred to first use, so the numba/numpy stack
costs nothing until the day it is needed.

The service is pure numerics: it takes a list of floats and returns lists of
floats. Dates, country codes, indicator ids, caching and persistence all live in
`services/forecast_store.py`, which keeps this file unit-testable without a
database and keeps the VPS the single writer.
"""

from __future__ import annotations

import math
import statistics
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import ClassVar

from config import settings
from logging_config import get_logger
from services import modal_client
from services.modal_client import ModalUnavailable

logger = get_logger(__name__)


class ForecastUnavailable(RuntimeError):
    """No model in the cascade produced a usable forecast."""


class ForecastRejected(RuntimeError):
    """A model answered, but its output failed the plausibility guard."""


@dataclass(frozen=True, slots=True)
class ForecastResult:
    model_used: str
    median: list[float]
    lower: list[float]
    upper: list[float]
    # Which models were tried and why they gave way — surfaced on /status and in job
    # history so "the cascade falls back correctly" is observable, not asserted.
    attempts: tuple[str, ...] = ()

    @property
    def horizon(self) -> int:
        return len(self.median)


def seasonality_for(frequency: str | None) -> int:
    """Season length implied by `indicators_catalog.frequency`.

    Decision #18 established that column precisely so this choice is made from
    declared metadata rather than guessed from the shape of the dates.
    """
    return {"monthly": 12, "quarterly": 4, "annual": 1}.get((frequency or "").lower(), 1)


def horizon_for(frequency: str | None) -> int:
    """Forecast horizon in periods of the series' own frequency.

    features.md 1.4 says "12-month". Read literally that is 12 steps for a monthly
    series and *one* step for an annual one, which is not a forecast — and 12 steps
    on an annual series is a twelve-year projection, which is not a defensible one.
    So the horizon is set per frequency and each is configurable.
    """
    return {
        "monthly": settings.forecast_horizon_monthly,
        "quarterly": settings.forecast_horizon_quarterly,
        "annual": settings.forecast_horizon_annual,
    }.get((frequency or "").lower(), settings.forecast_horizon_annual)


def _finite(values: list[float]) -> bool:
    return all(isinstance(v, (int, float)) and math.isfinite(v) for v in values)


def _check_plausible(history: list[float], result: ForecastResult) -> None:
    """Reject nonsense before it reaches storage.

    features.md 1.4 names structural breaks — redenomination, war, COVID-era
    discontinuities — as able to produce a nonsensical forecast. The envelope here
    is deliberately very wide: it is meant to catch NaN, infinities and numerical
    blow-ups, not to second-guess a model that predicts a large but real move. That
    is the same boundary `connectors/validation.py` draws for ingestion — reject
    the impossible, not the surprising — and it bit this project before, when a
    1000% policy-rate ceiling threw away real Brazilian data.
    """
    if not (_finite(result.median) and _finite(result.lower) and _finite(result.upper)):
        raise ForecastRejected("forecast contains NaN or infinity")
    if not result.median:
        raise ForecastRejected("forecast is empty")

    spread = max(history) - min(history)
    scale = max(spread, abs(history[-1]), 1.0)
    limit = 20.0 * scale
    drift = max(abs(v - history[-1]) for v in result.median)
    if drift > limit:
        raise ForecastRejected(
            f"median drifts {drift:.4g} from the last observation, beyond {limit:.4g}"
        )


class ForecastingService:
    """The cascade. `MODEL_CASCADE` is the authoritative order (CLAUDE.md hard rule)."""

    MODEL_CASCADE: ClassVar[tuple[str, ...]] = ("chronos2", "timesfm", "statsforecast")

    def __init__(self) -> None:
        self._backends: dict[str, Callable[[list[float], int, int], Awaitable[ForecastResult]]] = {
            "chronos2": self._chronos2,
            "timesfm": self._timesfm,
            "statsforecast": self._statsforecast,
        }

    async def predict(
        self,
        values: list[float],
        *,
        horizon: int,
        seasonality: int = 1,
    ) -> ForecastResult:
        """Walk the cascade, returning the first plausible forecast.

        A model that errors, times out, or returns implausible numbers hands over to
        the next one. Only exhausting the cascade is a failure.
        """
        if len(values) < settings.forecast_min_observations:
            raise ForecastUnavailable(
                f"series has {len(values)} observations, "
                f"below the {settings.forecast_min_observations} needed to forecast"
            )
        if horizon < 1:
            raise ForecastUnavailable(f"horizon must be at least 1, got {horizon}")

        # More context than the models accept is trimmed to the most recent points
        # rather than sent and silently truncated at the far end.
        context = values[-settings.forecast_max_context :]

        attempts: list[str] = []
        for model in self.MODEL_CASCADE:
            try:
                result = await self._backends[model](context, horizon, seasonality)
                _check_plausible(context, result)
            except (ModalUnavailable, ForecastRejected, ImportError) as exc:
                attempts.append(f"{model}: {exc}")
                logger.warning("forecast cascade: %s unavailable — %s", model, exc)
                continue
            except Exception as exc:
                attempts.append(f"{model}: {type(exc).__name__}: {exc}")
                logger.exception("forecast cascade: %s raised", model)
                continue

            if attempts:
                logger.info("forecast cascade fell back to %s after %s", model, "; ".join(attempts))
            return ForecastResult(
                model_used=result.model_used,
                median=result.median,
                lower=result.lower,
                upper=result.upper,
                attempts=tuple(attempts),
            )

        raise ForecastUnavailable("every model in the cascade failed: " + "; ".join(attempts))

    # ── backends ─────────────────────────────────────────────────────────────

    async def _chronos2(self, values: list[float], horizon: int, _season: int) -> ForecastResult:
        payload = await modal_client.call("chronos2_forecast", values, horizon)
        return _from_modal(payload, "chronos2")

    async def _timesfm(self, values: list[float], horizon: int, _season: int) -> ForecastResult:
        payload = await modal_client.call("timesfm_forecast", values, horizon)
        return _from_modal(payload, "timesfm")

    async def _statsforecast(
        self, values: list[float], horizon: int, seasonality: int
    ) -> ForecastResult:
        """Local ARIMA/ETS baseline — the step that survives a Modal outage.

        Runs in a worker thread: AutoETS is CPU-bound and fitting it on the event
        loop would stall every other request on a 1 vCPU box for its duration.
        """
        import asyncio

        return await asyncio.to_thread(_statsforecast_sync, values, horizon, seasonality)


def _from_modal(payload: dict, expected_model: str) -> ForecastResult:
    """Validate a Modal response into a ForecastResult.

    Shape is checked here rather than trusted: Modal returns whatever the remote
    function returned, and a silently-short array would become a forecast_cache row
    with fewer points than its stated horizon.
    """
    try:
        median = [float(v) for v in payload["median"]]
        lower = [float(v) for v in payload["lower"]]
        upper = [float(v) for v in payload["upper"]]
    except (KeyError, TypeError, ValueError) as exc:
        raise ForecastRejected(f"malformed response from {expected_model}: {exc}") from exc
    if not (len(median) == len(lower) == len(upper)):
        raise ForecastRejected(
            f"{expected_model} returned ragged quantiles: {len(lower)}/{len(median)}/{len(upper)}"
        )
    return ForecastResult(
        model_used=payload.get("model") or expected_model, median=median, lower=lower, upper=upper
    )


def _statsforecast_sync(values: list[float], horizon: int, seasonality: int) -> ForecastResult:
    """Blocking AutoETS fit. Imported lazily — see the module docstring.

    An 80% prediction interval *is* the p10/p90 pair the schema stores, so the
    bounds are read straight off `level=[80]` rather than being derived from a
    residual assumption we would then have to justify.
    """
    import numpy as np
    from statsforecast.models import AutoETS

    y = np.asarray(values, dtype="float64")
    season = seasonality if seasonality > 1 and len(y) >= 2 * seasonality else 1
    model = AutoETS(season_length=season)
    out = model.forecast(y=y, h=horizon, level=[80])

    try:
        median = [float(v) for v in out["mean"]]
        lower = [float(v) for v in out["lo-80"]]
        upper = [float(v) for v in out["hi-80"]]
    except KeyError as exc:
        raise ForecastRejected(f"StatsForecast returned no {exc} band") from exc

    # AutoETS emits a point forecast with no interval for some degenerate series
    # (a constant one, for instance). A zero-width band is honest; a missing one is not.
    if not lower or not upper:
        spread = statistics.pstdev(values) if len(values) > 1 else 0.0
        lower = [v - 1.2816 * spread for v in median]
        upper = [v + 1.2816 * spread for v in median]

    return ForecastResult(model_used="statsforecast", median=median, lower=lower, upper=upper)
