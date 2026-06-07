from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Iterable

from .cache import default_cache_dir
from .catalog import all_datasets, get_dataset
from .client import Client, _sample_path_params
from .errors import CatalogDriftError, QuiverFeedError


@dataclass(frozen=True, slots=True)
class DatasetDiagnostic:
    dataset: str
    ok: bool
    row_count: int
    columns: tuple[str, ...]
    message: str = ""


@dataclass(frozen=True, slots=True)
class DiagnoseReport:
    generated_at: datetime
    results: tuple[DatasetDiagnostic, ...]

    @property
    def ok(self) -> bool:
        return all(result.ok for result in self.results)

    def to_text(self) -> str:
        lines = [f"quiverfeed diagnose @ {self.generated_at.isoformat()}"]
        for result in self.results:
            status = "ok" if result.ok else "fail"
            detail = f" rows={result.row_count} cols={len(result.columns)}"
            if result.message:
                detail += f" message={result.message}"
            lines.append(f"- {result.dataset}: {status}{detail}")
        return "\n".join(lines)


def diagnose(
    token: str | None = None,
    datasets: Iterable[str] | None = None,
    *,
    client: Client | None = None,
    page_size: int = 1,
    cache_ttl: timedelta = timedelta(hours=1),
    force: bool = False,
    cache_dir: Path | str | None = None,
    sample_ticker: str = "AAPL",
) -> DiagnoseReport:
    active_client = client or Client(token=token)
    names = tuple(datasets) if datasets is not None else tuple(all_datasets().keys())

    if cache_dir is None and active_client._cache is not None:
        cache_dir = active_client._cache.cache_dir
    cache_path = _diagnose_cache_path(cache_dir, names, sample_ticker)
    if not force:
        cached = _load_report(cache_path, cache_ttl)
        if cached is not None:
            return cached

    results: list[DatasetDiagnostic] = []
    for name in names:
        dataset = get_dataset(name)
        if dataset is None:
            results.append(
                DatasetDiagnostic(
                    dataset=name,
                    ok=False,
                    row_count=0,
                    columns=(),
                    message="unknown dataset",
                )
            )
            continue

        try:
            params = _sample_path_params(dataset, sample_ticker=sample_ticker)
            df = active_client.fetch(
                dataset.name,
                page_size=page_size,
                max_pages=1,
                on_truncated="ignore",
                force=True,
                **params,
            )
            results.append(
                DatasetDiagnostic(
                    dataset=dataset.name,
                    ok=True,
                    row_count=len(df),
                    columns=tuple(str(col) for col in df.columns),
                )
            )
        except CatalogDriftError as exc:
            results.append(
                DatasetDiagnostic(
                    dataset=dataset.name,
                    ok=False,
                    row_count=0,
                    columns=tuple(exc.actual_cols),
                    message=str(exc),
                )
            )
        except QuiverFeedError as exc:
            results.append(
                DatasetDiagnostic(
                    dataset=dataset.name,
                    ok=False,
                    row_count=0,
                    columns=(),
                    message=str(exc),
                )
            )

    report = DiagnoseReport(generated_at=datetime.now(UTC), results=tuple(results))
    _save_report(cache_path, report)
    return report


def canary(
    token: str | None = None,
    *,
    plan: str | None = "hobbyist",
    page_size: int = 5,
    max_pages: int = 1,
    client: Client | None = None,
    sample_ticker: str = "AAPL",
):
    active_client = client or Client(token=token)
    return active_client.canary(
        plan=plan,
        page_size=page_size,
        max_pages=max_pages,
        sample_ticker=sample_ticker,
    )


def _diagnose_cache_path(
    cache_dir: Path | str | None,
    names: tuple[str, ...],
    sample_ticker: str,
) -> Path:
    root = Path(cache_dir) if cache_dir is not None else default_cache_dir()
    # Names are part of the filename so a partial diagnose() doesn't satisfy
    # a full-catalog cache hit and vice versa.
    key_parts = (*sorted(names), f"sample_ticker={sample_ticker}")
    material = json.dumps(key_parts, sort_keys=True, separators=(",", ":"))
    key = hashlib.sha1(material.encode("utf-8")).hexdigest()
    return root / "diagnose" / f"{key}.json"


def _load_report(path: Path, ttl: timedelta) -> DiagnoseReport | None:
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        generated_at = datetime.fromisoformat(payload["generated_at"])
        if generated_at.tzinfo is None:
            generated_at = generated_at.replace(tzinfo=UTC)
        if datetime.now(UTC) - generated_at > ttl:
            return None
        results = tuple(
            DatasetDiagnostic(
                dataset=r["dataset"],
                ok=r["ok"],
                row_count=r["row_count"],
                columns=tuple(r["columns"]),
                message=r.get("message", ""),
            )
            for r in payload["results"]
        )
        return DiagnoseReport(generated_at=generated_at, results=results)
    except (OSError, KeyError, ValueError, json.JSONDecodeError):
        return None


def _save_report(path: Path, report: DiagnoseReport) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "generated_at": report.generated_at.isoformat(),
        "results": [
            {
                "dataset": r.dataset,
                "ok": r.ok,
                "row_count": r.row_count,
                "columns": list(r.columns),
                "message": r.message,
            }
            for r in report.results
        ],
    }
    tmp = path.with_suffix(".tmp.json")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    tmp.replace(path)
