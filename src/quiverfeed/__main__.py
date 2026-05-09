"""Command-line interface: `python -m quiverfeed ...` or `quiverfeed ...`."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from pathlib import Path
from typing import Sequence

import pandas as pd

from . import __version__
from .cache import default_cache_dir
from .catalog import all_datasets
from .client import Client
from .diagnostics import diagnose
from .errors import QuiverFeedError
from .rate_limit import RateLimitPolicy


# --- helpers ----------------------------------------------------------------


def _build_client(args: argparse.Namespace) -> Client:
    return Client(
        token=args.token,
        cache_dir=args.cache_dir,
        rate_limit_policy=args.rate_limit_policy,
    )


def _write_dataframe(df: pd.DataFrame, fmt: str, out: Path | None) -> None:
    """Render `df` to stdout (when out is None) or to a file inferred or chosen."""
    if out is not None:
        # File output: use the chosen fmt, not the suffix — caller is explicit.
        if fmt == "parquet":
            df.to_parquet(out, index=False)
        elif fmt == "csv":
            df.to_csv(out, index=False)
        elif fmt == "json":
            df.to_json(out, orient="records", date_format="iso")
        else:  # table
            out.write_text(df.to_string(index=False), encoding="utf-8")
        return

    if fmt == "json":
        sys.stdout.write(df.to_json(orient="records", date_format="iso"))
        sys.stdout.write("\n")
    elif fmt == "csv":
        df.to_csv(sys.stdout, index=False)
    else:  # table — parquet to stdout makes no sense, fall back to table
        sys.stdout.write(df.to_string(index=False))
        sys.stdout.write("\n")


def _infer_format(out: Path | None, explicit: str | None) -> str:
    if explicit:
        return explicit
    if out is None:
        return "table"
    suffix = out.suffix.lower()
    return {".parquet": "parquet", ".csv": "csv", ".json": "json"}.get(suffix, "table")


# --- subcommands ------------------------------------------------------------


def cmd_fetch(args: argparse.Namespace) -> int:
    client = _build_client(args)
    extra = dict(args.param or [])
    df = client.fetch(
        args.dataset,
        page_size=args.page_size,
        max_pages=args.max_pages,
        force=args.force,
        **extra,
    )
    fmt = _infer_format(args.out, args.format)
    _write_dataframe(df, fmt, args.out)
    return 0


def cmd_diagnose(args: argparse.Namespace) -> int:
    client = _build_client(args)
    report = diagnose(client=client, force=args.force)
    if args.json:
        payload = {
            "generated_at": report.generated_at.isoformat(),
            "ok": report.ok,
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
        sys.stdout.write(json.dumps(payload, indent=2))
        sys.stdout.write("\n")
    else:
        sys.stdout.write(report.to_text())
        sys.stdout.write("\n")
    return 0 if report.ok else 1


def cmd_datasets(args: argparse.Namespace) -> int:
    catalog = all_datasets()
    if args.json:
        payload = {
            name: {
                "path": d.path,
                "plan": d.plan,
                "event_col": d.event_col,
                "disclosure_col": d.disclosure_col,
                "notes": d.notes,
            }
            for name, d in catalog.items()
        }
        sys.stdout.write(json.dumps(payload, indent=2))
        sys.stdout.write("\n")
        return 0

    rows = [
        {
            "name": name,
            "path": d.path,
            "plan": d.plan or "",
            "event_col": d.event_col or "",
            "disclosure_col": d.disclosure_col or "",
        }
        for name, d in catalog.items()
    ]
    sys.stdout.write(pd.DataFrame(rows).to_string(index=False))
    sys.stdout.write("\n")
    return 0


def cmd_cache(args: argparse.Namespace) -> int:
    cache_dir = Path(args.cache_dir) if args.cache_dir else default_cache_dir()
    if args.path:
        sys.stdout.write(str(cache_dir))
        sys.stdout.write("\n")
        return 0
    if args.clear:
        if not cache_dir.exists():
            sys.stdout.write(f"Nothing to clear: {cache_dir} does not exist.\n")
            return 0
        if not args.yes:
            sys.stderr.write(
                f"Refusing to delete {cache_dir} without --yes. "
                "Re-run with --yes to confirm.\n"
            )
            return 2
        shutil.rmtree(cache_dir)
        sys.stdout.write(f"Cleared {cache_dir}\n")
        return 0
    sys.stderr.write("cache: pass --path or --clear\n")
    return 2


# --- argparse setup ---------------------------------------------------------


def _kv_pair(value: str) -> tuple[str, str]:
    if "=" not in value:
        raise argparse.ArgumentTypeError(f"--param expects key=value, got {value!r}")
    key, _, val = value.partition("=")
    return (key, val)


def _add_common_client_args(p: argparse.ArgumentParser) -> None:
    p.add_argument(
        "--token",
        default=os.getenv("QUIVER_TOKEN"),
        help="Quiver API token (defaults to QUIVER_TOKEN env var).",
    )
    p.add_argument(
        "--cache-dir",
        type=Path,
        default=None,
        help="Override the cache directory.",
    )
    p.add_argument(
        "--rate-limit-policy",
        choices=("raise", "sleep", "off"),
        default="raise",
        help="What to do when the local rate-limit bucket is empty.",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="quiverfeed",
        description="Point-in-time-safe Python client for Quiver Quantitative data.",
    )
    parser.add_argument("--version", action="version", version=f"quiverfeed {__version__}")
    sub = parser.add_subparsers(dest="cmd", required=True)

    # fetch
    p_fetch = sub.add_parser("fetch", help="Fetch a dataset.")
    p_fetch.add_argument("dataset", help="Dataset name (see `quiverfeed datasets`).")
    p_fetch.add_argument("--page-size", type=int, default=5000)
    p_fetch.add_argument("--max-pages", type=int, default=None)
    p_fetch.add_argument("--force", action="store_true", help="Bypass the cache.")
    p_fetch.add_argument(
        "--out", type=Path, default=None,
        help="Write to this path (format inferred from suffix unless --format).",
    )
    p_fetch.add_argument(
        "--format", choices=("table", "json", "csv", "parquet"), default=None,
    )
    p_fetch.add_argument(
        "--param", action="append", type=_kv_pair, metavar="KEY=VALUE",
        help="Extra dataset parameter; repeatable.",
    )
    _add_common_client_args(p_fetch)
    p_fetch.set_defaults(func=cmd_fetch)

    # diagnose
    p_diag = sub.add_parser("diagnose", help="Health-check the catalog against Quiver.")
    p_diag.add_argument("--force", action="store_true", help="Skip the report cache.")
    p_diag.add_argument("--json", action="store_true")
    _add_common_client_args(p_diag)
    p_diag.set_defaults(func=cmd_diagnose)

    # datasets
    p_ds = sub.add_parser("datasets", help="List the catalog.")
    p_ds.add_argument("--json", action="store_true")
    p_ds.set_defaults(func=cmd_datasets)

    # cache
    p_cache = sub.add_parser("cache", help="Inspect or clear the on-disk cache.")
    p_cache.add_argument("--path", action="store_true", help="Print the cache directory.")
    p_cache.add_argument("--clear", action="store_true", help="Delete the cache directory.")
    p_cache.add_argument("--yes", action="store_true", help="Confirm --clear.")
    p_cache.add_argument("--cache-dir", type=Path, default=None)
    p_cache.set_defaults(func=cmd_cache)

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except QuiverFeedError as exc:
        sys.stderr.write(f"error: {exc}\n")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
