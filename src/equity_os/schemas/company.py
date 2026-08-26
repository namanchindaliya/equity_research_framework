"""CompanyDossier — the root state object for a covered company."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from pydantic import BaseModel, Field

from .agent import MonitoringTrigger
from .enums import Rating
from .episode import ThesisEpisode


class CompanyDossier(BaseModel):
    """Complete coverage record for a single company.

    The dossier is the root of the company's state tree.  Every ThesisEpisode
    and MonitoringTrigger for this company lives here.

    Design notes
    ------------
    - ``version`` increments on every persisted write (like an optimistic-lock
      counter), making concurrent-write collisions detectable.
    - ``monitoring_triggers`` here are *company-level* standing triggers (e.g.
      "alert if quarterly revenue YoY drops below 5%"); episode-level triggers
      live inside ThesisEpisode.
    - ``tags`` are free-form labels for screening/grouping (e.g. ["mag7", "ai-infra"]).
    - ``exchange`` and ``country`` are included in the normalized dossier so
      source and market context travel with the company record.
    """

    id: UUID = Field(default_factory=uuid4)
    ticker: str
    name: str
    sector: str | None = None
    industry: str | None = None
    exchange: str | None = None
    country: str = "US"
    description: str | None = None

    current_rating: Rating = Rating.NOT_RATED
    current_price_target: float | None = None
    currency: str = "USD"

    episodes: list[ThesisEpisode] = Field(default_factory=list)
    monitoring_triggers: list[MonitoringTrigger] = Field(default_factory=list)

    tags: list[str] = Field(default_factory=list)

    version: int = 1
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    # ------------------------------------------------------------------
    # Convenience helpers
    # ------------------------------------------------------------------

    def open_episodes(self) -> list[ThesisEpisode]:
        from .enums import EpisodeStatus
        return [e for e in self.episodes if e.status == EpisodeStatus.OPEN]

    def latest_episode(self) -> ThesisEpisode | None:
        if not self.episodes:
            return None
        return max(self.episodes, key=lambda e: e.created_at)
