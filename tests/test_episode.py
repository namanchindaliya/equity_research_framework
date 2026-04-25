"""Episode business-logic tests."""

from __future__ import annotations

import pytest

from equity_os.episode import (
    add_assumption,
    add_prediction,
    close_episode,
    open_episode,
    resolve_prediction,
    revise_assumption,
)
from equity_os.schemas import (
    AssumptionStatus,
    Company,
    EpisodeStatus,
    PredictionOutcome,
    Rating,
)
from equity_os.store import CompanyStore


def test_open_episode(store: CompanyStore, apple: Company):
    ep = open_episode(store, "AAPL", "Q1 thesis", "Services growth.", Rating.BUY, 210.0)
    assert ep.status == EpisodeStatus.OPEN
    assert ep.rating == Rating.BUY
    company = store.load("AAPL")
    assert len(company.episodes) == 1
    assert company.current_rating == Rating.BUY
    assert company.current_price_target == 210.0


def test_close_episode(store: CompanyStore, apple: Company):
    ep = open_episode(store, "AAPL", "Q1 thesis", "Services growth.", Rating.BUY)
    closed = close_episode(store, "AAPL", ep.id, "Thesis played out.")
    assert closed.status == EpisodeStatus.CLOSED
    assert closed.close_note == "Thesis played out."


def test_close_already_closed_raises(store: CompanyStore, apple: Company):
    ep = open_episode(store, "AAPL", "Q1 thesis", "Services growth.", Rating.BUY)
    close_episode(store, "AAPL", ep.id, "Done.")
    with pytest.raises(ValueError, match="already closed"):
        close_episode(store, "AAPL", ep.id, "Again.")


def test_add_and_revise_assumption(store: CompanyStore, apple: Company):
    ep = open_episode(store, "AAPL", "Q1 thesis", "Services growth.", Rating.BUY)
    a = add_assumption(store, "AAPL", ep.id, "rev_growth", 0.12, "Base case", "%")
    revised = revise_assumption(store, "AAPL", ep.id, a.id, 0.15, "Raised post Q1", "%")
    assert revised.revised_from == a.id
    assert revised.value == 0.15

    company = store.load("AAPL")
    ep_loaded = company.episodes[0]
    old = next(x for x in ep_loaded.assumptions if x.id == a.id)
    assert old.status == AssumptionStatus.REVISED


def test_add_prediction(store: CompanyStore, apple: Company):
    ep = open_episode(store, "AAPL", "Q1 thesis", "Services growth.", Rating.BUY)
    p = add_prediction(store, "AAPL", ep.id, "Revenue > $100B", "revenue", 100, "FY2026", "B USD")
    assert p.outcome == PredictionOutcome.PENDING
    company = store.load("AAPL")
    assert len(company.episodes[0].predictions) == 1


def test_resolve_prediction(store: CompanyStore, apple: Company):
    ep = open_episode(store, "AAPL", "Q1 thesis", "Services growth.", Rating.BUY)
    p = add_prediction(store, "AAPL", ep.id, "Revenue > $100B", "revenue", 100, "FY2026", "B USD")
    resolved = resolve_prediction(
        store, "AAPL", ep.id, p.id, PredictionOutcome.CORRECT, 105.5, "Beat by 5.5B"
    )
    assert resolved.outcome == PredictionOutcome.CORRECT
    assert resolved.actual_value == 105.5


def test_resolve_already_resolved_raises(store: CompanyStore, apple: Company):
    ep = open_episode(store, "AAPL", "Q1 thesis", "Services growth.", Rating.BUY)
    p = add_prediction(store, "AAPL", ep.id, "Revenue > $100B", "revenue", 100, "FY2026")
    resolve_prediction(store, "AAPL", ep.id, p.id, PredictionOutcome.CORRECT, 105, "Beat.")
    with pytest.raises(ValueError, match="already resolved"):
        resolve_prediction(store, "AAPL", ep.id, p.id, PredictionOutcome.INCORRECT, 95, "Wait.")


def test_episode_state_persisted_across_loads(store: CompanyStore, apple: Company):
    ep = open_episode(store, "AAPL", "Q1 thesis", "Services growth.", Rating.BUY)
    add_assumption(store, "AAPL", ep.id, "margin", 0.30, "Stable margins", "%")
    add_prediction(store, "AAPL", ep.id, "EPS > $7", "eps", 7, "FY2026Q2")

    company = store.load("AAPL")
    ep2 = company.episodes[0]
    assert len(ep2.assumptions) == 1
    assert len(ep2.predictions) == 1
