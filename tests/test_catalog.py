from __future__ import annotations

import pytest

from quiverfeed.catalog import (
    DATASETS,
    Dataset,
    all_datasets,
    get_dataset,
    normalize_dataset_name,
    register_dataset,
    unregister_dataset,
)


def test_datasets_is_immutable_mapping():
    try:
        DATASETS["new"] = Dataset(  # type: ignore[index]
            name="new",
            path="/x",
            plan=None,
            event_col=None,
            disclosure_col=None,
        )
    except TypeError:
        return
    raise AssertionError("DATASETS should be read-only")


def test_normalize_dataset_name_strips_separators_and_case():
    assert normalize_dataset_name("Congress_Trading") == "congresstrading"
    assert normalize_dataset_name("congress-trading") == "congresstrading"
    assert normalize_dataset_name("Congress Trading") == "congresstrading"


def test_get_dataset_exact_and_forgiving():
    direct = get_dataset("congresstrading")
    assert direct is not None
    assert direct.path == "/beta/bulk/congresstrading"

    forgiving = get_dataset("Congress-Trading")
    assert forgiving is direct


def test_get_dataset_unknown_returns_none():
    assert get_dataset("nope") is None
    assert get_dataset("") is None


def test_dataset_defaults_returns_fresh_dict():
    dataset = Dataset(
        name="x",
        path="/x",
        plan=None,
        event_col=None,
        disclosure_col=None,
        default_params=(("k", "v"),),
    )
    first = dataset.defaults()
    assert first == {"k": "v"}
    first["k"] = "MUTATED"
    assert dataset.defaults() == {"k": "v"}


def test_known_datasets_have_required_attributes():
    for name, dataset in DATASETS.items():
        assert dataset.name == name
        assert dataset.path.startswith("/")
        # event_col and disclosure_col may both be None for some datasets,
        # but the catalog must still describe an event column where one exists.
        if dataset.disclosure_col is not None:
            assert dataset.event_col is not None


def test_register_dataset_extends_catalog():
    custom = Dataset(
        name="custom_alpha",
        path="/beta/bulk/custom_alpha",
        plan=None,
        event_col="Date",
        disclosure_col=None,
    )
    try:
        register_dataset(custom)
        assert get_dataset("custom_alpha") is custom
        assert "custom_alpha" in all_datasets()
        assert "custom_alpha" not in DATASETS  # built-ins untouched
    finally:
        unregister_dataset("custom_alpha")


def test_register_dataset_rejects_duplicate_without_replace():
    custom = Dataset(
        name="custom_dup",
        path="/x",
        plan=None,
        event_col=None,
        disclosure_col=None,
    )
    register_dataset(custom)
    try:
        with pytest.raises(ValueError, match="already registered"):
            register_dataset(custom)
        register_dataset(custom, replace=True)  # idempotent under replace
    finally:
        unregister_dataset("custom_dup")


def test_register_dataset_can_override_builtin():
    overridden = Dataset(
        name="congresstrading",
        path="/beta/bulk/congresstrading",
        plan="hobbyist",
        event_col="Traded",
        disclosure_col="Filed",
        notes="local override",
    )
    try:
        register_dataset(overridden, replace=True)
        assert get_dataset("congresstrading") is overridden
    finally:
        unregister_dataset("congresstrading")
        # Built-in re-emerges via all_datasets() merge.
        assert get_dataset("congresstrading").notes != "local override"
