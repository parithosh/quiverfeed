from __future__ import annotations

from quiverfeed.errors import (
    AuthError,
    CatalogDriftError,
    PlanRequiredError,
    QuiverFeedError,
    RateLimitError,
    ResponseShapeError,
    TruncatedResultError,
    UnknownDatasetError,
)


def test_all_errors_subclass_quiverfeed_error():
    for cls in (
        AuthError,
        CatalogDriftError,
        PlanRequiredError,
        RateLimitError,
        ResponseShapeError,
        TruncatedResultError,
        UnknownDatasetError,
    ):
        assert issubclass(cls, QuiverFeedError)


def test_plan_required_error_includes_hint():
    err = PlanRequiredError(
        "congresstrading",
        "Upgrade required",
        hint_plan="hobbyist",
        path="/beta/bulk/congresstrading",
    )
    assert err.dataset == "congresstrading"
    assert err.hint_plan == "hobbyist"
    assert err.path == "/beta/bulk/congresstrading"
    assert "hobbyist" in str(err)
    assert "/beta/bulk/congresstrading" in str(err)


def test_plan_required_error_without_hint():
    err = PlanRequiredError("congresstrading", "Upgrade required")
    assert "Hint plan" not in str(err)


def test_rate_limit_error_message_uses_seconds():
    err = RateLimitError(retry_after_s=42)
    assert err.retry_after_s == 42.0
    assert "42" in str(err)


def test_catalog_drift_error_lists_missing_and_actual_columns():
    err = CatalogDriftError("ds", "Filed", ["A", "B"])
    assert err.missing_col == "Filed"
    assert err.actual_cols == ["A", "B"]
    assert "Filed" in str(err)
    assert "A" in str(err)


def test_truncated_result_error_records_max_pages():
    err = TruncatedResultError("ds", max_pages=5)
    assert err.max_pages == 5
    assert "max_pages=5" in str(err)


def test_unknown_dataset_error_lists_known():
    err = UnknownDatasetError("nope", ["a", "b"])
    assert err.name == "nope"
    assert "a" in str(err) and "b" in str(err)


def test_response_shape_error_describes_received_shape():
    err = ResponseShapeError("ds", "dict")
    assert err.dataset == "ds"
    assert err.shape == "dict"
    assert "dict" in str(err)
