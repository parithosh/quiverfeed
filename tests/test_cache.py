from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pandas as pd

from quiverfeed.cache import (
    CacheStore,
    cache_key,
    default_cache_dir,
    schema_hash,
)


def test_default_cache_dir_uses_xdg_when_set(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))
    assert default_cache_dir() == tmp_path / "quiverfeed"


def test_default_cache_dir_falls_back_to_home(monkeypatch):
    monkeypatch.delenv("XDG_CACHE_HOME", raising=False)
    assert default_cache_dir() == Path.home() / ".cache" / "quiverfeed"


def test_schema_hash_is_order_independent():
    assert schema_hash(["a", "b", "c"]) == schema_hash(["c", "b", "a"])
    assert schema_hash(["a"]) != schema_hash(["b"])


def test_cache_key_is_deterministic_and_param_order_independent():
    a = cache_key("ds", {"x": 1, "y": 2})
    b = cache_key("ds", {"y": 2, "x": 1})
    assert a == b
    assert cache_key("ds", {"x": 1}) != cache_key("ds", {"x": 2})


def test_cache_set_and_get_roundtrip(tmp_path):
    store = CacheStore(tmp_path)
    df = pd.DataFrame([{"a": 1, "b": "x"}, {"a": 2, "b": "y"}])

    store.set("ds", {"k": 1}, df, "0.0.0-test")
    loaded = store.get("ds", {"k": 1}, ttl=timedelta(hours=1))

    assert loaded is not None
    pd.testing.assert_frame_equal(loaded, df)


def test_cache_get_returns_none_when_missing(tmp_path):
    store = CacheStore(tmp_path)
    assert store.get("ds", {}, ttl=timedelta(hours=1)) is None


def test_cache_expired_entry_returns_none(tmp_path):
    store = CacheStore(tmp_path)
    df = pd.DataFrame([{"a": 1}])
    store.set("ds", {}, df, "0.0.0")

    # Rewrite metadata to look stale.
    parquet_path, meta_path = store._paths("ds", {})
    metadata = json.loads(meta_path.read_text(encoding="utf-8"))
    metadata["fetched_at"] = (datetime.now(UTC) - timedelta(hours=10)).isoformat()
    meta_path.write_text(json.dumps(metadata), encoding="utf-8")

    assert store.get("ds", {}, ttl=timedelta(hours=1)) is None


def test_cache_get_handles_corrupt_metadata(tmp_path):
    store = CacheStore(tmp_path)
    df = pd.DataFrame([{"a": 1}])
    store.set("ds", {}, df, "0.0.0")

    _, meta_path = store._paths("ds", {})
    meta_path.write_text("not-json", encoding="utf-8")

    assert store.get("ds", {}, ttl=timedelta(hours=1)) is None


def test_cache_schema_drift_invalidates_entry(tmp_path):
    store = CacheStore(tmp_path)
    df = pd.DataFrame([{"a": 1}])
    store.set("ds", {}, df, "0.0.0")

    _, meta_path = store._paths("ds", {})
    metadata = json.loads(meta_path.read_text(encoding="utf-8"))
    metadata["schema_hash"] = "deadbeef"
    meta_path.write_text(json.dumps(metadata), encoding="utf-8")

    assert store.get("ds", {}, ttl=timedelta(hours=1)) is None


def test_cache_set_writes_metadata_fields(tmp_path):
    store = CacheStore(tmp_path)
    df = pd.DataFrame([{"a": 1}, {"a": 2}])
    store.set("ds", {"foo": "bar"}, df, "9.9.9")

    _, meta_path = store._paths("ds", {"foo": "bar"})
    metadata = json.loads(meta_path.read_text(encoding="utf-8"))

    assert metadata["row_count"] == 2
    assert metadata["quiverfeed_version"] == "9.9.9"
    assert metadata["params"] == {"foo": "bar"}
    # schema_hash is over column names.
    assert metadata["schema_hash"] == schema_hash(["a"])


def test_cache_path_segregates_dataset_with_slash(tmp_path):
    store = CacheStore(tmp_path)
    parquet_path, _ = store._paths("group/sub", {})
    # No raw slash should leak into the filesystem layout under cache_dir.
    assert "group/sub" not in str(parquet_path.relative_to(tmp_path))
    assert parquet_path.parent.name == "group__sub"
