"""Safe, typed SEC EDGAR connector and synchronization service."""

from __future__ import annotations

import json
import mimetypes
import re
import time
from collections.abc import Callable
from datetime import date, datetime, timedelta, timezone
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlparse
from urllib.request import Request, urlopen

from pydantic import BaseModel, Field

from equity_os.config import EqosConfig, SecConfig
from equity_os.fs.layout import CompanyLayout
from equity_os.ingest import dedup
from equity_os.ingest.models import RawDocument
from equity_os.ingest.normalize import extract_html, extract_txt, full_normalize
from equity_os.ingest.pipeline import ingest_document


_SEC_HOSTS = frozenset({"data.sec.gov", "www.sec.gov"})
_TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
_SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik}.json"
_ARCHIVES_BASE = "https://www.sec.gov/Archives/edgar/data"


class SecConnectorError(RuntimeError):
    """Base exception for actionable SEC connector failures."""


class SecRequestError(SecConnectorError):
    """Raised when an SEC request fails after the configured retries."""


class SecFiling(BaseModel):
    accession_number: str
    filing_date: date
    report_date: date | None = None
    acceptance_datetime: datetime | None = None
    form: str
    items: list[str] = Field(default_factory=list)
    primary_document: str
    primary_document_description: str | None = None
    is_xbrl: bool = False
    is_inline_xbrl: bool = False

    @property
    def accession_compact(self) -> str:
        return self.accession_number.replace("-", "")

    @property
    def base_form(self) -> str:
        return self.form.removesuffix("/A")


class SecDocumentDescriptor(BaseModel):
    accession_number: str
    document_id: str
    file_name: str
    document_type: str
    url: str
    is_primary: bool = False


class SecSyncResult(BaseModel):
    ticker: str
    cik: str
    discovered_filings: int = 0
    discovered_documents: int = 0
    ingested_documents: int = 0
    skipped_documents: int = 0
    failures: list[str] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)


FetchBytes = Callable[[str, dict[str, str], float], bytes]
SleepFn = Callable[[float], None]
ClockFn = Callable[[], float]


def _parse_optional_date(value: Any) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def _parse_optional_datetime(value: Any) -> datetime | None:
    if not value:
        return None
    raw = str(value).replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(raw)
    except ValueError:
        return None


def _split_items(value: Any) -> list[str]:
    if not value:
        return []
    return [part for part in re.split(r"[\s,]+", str(value).strip()) if part]


def _remote_text(raw: bytes, file_name: str) -> str:
    decoded = raw.decode("utf-8", errors="replace")
    suffix = Path(file_name).suffix.lower()
    if suffix in {".htm", ".html", ".xml"}:
        return extract_html(decoded)[1]
    if suffix == ".txt":
        return extract_txt(decoded)[1]
    return full_normalize(decoded)


class _FilingIndexParser(HTMLParser):
    """Extract document links and SEC document types from a filing index table."""

    def __init__(self) -> None:
        super().__init__()
        self.rows: list[tuple[list[str], str | None]] = []
        self._in_row = False
        self._in_cell = False
        self._cells: list[str] = []
        self._cell_parts: list[str] = []
        self._href: str | None = None

    def handle_starttag(
        self, tag: str, attrs: list[tuple[str, str | None]]
    ) -> None:
        if tag == "tr":
            self._in_row = True
            self._cells = []
            self._href = None
        elif tag in {"td", "th"} and self._in_row:
            self._in_cell = True
            self._cell_parts = []
        elif tag == "a" and self._in_row:
            href = dict(attrs).get("href")
            if href:
                self._href = href

    def handle_data(self, data: str) -> None:
        if self._in_cell:
            self._cell_parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag in {"td", "th"} and self._in_cell:
            self._cells.append(" ".join("".join(self._cell_parts).split()))
            self._in_cell = False
        elif tag == "tr" and self._in_row:
            if self._cells:
                self.rows.append((self._cells, self._href))
            self._in_row = False


def _parse_filing_index(html: str) -> list[tuple[str, str, str]]:
    """Return ``(file_name, document_type, href)`` rows from an SEC index."""
    parser = _FilingIndexParser()
    parser.feed(html)
    documents: list[tuple[str, str, str]] = []
    for cells, href in parser.rows:
        if not href or len(cells) < 4:
            continue
        document_type = cells[-2].strip().upper()
        file_name = Path(urlparse(href).path).name
        if file_name and document_type:
            documents.append((file_name, document_type, href))
    return documents


class SecEdgarClient:
    """Small SEC client with rate limiting, identification, and retries."""

    def __init__(
        self,
        config: SecConfig,
        *,
        fetch_bytes: FetchBytes | None = None,
        sleep: SleepFn = time.sleep,
        clock: ClockFn = time.monotonic,
    ) -> None:
        config.validate_for_access()
        self.config = config
        self._fetch_bytes = fetch_bytes or self._urlopen_bytes
        self._sleep = sleep
        self._clock = clock
        self._last_request_at: float | None = None

    @property
    def headers(self) -> dict[str, str]:
        return {
            "User-Agent": self.config.user_agent,
            "Accept": "application/json,text/html,text/plain;q=0.9,*/*;q=0.8",
        }

    @staticmethod
    def _urlopen_bytes(url: str, headers: dict[str, str], timeout: float) -> bytes:
        request = Request(url, headers=headers, method="GET")
        with urlopen(request, timeout=timeout) as response:
            return response.read()

    def _validate_url(self, url: str) -> None:
        parsed = urlparse(url)
        if parsed.scheme != "https" or parsed.hostname not in _SEC_HOSTS:
            raise SecRequestError(f"Refusing non-SEC URL: {url}")

    def _wait_for_rate_limit(self) -> None:
        if self._last_request_at is None:
            return
        interval = 1.0 / self.config.requests_per_second
        remaining = interval - (self._clock() - self._last_request_at)
        if remaining > 0:
            self._sleep(remaining)

    def get_bytes(self, url: str) -> bytes:
        self._validate_url(url)
        last_error: Exception | None = None
        attempts = self.config.max_retries + 1
        for attempt in range(attempts):
            self._wait_for_rate_limit()
            try:
                payload = self._fetch_bytes(url, self.headers, self.config.timeout_seconds)
                self._last_request_at = self._clock()
                return payload
            except HTTPError as exc:
                self._last_request_at = self._clock()
                last_error = exc
                retryable = exc.code == 429 or 500 <= exc.code < 600
                if not retryable or attempt == attempts - 1:
                    break
            except (URLError, TimeoutError, OSError) as exc:
                self._last_request_at = self._clock()
                last_error = exc
                if attempt == attempts - 1:
                    break
            self._sleep(min(2.0**attempt, 8.0))
        raise SecRequestError(f"SEC request failed for {url}: {last_error}") from last_error

    def get_json(self, url: str) -> dict[str, Any]:
        try:
            return json.loads(self.get_bytes(url).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise SecRequestError(f"Invalid SEC JSON response from {url}") from exc

    def resolve_cik(self, ticker: str) -> tuple[str, str]:
        target = ticker.strip().upper()
        payload = self.get_json(_TICKERS_URL)
        for row in payload.values():
            if str(row.get("ticker", "")).upper() == target:
                cik = str(row["cik_str"]).zfill(10)
                return cik, str(row.get("title", target))
        raise SecConnectorError(f"SEC CIK not found for ticker {target}")

    def submissions(self, cik: str) -> dict[str, Any]:
        return self.get_json(_SUBMISSIONS_URL.format(cik=cik.zfill(10)))

    def discover_filings(
        self,
        submissions: dict[str, Any],
        *,
        since: date,
    ) -> list[SecFiling]:
        recent = submissions.get("filings", {}).get("recent", {})
        accessions = recent.get("accessionNumber", [])
        filings: list[SecFiling] = []

        def value(field: str, index: int, default: Any = None) -> Any:
            values = recent.get(field, [])
            return values[index] if index < len(values) else default

        allowed_forms = {form.upper() for form in self.config.forms}
        allowed_items = set(self.config.eight_k_items)
        for index, accession in enumerate(accessions):
            filing_date = _parse_optional_date(value("filingDate", index))
            form = str(value("form", index, "")).upper()
            primary_document = str(value("primaryDocument", index, ""))
            if not filing_date or filing_date < since or form not in allowed_forms:
                continue
            if not primary_document:
                continue
            items = _split_items(value("items", index, ""))
            if form.removesuffix("/A") == "8-K" and allowed_items:
                if not allowed_items.intersection(items):
                    continue
            filings.append(
                SecFiling(
                    accession_number=str(accession),
                    filing_date=filing_date,
                    report_date=_parse_optional_date(value("reportDate", index)),
                    acceptance_datetime=_parse_optional_datetime(
                        value("acceptanceDateTime", index)
                    ),
                    form=form,
                    items=items,
                    primary_document=primary_document,
                    primary_document_description=value(
                        "primaryDocDescription", index
                    ),
                    is_xbrl=bool(value("isXBRL", index, False)),
                    is_inline_xbrl=bool(value("isInlineXBRL", index, False)),
                )
            )
            if len(filings) >= self.config.max_filings_per_sync:
                break
        return filings

    @staticmethod
    def _filing_base_url(cik: str, filing: SecFiling) -> str:
        return f"{_ARCHIVES_BASE}/{int(cik)}/{filing.accession_compact}"

    def discover_documents(
        self, cik: str, filing: SecFiling
    ) -> list[SecDocumentDescriptor]:
        base = self._filing_base_url(cik, filing)
        descriptors = [
            SecDocumentDescriptor(
                accession_number=filing.accession_number,
                document_id=filing.primary_document,
                file_name=filing.primary_document,
                document_type=filing.form,
                url=f"{base}/{filing.primary_document}",
                is_primary=True,
            )
        ]
        if filing.base_form not in {"8-K", "6-K"}:
            return descriptors

        try:
            index_url = f"{base}/{filing.accession_number}-index.htm"
            index_html = self.get_bytes(index_url).decode("utf-8", errors="replace")
        except SecRequestError:
            return descriptors
        prefixes = tuple(prefix.upper() for prefix in self.config.exhibit_type_prefixes)
        for file_name, document_type, href in _parse_filing_index(index_html):
            if not file_name or file_name == filing.primary_document:
                continue
            if not document_type.startswith(prefixes):
                continue
            descriptors.append(
                SecDocumentDescriptor(
                    accession_number=filing.accession_number,
                    document_id=file_name,
                    file_name=file_name,
                    document_type=document_type,
                    url=urljoin(f"{base}/", href),
                )
            )
        return descriptors

    def fetch_document(
        self,
        ticker: str,
        company_name: str,
        cik: str,
        filing: SecFiling,
        descriptor: SecDocumentDescriptor,
    ) -> RawDocument:
        raw = self.get_bytes(descriptor.url)
        content_type = mimetypes.guess_type(descriptor.file_name)[0] or "application/octet-stream"
        logical_type = "filing" if descriptor.is_primary else "earnings_release"
        title = (
            f"{company_name} {filing.form} filed {filing.filing_date}"
            if descriptor.is_primary
            else f"{company_name} {descriptor.document_type} — {filing.form} {filing.filing_date}"
        )
        return RawDocument(
            provider="sec-edgar",
            external_id=filing.accession_number,
            document_id=descriptor.document_id,
            ticker=ticker.upper(),
            logical_type=logical_type,
            title=title,
            text=_remote_text(raw, descriptor.file_name),
            raw_content=raw,
            file_name=descriptor.file_name,
            content_type=content_type,
            source_date=filing.filing_date,
            source_name="SEC EDGAR",
            url=descriptor.url,
            reliability_score=1.0,
            metadata={
                "cik": cik,
                "accession_number": filing.accession_number,
                "form": filing.form,
                "filing_items": filing.items,
                "period_of_report": (
                    filing.report_date.isoformat() if filing.report_date else None
                ),
                "accepted_at": (
                    filing.acceptance_datetime.isoformat()
                    if filing.acceptance_datetime
                    else None
                ),
                "document_type": descriptor.document_type,
                "is_primary_document": descriptor.is_primary,
                "is_amendment": filing.form.endswith("/A"),
                "is_xbrl": filing.is_xbrl,
                "is_inline_xbrl": filing.is_inline_xbrl,
                "evidence_label": (
                    "fact_source_reported"
                    if descriptor.is_primary
                    else "issuer_management_claim"
                ),
            },
        )


def _write_sync_state(
    companies_root: Path,
    ticker: str,
    cik: str,
    filings: list[SecFiling],
    result: SecSyncResult,
) -> None:
    evidence_dir = companies_root / ticker.upper() / "evidence"
    evidence_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "provider": "sec-edgar",
        "ticker": ticker.upper(),
        "cik": cik,
        "last_synced_at": datetime.now(timezone.utc).isoformat(),
        "last_seen_accession": filings[0].accession_number if filings else None,
        "discovered_filings": result.discovered_filings,
        "ingested_documents": result.ingested_documents,
        "skipped_documents": result.skipped_documents,
        "failure_count": len(result.failures),
    }
    path = evidence_dir / "_sec_state.json"
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    temporary.replace(path)


def sync_ticker(
    config: EqosConfig,
    ticker: str,
    companies_root: Path,
    *,
    since: date | None = None,
    client: SecEdgarClient | None = None,
) -> SecSyncResult:
    """Fetch and ingest new SEC filings for one initialized company."""
    config.validate_for_sec_access()
    ticker = ticker.strip().upper()
    layout = CompanyLayout(companies_root, ticker)
    if not layout.exists():
        raise SecConnectorError(
            f"{ticker} is not initialized. Run eqos init-company first."
        )
    sec = client or SecEdgarClient(config.sec)
    cik, mapped_name = sec.resolve_cik(ticker)
    submissions = sec.submissions(cik)
    company_name = str(submissions.get("name") or mapped_name)
    start = since or (date.today() - timedelta(days=config.sync.default_since_days))
    filings = sec.discover_filings(submissions, since=start)
    result = SecSyncResult(
        ticker=ticker,
        cik=cik,
        discovered_filings=len(filings),
    )
    evidence_dir = companies_root / ticker / "evidence"

    for filing in filings:
        try:
            descriptors = sec.discover_documents(cik, filing)
        except SecConnectorError as exc:
            result.failures.append(f"{filing.accession_number}: {exc}")
            continue
        result.discovered_documents += len(descriptors)
        for descriptor in descriptors:
            if dedup.lookup_external(
                evidence_dir,
                "sec-edgar",
                filing.accession_number,
                descriptor.document_id,
            ):
                result.skipped_documents += 1
                continue
            try:
                document = sec.fetch_document(
                    ticker,
                    company_name,
                    cik,
                    filing,
                    descriptor,
                )
                evidence = ingest_document(
                    document,
                    companies_root,
                    store_raw=config.sync.store_raw_documents,
                    raw_dir_name=config.storage.raw_documents_dir,
                )
            except Exception as exc:
                result.failures.append(
                    f"{filing.accession_number}/{descriptor.document_id}: {exc}"
                )
                continue
            if evidence is None:
                result.skipped_documents += 1
            else:
                result.ingested_documents += 1
                result.evidence_ids.append(str(evidence.evidence_id))

    _write_sync_state(companies_root, ticker, cik, filings, result)
    return result
