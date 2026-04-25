"""Shared fixtures."""

from __future__ import annotations

from pathlib import Path

import pytest

from equity_os.schemas import Company
from equity_os.store import CompanyStore


@pytest.fixture()
def data_dir(tmp_path: Path) -> Path:
    return tmp_path / "equity_os_data"


@pytest.fixture()
def store(data_dir: Path) -> CompanyStore:
    return CompanyStore(data_dir)


@pytest.fixture()
def apple(store: CompanyStore) -> Company:
    company = Company(
        ticker="AAPL",
        name="Apple Inc.",
        sector="Technology",
        industry="Consumer Electronics",
        description="Designs and sells consumer electronics.",
    )
    store.create(company)
    return company
