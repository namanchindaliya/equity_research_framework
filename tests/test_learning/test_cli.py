"""CLI tests for score-company, resolve-episode, postmortem-episode."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from equity_os.v1_cli import app

runner = CliRunner()


def _cd(companies_dir: Path) -> list[str]:
    return ["--companies-dir", str(companies_dir)]


def _init_and_episode(companies_dir: Path, ticker: str = "AAPL") -> str:
    """Initialise company and create an episode with predictions. Returns slug."""
    runner.invoke(app, ["init-company", ticker, "--name", "Apple Inc.", *_cd(companies_dir)])
    r = runner.invoke(app, [
        "new-episode", ticker,
        "--title", "FY2026 Initiation",
        "--thesis", "Services flywheel.",
        "--rating", "BUY",
        *_cd(companies_dir),
    ])
    from equity_os.fs.layout import CompanyLayout
    layout = CompanyLayout(companies_dir, ticker)
    return layout.episode_slugs()[0]


def _log_prediction(companies_dir: Path, ticker: str, slug: str, metric: str = "services_revenue") -> None:
    runner.invoke(app, [
        "log-prediction", ticker, slug,
        "--metric", metric,
        "--description", "Services revenue >$110B",
        "--threshold", "110",
        "--horizon", "FY2026",
        "--due-date", "2026-11-01",
        "--probability", "0.7",
        *_cd(companies_dir),
    ])


def _resolve_single(companies_dir: Path, ticker: str, slug: str, metric: str, status: str, actual: str) -> None:
    runner.invoke(app, [
        "resolve-prediction", ticker, slug, metric,
        "--status", status,
        "--actual", actual,
        "--notes", "Test resolution",
        *_cd(companies_dir),
    ])


class TestScoreCompany:
    def test_score_company_runs(self, tmp_path: Path):
        slug = _init_and_episode(tmp_path)
        _log_prediction(tmp_path, "AAPL", slug)
        _resolve_single(tmp_path, "AAPL", slug, "services_revenue", "CORRECT", "115")
        result = runner.invoke(app, ["score-company", "AAPL", *_cd(tmp_path)])
        assert result.exit_code == 0, result.output

    def test_score_writes_json(self, tmp_path: Path):
        slug = _init_and_episode(tmp_path)
        _log_prediction(tmp_path, "AAPL", slug)
        _resolve_single(tmp_path, "AAPL", slug, "services_revenue", "CORRECT", "115")
        runner.invoke(app, ["score-company", "AAPL", *_cd(tmp_path)])
        from equity_os.fs.layout import CompanyLayout
        layout = CompanyLayout(tmp_path, "AAPL")
        assert layout.score_json(slug).exists()

    def test_score_writes_md(self, tmp_path: Path):
        slug = _init_and_episode(tmp_path)
        _log_prediction(tmp_path, "AAPL", slug)
        _resolve_single(tmp_path, "AAPL", slug, "services_revenue", "CORRECT", "115")
        runner.invoke(app, ["score-company", "AAPL", *_cd(tmp_path)])
        from equity_os.fs.layout import CompanyLayout
        layout = CompanyLayout(tmp_path, "AAPL")
        assert layout.score_md(slug).exists()

    def test_score_json_valid(self, tmp_path: Path):
        slug = _init_and_episode(tmp_path)
        _log_prediction(tmp_path, "AAPL", slug)
        _resolve_single(tmp_path, "AAPL", slug, "services_revenue", "CORRECT", "115")
        runner.invoke(app, ["score-company", "AAPL", *_cd(tmp_path)])
        from equity_os.fs.layout import CompanyLayout
        from equity_os.learning.models import EpisodeScore
        layout = CompanyLayout(tmp_path, "AAPL")
        score = EpisodeScore.model_validate_json(layout.score_json(slug).read_text())
        assert score.total_predictions == 1
        assert score.brier_score is not None

    def test_score_no_predictions_skips(self, tmp_path: Path):
        slug = _init_and_episode(tmp_path)
        result = runner.invoke(app, ["score-company", "AAPL", *_cd(tmp_path)])
        assert result.exit_code == 0
        assert "no predictions" in result.output.lower()

    def test_score_specific_episode(self, tmp_path: Path):
        slug = _init_and_episode(tmp_path)
        _log_prediction(tmp_path, "AAPL", slug)
        _resolve_single(tmp_path, "AAPL", slug, "services_revenue", "CORRECT", "115")
        result = runner.invoke(app, ["score-company", "AAPL", "--episode", slug, *_cd(tmp_path)])
        assert result.exit_code == 0

    def test_score_uninitialised_fails(self, tmp_path: Path):
        result = runner.invoke(app, ["score-company", "FAKE", *_cd(tmp_path)])
        assert result.exit_code == 1


class TestResolveEpisode:
    def test_resolve_from_file(self, tmp_path: Path):
        slug = _init_and_episode(tmp_path)
        _log_prediction(tmp_path, "AAPL", slug)
        resolutions = [{"metric": "services_revenue", "status": "CORRECT", "actual": "115", "notes": "Beat estimate"}]
        rfile = tmp_path / "resolutions.json"
        rfile.write_text(json.dumps(resolutions))
        result = runner.invoke(app, [
            "resolve-episode", "AAPL", slug,
            "--resolution-file", str(rfile),
            *_cd(tmp_path),
        ])
        assert result.exit_code == 0, result.output
        assert "Resolved" in result.output

    def test_resolve_from_flags(self, tmp_path: Path):
        slug = _init_and_episode(tmp_path)
        _log_prediction(tmp_path, "AAPL", slug)
        result = runner.invoke(app, [
            "resolve-episode", "AAPL", slug,
            "--metric", "services_revenue",
            "--status", "INCORRECT",
            "--actual", "98",
            "--notes", "Missed",
            *_cd(tmp_path),
        ])
        assert result.exit_code == 0
        assert "Resolved" in result.output

    def test_resolve_updates_episode_json(self, tmp_path: Path):
        slug = _init_and_episode(tmp_path)
        _log_prediction(tmp_path, "AAPL", slug)
        runner.invoke(app, [
            "resolve-episode", "AAPL", slug,
            "--metric", "services_revenue",
            "--status", "CORRECT",
            "--actual", "115",
            *_cd(tmp_path),
        ])
        from equity_os.fs.layout import CompanyLayout
        from equity_os.fs.readers import load_episode
        layout = CompanyLayout(tmp_path, "AAPL")
        ep = load_episode(layout, slug)
        assert ep.predictions[0].is_resolved

    def test_resolve_already_resolved_skipped(self, tmp_path: Path):
        slug = _init_and_episode(tmp_path)
        _log_prediction(tmp_path, "AAPL", slug)
        # Resolve first time
        runner.invoke(app, [
            "resolve-episode", "AAPL", slug,
            "--metric", "services_revenue",
            "--status", "CORRECT",
            "--actual", "115",
            *_cd(tmp_path),
        ])
        # Try again
        result = runner.invoke(app, [
            "resolve-episode", "AAPL", slug,
            "--metric", "services_revenue",
            "--status", "INCORRECT",
            "--actual", "80",
            *_cd(tmp_path),
        ])
        assert result.exit_code == 0
        assert "skipped" in result.output.lower()

    def test_resolve_unknown_metric_skipped(self, tmp_path: Path):
        slug = _init_and_episode(tmp_path)
        result = runner.invoke(app, [
            "resolve-episode", "AAPL", slug,
            "--metric", "nonexistent_metric",
            "--status", "CORRECT",
            "--actual", "99",
            *_cd(tmp_path),
        ])
        assert result.exit_code == 0
        assert "not found" in result.output.lower() or "skipped" in result.output.lower()

    def test_resolve_no_file_or_flags_fails(self, tmp_path: Path):
        slug = _init_and_episode(tmp_path)
        result = runner.invoke(app, ["resolve-episode", "AAPL", slug, *_cd(tmp_path)])
        assert result.exit_code == 1

    def test_resolve_bulk_from_file(self, tmp_path: Path):
        slug = _init_and_episode(tmp_path)
        for metric in ["m1", "m2", "m3"]:
            _log_prediction(tmp_path, "AAPL", slug, metric=metric)
        resolutions = [
            {"metric": "m1", "status": "CORRECT", "actual": "115"},
            {"metric": "m2", "status": "INCORRECT", "actual": "85"},
            {"metric": "m3", "status": "PARTIALLY_CORRECT", "actual": "102"},
        ]
        rfile = tmp_path / "bulk.json"
        rfile.write_text(json.dumps(resolutions))
        result = runner.invoke(app, [
            "resolve-episode", "AAPL", slug,
            "--resolution-file", str(rfile),
            *_cd(tmp_path),
        ])
        assert result.exit_code == 0
        assert "3 prediction" in result.output


class TestPostmortemEpisode:
    def test_postmortem_requires_resolved_predictions(self, tmp_path: Path):
        slug = _init_and_episode(tmp_path)
        _log_prediction(tmp_path, "AAPL", slug)
        # Don't resolve — should fail
        result = runner.invoke(app, ["postmortem-episode", "AAPL", slug, *_cd(tmp_path)])
        assert result.exit_code == 1
        assert "resolve" in result.output.lower() or "no resolved" in result.output.lower()

    def test_postmortem_runs_after_resolution(self, tmp_path: Path):
        slug = _init_and_episode(tmp_path)
        _log_prediction(tmp_path, "AAPL", slug)
        _resolve_single(tmp_path, "AAPL", slug, "services_revenue", "CORRECT", "115")
        result = runner.invoke(app, ["postmortem-episode", "AAPL", slug, *_cd(tmp_path)])
        assert result.exit_code == 0, result.output

    def test_postmortem_writes_json(self, tmp_path: Path):
        slug = _init_and_episode(tmp_path)
        _log_prediction(tmp_path, "AAPL", slug)
        _resolve_single(tmp_path, "AAPL", slug, "services_revenue", "CORRECT", "115")
        runner.invoke(app, ["postmortem-episode", "AAPL", slug, *_cd(tmp_path)])
        from equity_os.fs.layout import CompanyLayout
        layout = CompanyLayout(tmp_path, "AAPL")
        assert layout.postmortem_json(slug).exists()

    def test_postmortem_writes_md(self, tmp_path: Path):
        slug = _init_and_episode(tmp_path)
        _log_prediction(tmp_path, "AAPL", slug)
        _resolve_single(tmp_path, "AAPL", slug, "services_revenue", "CORRECT", "115")
        runner.invoke(app, ["postmortem-episode", "AAPL", slug, *_cd(tmp_path)])
        from equity_os.fs.layout import CompanyLayout
        layout = CompanyLayout(tmp_path, "AAPL")
        assert layout.postmortem_md(slug).exists()
        md = layout.postmortem_md(slug).read_text()
        assert "## 1. What We Believed" in md
        assert "## 6." in md

    def test_postmortem_json_valid(self, tmp_path: Path):
        slug = _init_and_episode(tmp_path)
        _log_prediction(tmp_path, "AAPL", slug)
        _resolve_single(tmp_path, "AAPL", slug, "services_revenue", "CORRECT", "115")
        runner.invoke(app, ["postmortem-episode", "AAPL", slug, *_cd(tmp_path)])
        from equity_os.fs.layout import CompanyLayout
        from equity_os.learning.models import PostmortemReport
        layout = CompanyLayout(tmp_path, "AAPL")
        report = PostmortemReport.model_validate_json(layout.postmortem_json(slug).read_text())
        assert report.verdict == "INSUFFICIENT_EVIDENCE"
        assert report.thesis_at_time

    def test_postmortem_custom_thesis(self, tmp_path: Path):
        slug = _init_and_episode(tmp_path)
        _log_prediction(tmp_path, "AAPL", slug)
        _resolve_single(tmp_path, "AAPL", slug, "services_revenue", "CORRECT", "115")
        runner.invoke(app, [
            "postmortem-episode", "AAPL", slug,
            "--thesis", "Custom thesis for this episode.",
            *_cd(tmp_path),
        ])
        from equity_os.fs.layout import CompanyLayout
        from equity_os.learning.models import PostmortemReport
        layout = CompanyLayout(tmp_path, "AAPL")
        report = PostmortemReport.model_validate_json(layout.postmortem_json(slug).read_text())
        assert "Custom thesis" in report.thesis_at_time
