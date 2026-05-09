from __future__ import annotations

import pandas as pd
import pytest

from quiverfeed.validation import assert_disclosure_dated


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
