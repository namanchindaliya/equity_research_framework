"""CLI tests for SEC configuration and synchronization commands."""

from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from equity_os.connectors.sec_edgar import SecSyncResult
from equity_os.v1_cli import app


runner = CliRunner()


def _config(path: Path, *, email: str = "operator@research.org") -> Path:
    path.write_text(
        f"""
[sec]
user_agent_name = "Research Operator"
contact_email = "{email}"

[watchlist]
tickers = ["AAPL", "MSFT"]
""".strip(),
        encoding="utf-8",
    )
    return path


def test_config_check_validates_without_printing_contact_email(tmp_path: Path) -> None:
    config_path = _config(tmp_path / "eqos.toml")

    result = runner.invoke(app, ["config-check", "--config", str(config_path)])

    assert result.exit_code == 0, result.output
    assert "Configuration valid" in result.output
    assert "operator@research.org" not in result.output


def test_config_check_rejects_placeholder(tmp_path: Path) -> None:
    config_path = _config(tmp_path / "eqos.toml", email="you@example.com")

    result = runner.invoke(app, ["config-check", "--config", str(config_path)])

    assert result.exit_code == 1
    assert "placeholder" in result.output


def test_sync_sec_uses_configured_connector(monkeypatch, tmp_path: Path) -> None:
    config_path = _config(tmp_path / "eqos.toml")
    calls: list[tuple[str, Path]] = []

    def fake_sync(config, ticker, companies_root, *, since=None):
        calls.append((ticker, companies_root))
        return SecSyncResult(
            ticker=ticker.upper(),
            cik="0000320193",
            discovered_filings=1,
            discovered_documents=2,
            ingested_documents=2,
        )

    monkeypatch.setattr("equity_os.connectors.sec_edgar.sync_ticker", fake_sync)
    result = runner.invoke(
        app,
        [
            "sync-sec",
            "aapl",
            "--config",
            str(config_path),
            "--companies-dir",
            str(tmp_path / "companies"),
        ],
    )

    assert result.exit_code == 0, result.output
    assert "Documents ingested: 2" in result.output
    assert calls == [("aapl", tmp_path / "companies")]


def test_watchlist_sync_processes_every_ticker(monkeypatch, tmp_path: Path) -> None:
    config_path = _config(tmp_path / "eqos.toml")
    calls: list[str] = []

    def fake_sync(config, ticker, companies_root, *, since=None):
        calls.append(ticker)
        return SecSyncResult(ticker=ticker, cik="1", discovered_filings=1)

    monkeypatch.setattr("equity_os.connectors.sec_edgar.sync_ticker", fake_sync)
    result = runner.invoke(
        app, ["sync-sec-watchlist", "--config", str(config_path)]
    )

    assert result.exit_code == 0, result.output
    assert calls == ["AAPL", "MSFT"]
