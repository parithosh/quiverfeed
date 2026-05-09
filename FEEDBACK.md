# Feedback: making `quiverfeed` actually useful

This is the gap list captured while integrating `quiverfeed` into the `tradoor`
research environment (`/Users/parithosh/Dev/personal/tradoor`). Items are
ranked by how badly they bite that integration today. The branch
`tradoor-integration-feedback` works through them in order.

## Blockers (would force notebook-side workarounds)

### 1. No inter-page pacing
`cockpit.quiver_bulk` (the function this client replaces) sleeps ~2 s between
pages. `quiverfeed` only enforces the hourly token bucket — five pages fire
back-to-back. Quiver doesn't publish per-second limits, but the existing
pacing was empirical: removing it risks tripping a per-second/burst rule
without a clean error.

**Fix:** add `Client(request_pause_s=...)` defaulting to ~1.0 s; sleep between
pages, not before the first request.

### 2. `congresstrading` defaults to `version=V2` with no source
`catalog.py:33` sets `default_params=(("version", "V2"),)`. The cockpit code
does **not** send this and works fine. If V2 isn't actually live or required,
every default fetch silently changes the response shape (or 4xx). There is no
note in `DISCOVERY.md` justifying it.

**Fix:** drop the default unless documented in `DISCOVERY.md` as required.

### 3. `on_truncated="raise"` is the wrong default
`client.py:71`. The notebook calls with `max_pages=5` because that's the right
size for a research run. A full final page is the *normal* outcome. With
`on_truncated="raise"`, the library raises on the happy path.

**Fix:** default to `"warn"`. Callers asking for `max_pages=N` are signalling
they accept partial results.

### 4. Forced UTC timestamps clash with naive-ET projects
`client.py:226` does `pd.to_datetime(df[source_col], utc=True)`. The cockpit
project pins everything to naive ET (cockpit.py:137-138). Every consumer must
re-localize. For date-only columns like `Filed`/`Traded` the localization is
also slightly lossy (midnight UTC ≠ midnight ET).

**Fix:** add `Client(tz=...)` with `tz=None` ⇒ naive output. Default kept
UTC-aware for backwards compatibility.

## Should-fix (felt during integration)

### 5. No escape hatch for endpoints outside the catalog
`tradoor/notebooks/00_setup_test.py:88` uses `/beta/bulk/congress/politicians`.
There's no way to reach it through `quiverfeed` without forking the package.

**Fix:** ship `politicians` in the catalog (the most useful immediate win) and
expose a `Client.request(path, params)` low-level method as escape hatch for
endpoints not yet catalogued.

### 6. Single-blob TTL cache, no incremental fetch
`congresstrading` is append-mostly with occasional restatements. Today, a
7-day TTL means stale signals or a full re-pull on every refresh. The cockpit
implementation has the same limitation — but a research client should improve
on this.

**Fix:** out of scope for this branch; tracked as a follow-up. Add a doc note
in the README that today's cache is whole-blob.

### 7. No retries on transient errors
A single 5xx or connection blip kills a multi-page fetch and burns the
rate-limit tokens already spent. With a 20/hr bucket, that's painful.

**Fix:** bounded jittered backoff for 5xx and connection errors. Never retry
401/403/429 — those are explicit signals.

### 8. `disclosure_col=None` datasets fail PIT validation silently
`assert_disclosure_dated` raises a generic `ValueError` if `available_at` is
missing. For datasets that the catalog *knows* have no disclosure column
(`lobbying`, `bill_summaries`), the error should be specific: "this dataset
has no advertised disclosure date; it cannot be used point-in-time."

**Fix:** add `validate_pit(df, dataset_name)` that consults the catalog.

### 9. Catalog isn't extensible
Adding a new dataset means editing the package. For exploratory research,
that's heavy-handed.

**Fix:** public `quiverfeed.register_dataset(Dataset(...))`.

### 10. Not on PyPI
Until `quiverfeed` is published, downstream projects depend on it via
`git+https://...` or local path. Not a code issue, but blocks frictionless
adoption.

**Fix:** out of scope for this branch — publish a `0.1.0` once these changes
land.

## Minor

### 11.a `RateLimitState.reset_at` only populates when exhausted
`rate_limit.py:69-72`. Useful info hidden behind exhaustion. Always populate
when there's at least one timestamp in the window.

### 11.b `bucket_file` is POSIX-only
`rate_limit.py:97` uses `fcntl`. Windows breaks. Document or guard. (Tradoor
is macOS only — fix deferred.)

### 11.c `diagnose()` burns 1 token per dataset per call
`diagnostics.py:67-73` issues `force=True` per dataset. Four datasets = 4
hourly tokens for a health check; non-trivial against a 20/hr bucket.

**Fix:** cache the report for ~1 h by default, with `force=True` to bypass.

### 11.d `pyproject.toml` Python version
Says `>=3.11`. Tradoor pins `>=3.14,<3.15`. Probably fine, but worth noting if
3.11-only syntax sneaks in. (Currently uses 3.11+ `UTC` import — OK.)

## Deferred (tracked, not in this branch)

- #6 incremental cache
- #10 PyPI publish
- #11.b Windows file-lock support
- Async client
- CLI (`python -m quiverfeed fetch ...`)
