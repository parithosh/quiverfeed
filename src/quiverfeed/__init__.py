"""Point-in-time-safe Python client for Quiver Quantitative data."""

from typing import Any, Iterable

from ._version import __version__
from .catalog import (
    DATASETS,
    Dataset,
    all_datasets,
    resolve_dataset_name,
    register_dataset,
    unregister_dataset,
)
from .client import Client, FetchInfo, FetchResult
from .diagnostics import DiagnoseReport, DatasetDiagnostic, canary, diagnose
from .errors import (
    AuthError,
    CatalogDriftError,
    CatalogDriftWarning,
    ParamIgnoredWarning,
    ParamStrippedWarning,
    PlanRequiredError,
    QuiverFeedError,
    RateLimitError,
    ResponseShapeError,
    TruncatedResultError,
    TruncatedResultWarning,
    UnknownDatasetError,
)
from .validation import PITValidationReport, assert_disclosure_dated, validate_pit


def _active_client(client: Client | None = None, token: str | None = None) -> Client:
    if client is not None:
        return client
    return Client(token=token)


def fetch(
    dataset: str,
    *args: Any,
    client: Client | None = None,
    token: str | None = None,
    **kwargs: Any,
):
    """Convenience wrapper around ``Client(...).fetch(...)``."""
    return _active_client(client=client, token=token).fetch(dataset, *args, **kwargs)


def fetch_many(
    dataset: str,
    tickers: Iterable[str],
    *args: Any,
    client: Client | None = None,
    token: str | None = None,
    **kwargs: Any,
):
    """Convenience wrapper around ``Client(...).fetch_many(...)``."""
    return _active_client(client=client, token=token).fetch_many(
        dataset,
        tickers,
        *args,
        **kwargs,
    )


def profile(
    dataset: str,
    *args: Any,
    client: Client | None = None,
    token: str | None = None,
    **kwargs: Any,
) -> dict[str, Any]:
    """Convenience wrapper around ``Client(...).profile(...)``."""
    return _active_client(client=client, token=token).profile(dataset, *args, **kwargs)


def resolve(name: str) -> str:
    """Return the canonical catalog name for a dataset name or alias."""
    resolved = resolve_dataset_name(name)
    if resolved is None:
        raise UnknownDatasetError(name, list(all_datasets().keys()))
    return resolved

__all__ = [
    "AuthError",
    "CatalogDriftError",
    "CatalogDriftWarning",
    "Client",
    "DATASETS",
    "Dataset",
    "DatasetDiagnostic",
    "DiagnoseReport",
    "FetchInfo",
    "FetchResult",
    "PITValidationReport",
    "ParamIgnoredWarning",
    "ParamStrippedWarning",
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
    "fetch",
    "fetch_many",
    "profile",
    "resolve",
    "resolve_dataset_name",
    "validate_pit",
    "register_dataset",
    "unregister_dataset",
    "__version__",
]
