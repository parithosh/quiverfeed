# Quiver API — DevEx critique & wrapper proposal

Notes from building `cockpit.quiver_bulk` against `/beta/bulk/...` and reviewing
the docs at https://api.quiverquant.com/docs/.

## DevEx improvement suggestions

### 1. Document rate limits — they're the single biggest footgun
The bucket is empirically ~20–30 req/hour with `Retry-After: 3600` on 429, and
there are **no `X-RateLimit-*` headers on success**. You only learn the limit by
tripping it and losing an hour. *Fix:* publish the bucket per plan tier, and
emit `X-RateLimit-Limit` / `Remaining` / `Reset` on every 200 — table stakes for
any paid REST API.

### 2. Don't silently ignore query params
`date_from` / `date_to` on `congresstrading` are accepted and dropped — the
response is identical to a call without them. Silent param drops are the worst
possible failure mode (you ship a backtest with a "filter" that did nothing).
*Fix:* either implement them or return `400` listing unsupported params.

### 3. Make response shape uniform
`/beta/bulk/...` returns `{"data": [...]}` while `/beta/live/...` and
`/beta/historical/...` return a bare array. Every client has to branch on
`isinstance(resp, list)`. *Fix:* envelope everything
(`{data, page, total, next_cursor}`) and deprecate the bare-array forms.

### 4. Auth scheme inconsistency
Docs say `Bearer`, but `Token <token>` also works undocumented. Pick one,
redirect/410 the other.

### 5. Entitlement errors should be machine-readable
`403 "Upgrade your subscription plan"` is a free-text body. *Fix:* return
`{"error": "plan_required", "required_plan": "premium", "dataset": "cnbc"}`.

### 6. Publish a real OpenAPI spec + dataset catalog endpoint
The docs page enumerates endpoints in prose. A `/beta/datasets` JSON index
listing each dataset's columns, two date fields (event vs disclosure), update
cadence, and required plan would let clients codegen and self-discover.

### 7. Be explicit about the two date fields
Every dataset has an *event date* and a *disclosure date* (`Traded` vs `Filed`,
etc.) and choosing wrong = lookahead bias in a backtest. The docs don't flag
this. *Fix:* mark each timestamp column as `event_time` or `available_at` in the
schema, and warn in prose.

### 8. The PyPI `quiverquant` package is lightweight, method-oriented, and easy to outgrow
It's the first thing a developer pip-installs and it has been updated recently,
so calling it stale is no longer fair. But it remains a thin convenience wrapper:
hand-written dataset methods, direct DataFrame conversion, no point-in-time
date semantics, no cache, no local rate-limit coordination, no drift detection,
and no fixture-backed contract tests. *Fix:* either grow it into a
correctness-first research client, or leave it as the quick-start wrapper and
document when users should move to a more analysis-safe client.

### 9. Pagination ergonomics
`page_size` up to 10,000 is great, but there's no `total` count and no
`next_cursor` — you discover the end by getting a short page.

### Why these matter
The current API forces every integrator to rediscover the same five things
empirically (rate bucket, ignored params, dual response shapes, two date
semantics, plan gating format) and bake that knowledge into a private wrapper.
Fixing 1–3 alone would eliminate the most common silent-correctness bug
(lookahead from misused dates + ignored date filters) and the most common
operational bug (burning the hourly bucket without warning).

---

## Who can fix what: Quiver vs a third-party wrapper

### Only Quiver can fix (server-side / contractual)
- **Rate-limit headers on 200s** — a wrapper can't synthesize
  `X-RateLimit-Remaining`; it can only count its own calls and guess.
- **Silently-ignored query params** (`date_from`/`date_to`) — a wrapper can't
  make the server filter; at best it can post-filter client-side after pulling
  everything, which still burns the bucket.
- **Publishing the actual rate-limit numbers per plan** — a wrapper can
  document empirical findings, but only Quiver can make them contractual
  (i.e. won't change without notice).
- **Machine-readable 403 entitlement bodies** — a wrapper can regex the string,
  but the canonical mapping of `dataset → required_plan` has to come from
  Quiver to stay correct as plans change.
- **Dataset catalog endpoint / real OpenAPI** — a wrapper can ship a
  hand-curated catalog, but it'll drift the moment Quiver adds a dataset or
  column.
- **Deprecating legacy auth (`Token`) and legacy paths (`/beta/live`,
  `/beta/historical`)** — only the server can 410 them.
- **Cursor pagination + `total` count** — wrapper can't fabricate a total
  without first paginating to the end.

### A well-maintained third-party package can fix
- **Uniform response shape** — unwrap `{"data": [...]}` vs bare arrays into one
  consistent return type. Trivial.
- **Auth normalization** — pick `Bearer`, hide the choice from users.
- **The two-date-fields footgun** — ship a per-dataset schema (`event_time` vs
  `available_at`) and either rename columns or expose a `disclosure_date()`
  accessor that's hard to misuse. Exactly the kind of domain knowledge a
  wrapper *should* own.
- **Rate-limit hygiene** — token-bucket client-side limiter (e.g. 25/hour
  default, configurable), automatic `Retry-After` honoring, clear error with
  reset window. `cockpit.quiver_bulk` already does this.
- **Pagination loop + progress** — hide `page`/`page_size`, stream pages,
  expose a generator + a "collect all" convenience.
- **Caching with sensible TTLs** — Parquet/SQLite cache keyed on
  `(dataset, params)`, force-refresh flag. Again, `quiver_bulk` does this.
- **Typed dataset clients** — `client.congress_trading()`, `client.lobbying()`
  returning typed dataframes/pydantic models, with the column quirks
  (e.g. `District` null for senators) documented in docstrings.
- **Plan-gating UX** — catch the 403, raise a typed
  `PlanRequiredError(dataset=..., required_plan=...)` with a hardcoded mapping
  the package maintainer keeps current.
- **Empirical docs** — README that captures all the "not in their docs"
  findings (the bucket size, ignored params, response-shape split). The
  highest-leverage thing a community package provides.
- **Complement the official-ish `quiverquant` package** — don't clone it.
  `quiverquant` is useful for quick pulls; a third-party package should focus on
  the correctness/operations layer it doesn't provide.

### Honest summary
**~70% of the devex pain is wrapper-fixable.** The two date fields,
response-shape split, auth duplication, pagination, caching, and rate-limit
pacing are all client-side concerns that a good package handles once for
everyone — and the fact that no such package exists is mostly why each user
re-implements `quiver_bulk` from scratch.

**The ~30% that needs Quiver** is the high-integrity stuff: rate-limit headers,
honoring documented params, machine-readable errors, and a stable schema
catalog. Without those, even the best wrapper has to guess and degrade
gracefully — fine for hobbyists, blocks production data pipelines.

A well-maintained `quiverfeed` would make 90% of users much happier tomorrow.
But the *correctness* ceiling is set by Quiver.

---

## Name suggestions for the wrapper

Trying to avoid the literal `quiver-py` since it's generic and the namespace
already has `quiverquant` baggage.

**Quiver-themed (signal the source):**
- `arrowquant` — quiver holds arrows; plays on "quant"
- `fletcher` — the craftsman who fletches (makes) arrows; nice that it implies
  "the thing that makes Quiver usable"
- `nock` — the notch on an arrow; short, available-looking, evocative of
  "ready to fire"
- `bowstring` — the tension between you and the data
- `quill` — close to "quiver", suggests "writing/recording," short

**Function-themed (signal what it does):**
- `altdata` — too generic, probably taken
- `congresspy` — too narrow, Quiver is more than congress
- `disclose` / `discloser` — leans into the disclosure-date semantics that the
  wrapper has to get right
- `filed` — same idea, even shorter; pairs well with the `Filed` column
  semantics

**Pun/portmanteau / direct names:**
- `quivverpy` (double-v) — squat, distinct, searchable
- `pyquiver` — boring but clear
- `unquiver` — "unwrap Quiver"; cheeky
- `quiverfeed` — clear, memorable, and directly signals "Quiver data feed"

**Chosen name: `quiverfeed`** — memorable, Quiver-specific, and less likely
than `pyquiver` / `quiver-py` to collide with stale or unrelated packages.
Distribution and import name are both `quiverfeed`.

---

## Positioning vs Quiver's `python-api` / `quiverquant`

Quiver already has a Python package at
https://github.com/Quiver-Quantitative/python-api, published as
`quiverquant`. PyPI shows current package activity (`0.2.5`, released
2026-05-06), even though GitHub's Releases page has no release objects.
`quiverfeed` should not try to win by being "the same thing with newer code."
It should win by being analysis-safe.

The existing package is a convenience wrapper: one class, many hand-written
dataset methods, direct URL construction, immediate `pandas.DataFrame`
conversion. That is approachable for casual users, and the method names are
easy to discover. Its weakness is correctness and operations: no point-in-time
date semantics, no rate-limit coordination, no cache, no pagination abstraction,
no drift detection, no typed errors, and no fixture-backed contract tests.

`quiverfeed` is deliberately different:

- **Point-in-time correctness first.** `available_at` is the headline feature;
  `event_time` is useful context, not the default analysis date.
- **Catalog-backed behavior.** Dataset metadata is explicit, testable, and
  diagnosed against live responses.
- **Sane operational defaults.** Cache by default, protect the local rate
  bucket, and make truncation loud.
- **Small generic API.** `fetch("dataset")`, not one method per endpoint.

Tradeoff: `quiverfeed` will feel less instantly friendly than
`quiverquant.congress_trading("TSLA")`. The README, `DATASETS` display, and
analysis examples need to compensate for that. Do not copy the per-dataset
method style unless real users prove discovery is a bigger problem than
maintenance.

---

## Architectural decisions for `quiverfeed`

This is the implementation contract. The guiding principle: **`quiverfeed`'s
value is the catalog and the canonical date columns, not the wrapper.**
Everything else should be the smallest possible amount of code that makes
those two things usable.

Default stance: choose the conservative behavior that prevents silent bad data,
document the tradeoff, and expose an explicit override when a caller has a
different operational need. Defaults should be boring and safe; overrides should
be visible in code review.

### What `quiverfeed` actually adds over a 50-line `requests` script

In honesty order:

1. A maintained **catalog** of datasets with plan, event/disclosure column
   names, and known ignored params.
2. **Canonical date columns** (`event_time`, `available_at`) added to every
   returned DataFrame, so callers cannot accidentally use the event column
   as a backtest signal date.
3. **Typed errors** so callers can branch on plan-gating vs throttling vs
   auth.
4. **Bucket-aware pacing** that survives across many calls in one session
   (the naive `time.sleep(2)` between pages doesn't help if you call three
   datasets back-to-back).
5. **Cached responses** keyed on `(dataset, params)`.

If a feature isn't directly serving one of those five, it's bloat.

### What `quiverfeed` deliberately doesn't do

A handful of things that look like reasonable defaults from a production
HTTP wrapper but are out of scope here. Read this before assuming they
exist (full list in "Non-goals" further down):

- **No async.** Sync `requests` only. Wrap calls in your own executor
  (`asyncio.to_thread`, `concurrent.futures`) if you need async.
- **Not thread-safe.** One `Client` per thread, or wrap calls in your
  own lock. The shared-state hazards are the bucket and cache writes;
  the fix is one mutex, but it's yours to own.
- **No auto-retry — on anything.** 4xx/5xx and `ConnectionError`
  propagate unchanged. 429 raises `RateLimitError(retry_after_s)`;
  sleeping and resuming is the caller's call (likely a human's, given
  the 1-hour bucket).
- **No typed-row layer.** `fetch()` returns a `pandas.DataFrame`.
  No pydantic, no msgspec, no `output=` knob. If you want stricter
  typing, that's one line in your code.
- **No per-dataset methods or CLI.** `fetch("congresstrading", ...)`
  with a string key is the entire surface. Discovery via
  `quiverfeed.DATASETS`.

The rationale for each is in the relevant section below; the full
non-goals list is at the end. If something here surprises you, the
project README will mirror this list — it's the negative space that
makes the positive space cheap to maintain.

### Public API

```
Client(token: str | None = None,         # falls back to QUIVER_TOKEN
       cache_dir: Path | None = None,    # default $XDG_CACHE_HOME/quiverfeed
       cache_ttl: timedelta = 24 hours,  # per-Dataset override available
       rate_limit_per_hour: int = 20,    # empirical floor of 20–30/hr range
       rate_limit_policy: Literal["raise", "sleep", "off"] = "raise",
       bucket_file: Path | None = None,  # disk-backed bucket; opt-in cross-process safety
       timeout: tuple[float, float] = (5, 30),
       strict_catalog: bool = True)      # raise on event/disclosure col drift

  .fetch(dataset: str,
         page_size: int = 5000,
         max_pages: int | None = None,   # None = until short page
         on_truncated: Literal["raise", "warn", "ignore"] = "raise",
         force: bool = False,
         **params) -> pandas.DataFrame

  .rate_limit_state() -> RateLimitState
```

`Client` is not thread-safe. One `Client` per thread, or wrap calls in
your own lock. No asyncio variant.

Plus two public v0 helpers and one module-level constant:

```
quiverfeed.diagnose(...) -> DiagnoseReport
quiverfeed.assert_disclosure_dated(df: pandas.DataFrame) -> None
quiverfeed.DATASETS: dict[str, Dataset]   # the catalog, frozen
```

That's the entire API. No per-dataset methods, no convenience subsets, no
streaming variants, no return-type modes. `fetch("congresstrading",
chamber="senate")` is the canonical call.

Unknown datasets raise `UnknownDatasetError` from `fetch()`. `quiverfeed` is a
catalog-backed client, not a raw path runner; callers who need an unmodeled
endpoint should add a `Dataset` entry first.

**Why not typed methods like `client.congress_trading()`?** They're
maintenance debt: every new Quiver dataset means a new method, a new test,
a new release. The catalog already encodes everything those methods would
encode. Discovery via `quiverfeed.DATASETS.keys()` is good enough; IDE
autocomplete on a string literal is not worth the maintenance tax.

**Why is `chamber=` passed as `**params`?** Because we don't know which
datasets honor it server-side. The catalog records what's known to be
ignored (and emits `ParamIgnoredWarning`); everything else passes through
unchecked. Adding kwargs requires per-dataset knowledge we don't reliably
have.

### Dataset catalog

A single Python module `quiverfeed/catalog.py` with a frozen dict. No YAML,
no codegen, no build step. Adding a dataset is a one-line PR.

```python
@dataclass(frozen=True, slots=True)
class Dataset:
    name: str
    path: str                          # "/beta/bulk/congresstrading"
    plan: str | None                   # "hobbyist" | "premium" | None if unknown
    event_col: str | None              # original column for when it happened
    disclosure_col: str | None         # original column for when it was filed
    ignored_params: tuple[str, ...] = ()
    default_params: tuple[tuple[str, object], ...] = ()  # e.g. version=V2
    ttl_hours: int | None = None       # None = use Client.cache_ttl default
    notes: str = ""
```

Deliberately minimal: no per-column type list, no update cadence, no
required_plan tier hierarchy. Quiver can change column types unilaterally;
pandas infers fine; encoding types in the catalog just creates a second
source of truth that drifts. `default_params` exists only for endpoint quirks
advertised by Quiver, such as `version=V2`; user params override defaults.

**Initial entries:** Hobbyist-accessible datasets only, discovered and verified
with the maintainer's current token. Premium/non-accessible datasets are
deferred until someone with access can verify the path, date columns, and plan
behavior. Plan field is `None` when uncertain rather than guessed.

**Drift handling:** `quiverfeed.diagnose()` is a public v0 API that any user can
run with their token to print a "your catalog vs reality" diff. Optionally wire
that into a GitHub Action with secrets, but don't make the project depend on a
CI cron — first user to notice drift opens a PR. Low ceremony.

### Canonical date columns

Returned DataFrames preserve original columns and **add** two:
`event_time` and `available_at`, both `datetime64[ns, UTC]`, populated
from `event_col` / `disclosure_col`. If either is `None` in the catalog
(a dataset that genuinely has only one date, or a catalog entry whose dates
are still unknown), the column is omitted; don't fabricate.

**Drift guard, on by default.** If the catalog names an `event_col` /
`disclosure_col` that isn't present in the response, `fetch()` raises
`CatalogDriftError` with the dataset, the missing column, and the
columns Quiver actually returned. This is the failure mode the canonical
columns exist to prevent — making it loud is the entire point. Override
with `Client(strict_catalog=False)` to fall back to a warning.

**Null semantics.** If a row's disclosure column is null, `available_at`
is null in that row. Never fall back to `event_time` — that's the exact
lookahead bug we're trying to prevent.

**Parsing.** Values are parsed with `pd.to_datetime(..., utc=True)`.
Naive timestamps are assumed UTC. If Quiver ever ships a non-UTC field,
`Dataset` can carry a `tz` hint; not added until we hit one.

`quiverfeed.assert_disclosure_dated(df)` still exists as a defensive
helper, but most users won't need it once the drift guard is on by
default.

No other DataFrame transformations. Don't normalize tickers, don't fix
column casing, don't rename `District`. Users who depend on Quiver's exact
schema should not have it shifted under them.

### Errors

Module `quiverfeed.errors`, all inheriting from `QuiverFeedError`:

- `AuthError` — 401 or missing token.
- `PlanRequiredError(dataset, message, hint_plan)` — 403. `message` is
  Quiver's response body verbatim (the source of truth). `hint_plan` is
  the catalog's guess at the required plan and may be `None`; treat it
  as a hint, not a contract — Quiver moves datasets between tiers
  unilaterally.
- `RateLimitError(retry_after_s)` — 429. No fancy reset-time math; the
  caller can do `time.time() + retry_after_s` if they want.
- `CatalogDriftError(dataset, missing_col, actual_cols)` — raised by
  `fetch()` when the catalog's `event_col` / `disclosure_col` isn't
  present in the response. On by default; downgrade to a warning via
  `Client(strict_catalog=False)`.
- `TruncatedResultError(dataset, max_pages)` — raised by default when an
  explicit `max_pages` cap is hit with a full final page, meaning more data may
  exist. Default `max_pages=None` means this never fires unless the user opted
  in.
- `UnknownDatasetError(name)` — raised by `fetch()` when `dataset` is not in
  `DATASETS`.

Plus one warning:

- `ParamIgnoredWarning` — emitted via `warnings.warn` when a passed param
  is in the dataset's `ignored_params`. Standard `warnings` controls apply.

No `UpstreamError` wrapper. `requests.HTTPError` and `ConnectionError`
propagate unchanged — wrapping them adds noise without adding signal.

### Rate limiting

Client-side token bucket, 20/hour default (the empirical floor of the
"20–30/hour" range — better to under-shoot than burn the bucket).
In-memory per-`Client` by default, or file-backed when `bucket_file=`
is set: a JSON file of recent request timestamps, locked with `fcntl`,
~30 lines of code. File-backed is opt-in but documented as the fix for
"two scripts with the same token cancel each other."

Default `rate_limit_policy="raise"`: before making a request, if the local
bucket has no slot, raise `RateLimitError(retry_after_s)` where
`retry_after_s` is computed from the local bucket. This avoids surprise
hour-long sleeps in notebooks and CI. Override policies:

- `"sleep"` — block until a local request slot is available, useful for
  unattended scripts where completion matters more than wall-clock time.
- `"off"` — disable local pacing and rely on Quiver's 429, useful when a caller
  has better external coordination or a higher-tier plan.

The bucket is the secondary defense; the primary defense is the cache.
Cache reads do not consume the bucket. `force=True` does (it makes a
real HTTP call).

On 429: raise `RateLimitError(retry_after_s)` with the server's
`Retry-After` value verbatim. No auto-retry, no exponential backoff,
no jitter. A 1-hour wait is a human decision.

### Caching

- Parquet under `cache_dir / dataset / <sha1(cache_key_params)>.parquet`,
  where `cache_key_params = sorted(params) - {page, page_size}` — those
  are loop concerns, not data identity.
- Sidecar `<sha1>.json` with `{fetched_at, params, row_count,
  quiverfeed_version, schema_hash}`. `schema_hash` is `sha1` of the sorted
  response column names; mismatch on read invalidates the entry. Cheap
  insurance against Quiver adding/renaming columns.
- TTL: 24h default (`Client.cache_ttl`), overridable per-dataset via
  `Dataset.ttl_hours`.
- `force=True` skips the cache read but still writes — and still
  consumes the rate-limit bucket.
- Cache reads do not consume the rate-limit bucket.
- Only completed fetches are cached. Failed requests and truncated partial
  results are not written, even when `on_truncated="warn"` or `"ignore"`, because
  a normal cache hit must mean "complete for these params."

That's it. No DuckDB, no S3, no pluggable backend protocol. If someone
wants those, they fork or PR; designing the abstraction up front means
maintaining it forever for hypothetical users.

### Auth, response shape, pagination

- Only `Authorization: Bearer <token>`. The legacy `Token` form is not
  supported.
- Both `{"data": [...]}` and bare-array responses are unwrapped to
  `list[dict]` before DataFrame construction.
- Pagination: internal loop, `page` + `page_size`, stops on short page.
  Page numbering starts at 1. Default `max_pages=None` means no cap. If
  `max_pages` is set and the final allowed page is full, the result may be
  incomplete; default `on_truncated="raise"` raises `TruncatedResultError`.
  `on_truncated="warn"` returns the partial DataFrame with a warning, and
  `on_truncated="ignore"` returns it silently. If the final allowed page is
  short, return normally.
- Passing `page=` or `page_size=` in `**params` raises `ValueError`;
  those are loop concerns owned by `fetch()`.
- HTTP timeout default `(connect=5, read=30)`. Configurable via
  `Client(timeout=...)`.
- All requests logged via `logging.getLogger("quiverfeed")` at DEBUG
  (method, path, status, latency, page). Stdlib logger only — no
  opinionated structured-logging integration.
- Legacy `/beta/live/...` and `/beta/historical/...` paths are accessible
  by setting `Dataset.path` to them in the catalog; no separate API.

### Dependencies and Python floor

- Hard deps: `requests`, `pandas`, `pyarrow` (Parquet).
- No optional extras. No `pydantic`, no `polars`, no `duckdb`. Anyone
  who wants those wraps the returned DataFrame themselves — one line.
- Python 3.11+. `datetime.UTC`, `Self`, `tomllib`, `StrEnum` if useful.
- License: MIT.

### `DISCOVERY.md`

A short companion doc in the repo capturing every empirically-found fact
about the API: bucket size, ignored-params list, response-shape split,
date-column conventions per dataset, plan-gating string format. Cited
from the README. The point: if `quiverfeed` is ever abandoned, the
discovery survives. This is at least as valuable as the code.

### Testing

- Recorded HTTP fixtures (VCR-style) under `tests/fixtures/`, token
  scrubbed. These run on every commit and don't need network or a token.
- Live tests behind `QUIVERFEED_LIVE=1`. One test per Hobbyist dataset:
  fetches page 1, asserts `event_time` and `available_at` are populated.
  No assertion on column counts or types — those will drift.
- Live tests are not run in CI — they burn the rate-limit bucket. Run
  manually before a release, or on a scheduled job with a dedicated
  token.
- Bucket / cache logic tested with a mocked transport; no live calls.

### Non-goals — keep these explicit

- No typed per-dataset methods.
- No DataFrame joins, signal construction, or backtesting.
- No async client.
- No CLI.
- No OpenBB provider in this package.
- No auto-retry on any error.
- No structured logging mode.
- No cross-process rate-limit coordination *by default*. `bucket_file=`
  is opt-in; we don't ship Redis, etcd, or any service-backed bucket.
- No pluggable cache backend.
- No typed-row layer shipped by `quiverfeed`. Users who want pydantic /
  msgspec / TypedDict over the rows do that in their own code.

If a future maintainer is tempted to add any of these, the burden of proof
is on them: a real user with a concrete need, not a hypothetical.

### Migration from `cockpit.quiver_bulk`

Drop-in for current usage:

```python
# before
df = cockpit.quiver_bulk("congresstrading", max_pages=5)

# after — explicit cap raises TruncatedResultError if final page is full
df = quiverfeed.Client().fetch("congresstrading", max_pages=5)

# or — unbounded (new default), pulls until short page
df = quiverfeed.Client().fetch("congresstrading")
```

The returned DataFrame is a superset (adds `event_time` / `available_at`),
so downstream code that selects specific columns is unaffected.

### Open questions after the Hobbyist-first v0

1. Premium/exhaustive dataset list — what does a Premium token actually expose?
2. Plan-tier matrix — `premium` is probably 2–3 tiers in reality. Either
   collapse to `non_hobbyist` or wait until Quiver clarifies.
3. Per-dataset honored-params probe — `date_from` / `date_to` are dropped
   on `congresstrading`, but other datasets are unverified.
4. Cursor pagination — does any endpoint expose it? Prefer over page
   numbering if so.

Don't gate the Hobbyist-first v0 on Quiver answering anything — they may never.
Ship 0.x with the catalog as-known; tag v1.0 when `quiverfeed.diagnose()` passes
against the major datasets a maintainer can reach, and (3) is verified for
those datasets. (1), (2), and (4) become continuously-improved metadata, not
release blockers.
