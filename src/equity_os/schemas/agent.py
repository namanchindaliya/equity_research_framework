"""AgentOutput, OrchestratorDecision, MonitoringTrigger, and supporting models."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, Field

from .common import Confidence
from .enums import AgentType, Rating, TriggerAction, TriggerFrequency


# ---------------------------------------------------------------------------
# Supporting models for OrchestratorDecision
# ---------------------------------------------------------------------------


class RiskItem(BaseModel):
    """A discrete risk the orchestrator has identified."""

    id: UUID = Field(default_factory=uuid4)
    description: str
    category: str                          # "macro", "competitive", "execution", "regulatory"
    severity: str                          # "HIGH" | "MEDIUM" | "LOW"  (keep flexible for now)
    probability: Confidence = 0.3
    mitigants: list[str] = Field(default_factory=list)


class ConflictItem(BaseModel):
    """A conflict between two agents, assumptions, or evidence items.

    ``between`` names the conflicting parties — e.g. ["bull_case_agent", "risk_agent"].
    The orchestrator records the conflict even when it cannot resolve it, so
    downstream reviewers see where disagreements exist.
    """

    id: UUID = Field(default_factory=uuid4)
    description: str
    between: list[str] = Field(min_length=2)
    resolution: str | None = None          # None means unresolved


class FalsificationCondition(BaseModel):
    """An explicit condition that, if observed, would invalidate the thesis.

    Making falsification conditions explicit up-front forces the analyst to
    pre-commit to what would change their mind, which makes postmortems honest.
    """

    id: UUID = Field(default_factory=uuid4)
    description: str
    metric: str
    threshold: Any
    check_by: date                         # when to evaluate this condition


# ---------------------------------------------------------------------------
# AgentOutput
# ---------------------------------------------------------------------------


class AgentOutput(BaseModel):
    """The structured output of a single agent run.

    An agent can produce either a ``payload`` dict (structured output consumed
    programmatically) or a ``memo_path`` (path to a markdown memo for human
    review) or both.  At least one must be present.

    ``evidence_consumed`` and ``assumptions_produced`` / ``predictions_produced``
    allow the orchestrator to trace the provenance of every claim back to the
    agent that produced it.
    """

    id: UUID = Field(default_factory=uuid4)
    agent_type: AgentType
    agent_id: str                           # logical name, e.g. "thesis_builder_v1"
    episode_id: UUID | None = None
    ticker: str
    version: int = 1
    payload: dict[str, Any] | None = None   # structured output
    memo_path: str | None = None            # relative path to markdown memo
    confidence: Confidence = 0.7
    reasoning: str                          # brief explanation of conclusions
    evidence_consumed: list[UUID] = Field(default_factory=list)    # EvidenceItem IDs
    assumptions_produced: list[UUID] = Field(default_factory=list) # AssumptionRecord IDs
    predictions_produced: list[UUID] = Field(default_factory=list) # PredictionRecord IDs
    created_at: datetime = Field(default_factory=datetime.utcnow)

    def has_output(self) -> bool:
        return self.payload is not None or self.memo_path is not None


# ---------------------------------------------------------------------------
# MonitoringTrigger
# ---------------------------------------------------------------------------


class MonitoringTrigger(BaseModel):
    """A standing watch condition that fires when a metric crosses a threshold.

    ``operator`` and ``threshold`` together define the condition.  When it fires,
    ``action`` tells the system what to do automatically (alert, revise an
    assumption, rerun the full thesis, or close the episode).
    """

    id: UUID = Field(default_factory=uuid4)
    episode_id: UUID
    label: str
    description: str
    metric: str
    operator: str                            # ">", "<", ">=", "<=", "==", "changes"
    threshold: Any
    frequency: TriggerFrequency = TriggerFrequency.EVENT_DRIVEN
    action: TriggerAction = TriggerAction.ALERT
    action_note: str | None = None           # optional instruction for the action handler
    active: bool = True
    last_checked_at: datetime | None = None
    triggered_at: datetime | None = None
    created_at: datetime = Field(default_factory=datetime.utcnow)


# ---------------------------------------------------------------------------
# OrchestratorDecision
# ---------------------------------------------------------------------------


class OrchestratorDecision(BaseModel):
    """The synthesis output from the orchestrator agent.

    Design rationale
    ----------------
    - ``thesis`` is the affirmative case in 1-3 sentences.
    - ``variant_view`` is the most credible bear / alternative interpretation.
      Forcing the orchestrator to articulate the variant view prevents
      confirmation bias and is required before generating falsification conditions.
    - ``conflicts`` records where agents disagreed; the orchestrator must
      acknowledge conflicts rather than silently averaging them away.
    - ``falsification_conditions`` are pre-committed trip-wires. If *any* fires,
      the thesis must be reconsidered.
    - ``monitoring_triggers`` are UUIDs referencing MonitoringTrigger records
      stored at the episode level.
    - ``next_evidence_needed`` is the prioritized list of information gaps.
    - ``price_target_bear`` and ``price_target_bull`` frame the scenario range.
    """

    id: UUID = Field(default_factory=uuid4)
    episode_id: UUID
    ticker: str
    version: int = 1
    thesis: str
    variant_view: str | None = None
    rating: Rating
    price_target: float | None = None
    price_target_bear: float | None = None
    price_target_bull: float | None = None
    currency: str = "USD"
    risks: list[RiskItem] = Field(default_factory=list)
    conflicts: list[ConflictItem] = Field(default_factory=list)
    falsification_conditions: list[FalsificationCondition] = Field(default_factory=list)
    monitoring_triggers: list[UUID] = Field(default_factory=list)  # MonitoringTrigger IDs
    next_evidence_needed: list[str] = Field(default_factory=list)
    confidence: Confidence = 0.7
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
