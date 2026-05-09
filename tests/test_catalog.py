from __future__ import annotations

from quiverfeed.catalog import (
    DATASETS,
    Dataset,
    get_dataset,
    normalize_dataset_name,
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
    dataset = DATASETS["congresstrading"]
    first = dataset.defaults()
    assert first == {"version": "V2"}
    first["version"] = "MUTATED"
    assert dataset.defaults() == {"version": "V2"}


def test_known_datasets_have_required_attributes():
    for name, dataset in DATASETS.items():
        assert dataset.name == name
        assert dataset.path.startswith("/")
        # event_col and disclosure_col may both be None for some datasets,
        # but the catalog must still describe an event column where one exists.
        if dataset.disclosure_col is not None:
            assert dataset.event_col is not None
