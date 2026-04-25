"""CLI integration tests using typer's test runner."""

from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from equity_os.cli import app
from equity_os.schemas import Company
from equity_os.store import CompanyStore

runner = CliRunner()


def _data_dir_args(tmp_path: Path) -> list[str]:
    return ["--data-dir", str(tmp_path / "data")]


def test_init_company(tmp_path: Path):
    result = runner.invoke(
        app, ["init", "AAPL", "--name", "Apple Inc.", "--sector", "Technology", *_data_dir_args(tmp_path)]
    )
    assert result.exit_code == 0, result.output
    assert "AAPL" in result.output


def test_init_duplicate_fails(tmp_path: Path):
    args = ["init", "AAPL", "--name", "Apple Inc.", *_data_dir_args(tmp_path)]
    runner.invoke(app, args)
    result = runner.invoke(app, args)
    assert result.exit_code == 1
    assert "already exists" in result.output


def test_show_company(tmp_path: Path):
    runner.invoke(app, ["init", "TSLA", "--name", "Tesla Inc.", *_data_dir_args(tmp_path)])
    result = runner.invoke(app, ["show", "TSLA", *_data_dir_args(tmp_path)])
    assert result.exit_code == 0, result.output
    assert "Tesla" in result.output


def test_show_nonexistent_exits_1(tmp_path: Path):
    result = runner.invoke(app, ["show", "FAKE", *_data_dir_args(tmp_path)])
    assert result.exit_code == 1


def test_list_companies(tmp_path: Path):
    for ticker, name in [("AAPL", "Apple"), ("MSFT", "Microsoft")]:
        runner.invoke(app, ["init", ticker, "--name", name, *_data_dir_args(tmp_path)])
    result = runner.invoke(app, ["list-companies", *_data_dir_args(tmp_path)])
    assert result.exit_code == 0
    assert "AAPL" in result.output
    assert "MSFT" in result.output


def test_episode_new_and_show(tmp_path: Path):
    runner.invoke(app, ["init", "AAPL", "--name", "Apple Inc.", *_data_dir_args(tmp_path)])
    result = runner.invoke(
        app,
        [
            "episode", "new", "AAPL",
            "--title", "Q1 2026 Thesis",
            "--thesis", "Services growth drives upside.",
            "--rating", "BUY",
            "--pt", "210.0",
            *_data_dir_args(tmp_path),
        ],
    )
    assert result.exit_code == 0, result.output
    assert "Episode opened" in result.output

    ep_id = result.output.split("ID: ")[1].strip()
    result2 = runner.invoke(app, ["episode", "show", "AAPL", ep_id[:8], *_data_dir_args(tmp_path)])
    assert result2.exit_code == 0
    assert "Q1 2026 Thesis" in result2.output


def test_episode_close(tmp_path: Path):
    runner.invoke(app, ["init", "AAPL", "--name", "Apple Inc.", *_data_dir_args(tmp_path)])
    r = runner.invoke(
        app,
        ["episode", "new", "AAPL", "--title", "T", "--thesis", "X", "--rating", "BUY", *_data_dir_args(tmp_path)],
    )
    ep_id = r.output.split("ID: ")[1].strip()
    result = runner.invoke(
        app, ["episode", "close", "AAPL", ep_id[:8], "--note", "Done.", *_data_dir_args(tmp_path)]
    )
    assert result.exit_code == 0
    assert "Episode closed" in result.output


def test_assumption_add(tmp_path: Path):
    runner.invoke(app, ["init", "AAPL", "--name", "Apple Inc.", *_data_dir_args(tmp_path)])
    r = runner.invoke(
        app,
        ["episode", "new", "AAPL", "--title", "T", "--thesis", "X", "--rating", "BUY", *_data_dir_args(tmp_path)],
    )
    ep_id = r.output.split("ID: ")[1].strip()
    result = runner.invoke(
        app,
        [
            "assumption", "add", "AAPL", ep_id[:8],
            "--key", "rev_growth",
            "--value", "0.12",
            "--rationale", "Base case",
            "--unit", "%",
            *_data_dir_args(tmp_path),
        ],
    )
    assert result.exit_code == 0, result.output
    assert "Assumption added" in result.output


def test_prediction_add_and_resolve(tmp_path: Path):
    runner.invoke(app, ["init", "AAPL", "--name", "Apple Inc.", *_data_dir_args(tmp_path)])
    r = runner.invoke(
        app,
        ["episode", "new", "AAPL", "--title", "T", "--thesis", "X", "--rating", "BUY", *_data_dir_args(tmp_path)],
    )
    ep_id = r.output.split("ID: ")[1].strip()

    r2 = runner.invoke(
        app,
        [
            "prediction", "add", "AAPL", ep_id[:8],
            "--description", "Revenue > 100B",
            "--metric", "revenue",
            "--target", "100",
            "--horizon", "FY2026",
            "--unit", "B USD",
            *_data_dir_args(tmp_path),
        ],
    )
    assert r2.exit_code == 0, r2.output
    pred_id = r2.output.split("ID: ")[1].strip()

    r3 = runner.invoke(
        app,
        [
            "prediction", "resolve", "AAPL", ep_id[:8], pred_id[:8],
            "--outcome", "CORRECT",
            "--actual", "105.5",
            "--note", "Beat by 5.5B",
            *_data_dir_args(tmp_path),
        ],
    )
    assert r3.exit_code == 0, r3.output
    assert "CORRECT" in r3.output


def test_report_markdown(tmp_path: Path):
    runner.invoke(app, ["init", "AAPL", "--name", "Apple Inc.", *_data_dir_args(tmp_path)])
    runner.invoke(
        app,
        ["episode", "new", "AAPL", "--title", "T", "--thesis", "Services growth.", "--rating", "BUY", *_data_dir_args(tmp_path)],
    )
    result = runner.invoke(app, ["report", "AAPL", *_data_dir_args(tmp_path)])
    assert result.exit_code == 0
    assert "# Apple Inc." in result.output
    assert "BUY" in result.output
