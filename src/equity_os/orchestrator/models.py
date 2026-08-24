"""OrchestratorDecision and its three constituent layers.

Three-section structure (structurally enforced, not just named)
---------------------------------------------------------------
ObservationLayer — raw facts from agents, assumption ledger, change log.
                   No interpretation added.
InferenceLayer   — what the orchestrator concludes by reconciling observations.
                   Includes conflict resolution and adjusted assumptions.
DecisionLayer    — what to do next. Predictions, falsification conditions,
                   monitoring triggers, next evidence needed.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Observation layer — verbatim facts from specialist agents
# ---------------------------------------------------------------------------


class SynthesisStatus(str, Enum):
    """Whether the orchestrator may publish a synthesized thesis."""

    COMPLETE = "COMPLETE"
    LIMITED = "LIMITED"
    ABSTAINED = "ABSTAINED"


class AgentObservation(BaseModel):
    """One agent's raw output, summarised for the orchestrator."""
    agent_id: str
    generated_at: datetime | None = None
    overall_confidence: float = Field(ge=0.0, le=1.0, default=0.5)
    freshness_penalty_applied: float = Field(ge=0.0, le=1.0, default=0.0)
    evidence_id_count: int = 0
    key_findings: list[str] = Field(default_factory=list)   # top findings verbatim
    analysis_status: str = "COMPLETE"


class ObservationLayer(BaseModel):
    """Layer 1: raw observations from every input. No orchestrator interpretation."""

    # Agent summaries
    industry_observation: AgentObservation | None = None
    strategy_observation: AgentObservation | None = None

    # Key facts from IndustryAgent (verbatim)
    market_structure: str = "UNKNOWN"
    cycle_stage: str = "UNKNOWN"
    industry_label: str = ""
    porter_forces_summary: dict[str, str] = Field(default_factory=dict)   # name → level
    regulatory_factors: list[str] = Field(default_factory=list)           # factor names
    industry_risks: list[str] = Field(default_factory=list)               # risk names

    # Key facts from CompanyStrategyAgent (verbatim)
    management_priorities_raw: list[str] = Field(default_factory=list)    # text of each
    segment_priority_order: list[str] = Field(default_factory=list)       # ordered by rank
    strategic_target_market: str = ""
    strategic_moat: list[str] = Field(default_factory=list)
    disclosed_risk_categories: list[str] = Field(default_factory=list)    # category list
    narrative_shifts: list[str] = Field(default_factory=list)             # shift descriptions

    # Assumption ledger state
    active_assumption_count: int = 0
    revised_assumption_count: int = 0
    critical_assumptions: list[str] = Field(default_factory=list)        # CRITICAL materiality keys

    # Change log state (if provided)
    recent_material_changes: list[str] = Field(default_factory=list)
    recent_conflicts_flagged: list[str] = Field(default_factory=list)
    has_prior_thesis: bool = False
    prior_thesis_statement: str | None = None


# ---------------------------------------------------------------------------
# Inference layer — orchestrator's interpretations
# ---------------------------------------------------------------------------


class AdjustedAssumption(BaseModel):
    """An assumption value after policy-based confidence adjustments."""
    key: str
    label: str
    value: Any
    base_confidence: float = Field(ge=0.0, le=1.0)
    adjusted_confidence: float = Field(ge=0.0, le=1.0)
    adjustment_reasons: list[str] = Field(default_factory=list)
    materiality: str = "MEDIUM"
    owner_agent: str = ""
    source: str = "ledger"       # "ledger" | "industry" | "strategy" | "synthesized"


class AgentConflict(BaseModel):
    """A disagreement between two agents on the same analytical dimension."""
    conflict_id: UUID = Field(default_factory=uuid4)
    dimension: str                  # "competitive_intensity", "regulatory_risk", etc.
    industry_view: str
    strategy_view: str
    conflict_severity: str          # "hard" | "soft"
    resolution: str                 # which agent was trusted and what was concluded
    resolution_basis: str           # policy rule cited: e.g. "conflict_resolution.regulatory_risk"
    trusted_agent: str              # "industry_v1" | "strategy_v1" | "higher_confidence"
    confidence_after: float = Field(ge=0.0, le=1.0)


class OrchestratorInference(BaseModel):
    """One inference statement with grounding and dissent tracking."""
    text: str
    confidence: float = Field(ge=0.0, le=1.0)
    based_on: list[str] = Field(default_factory=list)          # observation field names
    dissenting_source: str | None = None                       # agent that disagreed
    dissent_description: str | None = None


class InferenceLayer(BaseModel):
    """Layer 2: orchestrator's synthesis across agents."""

    thesis_statement: str
    variant_view: str               # strongest counter-thesis

    # Weighted / adjusted assumptions
    key_assumptions: list[AdjustedAssumption] = Field(default_factory=list)

    # Top analytical drivers
    top_drivers: list[OrchestratorInference] = Field(default_factory=list)

    # Conflict resolution record
    agent_conflicts: list[AgentConflict] = Field(default_factory=list)

    # Where both agents agreed
    cross_validated: list[str] = Field(default_factory=list)

    # Unresolved conflicts (too ambiguous to resolve)
    unresolved_conflicts: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Decision layer — what to do next
# ---------------------------------------------------------------------------


class OrchestratorPrediction(BaseModel):
    description: str
    metric: str
    direction: str              # ">" | "<" | "=" | "changes" | "holds"
    horizon: str
    probability: float = Field(ge=0.0, le=1.0)
    confidence: float = Field(ge=0.0, le=1.0)
    based_on_assumption_keys: list[str] = Field(default_factory=list)


class FalsificationCondition(BaseModel):
    condition: str              # plain-language description
    metric: str
    threshold: str
    check_by: str               # "next quarter" | "within 6 months" | etc.
    assumption_key: str         # which assumption this would invalidate


class MonitoringTrigger(BaseModel):
    metric: str
    condition: str
    action: str                 # "alert" | "rerun_thesis" | "revise_assumption"
    frequency: str              # "quarterly" | "monthly" | "event-driven"
    rationale: str


class DecisionLayer(BaseModel):
    """Layer 3: decisions — what the analyst should do next."""

    # Duplicated from inference for standalone readability
    current_thesis: str
    rating_stance: str          # "constructive" | "cautious" | "neutral" | "not_rated"

    predictions: list[OrchestratorPrediction] = Field(default_factory=list)
    falsification_conditions: list[FalsificationCondition] = Field(default_factory=list)
    monitoring_triggers: list[MonitoringTrigger] = Field(default_factory=list)
    next_evidence_needed: list[str] = Field(default_factory=list)
    unresolved_conflicts: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Confidence summary
# ---------------------------------------------------------------------------


class ConfidenceSummary(BaseModel):
    overall: float = Field(ge=0.0, le=1.0)
    industry_confidence: float = Field(ge=0.0, le=1.0)
    strategy_confidence: float = Field(ge=0.0, le=1.0)
    freshness_penalty: float = Field(ge=0.0, le=1.0, default=0.0)
    conflict_penalty: float = Field(ge=0.0, le=1.0, default=0.0)
    basis: str = ""             # plain-language explanation


# ---------------------------------------------------------------------------
# OrchestratorDecision — top-level output
# ---------------------------------------------------------------------------


class OrchestratorDecision(BaseModel):
    """Full synthesised output of one orchestrator run.

    The three layers are structurally separated so readers can't confuse
    raw observations with inferences or decisions.
    """

    decision_id: UUID = Field(default_factory=uuid4)
    ticker: str
    generated_at: datetime = Field(default_factory=datetime.utcnow)
    policy_version: str = "1.0"
    synthesis_status: SynthesisStatus = SynthesisStatus.COMPLETE
    abstention_reasons: list[str] = Field(default_factory=list)

    observations: ObservationLayer
    inferences: InferenceLayer
    decisions: DecisionLayer
    confidence_summary: ConfidenceSummary

    # Provenance
    industry_run_id: str = ""
    strategy_run_id: str = ""
    evidence_ids: list[str] = Field(default_factory=list)
