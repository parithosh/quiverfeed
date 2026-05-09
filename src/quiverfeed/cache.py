from __future__ import annotations

import hashlib
import json
import os
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any, Mapping

import pandas as pd


def default_cache_dir() -> Path:
    xdg = os.getenv("XDG_CACHE_HOME")
    if xdg:
        return Path(xdg) / "quiverfeed"
    return Path.home() / ".cache" / "quiverfeed"


def schema_hash(columns: list[str]) -> str:
    payload = json.dumps(sorted(columns), separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()


class CacheStore:
    def __init__(self, cache_dir: Path | str | None):
        self.cache_dir = Path(cache_dir) if cache_dir is not None else default_cache_dir()

    def get(
        self,
        dataset: str,
        params: Mapping[str, Any],
        ttl: timedelta,
    ) -> pd.DataFrame | None:
        parquet_path, meta_path = self._paths(dataset, params)
        if not parquet_path.exists() or not meta_path.exists():
            return None

        try:
            metadata = json.loads(meta_path.read_text(encoding="utf-8"))
            fetched_at = datetime.fromisoformat(metadata["fetched_at"])
            if fetched_at.tzinfo is None:
                fetched_at = fetched_at.replace(tzinfo=UTC)
            if datetime.now(UTC) - fetched_at > ttl:
                return None

            df = pd.read_parquet(parquet_path)
            if metadata.get("schema_hash") != schema_hash(list(df.columns)):
                return None
            return df
        except (OSError, KeyError, ValueError, json.JSONDecodeError):
            return None

    def set(
        self,
        dataset: str,
        params: Mapping[str, Any],
        df: pd.DataFrame,
        version: str,
    ) -> None:
        parquet_path, meta_path = self._paths(dataset, params)
        parquet_path.parent.mkdir(parents=True, exist_ok=True)

        tmp_parquet = parquet_path.with_suffix(".tmp.parquet")
        tmp_meta = meta_path.with_suffix(".tmp.json")
        df.to_parquet(tmp_parquet, index=False)

        metadata = {
            "fetched_at": datetime.now(UTC).isoformat(),
            "params": _normalize(params),
            "row_count": int(len(df)),
            "quiverfeed_version": version,
            "schema_hash": schema_hash(list(df.columns)),
        }
        tmp_meta.write_text(
            json.dumps(metadata, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        os.replace(tmp_parquet, parquet_path)
        os.replace(tmp_meta, meta_path)

    def _paths(self, dataset: str, params: Mapping[str, Any]) -> tuple[Path, Path]:
        key = cache_key(dataset, params)
        safe_dataset = dataset.replace("/", "__")
        root = self.cache_dir / safe_dataset
        return root / f"{key}.parquet", root / f"{key}.json"


def cache_key(dataset: str, params: Mapping[str, Any]) -> str:
    material = {
        "dataset": dataset,
        "params": _normalize(params),
    }
    payload = json.dumps(material, sort_keys=True, separators=(",", ":"))
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()


def _normalize(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(k): _normalize(value[k]) for k in sorted(value)}
    if isinstance(value, (list, tuple)):
        return [_normalize(item) for item in value]
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)
