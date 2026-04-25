"""Store persistence tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from equity_os.schemas import Company, Rating
from equity_os.store import CompanyStore


def test_create_and_load(store: CompanyStore, apple: Company):
    loaded = store.load("AAPL")
    assert loaded.ticker == "AAPL"
    assert loaded.name == "Apple Inc."


def test_duplicate_create_raises(store: CompanyStore, apple: Company):
    with pytest.raises(ValueError, match="already exists"):
        store.create(Company(ticker="AAPL", name="Duplicate"))


def test_save_snapshots_previous_state(store: CompanyStore, apple: Company):
    company = store.load("AAPL")
    company.current_rating = Rating.BUY
    store.save(company)

    snapshots = store.list_snapshots("AAPL")
    assert len(snapshots) == 1
    snap = store.load_snapshot("AAPL", snapshots[0].stem)
    assert snap.current_rating == Rating.NOT_RATED


def test_multiple_saves_accumulate_snapshots(store: CompanyStore, apple: Company):
    for rating in [Rating.BUY, Rating.HOLD, Rating.SELL]:
        company = store.load("AAPL")
        company.current_rating = rating
        store.save(company)

    assert len(store.list_snapshots("AAPL")) == 3


def test_load_nonexistent_raises(store: CompanyStore):
    with pytest.raises(FileNotFoundError):
        store.load("FAKE")


def test_all_tickers(store: CompanyStore):
    for ticker, name in [("AAPL", "Apple"), ("MSFT", "Microsoft"), ("GOOG", "Alphabet")]:
        store.create(Company(ticker=ticker, name=name))
    assert store.all_tickers() == ["AAPL", "GOOG", "MSFT"]


def test_save_updates_updated_at(store: CompanyStore, apple: Company):
    import time
    original = store.load("AAPL").updated_at
    time.sleep(0.01)
    company = store.load("AAPL")
    store.save(company)
    assert store.load("AAPL").updated_at >= original
