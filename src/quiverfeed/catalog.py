from __future__ import annotations

import re
from dataclasses import dataclass
from types import MappingProxyType
from typing import Mapping

ParamValue = str | int | float | bool | None


@dataclass(frozen=True, slots=True)
class Dataset:
    name: str
    path: str
    plan: str | None
    event_col: str | None
    disclosure_col: str | None
    aliases: tuple[str, ...] = ()
    paginated: bool = True
    ignored_params: tuple[str, ...] = ()
    default_params: tuple[tuple[str, ParamValue], ...] = ()
    ttl_hours: int | None = None
    notes: str = ""

    def defaults(self) -> dict[str, ParamValue]:
        return dict(self.default_params)


_DATASETS: dict[str, Dataset] = {
    "congresstrading": Dataset(
        name="congresstrading",
        path="/beta/bulk/congresstrading",
        plan="hobbyist",
        event_col="Traded",
        disclosure_col="Filed",
        aliases=("congress_trading", "congress_trades"),
        ignored_params=("date_from", "date_to"),
        default_params=(("version", "V2"),),
        notes=(
            "Congressional stock trades. Use available_at/Filed for "
            "point-in-time analysis; Traded is the event date. The catalog "
            "defaults to version='V2' because these PIT columns are the V2 "
            "shape advertised by the API."
        ),
    ),
    "insiders": Dataset(
        name="insiders",
        path="/beta/live/insiders",
        plan="tier2",
        event_col="Date",
        disclosure_col="fileDate",
        default_params=(("limit_codes", True),),
        notes=(
            "Recent insider transactions. Date is the transaction date; "
            "fileDate is when the filing became available. Tagged Tier 2 "
            "by the current OpenAPI schema."
        ),
    ),
    "politicians": Dataset(
        name="politicians",
        path="/beta/bulk/congress/politicians",
        plan="hobbyist",
        event_col=None,
        disclosure_col=None,
        aliases=("congress_politicians", "politician_net_worth"),
        notes=(
            "Roster of congressional traders, sortable by activity. Reference "
            "data, not an event stream; no event_time / available_at columns "
            "are added."
        ),
    ),
    "corporate_donors": Dataset(
        name="corporate_donors",
        path="/beta/bulk/corporatedonors",
        plan="hobbyist",
        event_col="TransactionDate",
        disclosure_col="Uploaded",
        aliases=("corporatedonors", "donors", "corporate_election_contributions"),
        notes=(
            "Bulk PAC donations to politicians. TransactionDate is the "
            "contribution date; Uploaded is treated as the public/ingestion "
            "date when parseable."
        ),
    ),
    "trump_stock_trades": Dataset(
        name="trump_stock_trades",
        path="/beta/bulk/trumpstocktrades",
        plan="hobbyist",
        event_col="Traded",
        disclosure_col="Filed",
        aliases=("trumpstocktrades",),
        notes=(
            "Bulk Trump-family stock trades. Traded is the event date; Filed "
            "is the disclosure date."
        ),
    ),
    "gov_contracts_live": Dataset(
        name="gov_contracts_live",
        path="/beta/live/govcontracts",
        plan="hobbyist",
        event_col=None,
        disclosure_col=None,
        aliases=("govcontracts_live",),
        paginated=False,
        notes=(
            "Recent quarterly government contract totals. The schema exposes "
            "Qtr/Year only, so no canonical PIT timestamps are added."
        ),
    ),
    "gov_contracts_all_live": Dataset(
        name="gov_contracts_all_live",
        path="/beta/live/govcontractsall",
        plan="hobbyist",
        event_col="action_date",
        disclosure_col="Date",
        aliases=("govcontractsall_live", "government_contracts_live"),
        notes=(
            "Recent government contract announcements. action_date is the "
            "contract action date; Date is the public announcement date."
        ),
    ),
    "gov_contracts_historical": Dataset(
        name="gov_contracts_historical",
        path="/beta/historical/govcontractsall/{ticker}",
        plan="hobbyist",
        event_col="action_date",
        disclosure_col="Date",
        aliases=("govcontracts", "gov_contracts", "government_contracts"),
        paginated=False,
        notes=(
            "Historical government contract announcements by ticker. "
            "Requires ticker=... as a path parameter."
        ),
    ),
    "lobbying_live": Dataset(
        name="lobbying_live",
        path="/beta/live/lobbying",
        plan="hobbyist",
        event_col="Date",
        disclosure_col=None,
        aliases=("lobbying", "corporate_lobbying"),
        notes=(
            "Live corporate lobbying records. The advertised schema exposes "
            "one Date column, so quiverfeed adds event_time but not "
            "available_at."
        ),
    ),
    "lobbying_historical": Dataset(
        name="lobbying_historical",
        path="/beta/historical/lobbying/{ticker}",
        plan="hobbyist",
        event_col="Date",
        disclosure_col=None,
        aliases=("lobbying_by_ticker",),
        notes=(
            "Historical corporate lobbying records by ticker. Requires "
            "ticker=... as a path parameter."
        ),
    ),
    "off_exchange_live": Dataset(
        name="off_exchange_live",
        path="/beta/live/offexchange",
        plan="hobbyist",
        event_col="Date",
        disclosure_col=None,
        aliases=("offexchange_live",),
        notes=(
            "Live off-exchange trading data. Date is modeled as event_time; "
            "no separate disclosure date is advertised."
        ),
    ),
    "off_exchange_historical": Dataset(
        name="off_exchange_historical",
        path="/beta/historical/offexchange/{ticker}",
        plan="hobbyist",
        event_col="Date",
        disclosure_col=None,
        aliases=("offexchange", "off_exchange", "dark_pool"),
        paginated=False,
        notes=(
            "Historical off-exchange trading data by ticker. Requires "
            "ticker=... as a path parameter."
        ),
    ),
    "bill_summaries": Dataset(
        name="bill_summaries",
        path="/beta/live/bill_summaries",
        plan="tier1_enterprise",
        event_col="lastActionDate",
        disclosure_col=None,
        default_params=(("summary_limit", 5000),),
        notes=(
            "Recent congressional bill summaries. The current OpenAPI schema "
            "tags this endpoint Tier 1 plus enterprise/internal, so it is not "
            "included in the normal Hobbyist canary set."
        ),
    ),
}

DATASETS: Mapping[str, Dataset] = MappingProxyType(_DATASETS)

# User-registered datasets via register_dataset(); they override built-ins on
# name collision so callers can patch a built-in entry whose schema has
# drifted upstream without forking the package.
_USER_DATASETS: dict[str, Dataset] = {}


def normalize_dataset_name(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", name.lower())


def all_datasets() -> dict[str, Dataset]:
    merged = dict(_DATASETS)
    merged.update(_USER_DATASETS)
    return merged


def register_dataset(dataset: Dataset, *, replace: bool = False) -> None:
    if not replace and dataset.name in _USER_DATASETS:
        raise ValueError(
            f"Dataset {dataset.name!r} already registered; pass replace=True "
            "to overwrite."
        )
    _USER_DATASETS[dataset.name] = dataset


def unregister_dataset(name: str) -> None:
    _USER_DATASETS.pop(name, None)


def get_dataset(name: str) -> Dataset | None:
    catalog = all_datasets()
    if name in catalog:
        return catalog[name]

    normalized = normalize_dataset_name(name)
    matches_by_name = {}
    for key, dataset in catalog.items():
        candidates = (key, dataset.name, *dataset.aliases)
        if any(
            normalize_dataset_name(candidate) == normalized
            for candidate in candidates
        ):
            matches_by_name[dataset.name] = dataset
    matches = list(matches_by_name.values())
    if len(matches) == 1:
        return matches[0]
    return None
