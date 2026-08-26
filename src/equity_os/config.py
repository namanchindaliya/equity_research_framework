"""Typed EQOS configuration loaded from TOML files."""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

from pydantic import BaseModel, Field


DEFAULT_FORMS = [
    "10-K",
    "10-K/A",
    "10-Q",
    "10-Q/A",
    "8-K",
    "8-K/A",
    "6-K",
    "6-K/A",
    "20-F",
    "20-F/A",
    "DEF 14A",
]
DEFAULT_EIGHT_K_ITEMS = ["2.02", "4.02", "5.02", "7.01", "8.01"]


class SecConfig(BaseModel):
    enabled: bool = True
    user_agent_name: str
    contact_email: str
    requests_per_second: float = Field(default=3.0, gt=0.0, le=10.0)
    timeout_seconds: float = Field(default=30.0, gt=0.0, le=120.0)
    max_retries: int = Field(default=4, ge=0, le=8)
    forms: list[str] = Field(default_factory=lambda: list(DEFAULT_FORMS))
    eight_k_items: list[str] = Field(
        default_factory=lambda: list(DEFAULT_EIGHT_K_ITEMS)
    )
    exhibit_type_prefixes: list[str] = Field(default_factory=lambda: ["EX-99"])
    max_filings_per_sync: int = Field(default=50, ge=1, le=500)

    @property
    def user_agent(self) -> str:
        return f"{self.user_agent_name.strip()} {self.contact_email.strip()}"

    def validate_for_access(self) -> None:
        """Fail closed when SEC identification is missing or still placeholder text."""
        name = self.user_agent_name.strip()
        email = self.contact_email.strip().lower()
        if not name or name.lower() in {"your name", "your organization", "eqos"}:
            raise ValueError("sec.user_agent_name must identify the operator.")
        if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email):
            raise ValueError("sec.contact_email must be a valid contact email.")
        if email.endswith("@example.com") or email.endswith(".invalid"):
            raise ValueError(
                "sec.contact_email is still a placeholder; use a real contact email."
            )


class SyncConfig(BaseModel):
    default_since_days: int = Field(default=730, ge=1, le=36500)
    store_raw_documents: bool = True
    auto_create_episode: bool = False
    evaluate_monitoring_triggers: bool = True


class WatchlistConfig(BaseModel):
    tickers: list[str] = Field(default_factory=list)

    def normalized_tickers(self) -> list[str]:
        return list(dict.fromkeys(t.strip().upper() for t in self.tickers if t.strip()))


class StorageConfig(BaseModel):
    companies_dir: Path = Path("companies")
    raw_documents_dir: str = "raw"


class EqosConfig(BaseModel):
    sec: SecConfig
    sync: SyncConfig = Field(default_factory=SyncConfig)
    watchlist: WatchlistConfig = Field(default_factory=WatchlistConfig)
    storage: StorageConfig = Field(default_factory=StorageConfig)

    def validate_for_sec_access(self) -> None:
        if not self.sec.enabled:
            raise ValueError("SEC access is disabled in the configuration.")
        self.sec.validate_for_access()


def config_candidates(cwd: Path | None = None, home: Path | None = None) -> list[Path]:
    base = cwd or Path.cwd()
    home_dir = home or Path.home()
    return [
        base / "config" / "eqos.toml",
        home_dir / ".config" / "eqos" / "config.toml",
    ]


def resolve_config_path(path: Path | None = None) -> Path:
    if path is not None:
        resolved = path.expanduser()
        if not resolved.exists():
            raise FileNotFoundError(f"Configuration file not found: {resolved}")
        return resolved
    for candidate in config_candidates():
        if candidate.exists():
            return candidate
    checked = ", ".join(str(p) for p in config_candidates())
    raise FileNotFoundError(
        f"No EQOS configuration found. Checked: {checked}. "
        "Copy config/eqos.example.toml to config/eqos.toml."
    )


def load_config(path: Path | None = None) -> EqosConfig:
    resolved = resolve_config_path(path)
    with resolved.open("rb") as handle:
        payload = tomllib.load(handle)
    return EqosConfig.model_validate(payload)
