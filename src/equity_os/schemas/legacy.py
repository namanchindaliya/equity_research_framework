"""v0 models — preserved verbatim for backward compatibility.

New code should use the richer domain models in assumption.py, prediction.py,
episode.py, and company.py. These remain the storage format for the v0 CLI.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, Field

from .enums import AssumptionStatus, EpisodeStatus, PredictionOutcome, Rating


class Assumption(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    key: str
    value: Any
    unit: str | None = None
    rationale: str
    status: AssumptionStatus = AssumptionStatus.ACTIVE
    created_at: datetime = Field(default_factory=datetime.utcnow)
    revised_from: UUID | None = None


class Prediction(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    description: str
    metric: str
    target_value: Any
    unit: str | None = None
    horizon: str
    outcome: PredictionOutcome = PredictionOutcome.PENDING
    actual_value: Any | None = None
    resolved_at: datetime | None = None
    resolution_note: str | None = None
    created_at: datetime = Field(default_factory=datetime.utcnow)


class Episode(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    ticker: str
    title: str
    thesis: str
    rating: Rating
    price_target: float | None = None
    currency: str = "USD"
    status: EpisodeStatus = EpisodeStatus.OPEN
    assumptions: list[Assumption] = Field(default_factory=list)
    predictions: list[Prediction] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    closed_at: datetime | None = None
    close_note: str | None = None


class Company(BaseModel):
    ticker: str
    name: str
    sector: str | None = None
    industry: str | None = None
    description: str | None = None
    current_rating: Rating = Rating.NOT_RATED
    current_price_target: float | None = None
    currency: str = "USD"
    episodes: list[Episode] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
