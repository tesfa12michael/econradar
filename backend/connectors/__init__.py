"""Data-source connectors. Every source subclasses BaseDataSourceConnector."""

from connectors.base import (
    BaseDataSourceConnector,
    NormalizationError,
    PipelineRunResult,
    SkipRecord,
)
from connectors.bis import BISConnector
from connectors.countries import UnknownCountryCode, to_alpha3
from connectors.dates import UnparseableDate, parse_period
from connectors.fred import FREDConnector
from connectors.http import SourceAPIError
from connectors.imf import IMFConnector
from connectors.validation import DuplicateRecord, ValidationError, ValueKind
from connectors.wb_databank import WBDataBankConnector
from connectors.world_bank import WorldBankConnector

#: Every source, keyed by its data_sources.name. Used by the scheduler and any
#: "refresh all sources" tooling so a new connector is registered in exactly one place.
CONNECTOR_REGISTRY: dict[str, type[BaseDataSourceConnector]] = {
    WorldBankConnector.source_name: WorldBankConnector,
    IMFConnector.source_name: IMFConnector,
    FREDConnector.source_name: FREDConnector,
    BISConnector.source_name: BISConnector,
    WBDataBankConnector.source_name: WBDataBankConnector,
}

__all__ = [
    "CONNECTOR_REGISTRY",
    "BISConnector",
    "BaseDataSourceConnector",
    "DuplicateRecord",
    "FREDConnector",
    "IMFConnector",
    "NormalizationError",
    "PipelineRunResult",
    "SkipRecord",
    "SourceAPIError",
    "UnknownCountryCode",
    "UnparseableDate",
    "ValidationError",
    "ValueKind",
    "WBDataBankConnector",
    "WorldBankConnector",
    "parse_period",
    "to_alpha3",
]
