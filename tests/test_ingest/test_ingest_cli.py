"""CLI tests for the ingest and list-evidence commands."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from equity_os.v1_cli import app
from tests.test_ingest.conftest import AAPL_INPUTS

runner = CliRunner()


def _args(companies_dir: Path, inputs_dir: Path) -> list[str]:
    return ["--companies-dir", str(companies_dir), "--inputs-dir", str(inputs_dir)]


def _init_company(companies_dir: Path) -> None:
    result = runner.invoke(
        app,
        ["init-company", "AAPL", "--name", "Apple Inc.", "--companies-dir", str(companies_dir)],
    )
    assert result.exit_code == 0, result.output


class TestIngestCommand:
    def test_ingest_single_file(self, tmp_path: Path):
        _init_company(tmp_path)
        result = runner.invoke(
            app,
            ["ingest", "AAPL", "--file", str(AAPL_INPUTS / "filing_10k_fy2025.txt"),
             "--companies-dir", str(tmp_path)],
        )
        assert result.exit_code == 0, result.output
        assert "Ingested" in result.output

    def test_ingest_batch_dir(self, tmp_path: Path):
        _init_company(tmp_path)
        inputs_parent = AAPL_INPUTS.parent
        result = runner.invoke(
            app,
            ["ingest", "AAPL", *_args(tmp_path, inputs_parent)],
        )
        assert result.exit_code == 0, result.output
        assert "ingested" in result.output.lower()

    def test_duplicate_shown_as_duplicate(self, tmp_path: Path):
        _init_company(tmp_path)
        file_arg = ["--file", str(AAPL_INPUTS / "filing_10k_fy2025.txt")]
        runner.invoke(app, ["ingest", "AAPL", *file_arg, "--companies-dir", str(tmp_path)])
        result = runner.invoke(app, ["ingest", "AAPL", *file_arg, "--companies-dir", str(tmp_path)])
        assert result.exit_code == 0
        assert "duplicate" in result.output.lower() or "Skipped" in result.output

    def test_force_reingest(self, tmp_path: Path):
        _init_company(tmp_path)
        file_arg = ["--file", str(AAPL_INPUTS / "filing_10k_fy2025.txt")]
        runner.invoke(app, ["ingest", "AAPL", *file_arg, "--companies-dir", str(tmp_path)])
        result = runner.invoke(
            app,
            ["ingest", "AAPL", "--force", *file_arg, "--companies-dir", str(tmp_path)],
        )
        assert result.exit_code == 0
        assert "Ingested" in result.output

    def test_uninitialised_company_fails(self, tmp_path: Path):
        result = runner.invoke(
            app,
            ["ingest", "FAKE", "--file", str(AAPL_INPUTS / "filing_10k_fy2025.txt"),
             "--companies-dir", str(tmp_path)],
        )
        assert result.exit_code == 1

    def test_missing_file_fails(self, tmp_path: Path):
        _init_company(tmp_path)
        result = runner.invoke(
            app,
            ["ingest", "AAPL", "--file", str(tmp_path / "nonexistent.txt"),
             "--companies-dir", str(tmp_path)],
        )
        assert result.exit_code == 1

    def test_logical_type_override(self, tmp_path: Path):
        _init_company(tmp_path)
        result = runner.invoke(
            app,
            ["ingest", "AAPL",
             "--file", str(AAPL_INPUTS / "filing_10k_fy2025.txt"),
             "--logical-type", "industry_note",
             "--companies-dir", str(tmp_path)],
        )
        assert result.exit_code == 0, result.output
        ev_dir = tmp_path / "AAPL" / "evidence"
        json_files = [f for f in ev_dir.iterdir() if f.suffix == ".json" and not f.stem.startswith("_")]
        assert len(json_files) >= 1
        from equity_os.ingest.models import IngestedEvidence
        ev = IngestedEvidence.model_validate_json(json_files[0].read_text())
        assert ev.logical_type == "industry_note"

    def test_creates_evidence_json_file(self, tmp_path: Path):
        _init_company(tmp_path)
        runner.invoke(
            app,
            ["ingest", "AAPL", "--file", str(AAPL_INPUTS / "filing_10k_fy2025.txt"),
             "--companies-dir", str(tmp_path)],
        )
        ev_dir = tmp_path / "AAPL" / "evidence"
        json_files = [f for f in ev_dir.iterdir() if f.suffix == ".json" and not f.stem.startswith("_")]
        assert len(json_files) == 1


class TestListEvidenceCommand:
    def test_list_after_ingest(self, tmp_path: Path):
        _init_company(tmp_path)
        runner.invoke(
            app,
            ["ingest", "AAPL", "--file", str(AAPL_INPUTS / "filing_10k_fy2025.txt"),
             "--companies-dir", str(tmp_path)],
        )
        result = runner.invoke(
            app, ["list-evidence", "AAPL", "--companies-dir", str(tmp_path)]
        )
        assert result.exit_code == 0
        assert "filing" in result.output

    def test_empty_catalog_message(self, tmp_path: Path):
        _init_company(tmp_path)
        result = runner.invoke(
            app, ["list-evidence", "AAPL", "--companies-dir", str(tmp_path)]
        )
        assert result.exit_code == 0
        assert "No evidence" in result.output

    def test_uninitialised_fails(self, tmp_path: Path):
        result = runner.invoke(
            app, ["list-evidence", "FAKE", "--companies-dir", str(tmp_path)]
        )
        assert result.exit_code == 1
