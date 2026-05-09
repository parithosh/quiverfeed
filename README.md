# quiverfeed

`quiverfeed` is a point-in-time-safe Python client for Quiver Quantitative data.

The headline feature is not the HTTP wrapper. It is the two canonical date
columns added to returned DataFrames:

- `event_time`: when the underlying thing happened.
- `available_at`: when the data became knowable to the market.

For backtests and historical analysis, use `available_at`.

## Install

```bash
pip install quiverfeed
```

For local development:

```bash
pip install -e ".[dev]"
```

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

## Pagination

By default, `fetch()` paginates until it receives a short page.

```python
df = client.fetch("congresstrading", page_size=5000)
```

If you cap pages and the final page is full, the result may be incomplete.
The default is to raise:

```python
df = client.fetch("congresstrading", max_pages=5)
```

If you intentionally want a bounded sample:

```python
sample = client.fetch(
    "congresstrading",
    max_pages=1,
    on_truncated="warn",
)
```

## Catalog Diagnostics

Run a live check against Quiver to see whether the local catalog still matches
the API:

```python
import quiverfeed

report = quiverfeed.diagnose()
print(report.to_text())
```

This performs real API calls and consumes rate-limit budget.

## Compared With `quiverquant`

`quiverquant` is Quiver's lightweight method-oriented package and is useful for
quick pulls. `quiverfeed` is stricter: it is built around point-in-time date
semantics, caching, rate-limit hygiene, pagination, typed errors, and catalog
drift checks.
