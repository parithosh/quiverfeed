from __future__ import annotations

import warnings

import requests

import quiverfeed
from quiverfeed.errors import TruncatedResultWarning


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
        self.calls.append({"url": url, "params": dict(params)})
        if not self.responses:
            raise AssertionError("No fake responses left")
        return self.responses.pop(0)


def make_client(tmp_path, responses):
    return quiverfeed.Client(
        token="token",
        cache_dir=tmp_path,
        session=FakeSession(responses),
        rate_limit_policy="off",
    )


def test_diagnose_reports_unknown_dataset(tmp_path):
    c = make_client(tmp_path, [])
    report = quiverfeed.diagnose(client=c, datasets=["not-a-dataset"])

    assert not report.ok
    assert report.results[0].dataset == "not-a-dataset"
    assert report.results[0].message == "unknown dataset"
    assert "fail" in report.to_text()


def test_diagnose_reports_catalog_drift(tmp_path):
    # Strict client + missing canonical column triggers CatalogDriftError.
    c = make_client(
        tmp_path,
        [FakeResponse({"data": [{"NotTraded": "2024-01-01", "NotFiled": "2024-01-10"}]})],
    )
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", TruncatedResultWarning)
        report = quiverfeed.diagnose(client=c, datasets=["congresstrading"])

    assert not report.ok
    diag = report.results[0]
    assert diag.dataset == "congresstrading"
    assert "Catalog drift" in diag.message
    assert "NotTraded" in diag.columns


def test_diagnose_text_includes_generated_at_iso(tmp_path):
    c = make_client(tmp_path, [FakeResponse({"data": [{"Traded": "2024-01-03", "Filed": "2024-01-10"}]})])
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", TruncatedResultWarning)
        report = quiverfeed.diagnose(client=c, datasets=["congresstrading"])

    text = report.to_text()
    assert text.startswith("quiverfeed diagnose @ ")
    assert report.generated_at.isoformat() in text


def test_diagnose_defaults_to_full_catalog(tmp_path):
    # One response per dataset in the catalog. The fake responses each shape
    # match each dataset's expected event/disclosure cols.
    responses = [
        FakeResponse({"data": [{"Traded": "2024-01-03", "Filed": "2024-01-10"}]}),
        FakeResponse({"data": [{"Date": "2024-01-03", "fileDate": "2024-01-10"}]}),
        FakeResponse({"data": [{"Date": "2024-01-03"}]}),
        FakeResponse({"data": [{"lastActionDate": "2024-01-03"}]}),
    ]
    c = make_client(tmp_path, responses)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", TruncatedResultWarning)
        report = quiverfeed.diagnose(client=c)

    names = {r.dataset for r in report.results}
    assert names == set(quiverfeed.DATASETS.keys())
    assert report.ok
