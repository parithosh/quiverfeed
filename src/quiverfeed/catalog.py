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
        ignored_params=("date_from", "date_to"),
        notes=(
            "Congressional stock trades. Use available_at/Filed for "
            "point-in-time analysis; Traded is the event date. Pass "
            "version='V2' explicitly to opt into the V2 schema; default "
            "sends no version, matching the published API examples."
        ),
    ),
    "insiders": Dataset(
        name="insiders",
        path="/beta/live/insiders",
        plan="hobbyist",
        event_col="Date",
        disclosure_col="fileDate",
        default_params=(("limit_codes", True),),
        notes=(
            "Recent insider transactions. Date is the transaction date; "
            "fileDate is when the filing became available."
        ),
    ),
    "lobbying": Dataset(
        name="lobbying",
        path="/beta/historical/lobbying/SEARCHALL",
        plan="hobbyist",
        event_col="Date",
        disclosure_col=None,
        notes=(
            "Corporate lobbying search. The advertised schema exposes one "
            "Date column, so quiverfeed adds event_time but not available_at."
        ),
    ),
    "bill_summaries": Dataset(
        name="bill_summaries",
        path="/beta/live/billSummaries",
        plan="hobbyist",
        event_col="lastActionDate",
        disclosure_col=None,
        default_params=(("summary_limit", 5000),),
        notes=(
            "Recent congressional bill summaries. lastActionDate is modeled "
            "as event_time; no separate disclosure date is advertised."
        ),
    ),
}

DATASETS: Mapping[str, Dataset] = MappingProxyType(_DATASETS)


def normalize_dataset_name(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", name.lower())


def get_dataset(name: str) -> Dataset | None:
    if name in DATASETS:
        return DATASETS[name]

    normalized = normalize_dataset_name(name)
    matches = [
        dataset
        for key, dataset in DATASETS.items()
        if normalize_dataset_name(key) == normalized
    ]
    if len(matches) == 1:
        return matches[0]
    return None
