"""Data-source connectors. Every source subclasses BaseDataSourceConnector."""

from connectors.base import (
    BaseDataSourceConnector,
    NormalizationError,
    PipelineRunResult,
    SkipRecord,
)
from connectors.dates import UnparseableDate, parse_period
from connectors.validation import DuplicateRecord, ValidationError, ValueKind
from connectors.world_bank import WorldBankConnector

__all__ = [
    "BaseDataSourceConnector",
    "DuplicateRecord",
    "NormalizationError",
    "PipelineRunResult",
    "SkipRecord",
    "UnparseableDate",
    "ValidationError",
    "ValueKind",
    "WorldBankConnector",
    "parse_period",
]
