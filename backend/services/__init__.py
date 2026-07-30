"""AI service interfaces.

These are the authoritative definitions of the AI provider/model fallback order
(CLAUDE.md hard rule). The order lives in the ``*_ORDER`` / ``*_CASCADE`` class
constants below — do NOT reorder or modify without updating docs/architecture.md.

Where each step *runs* is a separate question, answered by decisions #21 and #22:
Chronos-2 and TimesFM execute on Modal, StatsForecast executes here, and every LLM
and VLM provider is a remote HTTP API.
"""

from services.anomaly import Anomaly, Observation, detect
from services.anomaly_store import count_anomalies, refresh_anomalies
from services.forecast_store import Forecast, get_forecast, refresh_forecasts
from services.forecasting import ForecastingService, ForecastUnavailable
from services.llm import LLMService
from services.vlm import VLMService

__all__ = [
    "Anomaly",
    "Forecast",
    "ForecastUnavailable",
    "ForecastingService",
    "LLMService",
    "Observation",
    "VLMService",
    "count_anomalies",
    "detect",
    "get_forecast",
    "refresh_anomalies",
    "refresh_forecasts",
]
