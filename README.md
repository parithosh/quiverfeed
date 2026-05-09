# quiverfeed

`quiverfeed` is a point-in-time-safe Python client for Quiver Quantitative data.

The headline feature is not the HTTP wrapper. It is the two canonical date
columns added to returned DataFrames:

- `event_time`: when the underlying thing happened.
- `available_at`: when the data became knowable to the market.

For backtests and historical analysis, use `available_at`.

## Install

```bash
uv pip install quiverfeed
```

For local development:

```bash
uv venv
uv pip install -e ".[dev]"
```

Or, using `uv sync` against the lockfile:

```bash
uv sync --extra dev
```

If you don't have `uv`, install it from [astral.sh/uv](https://docs.astral.sh/uv/) or
fall back to plain `pip install quiverfeed` / `pip install -e ".[dev]"`.

## Quickstart

```python
import quiverfeed

client = quiverfeed.Client(token="YOUR_QUIVER_TOKEN")
df = client.fetch("congresstrading")

print(df[["Ticker", "Traded", "Filed", "event_time", "available_at"]].head())
```

You can also set the token once:

```bash
export QUIVER_TOKEN="YOUR_QUIVER_TOKEN"
```

Then:

```python
import quiverfeed

df = quiverfeed.Client().fetch("congresstrading")
```

## Point-In-Time Analysis

Congressional trade data has at least two important dates:

- `Traded`: when the transaction happened.
- `Filed`: when the transaction was disclosed.

A backtest that trades on `Traded` is usually using information that was not
available yet. `quiverfeed` keeps the original columns and adds safe canonical
columns:

```python
df = client.fetch("congresstrading")

# Use this for "what did the market know by this date?"
asof = "2025-01-01"
known = df[df["available_at"] <= asof]

# event_time is still useful for describing what happened.
late = known[known["available_at"] > known["event_time"]]
```

For datasets that do not advertise a separate disclosure date, `quiverfeed`
adds `event_time` only. It does not fabricate `available_at`.

`validate_pit(df, dataset="...")` is the catalog-aware companion to
`assert_disclosure_dated`. It raises a clear error when the named dataset has
no disclosure column at all (rather than the generic "missing available_at"),
and it asserts the consistency invariant `available_at >= event_time`:

```python
quiverfeed.validate_pit(df, dataset="congresstrading")
quiverfeed.validate_pit(df, dataset="lobbying")  # raises: not PIT-capable
```

### Timezones

By default, canonical date columns are tz-aware UTC. Projects that pin to a
single zone can ask for naive output or a specific zone:

```python
quiverfeed.Client(tz=None)                      # tz-naive
quiverfeed.Client(tz="America/New_York")        # localized to ET
```

## Discovery

```python
import quiverfeed

for name, dataset in quiverfeed.DATASETS.items():
    print(name, dataset.path, dataset.event_col, dataset.disclosure_col)
```

Dataset names are forgiving for separators:

```python
client.fetch("congress_trading")  # resolves to "congresstrading"
```

Truly unknown datasets raise `UnknownDatasetError`.

### Custom datasets

Register a `Dataset` to reach an endpoint not in the built-in catalog or to
override a built-in whose schema has drifted:

```python
import quiverfeed

quiverfeed.register_dataset(
    quiverfeed.Dataset(
        name="my_signal",
        path="/beta/bulk/my_signal",
        plan="premium",
        event_col="event_date",
        disclosure_col="disclosed_at",
    )
)

df = quiverfeed.Client().fetch("my_signal")
```

`register_dataset(..., replace=True)` overwrites; `unregister_dataset(name)`
removes a registration.

## Caching

Successful complete fetches are cached as Parquet under
`$XDG_CACHE_HOME/quiverfeed` or `~/.cache/quiverfeed`.

```python
from datetime import timedelta

client = quiverfeed.Client(cache_ttl=timedelta(hours=6))

df = client.fetch("congresstrading")        # API call, then cache write
again = client.fetch("congresstrading")     # cache read, no API call
fresh = client.fetch("congresstrading", force=True)
```

Partial results from `max_pages` are not cached, because a normal cache hit
should mean "complete for these params."

The cache is intentionally whole-blob: when the TTL expires, `quiverfeed`
re-pulls every page rather than attempting an incremental append. This wastes
requests for append-mostly datasets (e.g. `congresstrading`) but never serves
stale data when upstream amends a historical filing. If you want longer
effective freshness, raise `cache_ttl`.

## Rate Limits

The default local limiter is conservative:

```python
client = quiverfeed.Client(
    rate_limit_per_hour=20,
    rate_limit_policy="raise",
)
```

Policies:

- `"raise"`: fail before making a request when the local bucket is empty.
- `"sleep"`: block until a request slot is available.
- `"off"`: disable local pacing and rely on Quiver's 429.

For multiple processes sharing a token:

```python
client = quiverfeed.Client(bucket_file="~/.cache/quiverfeed/bucket.json")
```

`bucket_file=` uses POSIX `fcntl` locking and is **not supported on Windows**.
On non-POSIX platforms, omit `bucket_file=` and rely on the in-memory bucket.
Cross-platform coordination would require a third-party file-lock library;
this is intentionally not pulled in.

## Pagination

By default, `fetch()` paginates until it receives a short page. Between pages
the client sleeps `request_pause_s` seconds (default 1.0) to stay under
Quiver's per-second/burst behavior, which the hourly token bucket does not
catch:

```python
df = client.fetch("congresstrading", page_size=5000)

# Tighter pacing for offline backfills against your own quota:
client = quiverfeed.Client(request_pause_s=2.0)
```

If you cap pages and the final page is full, the result may be incomplete.
The default is to warn and return the partial frame — passing `max_pages` is
treated as opting in to bounded results:

```python
df = client.fetch("congresstrading", max_pages=5)
```

If you would rather fail loudly on truncation, opt into raising:

```python
df = client.fetch(
    "congresstrading",
    max_pages=5,
    on_truncated="raise",
)
```

To suppress the warning entirely, use `on_truncated="ignore"`.

## Retries

Connection errors and `5xx` responses are retried with jittered exponential
backoff up to `max_retries` (default 2) extra attempts. `401`, `403`, and
`429` are never retried — they are explicit signals from upstream. Retries
do **not** consume extra rate-limit tokens; the bucket charges once per
logical page request.

```python
client = quiverfeed.Client(max_retries=2, retry_backoff_s=0.5)
```

## Command-line interface

```bash
quiverfeed --help
quiverfeed datasets                                   # list the catalog
quiverfeed datasets --json
quiverfeed fetch congresstrading --max-pages 5 --out trades.parquet
quiverfeed fetch insiders --param chamber=senate --format json
quiverfeed diagnose                                   # cached health check
quiverfeed diagnose --force --json
quiverfeed cache --path
quiverfeed cache --clear --yes
```

The token is read from `QUIVER_TOKEN` (or `--token`). Output format is
inferred from `--out` extension (`.parquet` / `.csv` / `.json`); `--format`
overrides. With no `--out`, results print to stdout — table by default,
machine-readable with `--format json` / `csv`.

`python -m quiverfeed ...` works as an alternative if the script entry isn't
on `PATH`.

## Catalog Diagnostics

Run a live check against Quiver to see whether the local catalog still matches
the API:

```python
import quiverfeed

report = quiverfeed.diagnose()
print(report.to_text())
```

Reports are cached for one hour by default to avoid burning rate-limit
tokens on repeated health checks. Pass `force=True` to bypass the cache or
shorten `cache_ttl` if you want fresher results:

```python
report = quiverfeed.diagnose(force=True)
```

This performs real API calls and consumes rate-limit budget.

