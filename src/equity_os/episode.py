"""Business logic for creating and closing thesis episodes."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from .schemas import (
    Assumption,
    AssumptionStatus,
    Company,
    Episode,
    EpisodeStatus,
    Prediction,
    PredictionOutcome,
    Rating,
)
from .store import CompanyStore


def open_episode(
    store: CompanyStore,
    ticker: str,
    title: str,
    thesis: str,
    rating: Rating,
    price_target: float | None = None,
    currency: str = "USD",
) -> Episode:
    """Create a new OPEN episode on the company and persist it."""
    company = store.load(ticker)
    episode = Episode(
        ticker=ticker.upper(),
        title=title,
        thesis=thesis,
        rating=rating,
        price_target=price_target,
        currency=currency,
    )
    company.episodes.append(episode)
    company.current_rating = rating
    company.current_price_target = price_target
    store.save(company)
    return episode


def close_episode(
    store: CompanyStore,
    ticker: str,
    episode_id: UUID,
    close_note: str,
) -> Episode:
    """Mark an episode CLOSED and persist."""
    company = store.load(ticker)
    episode = _find_episode(company, episode_id)
    if episode.status == EpisodeStatus.CLOSED:
        raise ValueError(f"Episode {episode_id} is already closed.")
    episode.status = EpisodeStatus.CLOSED
    episode.closed_at = datetime.utcnow()
    episode.close_note = close_note
    store.save(company)
    return episode


def add_assumption(
    store: CompanyStore,
    ticker: str,
    episode_id: UUID,
    key: str,
    value: object,
    rationale: str,
    unit: str | None = None,
) -> Assumption:
    """Append a new assumption to an episode."""
    company = store.load(ticker)
    episode = _find_episode(company, episode_id)
    assumption = Assumption(key=key, value=value, rationale=rationale, unit=unit)
    episode.assumptions.append(assumption)
    store.save(company)
    return assumption


def revise_assumption(
    store: CompanyStore,
    ticker: str,
    episode_id: UUID,
    assumption_id: UUID,
    new_value: object,
    rationale: str,
    unit: str | None = None,
) -> Assumption:
    """Retire the old assumption and add a revised version."""
    company = store.load(ticker)
    episode = _find_episode(company, episode_id)
    old = _find_assumption(episode, assumption_id)
    old.status = AssumptionStatus.REVISED
    new = Assumption(
        key=old.key,
        value=new_value,
        unit=unit or old.unit,
        rationale=rationale,
        revised_from=old.id,
    )
    episode.assumptions.append(new)
    store.save(company)
    return new


def add_prediction(
    store: CompanyStore,
    ticker: str,
    episode_id: UUID,
    description: str,
    metric: str,
    target_value: object,
    horizon: str,
    unit: str | None = None,
) -> Prediction:
    """Append a prediction to an episode."""
    company = store.load(ticker)
    episode = _find_episode(company, episode_id)
    prediction = Prediction(
        description=description,
        metric=metric,
        target_value=target_value,
        horizon=horizon,
        unit=unit,
    )
    episode.predictions.append(prediction)
    store.save(company)
    return prediction


def resolve_prediction(
    store: CompanyStore,
    ticker: str,
    episode_id: UUID,
    prediction_id: UUID,
    outcome: PredictionOutcome,
    actual_value: object,
    resolution_note: str,
) -> Prediction:
    """Record the outcome of a prediction."""
    company = store.load(ticker)
    episode = _find_episode(company, episode_id)
    prediction = _find_prediction(episode, prediction_id)
    if prediction.outcome != PredictionOutcome.PENDING:
        raise ValueError(f"Prediction {prediction_id} already resolved as {prediction.outcome}.")
    prediction.outcome = outcome
    prediction.actual_value = actual_value
    prediction.resolution_note = resolution_note
    prediction.resolved_at = datetime.utcnow()
    store.save(company)
    return prediction


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _find_episode(company: Company, episode_id: UUID) -> Episode:
    for ep in company.episodes:
        if ep.id == episode_id:
            return ep
    raise ValueError(f"Episode {episode_id} not found for {company.ticker!r}.")


def _find_assumption(episode: Episode, assumption_id: UUID) -> Assumption:
    for a in episode.assumptions:
        if a.id == assumption_id:
            return a
    raise ValueError(f"Assumption {assumption_id} not found in episode {episode.id}.")


def _find_prediction(episode: Episode, prediction_id: UUID) -> Prediction:
    for p in episode.predictions:
        if p.id == prediction_id:
            return p
    raise ValueError(f"Prediction {prediction_id} not found in episode {episode.id}.")
