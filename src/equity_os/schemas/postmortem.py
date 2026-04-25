"""Postmortem — post-episode analysis of thesis quality and process."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from pydantic import BaseModel, Field, model_validator

from .common import Confidence
from .enums import PostmortemVerdict


class AssumptionError(BaseModel):
    """Records which assumption was wrong and by how much."""

    assumption_id: UUID
    key: str
    assumed_value: object
    actual_value: object
    error_magnitude: float | None = None  # (actual - assumed) / |assumed| if numeric
    explanation: str


class Postmortem(BaseModel):
    """A structured retrospective written after a ThesisEpisode is closed.

    Design rationale
    ----------------
    - ``prediction_accuracy`` is the fraction of resolved predictions that came
      out CORRECT.  Only non-EXPIRED / non-WITHDRAWN predictions count.
    - ``assumption_errors`` are explicit call-outs of which assumptions were wrong;
      this is harder than tracking predictions because assumptions rarely have
      a single observable outcome, so the analyst must make a judgment call.
    - The four list fields (what_went_right, what_went_wrong, lessons_learned,
      process_improvements) are kept separate so they can be aggregated across
      many postmortems for recurring-pattern analysis.
    - ``version`` allows for a revised postmortem if new information surfaces.
    """

    id: UUID = Field(default_factory=uuid4)
    episode_id: UUID
    ticker: str

    verdict: PostmortemVerdict
    prediction_accuracy: Confidence      # fraction of non-expired predictions correct

    what_went_right: list[str] = Field(default_factory=list)
    what_went_wrong: list[str] = Field(default_factory=list)
    lessons_learned: list[str] = Field(default_factory=list)
    assumption_errors: list[AssumptionError] = Field(default_factory=list)
    process_improvements: list[str] = Field(default_factory=list)

    authored_by: str
    version: int = 1
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    @model_validator(mode="after")
    def verdict_accuracy_consistent(self) -> Postmortem:
        """Cross-check that the verdict is plausible given prediction_accuracy."""
        if self.verdict == PostmortemVerdict.THESIS_CORRECT and self.prediction_accuracy < 0.5:
            raise ValueError(
                "verdict=THESIS_CORRECT but prediction_accuracy < 0.5 — "
                "either update the verdict or the accuracy."
            )
        if self.verdict == PostmortemVerdict.THESIS_INCORRECT and self.prediction_accuracy > 0.8:
            raise ValueError(
                "verdict=THESIS_INCORRECT but prediction_accuracy > 0.8 — "
                "either update the verdict or the accuracy."
            )
        return self
