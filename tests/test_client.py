from __future__ import annotations

import warnings

import pytest
import requests

import quiverfeed
from quiverfeed.errors import (
    AuthError,
    ParamIgnoredWarning,
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


def client(tmp_path, responses, **kwargs):
    return quiverfeed.Client(
        token="token",
        cache_dir=tmp_path,
        session=FakeSession(responses),
        rate_limit_policy="off",
        **kwargs,
    )


def test_fetch_adds_canonical_dates_and_uses_cache(tmp_path):
    c = client(tmp_path, [FakeResponse({"data": [congress_row()]})])

    df = c.fetch("congress_trading", page_size=10)

    assert len(df) == 1
    assert "event_time" in df.columns
    assert "available_at" in df.columns
    assert df.loc[0, "event_time"].isoformat() == "2024-01-03T00:00:00+00:00"
    assert df.loc[0, "available_at"].isoformat() == "2024-01-10T00:00:00+00:00"
    assert "version" not in c._session.calls[0]["params"]
    assert c._session.calls[0]["params"]["page"] == 1
    assert c._session.calls[0]["params"]["page_size"] == 10

    cached = c.fetch("congresstrading", page_size=10)

    assert len(cached) == 1
    assert len(c._session.calls) == 1


def test_unknown_dataset_raises(tmp_path):
    c = client(tmp_path, [])

    with pytest.raises(UnknownDatasetError):
        c.fetch("not-a-dataset")


def test_known_ignored_param_warns_but_passes_through(tmp_path):
    c = client(tmp_path, [FakeResponse({"data": [congress_row()]})])

    with pytest.warns(ParamIgnoredWarning):
        c.fetch("congresstrading", date_from="2024-01-01", page_size=10)

    assert c._session.calls[0]["params"]["date_from"] == "2024-01-01"


def test_page_and_page_size_params_are_reserved(tmp_path):
    c = client(tmp_path, [])

    with pytest.raises(ValueError, match="page and page_size"):
        c.fetch("congresstrading", page=2)


def test_max_pages_full_final_page_raises_when_requested(tmp_path):
    c = client(tmp_path, [FakeResponse({"data": [congress_row()]})])

    with pytest.raises(TruncatedResultError):
        c.fetch("congresstrading", page_size=1, max_pages=1, on_truncated="raise")


def test_max_pages_full_final_page_warns_by_default(tmp_path):
    c = client(tmp_path, [FakeResponse({"data": [congress_row()]})])

    with pytest.warns(TruncatedResultWarning):
        partial = c.fetch("congresstrading", page_size=1, max_pages=1)

    assert len(partial) == 1


def test_request_pause_fires_between_pages_only(tmp_path):
    sleeps: list[float] = []
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
        sleep=sleeps.append,
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


def test_request_pause_zero_disables_sleeping(tmp_path):
    sleeps: list[float] = []
    c = quiverfeed.Client(
        token="token",
        cache_dir=tmp_path,
        session=FakeSession(
            [
                FakeResponse({"data": [congress_row()]}),
                FakeResponse({"data": []}),
            ]
        ),
        rate_limit_policy="off",
        request_pause_s=0.0,
        sleep=sleeps.append,
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


def test_upstream_429_uses_retry_after(tmp_path):
    c = client(
        tmp_path,
        [FakeResponse({}, status_code=429, headers={"Retry-After": "123"})],
    )

    with pytest.raises(RateLimitError) as exc:
        c.fetch("congresstrading", page_size=10, force=True)

    assert exc.value.retry_after_s == 123


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
