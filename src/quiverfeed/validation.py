from __future__ import annotations

import pandas as pd

from .catalog import get_dataset


def assert_disclosure_dated(df: pd.DataFrame) -> None:
    if "available_at" not in df.columns:
        raise ValueError("DataFrame is missing required 'available_at' column.")
    if df["available_at"].isna().any():
        null_count = int(df["available_at"].isna().sum())
        raise ValueError(f"'available_at' contains {null_count} null values.")
    if not pd.api.types.is_datetime64_any_dtype(df["available_at"]):
        raise ValueError("'available_at' must be a pandas datetime64 column.")


def validate_pit(df: pd.DataFrame, dataset: str | None = None) -> None:
    """Assert a frame is safe to use point-in-time.

    When `dataset` is provided and the catalog records that dataset has no
    advertised disclosure column (e.g. `lobbying`, `bill_summaries`), raise
    a specific error rather than the generic "missing available_at" — using
    those datasets PIT is a category error, not a missing-column bug.

    Also asserts the consistency invariant: where both columns are present,
    `available_at >= event_time`. A disclosure that predates the event is a
    sign of upstream data corruption.
    """
    if dataset is not None:
        meta = get_dataset(dataset)
        if meta is not None and meta.disclosure_col is None:
            raise ValueError(
                f"Dataset {dataset!r} has no advertised disclosure column; "
                "it cannot be used point-in-time. Use event_time for "
                "descriptive analysis only."
            )

    assert_disclosure_dated(df)

    if "event_time" in df.columns:
        both = df.dropna(subset=["event_time", "available_at"])
        if not both.empty and (both["available_at"] < both["event_time"]).any():
            n_bad = int((both["available_at"] < both["event_time"]).sum())
            raise ValueError(
                f"{n_bad} rows have available_at < event_time, which violates "
                "the point-in-time invariant. Inspect those rows before use."
            )
