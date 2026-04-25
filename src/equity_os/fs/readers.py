"""High-level read helpers that combine layout + io + schema knowledge."""

from __future__ import annotations

from pathlib import Path

from equity_os.schemas import (
    AssumptionChange,
    AssumptionRecord,
    AssumptionStatus,
    CompanyDossier,
    PredictionRecord,
    ThesisEpisode,
)

from .io import read_json, read_jsonl
from .layout import CompanyLayout


def load_dossier(layout: CompanyLayout) -> CompanyDossier:
    """Load the slim company dossier (episodes list is always [] on disk)."""
    if not layout.dossier_json.exists():
        raise FileNotFoundError(
            f"Company {layout.ticker!r} not found at {layout.dossier_json}"
        )
    return read_json(layout.dossier_json, CompanyDossier)


def load_episode(layout: CompanyLayout, slug: str) -> ThesisEpisode:
    path = layout.episode_json(slug)
    if not path.exists():
        raise FileNotFoundError(
            f"Episode {slug!r} not found for {layout.ticker}"
        )
    return read_json(path, ThesisEpisode)


def load_full_dossier(layout: CompanyLayout) -> CompanyDossier:
    """Load dossier + all episodes from disk, assembling the complete in-memory object."""
    dossier = load_dossier(layout)
    episodes = [load_episode(layout, slug) for slug in layout.episode_slugs()]
    return dossier.model_copy(update={"episodes": episodes})


def resolve_episode_slug(layout: CompanyLayout, prefix: str) -> str:
    """Match a prefix (or full slug) to exactly one episode directory name."""
    slugs = layout.episode_slugs()
    # Exact match first
    if prefix in slugs:
        return prefix
    matches = [s for s in slugs if s.startswith(prefix)]
    if not matches:
        raise ValueError(
            f"No episode matching {prefix!r} for {layout.ticker}. "
            f"Available: {slugs or '(none)'}"
        )
    if len(matches) > 1:
        raise ValueError(
            f"Ambiguous episode prefix {prefix!r} — matches: {matches}"
        )
    return matches[0]


def find_active_assumption(episode: ThesisEpisode, key: str) -> AssumptionRecord:
    """Return the first ACTIVE assumption with the given key."""
    for a in episode.assumptions:
        if a.key == key and a.status == AssumptionStatus.ACTIVE:
            return a
    active_keys = [a.key for a in episode.assumptions if a.status == AssumptionStatus.ACTIVE]
    raise ValueError(
        f"No active assumption with key {key!r}. Active keys: {active_keys or '(none)'}"
    )


def find_prediction_by_metric(episode: ThesisEpisode, metric: str) -> PredictionRecord:
    """Return the prediction matching the metric name."""
    for p in episode.predictions:
        if p.metric == metric:
            return p
    metrics = [p.metric for p in episode.predictions]
    raise ValueError(
        f"No prediction with metric {metric!r}. Available: {metrics or '(none)'}"
    )


def load_assumption_changes(
    layout: CompanyLayout, episode_slug: str, key: str
) -> list[AssumptionChange]:
    """Read the full change log for an assumption key."""
    return read_jsonl(layout.assumption_changes(episode_slug, key), AssumptionChange)
