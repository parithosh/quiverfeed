from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Iterable

from .catalog import DATASETS, get_dataset
from .client import Client
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
) -> DiagnoseReport:
    active_client = client or Client(token=token)
    names = tuple(datasets) if datasets is not None else tuple(DATASETS.keys())
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
            df = active_client.fetch(
                dataset.name,
                page_size=page_size,
                max_pages=1,
                on_truncated="ignore",
                force=True,
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

    return DiagnoseReport(generated_at=datetime.now(UTC), results=tuple(results))
