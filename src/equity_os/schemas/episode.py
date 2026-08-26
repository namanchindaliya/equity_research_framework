"""ThesisEpisode — a full coverage cycle separating observations, inferences, decisions."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from pydantic import BaseModel, Field

from .agent import MonitoringTrigger, OrchestratorDecision
from .assumption import AssumptionRecord
from .common import EvidenceItem, SourceMetadata
from .enums import EpisodeStatus, Rating
from .prediction import PredictionRecord


# ---------------------------------------------------------------------------
# Episode sub-documents: observations, inferences, decisions
# ---------------------------------------------------------------------------


class ObservationRecord(BaseModel):
    """A raw factual observation entering the episode — not yet interpreted.

    Observations are the unprocessed inputs: data points, quotes, filings,
    channel-check findings.  They carry a source reference and are kept
    separate from inferences so the provenance chain stays clean.
    """

    id: UUID = Field(default_factory=uuid4)
    content: str
    source: SourceMetadata | None = None
    tags: list[str] = Field(default_factory=list)
    recorded_at: datetime = Field(default_factory=datetime.utcnow)


class InferenceRecord(BaseModel):
    """An interpretation drawn from one or more observations.

    ``based_on`` lists ObservationRecord IDs.  Requiring this link enforces
    that every inference is grounded — not derived from thin air.
    ``confidence`` reflects how strongly the evidence supports the inference.
    """

    id: UUID = Field(default_factory=uuid4)
    content: str
    based_on: list[UUID] = Field(default_factory=list)  # ObservationRecord IDs
    confidence: float = Field(default=0.7, ge=0.0, le=1.0)
    created_at: datetime = Field(default_factory=datetime.utcnow)


class DecisionRecord(BaseModel):
    """A concrete analytical or investment decision made during this episode.

    Decision types include RATING_INITIATION, RATING_CHANGE, PT_CHANGE,
    ASSUMPTION_REVISION, EPISODE_CLOSE, etc.  Keeping decisions explicit
    means the postmortem can evaluate whether the process was sound
    independent of whether the outcome was correct.
    """

    id: UUID = Field(default_factory=uuid4)
    decision_type: str             # free-form label; use consistent slugs
    content: str                   # what was decided
    rationale: str
    made_by: str                   # agent or analyst id
    made_at: datetime = Field(default_factory=datetime.utcnow)


# ---------------------------------------------------------------------------
# ThesisEpisode
# ---------------------------------------------------------------------------


class ThesisEpisode(BaseModel):
    """One full thesis cycle for a company.

    The three-layer structure (observations → inferences → decisions) mirrors
    how good analysts actually work: consume raw data, draw conclusions,
    then act.  Keeping the layers separate makes the reasoning chain
    auditable and reproducible.

    Each episode is self-contained and stored in its own immutable coverage
    directory, so earlier analytical states remain reproducible.
    """

    id: UUID = Field(default_factory=uuid4)
    ticker: str
    title: str
    version: int = 1
    thesis_statement: str                  # the core investment thesis in 1-3 sentences

    rating: Rating
    price_target: float | None = None
    currency: str = "USD"
    status: EpisodeStatus = EpisodeStatus.OPEN

    # Three-layer structure
    observations: list[ObservationRecord] = Field(default_factory=list)
    inferences: list[InferenceRecord] = Field(default_factory=list)
    decisions: list[DecisionRecord] = Field(default_factory=list)

    # Evidence pool for the episode (shared across assumptions and the orchestrator)
    evidence: list[EvidenceItem] = Field(default_factory=list)

    # Core analytical objects
    assumptions: list[AssumptionRecord] = Field(default_factory=list)
    predictions: list[PredictionRecord] = Field(default_factory=list)
    monitoring_triggers: list[MonitoringTrigger] = Field(default_factory=list)

    # Synthesis — populated after the orchestrator runs
    orchestrator_decision: OrchestratorDecision | None = None

    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    closed_at: datetime | None = None
    close_note: str | None = None

    # ------------------------------------------------------------------
    # Convenience helpers
    # ------------------------------------------------------------------

    def open_assumption_records(self) -> list[AssumptionRecord]:
        from .enums import AssumptionStatus
        return [a for a in self.assumptions if a.status == AssumptionStatus.ACTIVE]

    def pending_predictions(self) -> list[PredictionRecord]:
        return [p for p in self.predictions if not p.is_resolved]

    def active_triggers(self) -> list[MonitoringTrigger]:
        return [t for t in self.monitoring_triggers if t.active]
