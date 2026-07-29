"""AI service interfaces.

These are the authoritative definitions of the AI provider/model fallback order
(CLAUDE.md hard rule). The order lives in the ``*_ORDER`` / ``*_CASCADE`` class
constants below — do NOT reorder or modify without updating docs/architecture.md.

Implementations land in Phase 3; Phase 1 only fixes the contract and the order.
"""

from services.anomaly import Anomaly, Observation, detect
from services.anomaly_store import count_anomalies, refresh_anomalies
from services.forecasting import ForecastingService
from services.llm import LLMService
from services.vlm import VLMService

__all__ = [
    "Anomaly",
    "ForecastingService",
    "LLMService",
    "Observation",
    "VLMService",
    "count_anomalies",
    "detect",
    "refresh_anomalies",
]
