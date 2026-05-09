"""Point-in-time-safe Python client for Quiver Quantitative data."""

from ._version import __version__
from .catalog import DATASETS, Dataset
from .client import Client
from .diagnostics import DiagnoseReport, DatasetDiagnostic, diagnose
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
from .validation import assert_disclosure_dated

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
    "assert_disclosure_dated",
    "diagnose",
    "__version__",
]
