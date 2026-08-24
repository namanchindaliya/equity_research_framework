"""Tests for all 8 eqos v1 CLI commands."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from equity_os.fs.io import read_jsonl
from equity_os.fs.layout import CompanyLayout
from equity_os.fs.readers import load_dossier, load_episode, load_full_dossier
from equity_os.schemas import (
    AssumptionChange,
    AssumptionRecord,
    CompanyDossier,
    MaterialityLevel,
    PredictionRecord,
    ResolutionRecord,
    ThesisEpisode,
)
from equity_os.v1_cli import app

runner = CliRunner()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _args(companies_dir: Path) -> list[str]:
    return ["--companies-dir", str(companies_dir)]


def _init(companies_dir: Path, ticker: str = "AAPL") -> None:
    result = runner.invoke(
        app,
        ["init-company", ticker, "--name", "Apple Inc.", "--sector", "Technology", *_args(companies_dir)],
    )
    assert result.exit_code == 0, result.output


def _new_episode(companies_dir: Path, ticker: str = "AAPL") -> str:
    """Create an episode and return its slug."""
    result = runner.invoke(
        app,
        [
            "new-episode", ticker,
            "--title", "FY2026 Initiation",
            "--thesis", "Services flywheel drives durable margin expansion.",
            "--rating", "BUY",
            "--price-target", "230.0",
            *_args(companies_dir),
        ],
    )
    assert result.exit_code == 0, result.output
    layout = CompanyLayout(companies_dir, ticker)
    return layout.episode_slugs()[0]


def _add_assumption(companies_dir: Path, ticker: str, slug: str, key: str = "services_cagr") -> None:
    result = runner.invoke(
        app,
        [
            "add-assumption", ticker, slug,
            "--key", key,
            "--label", "Services 3yr CAGR",
            "--value", "0.13",
            "--unit", "%",
            "--rationale", "Install base compounding + ARPU expansion.",
            "--confidence", "0.72",
            "--materiality", "CRITICAL",
            *_args(companies_dir),
        ],
    )
    assert result.exit_code == 0, result.output


def _log_prediction(companies_dir: Path, ticker: str, slug: str) -> None:
    result = runner.invoke(
        app,
        [
            "log-prediction", ticker, slug,
            "--metric", "aapl_services_revenue",
            "--description", "Apple services revenue exceeds $110B in FY2026",
            "--threshold", "110",
            "--horizon", "FY2026 full-year",
            "--due-date", "2026-11-01",
            "--resolution-rule", "Apple FY2026 annual report total Services revenue.",
            "--unit", "USD B",
            "--probability", "0.65",
            "--materiality", "HIGH",
            *_args(companies_dir),
        ],
    )
    assert result.exit_code == 0, result.output


# ===========================================================================
# init-company
# ===========================================================================


class TestInitCompany:
    def test_creates_folder_tree(self, tmp_path: Path):
        _init(tmp_path)
        layout = CompanyLayout(tmp_path, "AAPL")
        for subdir in ("core", "episodes", "assumptions", "predictions", "resolutions", "evidence", "outputs", "policy"):
            assert (layout.root / subdir).is_dir(), f"Missing dir: {subdir}"

    def test_writes_dossier_json(self, tmp_path: Path):
        _init(tmp_path)
        layout = CompanyLayout(tmp_path, "AAPL")
        dossier = load_dossier(layout)
        assert dossier.ticker == "AAPL"
        assert dossier.name == "Apple Inc."
        assert dossier.sector == "Technology"

    def test_writes_dossier_md(self, tmp_path: Path):
        _init(tmp_path)
        layout = CompanyLayout(tmp_path, "AAPL")
        assert layout.dossier_md.exists()
        md = layout.dossier_md.read_text()
        assert "Apple Inc." in md
        assert "AAPL" in md

    def test_duplicate_init_fails(self, tmp_path: Path):
        _init(tmp_path)
        result = runner.invoke(
            app,
            ["init-company", "AAPL", "--name", "Apple Again", *_args(tmp_path)],
        )
        assert result.exit_code == 1
        assert "already initialised" in result.output

    def test_tags_stored(self, tmp_path: Path):
        runner.invoke(
            app,
            ["init-company", "MSFT", "--name", "Microsoft", "--tags", "cloud,ai", *_args(tmp_path)],
        )
        layout = CompanyLayout(tmp_path, "MSFT")
        dossier = load_dossier(layout)
        assert dossier.tags == ["cloud", "ai"]


# ===========================================================================
# new-episode
# ===========================================================================


class TestNewEpisode:
    def test_creates_episode_json(self, tmp_path: Path):
        _init(tmp_path)
        slug = _new_episode(tmp_path)
        layout = CompanyLayout(tmp_path, "AAPL")
        assert layout.episode_json(slug).exists()
        ep = load_episode(layout, slug)
        assert ep.ticker == "AAPL"
        assert ep.title == "FY2026 Initiation"

    def test_creates_episode_md(self, tmp_path: Path):
        _init(tmp_path)
        slug = _new_episode(tmp_path)
        layout = CompanyLayout(tmp_path, "AAPL")
        assert layout.episode_md(slug).exists()
        md = layout.episode_md(slug).read_text()
        assert "FY2026 Initiation" in md
        assert "BUY" in md

    def test_slug_format(self, tmp_path: Path):
        _init(tmp_path)
        slug = _new_episode(tmp_path)
        # slug should be YYYY-MM-DD_<something>
        parts = slug.split("_", 1)
        assert len(parts) == 2
        assert len(parts[0]) == 10  # YYYY-MM-DD

    def test_episode_has_correct_fields(self, tmp_path: Path):
        _init(tmp_path)
        slug = _new_episode(tmp_path)
        layout = CompanyLayout(tmp_path, "AAPL")
        ep = load_episode(layout, slug)
        assert ep.rating.value == "BUY"
        assert ep.price_target == 230.0
        assert ep.thesis_statement == "Services flywheel drives durable margin expansion."

    def test_uninitialised_company_fails(self, tmp_path: Path):
        result = runner.invoke(
            app,
            ["new-episode", "FAKE", "--title", "T", "--thesis", "T", "--rating", "BUY",
             *_args(tmp_path)],
        )
        assert result.exit_code == 1


# ===========================================================================
# add-assumption
# ===========================================================================


class TestAddAssumption:
    def test_adds_assumption_to_episode(self, tmp_path: Path):
        _init(tmp_path)
        slug = _new_episode(tmp_path)
        _add_assumption(tmp_path, "AAPL", slug)

        layout = CompanyLayout(tmp_path, "AAPL")
        ep = load_episode(layout, slug)
        assert len(ep.assumptions) == 1
        a = ep.assumptions[0]
        assert a.key == "services_cagr"
        assert a.value == 0.13
        assert a.version == 1

    def test_writes_versioned_assumption_file(self, tmp_path: Path):
        _init(tmp_path)
        slug = _new_episode(tmp_path)
        _add_assumption(tmp_path, "AAPL", slug)

        layout = CompanyLayout(tmp_path, "AAPL")
        v1_path = layout.assumption_json(slug, "services_cagr", 1)
        assert v1_path.exists()
        a = AssumptionRecord.model_validate_json(v1_path.read_text())
        assert a.key == "services_cagr"
        assert a.version == 1

    def test_updates_episode_md(self, tmp_path: Path):
        _init(tmp_path)
        slug = _new_episode(tmp_path)
        _add_assumption(tmp_path, "AAPL", slug)

        layout = CompanyLayout(tmp_path, "AAPL")
        md = layout.episode_md(slug).read_text()
        assert "services_cagr" in md

    def test_duplicate_key_fails(self, tmp_path: Path):
        _init(tmp_path)
        slug = _new_episode(tmp_path)
        _add_assumption(tmp_path, "AAPL", slug)

        result = runner.invoke(
            app,
            ["add-assumption", "AAPL", slug,
             "--key", "services_cagr",
             "--label", "Duplicate",
             "--value", "0.20",
             "--rationale", "r",
             *_args(tmp_path)],
        )
        assert result.exit_code == 1
        assert "already exists" in result.output

    def test_slug_prefix_resolution(self, tmp_path: Path):
        _init(tmp_path)
        slug = _new_episode(tmp_path)
        prefix = slug[:10]  # just the date part
        result = runner.invoke(
            app,
            ["add-assumption", "AAPL", prefix,
             "--key", "margin",
             "--label", "Gross Margin",
             "--value", "0.46",
             "--rationale", "r",
             *_args(tmp_path)],
        )
        assert result.exit_code == 0, result.output


# ===========================================================================
# update-assumption
# ===========================================================================


class TestUpdateAssumption:
    def test_revises_value_and_bumps_version(self, tmp_path: Path):
        _init(tmp_path)
        slug = _new_episode(tmp_path)
        _add_assumption(tmp_path, "AAPL", slug)

        result = runner.invoke(
            app,
            ["update-assumption", "AAPL", slug, "services_cagr",
             "--new-value", "0.15",
             "--reason", "Q1 beat confirmed acceleration",
             "--confidence", "0.8",
             *_args(tmp_path)],
        )
        assert result.exit_code == 0, result.output

        layout = CompanyLayout(tmp_path, "AAPL")
        ep = load_episode(layout, slug)
        a = next(x for x in ep.assumptions if x.key == "services_cagr")
        assert a.value == 0.15
        assert a.version == 2
        assert a.confidence == 0.8

    def test_creates_change_record_in_episode(self, tmp_path: Path):
        _init(tmp_path)
        slug = _new_episode(tmp_path)
        _add_assumption(tmp_path, "AAPL", slug)
        runner.invoke(
            app,
            ["update-assumption", "AAPL", slug, "services_cagr",
             "--new-value", "0.15", "--reason", "R", *_args(tmp_path)],
        )

        layout = CompanyLayout(tmp_path, "AAPL")
        ep = load_episode(layout, slug)
        a = next(x for x in ep.assumptions if x.key == "services_cagr")
        assert len(a.history) == 1
        assert a.history[0].previous_value == 0.13
        assert a.history[0].new_value == 0.15

    def test_appends_to_jsonl_changes_file(self, tmp_path: Path):
        _init(tmp_path)
        slug = _new_episode(tmp_path)
        _add_assumption(tmp_path, "AAPL", slug)
        # Two revisions
        for val in ["0.15", "0.17"]:
            runner.invoke(
                app,
                ["update-assumption", "AAPL", slug, "services_cagr",
                 "--new-value", val, "--reason", "R", *_args(tmp_path)],
            )

        layout = CompanyLayout(tmp_path, "AAPL")
        changes = read_jsonl(layout.assumption_changes(slug, "services_cagr"), AssumptionChange)
        assert len(changes) == 2
        assert changes[0].new_value == 0.15
        assert changes[1].new_value == 0.17

    def test_writes_new_versioned_file(self, tmp_path: Path):
        _init(tmp_path)
        slug = _new_episode(tmp_path)
        _add_assumption(tmp_path, "AAPL", slug)
        runner.invoke(
            app,
            ["update-assumption", "AAPL", slug, "services_cagr",
             "--new-value", "0.15", "--reason", "R", *_args(tmp_path)],
        )

        layout = CompanyLayout(tmp_path, "AAPL")
        assert layout.assumption_json(slug, "services_cagr", 1).exists()
        assert layout.assumption_json(slug, "services_cagr", 2).exists()
        v2 = AssumptionRecord.model_validate_json(
            layout.assumption_json(slug, "services_cagr", 2).read_text()
        )
        assert v2.version == 2
        assert v2.value == 0.15

    def test_nonexistent_key_fails(self, tmp_path: Path):
        _init(tmp_path)
        slug = _new_episode(tmp_path)
        _add_assumption(tmp_path, "AAPL", slug)
        result = runner.invoke(
            app,
            ["update-assumption", "AAPL", slug, "nonexistent_key",
             "--new-value", "0.5", "--reason", "R", *_args(tmp_path)],
        )
        assert result.exit_code == 1
        assert "No active assumption" in result.output

    def test_history_preserved_after_multiple_revisions(self, tmp_path: Path):
        _init(tmp_path)
        slug = _new_episode(tmp_path)
        _add_assumption(tmp_path, "AAPL", slug)
        for val, reason in [("0.14", "R1"), ("0.15", "R2"), ("0.16", "R3")]:
            runner.invoke(
                app,
                ["update-assumption", "AAPL", slug, "services_cagr",
                 "--new-value", val, "--reason", reason, *_args(tmp_path)],
            )

        layout = CompanyLayout(tmp_path, "AAPL")
        ep = load_episode(layout, slug)
        a = next(x for x in ep.assumptions if x.key == "services_cagr")
        assert a.version == 4
        assert len(a.history) == 3
        assert a.history[0].reason == "R1"
        assert a.history[2].reason == "R3"


# ===========================================================================
# list-assumptions
# ===========================================================================


class TestListAssumptions:
    def test_lists_active_assumptions(self, tmp_path: Path):
        _init(tmp_path)
        slug = _new_episode(tmp_path)
        _add_assumption(tmp_path, "AAPL", slug, key="services_cagr")
        _add_assumption(tmp_path, "AAPL", slug, key="margin")

        result = runner.invoke(
            app, ["list-assumptions", "AAPL", slug, *_args(tmp_path)]
        )
        assert result.exit_code == 0
        # Rich truncates "services_cagr" → "servic…" at narrow terminal widths
        assert "servic" in result.output
        assert "margin" in result.output

    def test_empty_episode_message(self, tmp_path: Path):
        _init(tmp_path)
        slug = _new_episode(tmp_path)
        result = runner.invoke(
            app, ["list-assumptions", "AAPL", slug, *_args(tmp_path)]
        )
        assert result.exit_code == 0
        assert "No assumptions" in result.output


# ===========================================================================
# log-prediction
# ===========================================================================


class TestLogPrediction:
    def test_adds_prediction_to_episode(self, tmp_path: Path):
        _init(tmp_path)
        slug = _new_episode(tmp_path)
        _log_prediction(tmp_path, "AAPL", slug)

        layout = CompanyLayout(tmp_path, "AAPL")
        ep = load_episode(layout, slug)
        assert len(ep.predictions) == 1
        p = ep.predictions[0]
        assert p.metric == "aapl_services_revenue"
        assert p.threshold == 110
        assert p.materiality == MaterialityLevel.HIGH
        assert not p.is_resolved

    def test_writes_prediction_artifact(self, tmp_path: Path):
        _init(tmp_path)
        slug = _new_episode(tmp_path)
        _log_prediction(tmp_path, "AAPL", slug)

        layout = CompanyLayout(tmp_path, "AAPL")
        ep = load_episode(layout, slug)
        pred_id = ep.predictions[0].id
        pred_path = layout.prediction_json(slug, "aapl_services_revenue", pred_id)
        assert pred_path.exists()
        p = PredictionRecord.model_validate_json(pred_path.read_text())
        assert p.metric == "aapl_services_revenue"

    def test_duplicate_metric_fails(self, tmp_path: Path):
        _init(tmp_path)
        slug = _new_episode(tmp_path)
        _log_prediction(tmp_path, "AAPL", slug)
        result = runner.invoke(
            app,
            ["log-prediction", "AAPL", slug,
             "--metric", "aapl_services_revenue",
             "--description", "Dup",
             "--threshold", "100",
             "--horizon", "FY2026",
             "--due-date", "2026-11-01",
             *_args(tmp_path)],
        )
        assert result.exit_code == 1
        assert "already exists" in result.output

    def test_updates_episode_md(self, tmp_path: Path):
        _init(tmp_path)
        slug = _new_episode(tmp_path)
        _log_prediction(tmp_path, "AAPL", slug)

        layout = CompanyLayout(tmp_path, "AAPL")
        md = layout.episode_md(slug).read_text()
        assert "aapl_services_revenue" in md


# ===========================================================================
# resolve-prediction
# ===========================================================================


class TestResolvePrediction:
    def test_resolves_prediction_correct(self, tmp_path: Path):
        _init(tmp_path)
        slug = _new_episode(tmp_path)
        _log_prediction(tmp_path, "AAPL", slug)

        result = runner.invoke(
            app,
            ["resolve-prediction", "AAPL", slug, "aapl_services_revenue",
             "--status", "CORRECT",
             "--actual", "112.5",
             "--notes", "Beat by $2.5B",
             *_args(tmp_path)],
        )
        assert result.exit_code == 0, result.output
        assert "CORRECT" in result.output

    def test_resolution_embedded_in_episode(self, tmp_path: Path):
        _init(tmp_path)
        slug = _new_episode(tmp_path)
        _log_prediction(tmp_path, "AAPL", slug)
        runner.invoke(
            app,
            ["resolve-prediction", "AAPL", slug, "aapl_services_revenue",
             "--status", "CORRECT", "--actual", "112.5", "--notes", "N",
             *_args(tmp_path)],
        )

        layout = CompanyLayout(tmp_path, "AAPL")
        ep = load_episode(layout, slug)
        p = ep.predictions[0]
        assert p.is_resolved
        assert p.resolution.resolved_status.value == "CORRECT"
        assert p.resolution.actual_outcome == 112.5

    def test_writes_resolution_artifact(self, tmp_path: Path):
        _init(tmp_path)
        slug = _new_episode(tmp_path)
        _log_prediction(tmp_path, "AAPL", slug)
        runner.invoke(
            app,
            ["resolve-prediction", "AAPL", slug, "aapl_services_revenue",
             "--status", "INCORRECT", "--actual", "98", "--notes", "N",
             *_args(tmp_path)],
        )

        layout = CompanyLayout(tmp_path, "AAPL")
        ep = load_episode(layout, slug)
        pred_id = ep.predictions[0].id
        res_path = layout.resolution_json(slug, "aapl_services_revenue", pred_id)
        assert res_path.exists()
        r = ResolutionRecord.model_validate_json(res_path.read_text())
        assert r.resolved_status.value == "INCORRECT"

    def test_double_resolve_fails(self, tmp_path: Path):
        _init(tmp_path)
        slug = _new_episode(tmp_path)
        _log_prediction(tmp_path, "AAPL", slug)
        runner.invoke(
            app,
            ["resolve-prediction", "AAPL", slug, "aapl_services_revenue",
             "--status", "CORRECT", "--actual", "112", "--notes", "N",
             *_args(tmp_path)],
        )
        result = runner.invoke(
            app,
            ["resolve-prediction", "AAPL", slug, "aapl_services_revenue",
             "--status", "INCORRECT", "--actual", "90", "--notes", "Again",
             *_args(tmp_path)],
        )
        assert result.exit_code == 1
        assert "already resolved" in result.output

    def test_error_magnitude_calculated(self, tmp_path: Path):
        _init(tmp_path)
        slug = _new_episode(tmp_path)
        _log_prediction(tmp_path, "AAPL", slug)
        runner.invoke(
            app,
            ["resolve-prediction", "AAPL", slug, "aapl_services_revenue",
             "--status", "INCORRECT", "--actual", "99", "--notes", "Missed",
             *_args(tmp_path)],
        )
        layout = CompanyLayout(tmp_path, "AAPL")
        ep = load_episode(layout, slug)
        p = ep.predictions[0]
        # (99 - 110) / 110 ≈ -0.1
        assert p.resolution.error_magnitude == pytest.approx((99 - 110) / 110)


# ===========================================================================
# render-company-summary
# ===========================================================================


class TestRenderCompanySummary:
    def test_writes_dossier_md(self, tmp_path: Path):
        _init(tmp_path)
        _new_episode(tmp_path)
        result = runner.invoke(
            app, ["render-company-summary", "AAPL", *_args(tmp_path)]
        )
        assert result.exit_code == 0, result.output

        layout = CompanyLayout(tmp_path, "AAPL")
        assert layout.dossier_md.exists()
        md = layout.dossier_md.read_text()
        assert "Apple Inc." in md
        assert "FY2026 Initiation" in md

    def test_summary_includes_episode_data(self, tmp_path: Path):
        _init(tmp_path)
        slug = _new_episode(tmp_path)
        _add_assumption(tmp_path, "AAPL", slug)
        _log_prediction(tmp_path, "AAPL", slug)
        runner.invoke(app, ["render-company-summary", "AAPL", *_args(tmp_path)])

        layout = CompanyLayout(tmp_path, "AAPL")
        md = layout.dossier_md.read_text()
        assert "1 active" in md
        assert "1 pending" in md

    def test_uninitialised_fails(self, tmp_path: Path):
        result = runner.invoke(
            app, ["render-company-summary", "FAKE", *_args(tmp_path)]
        )
        assert result.exit_code == 1

    def test_full_dossier_assembles_episodes(self, tmp_path: Path):
        _init(tmp_path)
        _new_episode(tmp_path)
        layout = CompanyLayout(tmp_path, "AAPL")
        full = load_full_dossier(layout)
        assert len(full.episodes) == 1
        assert full.episodes[0].title == "FY2026 Initiation"


# ===========================================================================
# Cross-command: file naming determinism
# ===========================================================================


class TestDeterministicNaming:
    def test_assumption_v1_file_name(self, tmp_path: Path):
        _init(tmp_path)
        slug = _new_episode(tmp_path)
        _add_assumption(tmp_path, "AAPL", slug, key="services_cagr")
        layout = CompanyLayout(tmp_path, "AAPL")
        v1 = layout.assumption_json(slug, "services_cagr", 1)
        assert v1.name == "services_cagr_v001.json"

    def test_assumption_v2_file_name(self, tmp_path: Path):
        _init(tmp_path)
        slug = _new_episode(tmp_path)
        _add_assumption(tmp_path, "AAPL", slug)
        runner.invoke(
            app,
            ["update-assumption", "AAPL", slug, "services_cagr",
             "--new-value", "0.15", "--reason", "R", *_args(tmp_path)],
        )
        layout = CompanyLayout(tmp_path, "AAPL")
        v2 = layout.assumption_json(slug, "services_cagr", 2)
        assert v2.name == "services_cagr_v002.json"
        assert v2.exists()

    def test_prediction_file_name_contains_metric(self, tmp_path: Path):
        _init(tmp_path)
        slug = _new_episode(tmp_path)
        _log_prediction(tmp_path, "AAPL", slug)
        layout = CompanyLayout(tmp_path, "AAPL")
        pred_files = list(layout.predictions_dir(slug).iterdir())
        assert len(pred_files) == 1
        assert "aapl-services-revenue" in pred_files[0].name

    def test_resolution_file_name_contains_metric(self, tmp_path: Path):
        _init(tmp_path)
        slug = _new_episode(tmp_path)
        _log_prediction(tmp_path, "AAPL", slug)
        runner.invoke(
            app,
            ["resolve-prediction", "AAPL", slug, "aapl_services_revenue",
             "--status", "CORRECT", "--actual", "115", "--notes", "N",
             *_args(tmp_path)],
        )
        layout = CompanyLayout(tmp_path, "AAPL")
        res_files = list(layout.resolutions_dir(slug).iterdir())
        assert len(res_files) == 1
        assert "aapl-services-revenue" in res_files[0].name
        assert "_resolution.json" in res_files[0].name
