"""Tests for pipeline.py: end-to-end ingestion from fixture files."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from equity_os.ingest.models import IngestedEvidence
from equity_os.ingest.pipeline import (
    ingest_dir,
    ingest_file,
    list_catalog,
    load_evidence,
)
from tests.test_ingest.conftest import AAPL_INPUTS


def _init_company(companies_dir: Path) -> None:
    """Minimally initialise AAPL so the company dir exists."""
    (companies_dir / "AAPL" / "evidence").mkdir(parents=True, exist_ok=True)


# ===========================================================================
# ingest_file
# ===========================================================================


class TestIngestFile:
    def test_txt_filing_produces_record(self, tmp_path: Path):
        _init_company(tmp_path)
        ev = ingest_file(AAPL_INPUTS / "filing_10k_fy2025.txt", "AAPL", tmp_path)
        assert ev is not None
        assert ev.ticker == "AAPL"
        assert ev.logical_type == "filing"
        assert ev.source_type == "FILING"
        assert ev.reliability_score == 1.0
        assert len(ev.text) > 100
        assert len(ev.chunks) >= 1

    def test_md_transcript_produces_record(self, tmp_path: Path):
        _init_company(tmp_path)
        ev = ingest_file(AAPL_INPUTS / "earnings_transcript_q1_fy2026.md", "AAPL", tmp_path)
        assert ev is not None
        assert ev.logical_type == "earnings_transcript"
        assert ev.source_date is not None
        assert ev.source_date.year == 2026

    def test_html_news_produces_record(self, tmp_path: Path):
        _init_company(tmp_path)
        ev = ingest_file(AAPL_INPUTS / "news_note_dma_ruling.html", "AAPL", tmp_path)
        assert ev is not None
        assert ev.logical_type == "news_note"
        assert ev.reliability_score == pytest.approx(0.70)

    def test_csv_channel_check_produces_record(self, tmp_path: Path):
        _init_company(tmp_path)
        ev = ingest_file(AAPL_INPUTS / "channel_check_q1_asia.csv", "AAPL", tmp_path)
        assert ev is not None
        assert ev.logical_type == "channel_check_note"
        assert ev.source_type == "CHANNEL_CHECK"

    def test_json_written_to_evidence_dir(self, tmp_path: Path):
        _init_company(tmp_path)
        ev = ingest_file(AAPL_INPUTS / "filing_10k_fy2025.txt", "AAPL", tmp_path)
        assert ev is not None
        ev_dir = tmp_path / "AAPL" / "evidence"
        out = ev_dir / f"{ev.evidence_id}.json"
        assert out.exists()
        loaded = IngestedEvidence.model_validate_json(out.read_text())
        assert loaded.evidence_id == ev.evidence_id

    def test_dedup_index_created(self, tmp_path: Path):
        _init_company(tmp_path)
        ingest_file(AAPL_INPUTS / "filing_10k_fy2025.txt", "AAPL", tmp_path)
        index = tmp_path / "AAPL" / "evidence" / "_index.jsonl"
        assert index.exists()
        lines = [l for l in index.read_text().splitlines() if l.strip()]
        assert len(lines) == 1

    def test_duplicate_returns_none(self, tmp_path: Path):
        _init_company(tmp_path)
        ev1 = ingest_file(AAPL_INPUTS / "filing_10k_fy2025.txt", "AAPL", tmp_path)
        ev2 = ingest_file(AAPL_INPUTS / "filing_10k_fy2025.txt", "AAPL", tmp_path)
        assert ev1 is not None
        assert ev2 is None  # duplicate

    def test_force_reingest_bypasses_dedup(self, tmp_path: Path):
        _init_company(tmp_path)
        ev1 = ingest_file(AAPL_INPUTS / "filing_10k_fy2025.txt", "AAPL", tmp_path)
        ev2 = ingest_file(AAPL_INPUTS / "filing_10k_fy2025.txt", "AAPL", tmp_path, force=True)
        assert ev1 is not None
        assert ev2 is not None
        assert ev1.evidence_id != ev2.evidence_id  # new UUID on force re-ingest

    def test_catalog_updated(self, tmp_path: Path):
        _init_company(tmp_path)
        ev = ingest_file(AAPL_INPUTS / "filing_10k_fy2025.txt", "AAPL", tmp_path)
        catalog_path = tmp_path / "AAPL" / "evidence" / "_catalog.json"
        assert catalog_path.exists()
        entries = json.loads(catalog_path.read_text())
        assert len(entries) == 1
        assert entries[0]["evidence_id"] == str(ev.evidence_id)

    def test_content_hash_present(self, tmp_path: Path):
        _init_company(tmp_path)
        ev = ingest_file(AAPL_INPUTS / "filing_10k_fy2025.txt", "AAPL", tmp_path)
        assert ev is not None
        assert len(ev.content_hash) == 64

    def test_chunks_have_citation_anchors(self, tmp_path: Path):
        _init_company(tmp_path)
        ev = ingest_file(AAPL_INPUTS / "filing_10k_fy2025.txt", "AAPL", tmp_path)
        assert ev is not None
        for chunk in ev.chunks:
            assert chunk.chunk_id.startswith("AAPL-")
            assert "-" in chunk.chunk_id

    def test_extracted_metadata_has_word_count(self, tmp_path: Path):
        _init_company(tmp_path)
        ev = ingest_file(AAPL_INPUTS / "filing_10k_fy2025.txt", "AAPL", tmp_path)
        assert ev is not None
        assert "word_count" in ev.extracted_metadata
        assert ev.extracted_metadata["word_count"] > 0

    def test_filing_extracts_filing_types(self, tmp_path: Path):
        _init_company(tmp_path)
        ev = ingest_file(AAPL_INPUTS / "filing_10k_fy2025.txt", "AAPL", tmp_path)
        assert ev is not None
        meta = ev.extracted_metadata
        assert "detected_filing_types" in meta
        assert any("10-K" in ft for ft in meta["detected_filing_types"])

    def test_transcript_extracts_quarter(self, tmp_path: Path):
        _init_company(tmp_path)
        ev = ingest_file(AAPL_INPUTS / "earnings_transcript_q1_fy2026.md", "AAPL", tmp_path)
        assert ev is not None
        meta = ev.extracted_metadata
        assert meta.get("quarter") == "Q1"
        assert meta.get("fiscal_year") == 2026

    def test_logical_type_override(self, tmp_path: Path, tmp_path_factory):
        _init_company(tmp_path)
        # Override the frontmatter-declared type
        ev = ingest_file(
            AAPL_INPUTS / "filing_10k_fy2025.txt", "AAPL", tmp_path,
            logical_type="industry_note"
        )
        assert ev is not None
        assert ev.logical_type == "industry_note"

    def test_invalid_logical_type_raises(self, tmp_path: Path):
        _init_company(tmp_path)
        with pytest.raises(ValueError, match="Unknown logical_type"):
            ingest_file(
                AAPL_INPUTS / "filing_10k_fy2025.txt", "AAPL", tmp_path,
                logical_type="not_a_real_type"
            )

    def test_unsupported_extension_raises(self, tmp_path: Path):
        _init_company(tmp_path)
        bad = tmp_path / "doc.pdf"
        bad.write_text("content")
        with pytest.raises(ValueError, match="Unsupported file type"):
            ingest_file(bad, "AAPL", tmp_path)

    def test_round_trip_json(self, tmp_path: Path):
        _init_company(tmp_path)
        ev = ingest_file(AAPL_INPUTS / "filing_10k_fy2025.txt", "AAPL", tmp_path)
        assert ev is not None
        raw = (tmp_path / "AAPL" / "evidence" / f"{ev.evidence_id}.json").read_text()
        ev2 = IngestedEvidence.model_validate_json(raw)
        assert ev2.evidence_id == ev.evidence_id
        assert ev2.content_hash == ev.content_hash
        assert len(ev2.chunks) == len(ev.chunks)


# ===========================================================================
# ingest_dir
# ===========================================================================


class TestIngestDir:
    def test_ingests_all_four_fixtures(self, tmp_path: Path):
        _init_company(tmp_path)
        ingested, skipped, failed = ingest_dir(AAPL_INPUTS, "AAPL", tmp_path)
        assert len(failed) == 0, f"Failures: {failed}"
        assert len(ingested) == 4

    def test_second_run_all_skipped(self, tmp_path: Path):
        _init_company(tmp_path)
        ingest_dir(AAPL_INPUTS, "AAPL", tmp_path)
        ingested, skipped, failed = ingest_dir(AAPL_INPUTS, "AAPL", tmp_path)
        assert ingested == []
        assert len(skipped) == 4

    def test_evidence_dir_has_four_json_files(self, tmp_path: Path):
        _init_company(tmp_path)
        ingest_dir(AAPL_INPUTS, "AAPL", tmp_path)
        ev_dir = tmp_path / "AAPL" / "evidence"
        json_files = [f for f in ev_dir.iterdir() if f.suffix == ".json" and not f.stem.startswith("_")]
        assert len(json_files) == 4


# ===========================================================================
# load_evidence and list_catalog
# ===========================================================================


class TestLoadAndCatalog:
    def test_load_evidence_round_trip(self, tmp_path: Path):
        _init_company(tmp_path)
        ev = ingest_file(AAPL_INPUTS / "filing_10k_fy2025.txt", "AAPL", tmp_path)
        assert ev is not None
        loaded = load_evidence(tmp_path, "AAPL", str(ev.evidence_id))
        assert loaded.evidence_id == ev.evidence_id

    def test_load_evidence_missing_raises(self, tmp_path: Path):
        _init_company(tmp_path)
        with pytest.raises(FileNotFoundError):
            load_evidence(tmp_path, "AAPL", "00000000-0000-0000-0000-000000000099")

    def test_list_catalog_returns_entries(self, tmp_path: Path):
        _init_company(tmp_path)
        ingest_dir(AAPL_INPUTS, "AAPL", tmp_path)
        catalog = list_catalog(tmp_path, "AAPL")
        assert len(catalog) == 4
        types = {e.logical_type for e in catalog}
        assert "filing" in types
        assert "earnings_transcript" in types
