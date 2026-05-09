from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from quiverfeed.__main__ import (
    _infer_format,
    _kv_pair,
    _write_dataframe,
    build_parser,
    main,
)


# --- arg parsing ------------------------------------------------------------


def test_kv_pair_parses():
    assert _kv_pair("chamber=senate") == ("chamber", "senate")
    assert _kv_pair("k=") == ("k", "")
    assert _kv_pair("k=v=v") == ("k", "v=v")  # only first '=' splits


def test_kv_pair_rejects_missing_equals():
    with pytest.raises(Exception):
        _kv_pair("nope")


def test_fetch_parser_collects_repeated_params():
    args = build_parser().parse_args(
        [
            "fetch",
            "congresstrading",
            "--param",
            "chamber=senate",
            "--param",
            "version=V2",
        ]
    )
    assert args.param == [("chamber", "senate"), ("version", "V2")]


# --- format inference --------------------------------------------------------


def test_infer_format_uses_explicit_when_set(tmp_path):
    assert _infer_format(tmp_path / "x.csv", "json") == "json"


def test_infer_format_uses_suffix(tmp_path):
    assert _infer_format(tmp_path / "x.parquet", None) == "parquet"
    assert _infer_format(tmp_path / "x.csv", None) == "csv"
    assert _infer_format(tmp_path / "x.json", None) == "json"
    assert _infer_format(tmp_path / "x.txt", None) == "table"


def test_infer_format_no_out_means_table():
    assert _infer_format(None, None) == "table"


# --- write_dataframe --------------------------------------------------------


def test_write_dataframe_to_parquet_file(tmp_path):
    df = pd.DataFrame({"a": [1, 2], "b": ["x", "y"]})
    out = tmp_path / "out.parquet"
    _write_dataframe(df, "parquet", out)
    assert out.exists()
    pd.testing.assert_frame_equal(pd.read_parquet(out), df)


def test_write_dataframe_to_csv_file(tmp_path):
    df = pd.DataFrame({"a": [1, 2]})
    out = tmp_path / "out.csv"
    _write_dataframe(df, "csv", out)
    assert "a" in out.read_text()


def test_write_dataframe_to_json_file(tmp_path):
    df = pd.DataFrame({"a": [1, 2]})
    out = tmp_path / "out.json"
    _write_dataframe(df, "json", out)
    payload = json.loads(out.read_text())
    assert payload == [{"a": 1}, {"a": 2}]


# --- datasets subcommand (no network) ---------------------------------------


def test_datasets_text_output(capsys):
    rc = main(["datasets"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "congresstrading" in out
    assert "/beta/bulk/congresstrading" in out


def test_datasets_json_output(capsys):
    rc = main(["datasets", "--json"])
    out = capsys.readouterr().out
    assert rc == 0
    payload = json.loads(out)
    assert "congresstrading" in payload
    assert payload["congresstrading"]["event_col"] == "Traded"


# --- cache subcommand --------------------------------------------------------


def test_cache_path(capsys, tmp_path):
    rc = main(["cache", "--path", "--cache-dir", str(tmp_path)])
    out = capsys.readouterr().out.strip()
    assert rc == 0
    assert out == str(tmp_path)


def test_cache_clear_requires_yes(tmp_path, capsys):
    (tmp_path / "x.parquet").write_bytes(b"")
    rc = main(["cache", "--clear", "--cache-dir", str(tmp_path)])
    err = capsys.readouterr().err
    assert rc == 2
    assert "--yes" in err
    assert (tmp_path / "x.parquet").exists()  # nothing deleted


def test_cache_clear_with_yes(tmp_path, capsys):
    (tmp_path / "x.parquet").write_bytes(b"")
    rc = main(["cache", "--clear", "--yes", "--cache-dir", str(tmp_path)])
    out = capsys.readouterr().out
    assert rc == 0
    assert "Cleared" in out
    assert not tmp_path.exists()


def test_cache_clear_missing_dir_is_a_noop(tmp_path, capsys):
    target = tmp_path / "does-not-exist"
    rc = main(["cache", "--clear", "--yes", "--cache-dir", str(target)])
    out = capsys.readouterr().out
    assert rc == 0
    assert "Nothing to clear" in out


def test_cache_without_action_returns_usage_error(capsys, tmp_path):
    rc = main(["cache", "--cache-dir", str(tmp_path)])
    err = capsys.readouterr().err
    assert rc == 2
    assert "--path or --clear" in err
