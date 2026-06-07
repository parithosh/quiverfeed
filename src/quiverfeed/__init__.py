"""Point-in-time-safe Python client for Quiver Quantitative data."""

from ._version import __version__
from .catalog import (
    DATASETS,
    Dataset,
    all_datasets,
    register_dataset,
    unregister_dataset,
)
from .client import Client
from .diagnostics import DiagnoseReport, DatasetDiagnostic, canary, diagnose
from .errors import (
    AuthError,
    CatalogDriftError,
    CatalogDriftWarning,
    ParamIgnoredWarning,
    PlanRequiredError,
    QuiverFeedError,
    RateLimitError,
    ResponseShapeError,
    TruncatedResultError,
    TruncatedResultWarning,
    UnknownDatasetError,
)
from .validation import assert_disclosure_dated, validate_pit

__all__ = [
    "AuthError",
    "CatalogDriftError",
    "CatalogDriftWarning",
    "Client",
    "DATASETS",
    "Dataset",
    "DatasetDiagnostic",
    "DiagnoseReport",
    "ParamIgnoredWarning",
    "PlanRequiredError",
    "QuiverFeedError",
    "RateLimitError",
    "ResponseShapeError",
    "TruncatedResultError",
    "TruncatedResultWarning",
    "UnknownDatasetError",
    "all_datasets",
    "assert_disclosure_dated",
    "canary",
    "diagnose",
    "validate_pit",
    "register_dataset",
    "unregister_dataset",
    "__version__",
]
