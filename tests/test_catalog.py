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
    assert get_dataset("congress_trades") is direct


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


def test_catalog_contains_current_hobbyist_public_surface():
    expected = {
        "congresstrading": (
            "/beta/bulk/congresstrading",
            "hobbyist",
            "Traded",
            "Filed",
        ),
        "politicians": (
            "/beta/bulk/congress/politicians",
            "hobbyist",
            None,
            None,
        ),
        "corporate_donors": (
            "/beta/bulk/corporatedonors",
            "hobbyist",
            "TransactionDate",
            "Uploaded",
        ),
        "trump_stock_trades": (
            "/beta/bulk/trumpstocktrades",
            "hobbyist",
            "Traded",
            "Filed",
        ),
        "gov_contracts_live": (
            "/beta/live/govcontracts",
            "hobbyist",
            None,
            None,
        ),
        "gov_contracts_all_live": (
            "/beta/live/govcontractsall",
            "hobbyist",
            "action_date",
            "Date",
        ),
        "gov_contracts_historical": (
            "/beta/historical/govcontractsall/{ticker}",
            "hobbyist",
            "action_date",
            "Date",
        ),
        "lobbying_live": (
            "/beta/live/lobbying",
            "hobbyist",
            "Date",
            None,
        ),
        "lobbying_historical": (
            "/beta/historical/lobbying/{ticker}",
            "hobbyist",
            "Date",
            None,
        ),
        "off_exchange_live": (
            "/beta/live/offexchange",
            "hobbyist",
            "Date",
            None,
        ),
        "off_exchange_historical": (
            "/beta/historical/offexchange/{ticker}",
            "hobbyist",
            "Date",
            None,
        ),
    }

    for name, (path, plan, event_col, disclosure_col) in expected.items():
        dataset = DATASETS[name]
        assert dataset.path == path
        assert dataset.plan == plan
        assert dataset.event_col == event_col
        assert dataset.disclosure_col == disclosure_col


def test_catalog_corrections_for_non_hobbyist_datasets():
    assert DATASETS["insiders"].plan == "tier2"
    assert DATASETS["bill_summaries"].path == "/beta/live/bill_summaries"
    assert DATASETS["bill_summaries"].plan == "tier1_enterprise"


def test_new_dataset_aliases_resolve_to_canonical_entries():
    aliases = {
        "corporatedonors": "corporate_donors",
        "donors": "corporate_donors",
        "trumpstocktrades": "trump_stock_trades",
        "govcontracts_live": "gov_contracts_live",
        "govcontractsall_live": "gov_contracts_all_live",
        "govcontracts": "gov_contracts_historical",
        "government_contracts": "gov_contracts_historical",
        "lobbying": "lobbying_live",
        "corporate_lobbying": "lobbying_live",
        "lobbying_by_ticker": "lobbying_historical",
        "offexchange_live": "off_exchange_live",
        "offexchange": "off_exchange_historical",
        "dark_pool": "off_exchange_historical",
        "congress_politicians": "politicians",
    }

    for alias, canonical in aliases.items():
        assert get_dataset(alias) is DATASETS[canonical]


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
