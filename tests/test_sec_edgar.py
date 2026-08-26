"""Deterministic tests for the SEC EDGAR connector; no live requests are made."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from urllib.error import HTTPError

import pytest

from equity_os.config import EqosConfig, SecConfig
from equity_os.connectors.sec_edgar import (
    SecEdgarClient,
    SecRequestError,
    sync_ticker,
)
from equity_os.fs.io import write_json
from equity_os.fs.layout import CompanyLayout
from equity_os.ingest.pipeline import list_catalog
from equity_os.schemas import CompanyDossier


TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK0000320193.json"
ARCHIVE_BASE = "https://www.sec.gov/Archives/edgar/data/320193/000032019326000001"
INDEX_URL = f"{ARCHIVE_BASE}/0000320193-26-000001-index.htm"
TEN_Q_URL = f"{ARCHIVE_BASE}/aapl-20260630.htm"
EIGHT_K_URL = f"{ARCHIVE_BASE}/aapl-8k.htm"
EXHIBIT_URL = f"{ARCHIVE_BASE}/exhibit991.htm"


def _config(**overrides: object) -> EqosConfig:
    sec = {
        "user_agent_name": "Research Operator",
        "contact_email": "operator@research.org",
        "requests_per_second": 10,
        "max_retries": 0,
        "forms": ["10-Q", "8-K"],
        "eight_k_items": ["2.02", "8.01"],
        "exhibit_type_prefixes": ["EX-99"],
    }
    sec.update(overrides)
    return EqosConfig.model_validate({"sec": sec, "sync": {"store_raw_documents": True}})


def _submissions() -> dict[str, object]:
    return {
        "name": "Apple Inc.",
        "filings": {
            "recent": {
                "accessionNumber": [
                    "0000320193-26-000001",
                    "0000320193-26-000001",
                    "0000320193-26-000099",
                ],
                "filingDate": ["2026-08-01", "2026-08-01", "2026-08-02"],
                "reportDate": ["2026-06-30", "2026-07-31", "2026-08-01"],
                "acceptanceDateTime": [
                    "2026-08-01T16:00:00.000Z",
                    "2026-08-01T16:10:00.000Z",
                    "2026-08-02T16:00:00.000Z",
                ],
                "form": ["10-Q", "8-K", "8-K"],
                "items": ["", "2.02,9.01", "1.01"],
                "primaryDocument": ["aapl-20260630.htm", "aapl-8k.htm", "other.htm"],
                "primaryDocDescription": ["10-Q", "Current report", "Other event"],
                "isXBRL": [1, 0, 0],
                "isInlineXBRL": [1, 0, 0],
            }
        },
    }


def _index_html() -> bytes:
    return b"""
    <html><table class="tableFile" summary="Document Format Files">
      <tr><th>Seq</th><th>Description</th><th>Document</th><th>Type</th><th>Size</th></tr>
      <tr><td>1</td><td>Current report</td><td><a href="aapl-8k.htm">aapl-8k.htm</a></td><td>8-K</td><td>100</td></tr>
      <tr><td>2</td><td>Earnings release</td><td><a href="exhibit991.htm">exhibit991.htm</a></td><td>EX-99.1</td><td>200</td></tr>
    </table></html>
    """


class FakeFetcher:
    def __init__(self, responses: dict[str, bytes]) -> None:
        self.responses = responses
        self.calls: list[tuple[str, dict[str, str], float]] = []

    def __call__(self, url: str, headers: dict[str, str], timeout: float) -> bytes:
        self.calls.append((url, headers, timeout))
        return self.responses[url]


def _responses() -> dict[str, bytes]:
    return {
        TICKERS_URL: json.dumps(
            {"0": {"cik_str": 320193, "ticker": "AAPL", "title": "Apple Inc."}}
        ).encode(),
        SUBMISSIONS_URL: json.dumps(_submissions()).encode(),
        INDEX_URL: _index_html(),
        TEN_Q_URL: b"<html><body>FORM 10-Q quarterly reported facts and results.</body></html>",
        EIGHT_K_URL: b"<html><body>FORM 8-K results were furnished by Apple.</body></html>",
        EXHIBIT_URL: b"<html><body>Q3 2026 earnings release revenue increased.</body></html>",
    }


def _client(fetcher: FakeFetcher) -> SecEdgarClient:
    return SecEdgarClient(
        _config().sec,
        fetch_bytes=fetcher,
        sleep=lambda _: None,
        clock=lambda: 0.0,
    )


def _init_company(companies_root: Path) -> None:
    layout = CompanyLayout(companies_root, "AAPL")
    layout.init_dirs()
    write_json(layout.dossier_json, CompanyDossier(ticker="AAPL", name="Apple Inc."))


def test_declared_identity_is_sent_and_cik_is_resolved() -> None:
    fetcher = FakeFetcher(_responses())

    cik, company = _client(fetcher).resolve_cik("aapl")

    assert (cik, company) == ("0000320193", "Apple Inc.")
    assert fetcher.calls[0][1]["User-Agent"] == "Research Operator operator@research.org"


def test_filing_filters_and_exhibit_discovery() -> None:
    fetcher = FakeFetcher(_responses())
    client = _client(fetcher)
    filings = client.discover_filings(_submissions(), since=date(2026, 1, 1))

    assert [filing.form for filing in filings] == ["10-Q", "8-K"]
    assert len(client.discover_documents("0000320193", filings[0])) == 1
    descriptors = client.discover_documents("0000320193", filings[1])
    assert [descriptor.document_type for descriptor in descriptors] == ["8-K", "EX-99.1"]
    assert descriptors[1].url == EXHIBIT_URL


def test_non_sec_url_is_refused_before_fetch() -> None:
    fetcher = FakeFetcher({})
    client = _client(fetcher)

    with pytest.raises(SecRequestError, match="Refusing non-SEC URL"):
        client.get_bytes("https://example.org/filing")
    assert fetcher.calls == []


def test_retryable_response_is_retried() -> None:
    attempts = 0
    sleeps: list[float] = []

    def fetch(url: str, headers: dict[str, str], timeout: float) -> bytes:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise HTTPError(url, 429, "Too Many Requests", hdrs=None, fp=None)
        return b"success"

    config = SecConfig(
        user_agent_name="Research Operator",
        contact_email="operator@research.org",
        requests_per_second=10,
        max_retries=1,
    )
    client = SecEdgarClient(config, fetch_bytes=fetch, sleep=sleeps.append, clock=lambda: 0.0)

    assert client.get_bytes(TICKERS_URL) == b"success"
    assert attempts == 2
    assert 1.0 in sleeps


def test_sync_ingests_filings_release_and_skips_second_download(tmp_path: Path) -> None:
    _init_company(tmp_path)
    fetcher = FakeFetcher(_responses())
    client = _client(fetcher)

    first = sync_ticker(
        _config(), "aapl", tmp_path, since=date(2026, 1, 1), client=client
    )
    second = sync_ticker(
        _config(), "aapl", tmp_path, since=date(2026, 1, 1), client=client
    )

    assert first.discovered_filings == 2
    assert first.discovered_documents == 3
    assert first.ingested_documents == 3
    assert first.failures == []
    assert second.ingested_documents == 0
    assert second.skipped_documents == 3
    assert [item.logical_type for item in list_catalog(tmp_path, "AAPL")] == [
        "filing",
        "filing",
        "earnings_release",
    ]
    called_urls = [call[0] for call in fetcher.calls]
    assert called_urls.count(TEN_Q_URL) == 1
    assert called_urls.count(EIGHT_K_URL) == 1
    assert called_urls.count(EXHIBIT_URL) == 1
    assert (tmp_path / "AAPL" / "evidence" / "_sec_state.json").exists()
    assert len(list((tmp_path / "AAPL" / "evidence" / "raw").iterdir())) == 3


def test_sync_requires_initialized_company(tmp_path: Path) -> None:
    with pytest.raises(Exception, match="not initialized"):
        sync_ticker(_config(), "AAPL", tmp_path, since=date(2026, 1, 1))
