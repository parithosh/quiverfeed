from __future__ import annotations

import json
import warnings
from datetime import UTC, datetime, timedelta

import pandas as pd
import pytest
import requests

import quiverfeed
from quiverfeed.errors import (
    AuthError,
    ParamIgnoredWarning,
    ParamStrippedWarning,
    PlanRequiredError,
    RateLimitError,
    TruncatedResultError,
    TruncatedResultWarning,
    UnknownDatasetError,
)


class FakeResponse:
    def __init__(self, payload, status_code=200, headers=None, text=""):
        self._payload = payload
        self.status_code = status_code
        self.headers = headers or {}
        self.text = text

    def json(self):
        return self._payload

    def raise_for_status(self):
        raise requests.HTTPError(f"HTTP {self.status_code}")


class FakeSession:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def get(self, url, headers, params, timeout):
        self.calls.append(
            {
                "url": url,
                "headers": headers,
                "params": dict(params),
                "timeout": timeout,
            }
        )
        if not self.responses:
            raise AssertionError("No fake responses left")
        return self.responses.pop(0)


def congress_row():
    return {
        "Filed": "2024-01-10",
        "Traded": "2024-01-03",
        "Ticker": "NVDA",
        "Name": "Example Member",
    }


def donor_row():
    return {
        "TransactionDate": "2024-02-01",
        "Uploaded": "2024-02-08T13:45:00Z",
        "Ticker": "MSFT",
        "Amount": 2500,
    }


def trump_trade_row():
    return {
        "Filed": "2024-03-11",
        "Traded": "2024-03-01",
        "Ticker": "DJT",
    }


def gov_contract_row():
    return {
        "Date": "2024-04-15",
        "action_date": "2024-04-10",
        "Ticker": "MSFT",
        "Amount": 1000000,
    }


def lobbying_row():
    return {
        "Date": "2024-05-01",
        "Ticker": "NVDA",
        "Amount": 50000,
    }


def off_exchange_row():
    return {
        "Date": "2024-06-01",
        "Ticker": "AAPL",
        "Volume": 123456,
    }


def insiders_row():
    return {
        "Date": "2024-01-03",
        "fileDate": "2024-01-10",
        "Ticker": "NVDA",
    }


def client(tmp_path, responses, **kwargs):
    return quiverfeed.Client(
        token="token",
        cache_dir=tmp_path,
        session=FakeSession(responses),
        rate_limit_policy="off",
        **kwargs,
    )


def expire_cache_entry(c, dataset, params):
    _, meta_path = c._cache._paths(dataset, params)
    metadata = json.loads(meta_path.read_text(encoding="utf-8"))
    metadata["fetched_at"] = (datetime.now(UTC) - timedelta(days=2)).isoformat()
    meta_path.write_text(json.dumps(metadata), encoding="utf-8")


def test_fetch_adds_canonical_dates_and_uses_cache(tmp_path):
    c = client(tmp_path, [FakeResponse({"data": [congress_row()]})])

    df = c.fetch("congress_trading", page_size=10)

    assert len(df) == 1
    assert "event_time" in df.columns
    assert "available_at" in df.columns
    assert df.loc[0, "event_time"].isoformat() == "2024-01-03T00:00:00+00:00"
    assert df.loc[0, "available_at"].isoformat() == "2024-01-10T00:00:00+00:00"
    assert c._session.calls[0]["params"]["version"] == "V2"
    assert c._session.calls[0]["params"]["page"] == 1
    assert c._session.calls[0]["params"]["page_size"] == 10

    cached = c.fetch("congresstrading", page_size=10)

    assert len(cached) == 1
    assert len(c._session.calls) == 1


def test_top_level_fetch_delegates_to_client(tmp_path):
    c = client(tmp_path, [FakeResponse({"data": [congress_row()]})])

    df = quiverfeed.fetch("congresstrading", client=c, page_size=10)

    assert len(df) == 1
    assert len(c._session.calls) == 1


def test_unknown_dataset_raises(tmp_path):
    c = client(tmp_path, [])

    with pytest.raises(UnknownDatasetError):
        c.fetch("not-a-dataset")


def test_top_level_resolve_uses_aliases():
    assert quiverfeed.resolve("govcontracts") == "gov_contracts_historical"
    assert quiverfeed.resolve("lobbying") == "lobbying_live"


def test_fetch_accepts_bare_array_response(tmp_path):
    c = client(tmp_path, [FakeResponse([off_exchange_row()])])

    df = c.fetch("off_exchange_live", page_size=10)

    assert len(df) == 1
    assert "event_time" in df.columns
    assert "available_at" not in df.columns


def test_fetch_accepts_data_envelope_response(tmp_path):
    c = client(tmp_path, [FakeResponse({"data": [congress_row()]})])

    df = c.fetch("congresstrading", page_size=10)

    assert len(df) == 1
    assert "event_time" in df.columns
    assert "available_at" in df.columns


def test_fetch_paginates_until_short_page(tmp_path):
    c = client(
        tmp_path,
        [
            FakeResponse({"data": [congress_row()]}),
            FakeResponse({"data": [congress_row()]}),
            FakeResponse({"data": []}),
        ],
        request_pause_s=0.0,
    )

    df = c.fetch("congresstrading", page_size=1)

    assert len(df) == 2
    assert [call["params"]["page"] for call in c._session.calls] == [1, 2, 3]


def test_known_ignored_param_warns_but_passes_through(tmp_path):
    c = client(tmp_path, [FakeResponse({"data": [congress_row()]})])

    with pytest.warns(ParamIgnoredWarning):
        c.fetch("congresstrading", date_from="2024-01-01", page_size=10)

    assert c._session.calls[0]["params"]["date_from"] == "2024-01-01"


def test_known_unsafe_lobbying_params_are_stripped_and_page_size_capped(tmp_path):
    c = client(tmp_path, [FakeResponse([lobbying_row()])])

    with pytest.warns(ParamStrippedWarning):
        df = c.fetch(
            "lobbying",
            date_from="2019-01-01",
            date_to="2024-01-01",
            all=True,
            page_size=10000,
        )

    assert len(df) == 1
    params = c._session.calls[0]["params"]
    assert "date_from" not in params
    assert "date_to" not in params
    assert "all" not in params
    assert params["page_size"] == 5000


def test_page_and_page_size_params_are_reserved(tmp_path):
    c = client(tmp_path, [])

    with pytest.raises(ValueError, match="page and page_size"):
        c.fetch("congresstrading", page=2)


def test_path_param_interpolation_removes_query_param_and_encodes(tmp_path):
    c = client(tmp_path, [FakeResponse([gov_contract_row()])])

    df = c.fetch("gov_contracts_historical", ticker="BRK/B", page_size=10)

    assert len(df) == 1
    call = c._session.calls[0]
    assert call["url"].endswith("/beta/historical/govcontractsall/BRK%2FB")
    assert "ticker" not in call["params"]
    assert "page" not in call["params"]
    assert "page_size" not in call["params"]


def test_missing_path_param_raises(tmp_path):
    c = client(tmp_path, [])

    with pytest.raises(ValueError, match="Missing path parameter 'ticker'"):
        c.fetch("gov_contracts_historical", page_size=10, force=True)


def test_cache_key_includes_path_params(tmp_path):
    c = client(
        tmp_path,
        [
            FakeResponse([{**gov_contract_row(), "Ticker": "MSFT"}]),
            FakeResponse([{**gov_contract_row(), "Ticker": "AAPL"}]),
        ],
    )

    msft = c.fetch("gov_contracts_historical", ticker="MSFT", page_size=10)
    aapl = c.fetch("gov_contracts_historical", ticker="AAPL", page_size=10)
    cached_msft = c.fetch("gov_contracts_historical", ticker="MSFT", page_size=10)

    assert msft.loc[0, "Ticker"] == "MSFT"
    assert aapl.loc[0, "Ticker"] == "AAPL"
    assert cached_msft.loc[0, "Ticker"] == "MSFT"
    assert len(c._session.calls) == 2


def test_fetch_many_fetches_per_ticker_and_returns_status(tmp_path):
    c = client(
        tmp_path,
        [
            FakeResponse([{**gov_contract_row(), "Ticker": "MSFT"}]),
            FakeResponse([{**gov_contract_row(), "Ticker": "LMT"}]),
        ],
    )

    df, status = c.fetch_many(
        "govcontracts",
        tickers=["MSFT", "LMT"],
        page_size=5000,
        resume=True,
        continue_on_error=True,
    )

    assert list(df["Ticker"]) == ["MSFT", "LMT"]
    assert list(status["ticker"]) == ["MSFT", "LMT"]
    assert list(status["dataset"]) == [
        "gov_contracts_historical",
        "gov_contracts_historical",
    ]
    assert list(status["status"]) == ["ok", "ok"]
    assert list(status["rows"]) == [1, 1]
    assert list(status["cache_status"]) == ["miss", "miss"]
    assert c._session.calls[0]["url"].endswith("/beta/historical/govcontractsall/MSFT")
    assert c._session.calls[1]["url"].endswith("/beta/historical/govcontractsall/LMT")

    cached_df, cached_status = c.fetch_many(
        "govcontracts",
        tickers=["MSFT", "LMT"],
        page_size=5000,
        resume=True,
        continue_on_error=True,
    )

    assert len(cached_df) == 2
    assert list(cached_status["cache_status"]) == ["hit", "hit"]
    assert len(c._session.calls) == 2


def test_fetch_many_records_errors_when_requested(tmp_path):
    c = client(
        tmp_path,
        [
            FakeResponse([{**gov_contract_row(), "Ticker": "MSFT"}]),
            FakeResponse({}, status_code=429, headers={"Retry-After": "60"}),
        ],
    )

    df, status = c.fetch_many(
        "govcontracts",
        tickers=["MSFT", "LMT"],
        continue_on_error=True,
    )

    assert list(df["Ticker"]) == ["MSFT"]
    assert list(status["status"]) == ["ok", "rate_limited"]
    assert status.loc[1, "retry_after_seconds"] == 60
    assert status.loc[1, "reset_at"] is not None
    assert status.loc[1, "error_type"] == "RateLimitError"


def test_fetch_many_records_network_errors_when_requested(tmp_path):
    session = FlakySession([_raise_connection_error])
    c = quiverfeed.Client(
        token="token",
        cache_dir=tmp_path,
        session=session,
        rate_limit_policy="off",
        max_retries=0,
    )

    df, status = c.fetch_many(
        "govcontracts",
        tickers=["MSFT"],
        continue_on_error=True,
    )

    assert df.empty
    assert status.loc[0, "ticker"] == "MSFT"
    assert status.loc[0, "status"] == "error"
    assert status.loc[0, "error_type"] == "ConnectionError"


def test_fetch_many_does_not_swallow_programmer_errors(tmp_path):
    c = client(tmp_path, [])

    with pytest.raises(ValueError, match="page_size"):
        c.fetch_many(
            "govcontracts",
            tickers=["MSFT"],
            page_size=0,
            continue_on_error=True,
        )


def test_fetch_many_requires_ticker_path_dataset(tmp_path):
    c = client(tmp_path, [])

    with pytest.raises(ValueError, match="path parameter"):
        c.fetch_many("congresstrading", tickers=["MSFT"])


def test_max_pages_full_final_page_raises_when_requested(tmp_path):
    c = client(tmp_path, [FakeResponse({"data": [congress_row()]})])

    with pytest.raises(TruncatedResultError):
        c.fetch("congresstrading", page_size=1, max_pages=1, on_truncated="raise")


def test_max_pages_full_final_page_warns_by_default(tmp_path):
    c = client(tmp_path, [FakeResponse({"data": [congress_row()]})])

    with pytest.warns(TruncatedResultWarning):
        partial = c.fetch("congresstrading", page_size=1, max_pages=1)

    assert len(partial) == 1


def test_request_pause_fires_between_pages_only(tmp_path, monkeypatch):
    sleeps: list[float] = []
    monkeypatch.setattr("quiverfeed.client.time.sleep", lambda s: sleeps.append(s))
    c = quiverfeed.Client(
        token="token",
        cache_dir=tmp_path,
        session=FakeSession(
            [
                FakeResponse({"data": [congress_row()]}),
                FakeResponse({"data": [congress_row()]}),
                FakeResponse({"data": []}),
            ]
        ),
        rate_limit_policy="off",
        request_pause_s=0.25,
    )
    c.fetch("congresstrading", page_size=1)
    # Three HTTP calls, two inter-page gaps.
    assert sleeps == [0.25, 0.25]


def test_tz_none_returns_naive_timestamps(tmp_path):
    c = quiverfeed.Client(
        token="token",
        cache_dir=tmp_path,
        session=FakeSession([FakeResponse({"data": [congress_row()]})]),
        rate_limit_policy="off",
        tz=None,
    )
    df = c.fetch("congresstrading", page_size=10)
    assert df["event_time"].dt.tz is None
    assert df["available_at"].dt.tz is None
    assert df.loc[0, "event_time"].isoformat() == "2024-01-03T00:00:00"
    assert df.loc[0, "available_at"].isoformat() == "2024-01-10T00:00:00"


def test_tz_named_zone_converts(tmp_path):
    c = quiverfeed.Client(
        token="token",
        cache_dir=tmp_path,
        session=FakeSession([FakeResponse({"data": [congress_row()]})]),
        rate_limit_policy="off",
        tz="America/New_York",
    )
    df = c.fetch("congresstrading", page_size=10)
    assert str(df["available_at"].dt.tz) == "America/New_York"


class FlakySession:
    """Session that emits a sequence of responses or callables-that-raise."""

    def __init__(self, sequence):
        self.sequence = list(sequence)
        self.calls = 0

    def get(self, url, headers, params, timeout):
        self.calls += 1
        if not self.sequence:
            raise AssertionError("No fake responses left")
        item = self.sequence.pop(0)
        if callable(item):
            return item()
        return item


def _raise_connection_error():
    raise requests.ConnectionError("boom")


def test_retries_on_connection_error_then_succeeds(tmp_path, monkeypatch):
    sleeps: list[float] = []
    monkeypatch.setattr("quiverfeed.client.time.sleep", lambda s: sleeps.append(s))
    session = FlakySession([_raise_connection_error, FakeResponse({"data": []})])
    c = quiverfeed.Client(
        token="token",
        cache_dir=tmp_path,
        session=session,
        rate_limit_policy="off",
        request_pause_s=0.0,
        max_retries=2,
    )
    df = c.fetch("congresstrading", page_size=10)
    assert df.empty
    assert session.calls == 2
    assert sleeps == [0.5]  # base backoff (RETRY_BACKOFF_S) between attempts 0 and 1


def test_retries_on_5xx_then_succeeds(tmp_path, monkeypatch):
    sleeps: list[float] = []
    monkeypatch.setattr("quiverfeed.client.time.sleep", lambda s: sleeps.append(s))
    session = FlakySession(
        [FakeResponse({}, status_code=503), FakeResponse({"data": []})]
    )
    c = quiverfeed.Client(
        token="token",
        cache_dir=tmp_path,
        session=session,
        rate_limit_policy="off",
        request_pause_s=0.0,
        max_retries=2,
    )
    df = c.fetch("congresstrading", page_size=10)
    assert df.empty
    assert session.calls == 2
    assert sleeps == [0.5]


def test_retries_exhausted_surface_last_error(tmp_path, monkeypatch):
    monkeypatch.setattr("quiverfeed.client.time.sleep", lambda _s: None)
    session = FlakySession(
        [_raise_connection_error, _raise_connection_error, _raise_connection_error]
    )
    c = quiverfeed.Client(
        token="token",
        cache_dir=tmp_path,
        session=session,
        rate_limit_policy="off",
        request_pause_s=0.0,
        max_retries=2,
    )
    with pytest.raises(requests.ConnectionError):
        c.fetch("congresstrading", page_size=10, force=True)
    assert session.calls == 3  # initial + 2 retries


def test_does_not_retry_on_401(tmp_path):
    session = FlakySession([FakeResponse({}, status_code=401)])
    c = quiverfeed.Client(
        token="token",
        cache_dir=tmp_path,
        session=session,
        rate_limit_policy="off",
        max_retries=5,
    )
    with pytest.raises(AuthError):
        c.fetch("congresstrading", page_size=10, force=True)
    assert session.calls == 1


def test_does_not_retry_on_429(tmp_path):
    session = FlakySession(
        [FakeResponse({}, status_code=429, headers={"Retry-After": "60"})]
    )
    c = quiverfeed.Client(
        token="token",
        cache_dir=tmp_path,
        session=session,
        rate_limit_policy="off",
        max_retries=5,
    )
    with pytest.raises(RateLimitError):
        c.fetch("congresstrading", page_size=10, force=True)
    assert session.calls == 1


def test_request_pause_zero_disables_sleeping(tmp_path, monkeypatch):
    sleeps: list[float] = []
    monkeypatch.setattr("quiverfeed.client.time.sleep", lambda s: sleeps.append(s))
    c = quiverfeed.Client(
        token="token",
        cache_dir=tmp_path,
        session=FakeSession(
            [FakeResponse({"data": [congress_row()]}), FakeResponse({"data": []})]
        ),
        rate_limit_policy="off",
        request_pause_s=0.0,
    )
    c.fetch("congresstrading", page_size=1)
    assert sleeps == []


def test_on_truncated_warn_returns_partial_and_does_not_cache(tmp_path):
    c = client(
        tmp_path,
        [
            FakeResponse({"data": [congress_row()]}),
            FakeResponse({"data": []}),
        ],
    )

    with pytest.warns(TruncatedResultWarning):
        partial = c.fetch(
            "congresstrading",
            page_size=1,
            max_pages=1,
            on_truncated="warn",
        )

    assert len(partial) == 1

    complete = c.fetch("congresstrading", page_size=1)

    assert complete.empty
    assert len(c._session.calls) == 2


def test_local_rate_limit_raise_policy(tmp_path):
    session = FakeSession(
        [
            FakeResponse({"data": [congress_row()]}),
            FakeResponse({"data": [congress_row()]}),
        ]
    )
    c = quiverfeed.Client(
        token="token",
        cache_dir=tmp_path,
        session=session,
        rate_limit_per_hour=1,
        rate_limit_policy="raise",
    )

    c.fetch("congresstrading", page_size=10, force=True)

    with pytest.raises(RateLimitError):
        c.fetch("congresstrading", page_size=10, force=True)

    assert len(session.calls) == 1


def test_upstream_403_raises_plan_required(tmp_path):
    c = client(
        tmp_path,
        [FakeResponse({}, status_code=403, text="Upgrade your subscription plan")],
    )

    with pytest.raises(PlanRequiredError) as exc:
        c.fetch("congresstrading", page_size=10, force=True)

    assert exc.value.dataset == "congresstrading"
    assert exc.value.path == "/beta/bulk/congresstrading"
    assert "/beta/bulk/congresstrading" in str(exc.value)


def test_upstream_429_uses_retry_after(tmp_path):
    c = client(
        tmp_path,
        [FakeResponse({}, status_code=429, headers={"Retry-After": "123"})],
    )

    with pytest.raises(RateLimitError) as exc:
        c.fetch("congresstrading", page_size=10, force=True)

    assert exc.value.retry_after_s == 123
    assert exc.value.retry_after_seconds == 123
    assert exc.value.reset_at is not None
    assert exc.value.dataset == "congresstrading"
    assert exc.value.path == "/beta/bulk/congresstrading"


def test_fetch_can_return_stale_cache_on_rate_limit(tmp_path):
    c = client(tmp_path, [FakeResponse({"data": [congress_row()]})])
    c.fetch("congresstrading", page_size=10)
    expire_cache_entry(c, "congresstrading", {"version": "V2"})

    c._session.responses.append(
        FakeResponse({}, status_code=429, headers={"Retry-After": "60"})
    )

    stale = c.fetch("congresstrading", page_size=10, stale_if_rate_limit=True)

    assert len(stale) == 1
    assert len(c._session.calls) == 2


def test_fetch_can_return_stale_cache_on_5xx_after_retries(tmp_path, monkeypatch):
    monkeypatch.setattr("quiverfeed.client.time.sleep", lambda _s: None)
    c = client(tmp_path, [FakeResponse({"data": [congress_row()]})], max_retries=0)
    c.fetch("congresstrading", page_size=10)
    expire_cache_entry(c, "congresstrading", {"version": "V2"})

    c._session.responses.append(FakeResponse({}, status_code=500))

    stale = c.fetch("congresstrading", page_size=10, stale_if_error=True)

    assert len(stale) == 1
    assert len(c._session.calls) == 2


def test_fetch_without_stale_cache_still_raises_on_rate_limit(tmp_path):
    c = client(
        tmp_path,
        [FakeResponse({}, status_code=429, headers={"Retry-After": "60"})],
    )

    with pytest.raises(RateLimitError):
        c.fetch("congresstrading", page_size=10, stale_if_rate_limit=True)


@pytest.mark.parametrize(
    ("dataset", "payload", "event_iso", "available_iso", "params"),
    [
        (
            "congresstrading",
            {"data": [congress_row()]},
            "2024-01-03T00:00:00+00:00",
            "2024-01-10T00:00:00+00:00",
            {},
        ),
        (
            "corporate_donors",
            {"data": [donor_row()]},
            "2024-02-01T00:00:00+00:00",
            "2024-02-08T13:45:00+00:00",
            {},
        ),
        (
            "trump_stock_trades",
            {"data": [trump_trade_row()]},
            "2024-03-01T00:00:00+00:00",
            "2024-03-11T00:00:00+00:00",
            {},
        ),
        (
            "gov_contracts_all_live",
            [gov_contract_row()],
            "2024-04-10T00:00:00+00:00",
            "2024-04-15T00:00:00+00:00",
            {},
        ),
        (
            "gov_contracts_historical",
            [gov_contract_row()],
            "2024-04-10T00:00:00+00:00",
            "2024-04-15T00:00:00+00:00",
            {"ticker": "MSFT"},
        ),
    ],
)
def test_pit_columns_added_for_disclosure_dated_datasets(
    tmp_path,
    dataset,
    payload,
    event_iso,
    available_iso,
    params,
):
    c = client(tmp_path, [FakeResponse(payload)])

    df = c.fetch(dataset, page_size=10, **params)

    assert df.loc[0, "event_time"].isoformat() == event_iso
    assert df.loc[0, "available_at"].isoformat() == available_iso


@pytest.mark.parametrize(
    ("dataset", "payload", "event_iso", "params"),
    [
        ("lobbying_live", [lobbying_row()], "2024-05-01T00:00:00+00:00", {}),
        (
            "lobbying_historical",
            [lobbying_row()],
            "2024-05-01T00:00:00+00:00",
            {"ticker": "NVDA"},
        ),
        (
            "off_exchange_live",
            [off_exchange_row()],
            "2024-06-01T00:00:00+00:00",
            {},
        ),
        (
            "off_exchange_historical",
            [off_exchange_row()],
            "2024-06-01T00:00:00+00:00",
            {"ticker": "AAPL"},
        ),
    ],
)
def test_event_only_datasets_do_not_fake_available_at(
    tmp_path,
    dataset,
    payload,
    event_iso,
    params,
):
    c = client(tmp_path, [FakeResponse(payload)])

    df = c.fetch(dataset, page_size=10, **params)

    assert df.loc[0, "event_time"].isoformat() == event_iso
    assert "available_at" not in df.columns


def test_unparseable_canonical_dates_are_nat_without_touching_raw(tmp_path):
    c = client(
        tmp_path,
        [
            FakeResponse(
                {
                    "data": [
                        {
                            "TransactionDate": "not-a-date",
                            "Uploaded": "also-not-a-date",
                        },
                        {
                            "TransactionDate": "2024-02-01",
                            "Uploaded": "2024-02-08T13:45:00Z",
                        },
                    ]
                }
            )
        ],
    )

    df = c.fetch("corporate_donors", page_size=10)

    assert df.loc[0, "TransactionDate"] == "not-a-date"
    assert df.loc[0, "Uploaded"] == "also-not-a-date"
    assert pd.isna(df.loc[0, "event_time"])
    assert pd.isna(df.loc[0, "available_at"])
    assert df.loc[1, "event_time"].isoformat() == "2024-02-01T00:00:00+00:00"
    assert df.loc[1, "available_at"].isoformat() == "2024-02-08T13:45:00+00:00"


def test_canary_profiles_selected_plan(tmp_path):
    c = client(tmp_path, [FakeResponse({"data": [insiders_row()]})])

    report = quiverfeed.canary(client=c, plan="tier2", page_size=5, max_pages=1)

    assert list(report.columns) == [
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
    ]
    assert report.loc[0, "dataset"] == "insiders"
    assert report.loc[0, "status"] == "ok"
    assert report.loc[0, "rows"] == 1
    assert bool(report.loc[0, "has_event_time"]) is True
    assert bool(report.loc[0, "has_available_at"]) is True


def test_profile_returns_practical_dataset_summary_and_cache_status(tmp_path):
    c = client(
        tmp_path,
        [
            FakeResponse(
                {
                    "data": [
                        congress_row(),
                        {
                            **congress_row(),
                            "Filed": "2024-01-20",
                            "Traded": "2024-01-05",
                            "Ticker": "MSFT",
                        },
                    ]
                }
            )
        ],
    )

    profile = c.profile("congresstrading", page_size=10, max_pages=20)

    assert profile["dataset"] == "congresstrading"
    assert profile["rows"] == 2
    assert "event_time" in profile["columns"]
    assert profile["symbol_count"] == 2
    assert profile["null_event_time"] == 0
    assert profile["null_available_at"] == 0
    assert profile["median_lag"] == pd.Timedelta(days=11)
    assert profile["p90_lag"] == pd.Timedelta(days=14, hours=4, minutes=48)
    assert profile["max_lag"] == pd.Timedelta(days=15)
    assert profile["page_count"] == 1
    assert profile["cache_status"] == "miss"
    assert not profile["cache_hit"]

    cached = c.profile("congresstrading", page_size=10, max_pages=20)

    assert cached["cache_status"] == "hit"
    assert cached["cache_hit"]
    assert len(c._session.calls) == 1


def test_cache_hit_does_not_require_token(tmp_path):
    c = client(tmp_path, [FakeResponse({"data": [congress_row()]})])
    c.fetch("congresstrading", page_size=10)

    no_token = quiverfeed.Client(
        token=None,
        cache_dir=tmp_path,
        session=FakeSession([]),
        rate_limit_policy="off",
    )
    no_token.token = None

    cached = no_token.fetch("congresstrading", page_size=10)

    assert len(cached) == 1


def test_missing_token_raises_after_cache_miss(tmp_path):
    c = quiverfeed.Client(
        token=None,
        cache_dir=tmp_path,
        session=FakeSession([]),
        rate_limit_policy="off",
    )
    c.token = None

    with pytest.raises(AuthError):
        c.fetch("congresstrading", page_size=10, force=True)


def test_assert_disclosure_dated(tmp_path):
    c = client(tmp_path, [FakeResponse({"data": [congress_row()]})])
    df = c.fetch("congresstrading", page_size=10)

    quiverfeed.assert_disclosure_dated(df)

    with pytest.raises(ValueError):
        quiverfeed.assert_disclosure_dated(df.drop(columns=["available_at"]))


def test_diagnose_reports_success(tmp_path):
    c = client(tmp_path, [FakeResponse({"data": [congress_row()]})])

    with warnings.catch_warnings():
        warnings.simplefilter("ignore", TruncatedResultWarning)
        report = quiverfeed.diagnose(client=c, datasets=["congresstrading"])

    assert report.ok
    assert report.results[0].dataset == "congresstrading"
    assert "congresstrading: ok" in report.to_text()
