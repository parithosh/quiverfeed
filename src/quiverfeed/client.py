from __future__ import annotations

import logging
import os
import re
import time
import warnings
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any, Iterable, Literal, Mapping
from urllib.parse import quote, urljoin

import pandas as pd
import requests

from ._version import __version__
from .cache import CacheEntry, CacheStore
from .catalog import Dataset, all_datasets, get_dataset
from .errors import (
    AuthError,
    CatalogDriftError,
    CatalogDriftWarning,
    ParamIgnoredWarning,
    ParamStrippedWarning,
    PlanRequiredError,
    QuiverFeedError,
    RateLimitError,
    ResponseShapeError,
    TruncatedResultError,
    TruncatedResultWarning,
    UnknownDatasetError,
)
from .rate_limit import RateLimitPolicy, RateLimitState, TokenBucket

OnTruncated = Literal["raise", "warn", "ignore"]
CacheStatus = Literal["hit", "miss", "stale"]

LOGGER = logging.getLogger("quiverfeed")
DEFAULT_BASE_URL = "https://api.quiverquant.com"
RETRY_BACKOFF_S = 0.5  # base for exponential retry; tune via subclass if needed
CANARY_COLUMNS = (
    "dataset",
    "path",
    "status",
    "rows",
    "columns",
    "event_col",
    "disclosure_col",
    "has_event_time",
    "has_available_at",
    "error",
)
PATH_PARAM_RE = re.compile(r"\{([A-Za-z_][A-Za-z0-9_]*)\}")


@dataclass(frozen=True, slots=True)
class FetchInfo:
    dataset: str
    path: str
    rows: int
    page_count: int
    cache_status: CacheStatus
    cache_hit: bool
    stale: bool
    cache_fetched_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class FetchResult:
    df: pd.DataFrame
    info: FetchInfo


class Client:
    def __init__(
        self,
        token: str | None = None,
        cache_dir: Path | str | None = None,
        cache_ttl: timedelta = timedelta(hours=24),
        rate_limit_per_hour: int = 20,
        rate_limit_policy: RateLimitPolicy = "raise",
        bucket_file: Path | str | None = None,
        timeout: tuple[float, float] = (5, 30),
        strict_catalog: bool = True,
        request_pause_s: float = 1.0,
        tz: str | None = "UTC",
        max_retries: int = 2,
        *,
        session: requests.Session | None = None,
        base_url: str = DEFAULT_BASE_URL,
    ):
        self.token = token if token is not None else os.getenv("QUIVER_TOKEN")
        self.cache_ttl = cache_ttl
        self.timeout = timeout
        self.strict_catalog = strict_catalog
        self.request_pause_s = request_pause_s
        self.tz = tz
        self.max_retries = max_retries
        self.base_url = base_url
        self._session = session or requests.Session()
        self._cache = CacheStore(cache_dir)
        self._bucket = TokenBucket(
            limit_per_hour=rate_limit_per_hour,
            policy=rate_limit_policy,
            bucket_file=bucket_file,
        )

    def fetch(
        self,
        dataset: str,
        page_size: int = 5000,
        max_pages: int | None = None,
        on_truncated: OnTruncated = "warn",
        force: bool = False,
        stale_if_error: bool = False,
        stale_if_rate_limit: bool = False,
        **params: Any,
    ) -> pd.DataFrame:
        result = self._fetch(
            dataset,
            page_size=page_size,
            max_pages=max_pages,
            on_truncated=on_truncated,
            force=force,
            stale_if_error=stale_if_error,
            stale_if_rate_limit=stale_if_rate_limit,
            **params,
        )
        return result.df

    def fetch_many(
        self,
        dataset: str,
        tickers: Iterable[str],
        page_size: int = 5000,
        max_pages: int | None = None,
        on_truncated: OnTruncated = "warn",
        force: bool = False,
        resume: bool = True,
        continue_on_error: bool = False,
        stale_if_error: bool = False,
        stale_if_rate_limit: bool = False,
        ticker_param: str = "ticker",
        **params: Any,
    ) -> tuple[pd.DataFrame, pd.DataFrame]:
        dataset_meta = get_dataset(dataset)
        if dataset_meta is None:
            raise UnknownDatasetError(dataset, list(all_datasets().keys()))
        if ticker_param not in _path_param_names(dataset_meta):
            raise ValueError(
                f"Dataset {dataset_meta.name!r} does not have a "
                f"{ticker_param!r} path parameter."
            )
        if isinstance(tickers, str):
            raise ValueError("tickers must be an iterable of ticker strings.")

        frames: list[pd.DataFrame] = []
        status_rows: list[dict[str, Any]] = []
        effective_force = force or not resume
        for ticker in tickers:
            ticker_value = str(ticker).strip()
            if not ticker_value:
                raise ValueError("tickers must not contain blank values.")

            ticker_params = dict(params)
            ticker_params[ticker_param] = ticker_value
            try:
                result = self._fetch(
                    dataset_meta.name,
                    page_size=page_size,
                    max_pages=max_pages,
                    on_truncated=on_truncated,
                    force=effective_force,
                    stale_if_error=stale_if_error,
                    stale_if_rate_limit=stale_if_rate_limit,
                    **ticker_params,
                )
                frames.append(result.df)
                status_rows.append(
                    {
                        "ticker": ticker_value,
                        "dataset": result.info.dataset,
                        "status": "stale" if result.info.stale else "ok",
                        "rows": len(result.df),
                        "error": "",
                        "error_type": "",
                        "cache_status": result.info.cache_status,
                        "cache_hit": result.info.cache_hit,
                        "stale": result.info.stale,
                        "page_count": result.info.page_count,
                        "retry_after_seconds": None,
                        "reset_at": None,
                    }
                )
            except (QuiverFeedError, requests.RequestException) as exc:
                if not continue_on_error:
                    raise
                status_rows.append(
                    _fetch_many_error_row(
                        ticker_value,
                        dataset_meta.name,
                        exc,
                    )
                )

        if frames:
            df = pd.concat(frames, ignore_index=True)
        else:
            df = pd.DataFrame()
        status = pd.DataFrame(
            status_rows,
            columns=(
                "ticker",
                "dataset",
                "status",
                "rows",
                "error",
                "error_type",
                "cache_status",
                "cache_hit",
                "stale",
                "page_count",
                "retry_after_seconds",
                "reset_at",
            ),
        )
        return df, status

    def profile(
        self,
        dataset: str,
        page_size: int = 10000,
        max_pages: int = 20,
        force: bool = False,
        **params: Any,
    ) -> dict[str, Any]:
        result = self._fetch(
            dataset,
            page_size=page_size,
            max_pages=max_pages,
            on_truncated="ignore",
            force=force,
            **params,
        )
        df = result.df
        columns = tuple(str(col) for col in df.columns)
        symbol_col = _first_existing_column(df, ("Ticker", "ticker", "Symbol", "symbol"))

        event = df["event_time"] if "event_time" in df.columns else None
        available = df["available_at"] if "available_at" in df.columns else None
        lags = None
        if event is not None and available is not None:
            lags = (available - event).dropna()

        return {
            "dataset": result.info.dataset,
            "path": result.info.path,
            "rows": int(len(df)),
            "columns": columns,
            "symbol_count": (
                int(df[symbol_col].dropna().nunique()) if symbol_col is not None else None
            ),
            "event_time_min": _series_min(event),
            "event_time_max": _series_max(event),
            "available_at_min": _series_min(available),
            "available_at_max": _series_max(available),
            "null_event_time": (
                int(event.isna().sum()) if event is not None else int(len(df))
            ),
            "null_available_at": (
                int(available.isna().sum()) if available is not None else int(len(df))
            ),
            "median_lag": _lag_quantile(lags, 0.5),
            "p90_lag": _lag_quantile(lags, 0.9),
            "max_lag": _lag_max(lags),
            "page_count": result.info.page_count,
            "cache_status": result.info.cache_status,
            "cache_hit": result.info.cache_hit,
            "stale": result.info.stale,
        }

    def _fetch(
        self,
        dataset: str,
        page_size: int = 5000,
        max_pages: int | None = None,
        on_truncated: OnTruncated = "warn",
        force: bool = False,
        stale_if_error: bool = False,
        stale_if_rate_limit: bool = False,
        **params: Any,
    ) -> FetchResult:
        if page_size < 1:
            raise ValueError("page_size must be >= 1")
        if max_pages is not None and max_pages < 1:
            raise ValueError("max_pages must be >= 1 when provided")
        if on_truncated not in {"raise", "warn", "ignore"}:
            raise ValueError("on_truncated must be 'raise', 'warn', or 'ignore'")
        if "page" in params or "page_size" in params:
            raise ValueError("page and page_size are owned by fetch()")

        dataset_meta = get_dataset(dataset)
        if dataset_meta is None:
            raise UnknownDatasetError(dataset, list(all_datasets().keys()))

        page_size = self._safe_page_size(dataset_meta, page_size)
        safe_params = self._strip_unsafe_params(dataset_meta, params)
        self._warn_ignored_params(dataset_meta, safe_params)
        cache_params = self._cache_params(dataset_meta, safe_params)
        ttl = self._ttl_for(dataset_meta)

        if not force:
            cached = self._cache.get_entry(dataset_meta.name, cache_params, ttl=ttl)
            if cached is not None:
                return _cache_result(dataset_meta, cached, cache_status="hit")

        try:
            return self._fetch_uncached(
                dataset_meta,
                cache_params,
                page_size=page_size,
                max_pages=max_pages,
                on_truncated=on_truncated,
            )
        except RateLimitError:
            if stale_if_error or stale_if_rate_limit:
                stale = self._cache.get_stale(dataset_meta.name, cache_params)
                if stale is not None:
                    return _cache_result(dataset_meta, stale, cache_status="stale")
            raise
        except requests.RequestException:
            if stale_if_error:
                stale = self._cache.get_stale(dataset_meta.name, cache_params)
                if stale is not None:
                    return _cache_result(dataset_meta, stale, cache_status="stale")
            raise

    def _fetch_uncached(
        self,
        dataset_meta: Dataset,
        cache_params: Mapping[str, Any],
        *,
        page_size: int,
        max_pages: int | None,
        on_truncated: OnTruncated,
    ) -> FetchResult:

        rows: list[Mapping[str, Any]] = []
        truncated = False
        page_count = 0
        if dataset_meta.paginated:
            page = 1
            while True:
                page_params = dict(cache_params)
                page_params["page"] = page
                page_params["page_size"] = page_size

                page_rows = self._request_rows(dataset_meta, page_params, page)
                page_count += 1
                rows.extend(page_rows)

                if len(page_rows) < page_size:
                    break
                if max_pages is not None and page >= max_pages:
                    truncated = True
                    break
                page += 1
                # Pace inter-page requests. The hourly bucket protects against
                # daily-budget burn, but Quiver also appears to apply a
                # per-second/burst rule that the bucket doesn't catch.
                if self.request_pause_s > 0:
                    time.sleep(self.request_pause_s)
        else:
            page = 1
            page_rows = self._request_rows(dataset_meta, cache_params, page)
            page_count = 1
            rows.extend(page_rows)

        df = self._to_dataframe(dataset_meta, rows)
        if truncated:
            if on_truncated == "raise":
                raise TruncatedResultError(dataset_meta.name, max_pages or page)
            if on_truncated == "warn":
                warnings.warn(
                    (
                        f"Fetch for {dataset_meta.name!r} hit max_pages={max_pages} "
                        "with a full final page; returning a partial result."
                    ),
                    TruncatedResultWarning,
                    stacklevel=2,
                )
            return FetchResult(
                df=df,
                info=FetchInfo(
                    dataset=dataset_meta.name,
                    path=dataset_meta.path,
                    rows=len(df),
                    page_count=page_count,
                    cache_status="miss",
                    cache_hit=False,
                    stale=False,
                ),
            )

        self._cache.set(
            dataset_meta.name,
            cache_params,
            df,
            __version__,
            extra_metadata={
                "page_count": page_count,
                "page_size": page_size,
            },
        )
        return FetchResult(
            df=df,
            info=FetchInfo(
                dataset=dataset_meta.name,
                path=dataset_meta.path,
                rows=len(df),
                page_count=page_count,
                cache_status="miss",
                cache_hit=False,
                stale=False,
            ),
        )

    def rate_limit_state(self) -> RateLimitState:
        return self._bucket.state()

    def canary(
        self,
        plan: str | None = "hobbyist",
        page_size: int = 5,
        max_pages: int = 1,
        *,
        sample_ticker: str = "AAPL",
    ) -> pd.DataFrame:
        if page_size < 1:
            raise ValueError("page_size must be >= 1")
        if max_pages < 1:
            raise ValueError("max_pages must be >= 1")

        rows: list[dict[str, Any]] = []
        for dataset in all_datasets().values():
            if plan is not None and dataset.plan != plan:
                continue

            params = _sample_path_params(dataset, sample_ticker=sample_ticker)
            try:
                df = self.fetch(
                    dataset.name,
                    page_size=page_size,
                    max_pages=max_pages,
                    on_truncated="ignore",
                    force=True,
                    **params,
                )
                rows.append(_canary_row(dataset, "ok", df=df))
            except PlanRequiredError as exc:
                rows.append(_canary_row(dataset, "plan_required", error=str(exc)))
            except RateLimitError as exc:
                rows.append(_canary_row(dataset, "rate_limited", error=str(exc)))
            except CatalogDriftError as exc:
                rows.append(
                    _canary_row(
                        dataset,
                        "catalog_drift",
                        columns=tuple(str(col) for col in exc.actual_cols),
                        error=str(exc),
                    )
                )
            except Exception as exc:
                rows.append(
                    _canary_row(
                        dataset,
                        type(exc).__name__,
                        error=str(exc),
                    )
                )

        return pd.DataFrame(rows, columns=CANARY_COLUMNS)

    def _request_rows(
        self,
        dataset: Dataset,
        params: Mapping[str, Any],
        page: int,
    ) -> list[Mapping[str, Any]]:
        if not self.token:
            raise AuthError("Missing token. Pass token=... or set QUIVER_TOKEN.")

        headers = {
            "accept": "application/json",
            "Authorization": f"Bearer {self.token}",
        }
        path, query_params = _interpolate_path(dataset, params)
        url = urljoin(self.base_url.rstrip("/") + "/", path.lstrip("/"))

        # One bucket charge per logical page request — retries do not consume
        # extra tokens since the upstream never serviced the original.
        self._bucket.acquire(dataset=dataset.name, path=path)

        attempt = 0
        while True:
            try:
                response = self._session.get(
                    url,
                    headers=headers,
                    params=query_params,
                    timeout=self.timeout,
                )
            except (requests.ConnectionError, requests.Timeout):
                if attempt >= self.max_retries:
                    raise
                time.sleep(RETRY_BACKOFF_S * (2**attempt))
                attempt += 1
                continue

            status_code = getattr(response, "status_code", None)
            LOGGER.debug(
                "GET %s status=%s page=%s attempt=%d",
                path, status_code, page, attempt,
            )

            if status_code is not None and 500 <= status_code < 600:
                if attempt >= self.max_retries:
                    response.raise_for_status()
                time.sleep(RETRY_BACKOFF_S * (2**attempt))
                attempt += 1
                continue

            if status_code == 401:
                raise AuthError("Quiver returned 401 Unauthorized.")
            if status_code == 403:
                raise PlanRequiredError(
                    dataset.name,
                    _response_text(response),
                    dataset.plan,
                    path=dataset.path,
                )
            if status_code == 429:
                retry_after, reset_at = _retry_after_and_reset(response)
                raise RateLimitError(
                    retry_after,
                    reset_at=reset_at,
                    dataset=dataset.name,
                    path=path,
                )
            if status_code is not None and status_code >= 400:
                response.raise_for_status()

            payload = response.json()
            if isinstance(payload, list):
                return _ensure_rows(dataset.name, payload)
            if isinstance(payload, dict) and isinstance(payload.get("data"), list):
                return _ensure_rows(dataset.name, payload["data"])

            raise ResponseShapeError(dataset.name, type(payload).__name__)

    def _to_dataframe(
        self,
        dataset: Dataset,
        rows: list[Mapping[str, Any]],
    ) -> pd.DataFrame:
        df = pd.DataFrame(rows)
        if df.empty:
            return df

        if dataset.event_col is not None:
            self._add_canonical_date(df, dataset, dataset.event_col, "event_time")
        if dataset.disclosure_col is not None:
            self._add_canonical_date(
                df,
                dataset,
                dataset.disclosure_col,
                "available_at",
            )
        return df

    def _add_canonical_date(
        self,
        df: pd.DataFrame,
        dataset: Dataset,
        source_col: str,
        target_col: str,
    ) -> None:
        if source_col not in df.columns:
            if self.strict_catalog:
                raise CatalogDriftError(dataset.name, source_col, list(df.columns))
            warnings.warn(
                (
                    f"Catalog drift for {dataset.name!r}: expected column "
                    f"{source_col!r}, got columns {list(df.columns)!r}."
                ),
                CatalogDriftWarning,
                stacklevel=2,
            )
            return
        # Parse to UTC consistently, then project to caller-requested tz.
        # tz=None ⇒ naive output (lossy for tz-aware sources, intentional
        # for projects pinned to a single zone). tz="UTC" ⇒ unchanged.
        parsed = pd.to_datetime(
            df[source_col],
            utc=True,
            errors="coerce",
            format="mixed",
        )
        if self.tz is None:
            df[target_col] = parsed.dt.tz_localize(None)
        elif self.tz == "UTC":
            df[target_col] = parsed
        else:
            df[target_col] = parsed.dt.tz_convert(self.tz)

    @staticmethod
    def _warn_ignored_params(dataset: Dataset, params: Mapping[str, Any]) -> None:
        for param in dataset.ignored_params:
            if param in params:
                warnings.warn(
                    (
                        f"Parameter {param!r} is known to be ignored by "
                        f"dataset {dataset.name!r}; quiverfeed will pass it "
                        "through but the server may not filter."
                    ),
                    ParamIgnoredWarning,
                    stacklevel=3,
                )

    @staticmethod
    def _strip_unsafe_params(
        dataset: Dataset,
        params: Mapping[str, Any],
    ) -> dict[str, Any]:
        safe_params = dict(params)
        stripped = [param for param in dataset.stripped_params if param in safe_params]
        for param in stripped:
            safe_params.pop(param, None)
        if stripped:
            detail = dataset.param_safety_note or (
                f"parameters {stripped!r} are unsupported for {dataset.name!r}"
            )
            warnings.warn(
                (
                    f"Stripping parameter(s) {', '.join(stripped)!r} for "
                    f"dataset {dataset.name!r}: {detail}."
                ),
                ParamStrippedWarning,
                stacklevel=3,
            )
        return safe_params

    @staticmethod
    def _safe_page_size(dataset: Dataset, page_size: int) -> int:
        if dataset.max_page_size is None or page_size <= dataset.max_page_size:
            return page_size
        warnings.warn(
            (
                f"page_size={page_size} is above the known-safe limit for "
                f"dataset {dataset.name!r}; using page_size={dataset.max_page_size}."
            ),
            ParamStrippedWarning,
            stacklevel=3,
        )
        return dataset.max_page_size

    @staticmethod
    def _cache_params(dataset: Dataset, params: Mapping[str, Any]) -> dict[str, Any]:
        merged = dataset.defaults()
        merged.update(params)
        merged.pop("page", None)
        merged.pop("page_size", None)
        return merged

    def _ttl_for(self, dataset: Dataset) -> timedelta:
        if dataset.ttl_hours is not None:
            return timedelta(hours=dataset.ttl_hours)
        return self.cache_ttl


def _ensure_rows(dataset: str, rows: list[Any]) -> list[Mapping[str, Any]]:
    for row in rows:
        if not isinstance(row, Mapping):
            raise ResponseShapeError(dataset, f"list[{type(row).__name__}]")
    return rows


def _path_param_names(dataset: Dataset) -> tuple[str, ...]:
    return tuple(PATH_PARAM_RE.findall(dataset.path))


def _sample_path_params(dataset: Dataset, *, sample_ticker: str) -> dict[str, str]:
    params: dict[str, str] = {}
    for name in _path_param_names(dataset):
        if name == "ticker":
            params[name] = sample_ticker
    return params


def _interpolate_path(
    dataset: Dataset,
    params: Mapping[str, Any],
) -> tuple[str, dict[str, Any]]:
    query_params = dict(params)

    def replace(match: re.Match[str]) -> str:
        name = match.group(1)
        if name not in params or params[name] is None:
            raise ValueError(
                f"Missing path parameter {name!r} for dataset {dataset.name!r}."
            )
        query_params.pop(name, None)
        return quote(str(params[name]), safe="")

    return PATH_PARAM_RE.sub(replace, dataset.path), query_params


def _cache_result(
    dataset: Dataset,
    entry: CacheEntry,
    *,
    cache_status: CacheStatus,
) -> FetchResult:
    path = dataset.path
    params = entry.metadata.get("params", {})
    if isinstance(params, Mapping):
        try:
            path, _ = _interpolate_path(dataset, params)
        except ValueError:
            path = dataset.path
    return FetchResult(
        df=entry.df,
        info=FetchInfo(
            dataset=dataset.name,
            path=path,
            rows=len(entry.df),
            page_count=_metadata_int(entry.metadata, "page_count"),
            cache_status=cache_status,
            cache_hit=True,
            stale=cache_status == "stale",
            cache_fetched_at=entry.fetched_at,
        ),
    )


def _metadata_int(metadata: Mapping[str, Any], key: str) -> int:
    try:
        return int(metadata.get(key, 0) or 0)
    except (TypeError, ValueError):
        return 0


def _fetch_many_error_row(
    ticker: str,
    dataset: str,
    exc: Exception,
) -> dict[str, Any]:
    retry_after_seconds = None
    reset_at = None
    status = "error"
    if isinstance(exc, RateLimitError):
        status = "rate_limited"
        retry_after_seconds = exc.retry_after_seconds
        reset_at = exc.reset_at
    return {
        "ticker": ticker,
        "dataset": dataset,
        "status": status,
        "rows": 0,
        "error": str(exc),
        "error_type": type(exc).__name__,
        "cache_status": None,
        "cache_hit": False,
        "stale": False,
        "page_count": 0,
        "retry_after_seconds": retry_after_seconds,
        "reset_at": reset_at,
    }


def _first_existing_column(df: pd.DataFrame, candidates: tuple[str, ...]) -> str | None:
    for candidate in candidates:
        if candidate in df.columns:
            return candidate
    return None


def _series_min(series: pd.Series | None) -> Any:
    if series is None:
        return None
    value = series.min()
    return None if pd.isna(value) else value


def _series_max(series: pd.Series | None) -> Any:
    if series is None:
        return None
    value = series.max()
    return None if pd.isna(value) else value


def _lag_quantile(lags: pd.Series | None, quantile: float) -> Any:
    if lags is None or lags.empty:
        return None
    return lags.quantile(quantile)


def _lag_max(lags: pd.Series | None) -> Any:
    if lags is None or lags.empty:
        return None
    return lags.max()


def _canary_row(
    dataset: Dataset,
    status: str,
    *,
    df: pd.DataFrame | None = None,
    columns: tuple[str, ...] = (),
    error: str = "",
) -> dict[str, Any]:
    if df is not None:
        columns = tuple(str(col) for col in df.columns)
        rows = len(df)
    else:
        rows = 0
    return {
        "dataset": dataset.name,
        "path": dataset.path,
        "status": status,
        "rows": rows,
        "columns": columns,
        "event_col": dataset.event_col,
        "disclosure_col": dataset.disclosure_col,
        "has_event_time": "event_time" in columns,
        "has_available_at": "available_at" in columns,
        "error": error,
    }


def _response_text(response: Any) -> str:
    text = getattr(response, "text", "")
    if isinstance(text, str):
        return text.strip()
    return str(text)


def _retry_after(response: Any) -> float:
    retry_after, _ = _retry_after_and_reset(response)
    return retry_after


def _retry_after_and_reset(response: Any) -> tuple[float, datetime | None]:
    headers = getattr(response, "headers", {}) or {}
    if not hasattr(headers, "get"):
        return 3600.0, None

    now = datetime.now(UTC)
    value = headers.get("Retry-After")
    try:
        retry_after = max(float(value), 0.0)
        return retry_after, now + timedelta(seconds=retry_after)
    except (TypeError, ValueError):
        pass

    reset_at = _parse_datetime_header(value)
    if reset_at is not None:
        return max((reset_at - now).total_seconds(), 0.0), reset_at

    for key in ("X-RateLimit-Reset", "X-RateLimit-Reset-At", "RateLimit-Reset"):
        reset_at = _parse_reset_header(headers.get(key), now)
        if reset_at is not None:
            return max((reset_at - now).total_seconds(), 0.0), reset_at

    return 3600.0, now + timedelta(hours=1)


def _parse_reset_header(value: Any, now: datetime) -> datetime | None:
    if value is None:
        return None
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return _parse_datetime_header(value)

    if numeric > 1_000_000_000:
        return datetime.fromtimestamp(numeric, UTC)
    return now + timedelta(seconds=max(numeric, 0.0))


def _parse_datetime_header(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)
