"""Chronos-2 and TimesFM served from Modal (architecture decision #21).

Deploy with, from the repo root on a host holding Modal credentials::

    modal deploy backend/modal_app/forecast.py

Two independently-callable functions, one per model, so `ForecastingService` can
walk the documented cascade (Chronos-2 -> TimesFM -> StatsForecast) and have each
step fail on its own. Bundling both behind a single entrypoint would collapse two
cascade steps into one failure domain and make "which model produced this number"
unanswerable — and that field is written to `forecast_cache.model_used`.

**Numbers in, numbers out.** These functions accept a bare list of floats and
return bare lists of floats. They receive no dates, no country codes, no indicator
identifiers and no database credentials. Everything about *what* a series is, and
where its predictions are stored, stays on the VPS — which is what keeps decision
#21's "one writer, one enforcement point for groundedness" true rather than
aspirational.

Model weights are baked into the image at build time (`run_function` below), so a
cold start pays a container pull rather than a HuggingFace download, and a
HuggingFace outage cannot break inference.
"""

from __future__ import annotations

import modal

CHRONOS_MODEL = "amazon/chronos-2"
TIMESFM_MODEL = "google/timesfm-2.5-200m-pytorch"

# p10 / p50 / p90 — the three arrays forecast_cache stores (lower_bound,
# median_forecast, upper_bound). Kept here so both models are asked for the same
# quantiles and the caller never has to reconcile two conventions.
QUANTILE_LEVELS = [0.1, 0.5, 0.9]

app = modal.App("econradar-forecast")


def _bake_chronos() -> None:
    """Download Chronos-2 during the image build so it lives in the image layer."""
    from chronos import Chronos2Pipeline

    Chronos2Pipeline.from_pretrained("amazon/chronos-2", device_map="cpu")


def _bake_timesfm() -> None:
    import timesfm

    timesfm.TimesFM_2p5_200M_torch.from_pretrained("google/timesfm-2.5-200m-pytorch")


chronos_image = (
    modal.Image.debian_slim(python_version="3.12")
    .pip_install("chronos-forecasting>=2.0,<3", "numpy>=1.26", "torch>=2.4")
    .run_function(_bake_chronos)
)

timesfm_image = (
    modal.Image.debian_slim(python_version="3.12")
    .pip_install("timesfm[torch]>=2.0,<3", "numpy>=1.26")
    .run_function(_bake_timesfm)
)

# Containers are reused while warm, so a module-level cache turns the second call
# in a burst into pure inference. The forecast job runs weekly, so most calls are
# cold regardless — this is an optimisation for the burst, not the steady state.
_CHRONOS = None
_TIMESFM = None


def _quantile_response(model: str, lower: list, median: list, upper: list) -> dict:
    return {
        "model": model,
        "lower": [float(v) for v in lower],
        "median": [float(v) for v in median],
        "upper": [float(v) for v in upper],
    }


@app.function(image=chronos_image, gpu="T4", timeout=600, retries=1)
def chronos2_forecast(values: list[float], horizon: int) -> dict:
    """Zero-shot quantile forecast from Chronos-2. Primary model in the cascade."""
    global _CHRONOS
    import numpy as np

    if _CHRONOS is None:
        from chronos import Chronos2Pipeline

        _CHRONOS = Chronos2Pipeline.from_pretrained(CHRONOS_MODEL, device_map="cuda")

    quantiles, _mean = _CHRONOS.predict_quantiles(
        inputs=[np.asarray(values, dtype="float32")],
        prediction_length=horizon,
        quantile_levels=QUANTILE_LEVELS,
    )
    # (n_variates, prediction_length, n_quantiles) for the single series we sent.
    arr = quantiles[0].float().cpu().numpy()
    if arr.ndim == 3:
        arr = arr[0]
    if arr.shape != (horizon, len(QUANTILE_LEVELS)):
        raise RuntimeError(f"Chronos-2 returned unexpected shape {arr.shape}, want ({horizon}, 3)")

    return _quantile_response("chronos2", arr[:, 0], arr[:, 1], arr[:, 2])


@app.function(image=timesfm_image, gpu="T4", timeout=600, retries=1)
def timesfm_forecast(values: list[float], horizon: int) -> dict:
    """Quantile forecast from TimesFM 2.5. First fallback in the cascade.

    TimesFM's continuous quantile head emits ten channels per step — the mean
    followed by deciles q10..q90 — so p10/p50/p90 are channels 1, 5 and 9. The
    shape is asserted rather than assumed: silently reading the wrong channel would
    produce a plausible-looking forecast that is quietly the wrong quantile.
    """
    global _TIMESFM
    import numpy as np
    import timesfm

    if _TIMESFM is None:
        model = timesfm.TimesFM_2p5_200M_torch.from_pretrained(TIMESFM_MODEL)
        model.compile(
            timesfm.ForecastConfig(
                max_context=1024,
                max_horizon=256,
                normalize_inputs=True,
                use_continuous_quantile_head=True,
            )
        )
        _TIMESFM = model

    _point, quantile_forecast = _TIMESFM.forecast(
        horizon=horizon, inputs=[np.asarray(values, dtype="float32")]
    )
    arr = np.asarray(quantile_forecast)
    if arr.ndim == 3:
        arr = arr[0]
    if arr.shape != (horizon, 10):
        raise RuntimeError(f"TimesFM returned unexpected shape {arr.shape}, want ({horizon}, 10)")

    return _quantile_response("timesfm", arr[:, 1], arr[:, 5], arr[:, 9])


@app.local_entrypoint()
def smoke() -> None:
    """`modal run backend/modal_app/forecast.py` — proves both functions answer.

    A rising series with noise: any working model must return a median above the
    series minimum, which is enough to catch "deployed but returning garbage".
    """
    values = [100.0 + 2.0 * i + (i % 3) for i in range(60)]
    for name, fn in (("chronos2", chronos2_forecast), ("timesfm", timesfm_forecast)):
        try:
            out = fn.remote(values, 12)
            print(
                f"{name}: median[:3]={[round(v, 2) for v in out['median'][:3]]} n={len(out['median'])}"
            )
        except Exception as exc:
            print(f"{name}: FAILED {type(exc).__name__}: {exc}")
