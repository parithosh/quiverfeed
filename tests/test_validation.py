from __future__ import annotations

import pandas as pd
import pytest

from quiverfeed.validation import assert_disclosure_dated, validate_pit


def test_passes_when_available_at_is_a_clean_datetime_column():
    df = pd.DataFrame({"available_at": pd.to_datetime(["2024-01-01"], utc=True)})
    assert_disclosure_dated(df)


def test_missing_available_at_raises():
    with pytest.raises(ValueError, match="missing required 'available_at'"):
        assert_disclosure_dated(pd.DataFrame({"x": [1]}))


def test_null_values_raise():
    df = pd.DataFrame(
        {"available_at": pd.to_datetime([None, "2024-01-01"], utc=True)}
    )
    with pytest.raises(ValueError, match="null values"):
        assert_disclosure_dated(df)


def test_wrong_dtype_raises():
    df = pd.DataFrame({"available_at": ["2024-01-01"]})
    with pytest.raises(ValueError, match="datetime64"):
        assert_disclosure_dated(df)


def test_validate_pit_rejects_dataset_without_disclosure_column():
    df = pd.DataFrame(
        {
            "event_time": pd.to_datetime(["2024-01-01"], utc=True),
            "available_at": pd.to_datetime(["2024-01-10"], utc=True),
        }
    )
    with pytest.raises(ValueError, match="no advertised disclosure column"):
        validate_pit(df, dataset="lobbying")


def test_validate_pit_passes_for_consistent_frame():
    df = pd.DataFrame(
        {
            "event_time": pd.to_datetime(["2024-01-01"], utc=True),
            "available_at": pd.to_datetime(["2024-01-10"], utc=True),
        }
    )
    validate_pit(df, dataset="congresstrading")


def test_validate_pit_flags_disclosure_before_event():
    df = pd.DataFrame(
        {
            "event_time": pd.to_datetime(["2024-01-10"], utc=True),
            "available_at": pd.to_datetime(["2024-01-01"], utc=True),
        }
    )
    with pytest.raises(ValueError, match="violates"):
        validate_pit(df)
