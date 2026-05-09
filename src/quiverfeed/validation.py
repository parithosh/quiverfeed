from __future__ import annotations

import pandas as pd


def assert_disclosure_dated(df: pd.DataFrame) -> None:
    if "available_at" not in df.columns:
        raise ValueError("DataFrame is missing required 'available_at' column.")
    if df["available_at"].isna().any():
        null_count = int(df["available_at"].isna().sum())
        raise ValueError(f"'available_at' contains {null_count} null values.")
    if not pd.api.types.is_datetime64_any_dtype(df["available_at"]):
        raise ValueError("'available_at' must be a pandas datetime64 column.")
