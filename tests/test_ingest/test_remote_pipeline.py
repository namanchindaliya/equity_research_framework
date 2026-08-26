"""Tests for connector-originated documents using the shared evidence pipeline."""

from __future__ import annotations

from datetime import date
from pathlib import Path

from equity_os.ingest.models import RawDocument
from equity_os.ingest.pipeline import ingest_document, list_catalog


def _document(accession: str, document_id: str, *, text: str) -> RawDocument:
    return RawDocument(
        provider="sec-edgar",
        external_id=accession,
        document_id=document_id,
        ticker="AAPL",
        logical_type="filing",
        title="Apple filing",
        text=text,
        raw_content=f"<html><body>{text}</body></html>".encode(),
        file_name=document_id,
        content_type="text/html",
        source_date=date(2026, 8, 1),
        source_name="SEC EDGAR",
        url=f"https://www.sec.gov/Archives/{document_id}",
        reliability_score=1.0,
    )


def test_remote_document_preserves_raw_and_provenance(tmp_path: Path) -> None:
    evidence = ingest_document(
        _document("0000320193-26-000001", "aapl-10q.htm", text="Quarterly filing facts."),
        tmp_path,
    )

    assert evidence is not None
    assert evidence.provider == "sec-edgar"
    assert evidence.external_id == "0000320193-26-000001"
    assert evidence.raw_content_path is not None
    assert Path(evidence.raw_content_path).read_bytes().startswith(b"<html>")
    manifest = list_catalog(tmp_path, "AAPL")[0]
    assert manifest.document_id == "aapl-10q.htm"
    assert manifest.url == evidence.url


def test_external_identity_skips_exact_repeat(tmp_path: Path) -> None:
    document = _document(
        "0000320193-26-000001", "aapl-10q.htm", text="Quarterly filing facts."
    )

    assert ingest_document(document, tmp_path) is not None
    assert ingest_document(document, tmp_path) is None


def test_new_accession_is_kept_even_when_text_matches(tmp_path: Path) -> None:
    text = "The normalized filing wording is unchanged."

    first = ingest_document(
        _document("0000320193-26-000001", "aapl-10q.htm", text=text), tmp_path
    )
    amendment = ingest_document(
        _document("0000320193-26-000002", "aapl-10qa.htm", text=text), tmp_path
    )

    assert first is not None
    assert amendment is not None
    assert first.evidence_id != amendment.evidence_id
    assert len(list_catalog(tmp_path, "AAPL")) == 2
