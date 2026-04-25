"""Filesystem state management — never overwrites prior state."""

from __future__ import annotations

import json
import shutil
from datetime import datetime
from pathlib import Path
from typing import Iterator

from .schemas import Company, Episode

# Each company lives at <data_root>/<TICKER>/
# Current state:  <TICKER>/company.json
# Snapshots:      <TICKER>/snapshots/<iso-timestamp>.json


def _now_iso() -> str:
    return datetime.utcnow().strftime("%Y%m%dT%H%M%S_%fZ")


class CompanyStore:
    def __init__(self, data_root: Path) -> None:
        self.root = data_root
        self.root.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # Paths
    # ------------------------------------------------------------------

    def company_dir(self, ticker: str) -> Path:
        return self.root / ticker.upper()

    def _state_path(self, ticker: str) -> Path:
        return self.company_dir(ticker) / "company.json"

    def _snapshots_dir(self, ticker: str) -> Path:
        return self.company_dir(ticker) / "snapshots"

    # ------------------------------------------------------------------
    # Read
    # ------------------------------------------------------------------

    def exists(self, ticker: str) -> bool:
        return self._state_path(ticker).exists()

    def load(self, ticker: str) -> Company:
        path = self._state_path(ticker)
        if not path.exists():
            raise FileNotFoundError(f"No coverage found for {ticker!r}")
        return Company.model_validate_json(path.read_text())

    def all_tickers(self) -> list[str]:
        return sorted(
            d.name for d in self.root.iterdir() if d.is_dir() and not d.name.startswith(".")
        )

    # ------------------------------------------------------------------
    # Write (always snapshot before overwriting)
    # ------------------------------------------------------------------

    def _snapshot(self, ticker: str) -> None:
        """Copy current state to snapshots/ before saving a new version."""
        state_path = self._state_path(ticker)
        if not state_path.exists():
            return
        snap_dir = self._snapshots_dir(ticker)
        snap_dir.mkdir(parents=True, exist_ok=True)
        dest = snap_dir / f"{_now_iso()}.json"
        shutil.copy2(state_path, dest)

    def save(self, company: Company) -> Path:
        ticker = company.ticker.upper()
        cdir = self.company_dir(ticker)
        cdir.mkdir(parents=True, exist_ok=True)
        self._snapshot(ticker)
        company.updated_at = datetime.utcnow()
        path = self._state_path(ticker)
        path.write_text(company.model_dump_json(indent=2))
        return path

    def create(self, company: Company) -> Path:
        if self.exists(company.ticker):
            raise ValueError(f"{company.ticker!r} already exists. Use save() to update.")
        return self.save(company)

    # ------------------------------------------------------------------
    # Snapshots
    # ------------------------------------------------------------------

    def list_snapshots(self, ticker: str) -> list[Path]:
        snap_dir = self._snapshots_dir(ticker)
        if not snap_dir.exists():
            return []
        return sorted(snap_dir.glob("*.json"))

    def load_snapshot(self, ticker: str, timestamp: str) -> Company:
        snap_dir = self._snapshots_dir(ticker)
        path = snap_dir / f"{timestamp}.json"
        if not path.exists():
            raise FileNotFoundError(f"Snapshot {timestamp!r} not found for {ticker!r}")
        return Company.model_validate_json(path.read_text())
