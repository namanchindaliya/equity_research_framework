"""Schema validation tests."""

from __future__ import annotations

import json
from datetime import datetime
from uuid import uuid4

import pytest
from pydantic import ValidationError

from equity_os.schemas import (
    Assumption,
    AssumptionStatus,
    Company,
    Episode,
    EpisodeStatus,
    Prediction,
    PredictionOutcome,
    Rating,
)


def test_company_defaults():
    c = Company(ticker="TSLA", name="Tesla Inc.")
    assert c.ticker == "TSLA"
    assert c.current_rating == Rating.NOT_RATED
    assert c.episodes == []


def test_company_round_trip_json():
    c = Company(ticker="MSFT", name="Microsoft Corporation", sector="Technology")
    raw = c.model_dump_json()
    c2 = Company.model_validate_json(raw)
    assert c2.ticker == c.ticker
    assert c2.sector == c.sector


def test_episode_defaults():
    ep = Episode(ticker="AAPL", title="Q1 2026 thesis", thesis="Strong services growth.", rating=Rating.BUY)
    assert ep.status == EpisodeStatus.OPEN
    assert ep.assumptions == []
    assert ep.predictions == []


def test_assumption_revision_chain():
    a1 = Assumption(key="rev_growth", value=0.12, unit="%", rationale="Base case")
    a2 = Assumption(key="rev_growth", value=0.15, unit="%", rationale="Raised after strong Q1", revised_from=a1.id)
    assert a2.revised_from == a1.id
    assert a2.status == AssumptionStatus.ACTIVE


def test_prediction_defaults():
    p = Prediction(
        description="Revenue exceeds $100B",
        metric="revenue",
        target_value=100,
        unit="B USD",
        horizon="FY2026",
    )
    assert p.outcome == PredictionOutcome.PENDING
    assert p.actual_value is None


def test_company_missing_required_fields():
    with pytest.raises(ValidationError):
        Company(ticker="X")  # missing name


def test_rating_enum_values():
    assert set(Rating) == {Rating.BUY, Rating.HOLD, Rating.SELL, Rating.NOT_RATED}
