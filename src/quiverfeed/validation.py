from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pandas as pd

from .catalog import get_dataset


@dataclass(frozen=True, slots=True)
class PITValidationReport:
    dataset: str | None
    rows: int
    ok: bool
    available_before_event_rows: int
    missing_event_time: int
    missing_available_at: int
    median_lag: Any = None
    p90_lag: Any = None
    max_lag: Any = None
    errors: tuple[str, ...] = ()


def assert_disclosure_dated(df: pd.DataFrame) -> None:
    if "available_at" not in df.columns:
        raise ValueError("DataFrame is missing required 'available_at' column.")
    if df["available_at"].isna().any():
        null_count = int(df["available_at"].isna().sum())
        raise ValueError(f"'available_at' contains {null_count} null values.")
    if not pd.api.types.is_datetime64_any_dtype(df["available_at"]):
        raise ValueError("'available_at' must be a pandas datetime64 column.")


def validate_pit(
    df: pd.DataFrame,
    dataset: str | None = None,
    *,
    raise_on_error: bool = True,
) -> PITValidationReport:
    """Assert a frame is safe to use point-in-time.

    When `dataset` is provided and the catalog records that dataset has no
    advertised disclosure column (e.g. `lobbying`, `bill_summaries`), raise
    a specific error rather than the generic "missing available_at" — using
    those datasets PIT is a category error, not a missing-column bug.

    Also asserts the consistency invariant: where both columns are present,
    `available_at >= event_time`. A disclosure that predates the event is a
    sign of upstream data corruption.
    """
    report = _pit_report(df, dataset)

    if dataset is not None:
        meta = get_dataset(dataset)
        if meta is not None and meta.disclosure_col is None:
            message = (
                f"Dataset {dataset!r} has no advertised disclosure column; "
                "it cannot be used point-in-time. Use event_time for "
                "descriptive analysis only."
            )
            if raise_on_error:
                raise ValueError(message)
            return _with_report_error(report, message)

    if raise_on_error:
        assert_disclosure_dated(df)

    if report.available_before_event_rows:
        message = (
            f"{report.available_before_event_rows} rows have available_at < "
            "event_time, which violates the point-in-time invariant. Inspect "
            "those rows before use."
        )
        if raise_on_error:
            raise ValueError(message)
        return _with_report_error(report, message)

    return report


def _pit_report(df: pd.DataFrame, dataset: str | None) -> PITValidationReport:
    rows = int(len(df))
    event = _coerce_datetime_series(df, "event_time")
    available = _coerce_datetime_series(df, "available_at")

    missing_event_time = rows if event is None else int(event.isna().sum())
    missing_available_at = rows if available is None else int(available.isna().sum())
    available_before_event_rows = 0
    median_lag = None
    p90_lag = None
    max_lag = None

    if event is not None and available is not None:
        both = pd.DataFrame({"event_time": event, "available_at": available}).dropna()
        if not both.empty:
            invalid = both["available_at"] < both["event_time"]
            available_before_event_rows = int(invalid.sum())
            lags = both["available_at"] - both["event_time"]
            if not lags.empty:
                median_lag = lags.quantile(0.5)
                p90_lag = lags.quantile(0.9)
                max_lag = lags.max()

    errors: list[str] = []
    if missing_available_at:
        errors.append(f"missing available_at rows: {missing_available_at}")
    if available_before_event_rows:
        errors.append(
            f"available_at < event_time rows: {available_before_event_rows}"
        )

    return PITValidationReport(
        dataset=dataset,
        rows=rows,
        ok=not errors,
        available_before_event_rows=available_before_event_rows,
        missing_event_time=missing_event_time,
        missing_available_at=missing_available_at,
        median_lag=median_lag,
        p90_lag=p90_lag,
        max_lag=max_lag,
        errors=tuple(errors),
    )


def _coerce_datetime_series(df: pd.DataFrame, column: str) -> pd.Series | None:
    if column not in df.columns:
        return None
    return pd.to_datetime(df[column], utc=True, errors="coerce", format="mixed")


def _with_report_error(
    report: PITValidationReport,
    message: str,
) -> PITValidationReport:
    return PITValidationReport(
        dataset=report.dataset,
        rows=report.rows,
        ok=False,
        available_before_event_rows=report.available_before_event_rows,
        missing_event_time=report.missing_event_time,
        missing_available_at=report.missing_available_at,
        median_lag=report.median_lag,
        p90_lag=report.p90_lag,
        max_lag=report.max_lag,
        errors=(*report.errors, message),
    )
