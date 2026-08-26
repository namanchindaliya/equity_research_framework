"""Tests for TOML configuration and SEC access validation."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from equity_os.config import EqosConfig, config_candidates, load_config


def _write_config(path: Path, *, email: str = "operator@research.org") -> Path:
    path.write_text(
        f"""
[sec]
enabled = true
user_agent_name = "Research Operator"
contact_email = "{email}"
requests_per_second = 3
forms = ["10-Q", "8-K"]
eight_k_items = ["2.02", "8.01"]

[watchlist]
tickers = ["aapl", "MSFT", "AAPL", ""]

[storage]
companies_dir = "coverage"
""".strip(),
        encoding="utf-8",
    )
    return path


def test_load_config_and_normalize_watchlist(tmp_path: Path) -> None:
    config = load_config(_write_config(tmp_path / "eqos.toml"))

    config.validate_for_sec_access()
    assert config.sec.user_agent == "Research Operator operator@research.org"
    assert config.watchlist.normalized_tickers() == ["AAPL", "MSFT"]
    assert config.storage.companies_dir == Path("coverage")


def test_placeholder_contact_fails_closed(tmp_path: Path) -> None:
    config = load_config(
        _write_config(tmp_path / "eqos.toml", email="your-email@example.com")
    )

    with pytest.raises(ValueError, match="placeholder"):
        config.validate_for_sec_access()


def test_sec_rate_above_public_limit_is_rejected() -> None:
    with pytest.raises(ValidationError):
        EqosConfig.model_validate(
            {
                "sec": {
                    "user_agent_name": "Research Operator",
                    "contact_email": "operator@research.org",
                    "requests_per_second": 10.1,
                }
            }
        )


def test_config_candidates_prefer_repo_local_file(tmp_path: Path) -> None:
    candidates = config_candidates(cwd=tmp_path / "repo", home=tmp_path / "home")

    assert candidates[0] == tmp_path / "repo" / "config" / "eqos.toml"
    assert candidates[1] == tmp_path / "home" / ".config" / "eqos" / "config.toml"
