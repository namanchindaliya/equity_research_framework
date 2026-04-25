"""Pydantic output models for all specialist agents.

Design principles
-----------------
- Every analytical claim is a Finding with confidence + evidence_refs.
- Confidence is always [0, 1]. 0 = no evidence; 1 = unambiguous primary source.
- evidence_refs are TextChunk citation anchors (e.g. "AAPL-ab12cd34-0003").
- unresolved_questions is a first-class list, not an afterthought.
- No valuation, no earnings forecast.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Shared primitives
# ---------------------------------------------------------------------------


class EvidenceRef(BaseModel):
    """Citation pointing to a specific TextChunk inside an IngestedEvidence."""

    chunk_id: str       # e.g. "AAPL-ab12cd34-0003"
    evidence_id: str    # UUID of the IngestedEvidence document
    source_title: str
    quote: str          # first ≤ 250 chars of the chunk for quick inspection


class Finding(BaseModel):
    """A single analytical observation, grounded in evidence."""

    text: str
    confidence: float = Field(ge=0.0, le=1.0)
    evidence_refs: list[EvidenceRef] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Industry agent models
# ---------------------------------------------------------------------------


class MarketStructure(str, Enum):
    MONOPOLY = "MONOPOLY"
    OLIGOPOLY = "OLIGOPOLY"
    COMPETITIVE = "COMPETITIVE"
    FRAGMENTED = "FRAGMENTED"
    UNKNOWN = "UNKNOWN"


class CycleStage(str, Enum):
    EARLY_GROWTH = "EARLY_GROWTH"
    GROWTH = "GROWTH"
    MATURE = "MATURE"
    DECLINE = "DECLINE"
    UNKNOWN = "UNKNOWN"


class ForceLevel(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    UNKNOWN = "UNKNOWN"


class PorterForce(BaseModel):
    """One of the five Porter forces with a scored intensity and evidence."""

    name: str           # "Competitive Rivalry", "Supplier Power", etc.
    level: ForceLevel
    summary: str        # one-sentence interpretation
    confidence: float = Field(ge=0.0, le=1.0)
    evidence_refs: list[EvidenceRef] = Field(default_factory=list)


class IndustryKPI(BaseModel):
    name: str
    definition: str
    trend_direction: str    # "increasing" | "decreasing" | "stable" | "unknown"
    finding: Finding


class RegulatoryFactor(BaseModel):
    name: str
    jurisdiction: str
    impact_summary: str
    severity: str           # "HIGH" | "MEDIUM" | "LOW"
    finding: Finding


class CompetitiveDynamics(BaseModel):
    concentration_finding: Finding      # who are the main players
    moat_type: list[str]               # "switching_costs" | "brand" | "network_effects" | "scale" | "ip"
    basis_of_competition: list[str]    # "price" | "quality" | "features" | "ecosystem" | "distribution"
    overall_confidence: float = Field(ge=0.0, le=1.0)


class IndustryRisk(BaseModel):
    name: str
    category: str           # "regulatory" | "competitive" | "macro" | "technology" | "demand"
    finding: Finding


class IndustryAnalysis(BaseModel):
    """Full output of IndustryAgent. No valuation. No management quality judgments."""

    agent_id: str = "industry_v1"
    run_id: UUID = Field(default_factory=uuid4)
    ticker: str
    generated_at: datetime = Field(default_factory=datetime.utcnow)

    industry_label: str                 # e.g. "Consumer Electronics / Smartphone"
    market_structure: MarketStructure
    market_structure_finding: Finding
    cycle_stage: CycleStage
    cycle_stage_finding: Finding

    porter_forces: list[PorterForce]    # always 5 entries in canonical order
    key_kpis: list[IndustryKPI]
    regulatory_factors: list[RegulatoryFactor]
    competitive_dynamics: CompetitiveDynamics
    top_risks: list[IndustryRisk]

    unresolved_questions: list[str]
    overall_confidence: float = Field(ge=0.0, le=1.0)
    evidence_ids: list[str]             # UUIDs of IngestedEvidence consumed


# ---------------------------------------------------------------------------
# Company strategy agent models
# ---------------------------------------------------------------------------


class CapitalAllocationItem(BaseModel):
    category: str           # "buybacks" | "dividends" | "capex" | "m_and_a" | "debt"
    finding: Finding
    magnitude_hint: str     # extracted dollar amount or "not quantified"


class NarrativeShift(BaseModel):
    topic: str
    old_framing: str        # how the topic was framed in earlier evidence
    new_framing: str        # how it is framed in later evidence
    shift_type: str         # "emphasis_increase" | "emphasis_decrease" | "reframing"
    confidence: float = Field(ge=0.0, le=1.0)
    old_evidence_refs: list[EvidenceRef] = Field(default_factory=list)
    new_evidence_refs: list[EvidenceRef] = Field(default_factory=list)


class DisclosedRisk(BaseModel):
    name: str
    category: str           # "regulatory" | "competitive" | "operational" | "macro" | "financial"
    severity_from_disclosure: str   # "explicit" (stated severe) | "mentioned" | "implied"
    finding: Finding


class SegmentPriority(BaseModel):
    segment_name: str
    priority_rank: int      # 1 = highest management emphasis
    growth_framing: str     # how management described this segment's trajectory
    finding: Finding


class CredibilitySignal(BaseModel):
    signal_type: str        # "guidance_beat" | "guidance_miss" | "strategic_consistency" | "reversal"
    description: str
    finding: Finding


class StrategicPositioning(BaseModel):
    target_market: str              # "premium" | "mass_market" | "enterprise" | "mixed"
    differentiation_axes: list[str] # "ecosystem" | "brand" | "quality" | "price" | "vertical_integration"
    moat_assessment: list[str]      # only from disclosed material
    finding: Finding


class CompanyStrategyAnalysis(BaseModel):
    """Full output of CompanyStrategyAgent. No earnings forecast. No valuation."""

    agent_id: str = "strategy_v1"
    run_id: UUID = Field(default_factory=uuid4)
    ticker: str
    generated_at: datetime = Field(default_factory=datetime.utcnow)

    management_priorities: list[Finding]
    capital_allocation: list[CapitalAllocationItem]
    narrative_shifts: list[NarrativeShift]
    risk_disclosures: list[DisclosedRisk]
    segment_priorities: list[SegmentPriority]
    strategic_positioning: StrategicPositioning
    mgmt_credibility_signals: list[CredibilitySignal]

    unresolved_questions: list[str]
    overall_confidence: float = Field(ge=0.0, le=1.0)
    evidence_ids: list[str]


# ---------------------------------------------------------------------------
# Agent run envelope
# ---------------------------------------------------------------------------


class AgentRunResult(BaseModel):
    """Envelope produced by BaseAgent.run().

    payload holds the typed analysis (IndustryAnalysis | CompanyStrategyAnalysis).
    memo holds the rendered markdown string.
    validation_errors holds issues found by validate_output().
    """

    agent_id: str
    run_id: UUID = Field(default_factory=uuid4)
    ticker: str
    generated_at: datetime = Field(default_factory=datetime.utcnow)
    payload: dict[str, Any]             # model_dump() of the typed analysis
    memo: str                           # rendered markdown
    validation_errors: list[str] = Field(default_factory=list)
    evidence_ids_consumed: list[str] = Field(default_factory=list)
