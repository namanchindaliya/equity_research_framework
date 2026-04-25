"""Pydantic models for the diff / assumptions engine.

Hierarchy
---------
FieldChange          — one field that differed between two runs
AssumptionProposal   — a recommended assumption update triggered by ≥1 FieldChange
ConflictFlag         — a detected inconsistency worth surfacing
EpisodeDiff          — a full comparison of two consecutive agent runs
ChangeLog            — accumulates EpisodeDiffs over time (append-only)
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------


class ChangeType(str, Enum):
    ADDED = "ADDED"
    REMOVED = "REMOVED"
    MODIFIED = "MODIFIED"
    UNCHANGED = "UNCHANGED"


class DiffMateriality(str, Enum):
    HIGH = "HIGH"       # potentially thesis-altering
    MEDIUM = "MEDIUM"   # worth noting, monitor
    LOW = "LOW"         # cosmetic or noise


# ---------------------------------------------------------------------------
# FieldChange — atomic diff unit
# ---------------------------------------------------------------------------


class FieldChange(BaseModel):
    """A single field that changed between the prior and current agent run.

    field_path uses dot-notation with bracket-indexed lists:
        "cycle_stage"
        "porter_forces[Competitive Rivalry].level"
        "regulatory_factors[EU Digital Markets Act].severity"
    """

    change_id: UUID = Field(default_factory=uuid4)
    field_path: str
    change_type: ChangeType
    prior_value: Any
    current_value: Any
    # For numeric or enum fields: |current - prior| / |prior|; None otherwise
    change_magnitude: float | None = None
    materiality: DiffMateriality
    owner_agent: str
    # Evidence IDs that drove the current value (from current run)
    evidence_ids: list[str] = Field(default_factory=list)
    timestamp: datetime = Field(default_factory=datetime.utcnow)


# ---------------------------------------------------------------------------
# AssumptionProposal — recommended update to one assumption
# ---------------------------------------------------------------------------


class AssumptionProposal(BaseModel):
    """A recommended update to an AssumptionRecord.

    Captures everything an analyst needs to decide whether to accept the change:
    - what changed (prior_value → proposed_value)
    - why it changed (rationale + evidence)
    - what is affected downstream (impacted_model_fields)
    - what it means for the investment thesis and valuation

    Design note: this does NOT automatically update the AssumptionRecord.
    The analyst (or a future orchestrator agent) must accept it explicitly.
    """

    proposal_id: UUID = Field(default_factory=uuid4)
    assumption_key: str         # machine slug, matches AssumptionRecord.key
    assumption_label: str       # human-readable display name
    prior_value: Any
    proposed_value: Any
    change_type: ChangeType
    rationale: str              # plain-language explanation of why this changed
    evidence_ids: list[str] = Field(default_factory=list)
    owner_agent: str
    confidence: float = Field(ge=0.0, le=1.0)
    materiality: DiffMateriality
    # Which model fields are downstream of this assumption
    impacted_model_fields: list[str] = Field(default_factory=list)
    implication_for_thesis: str
    implication_for_valuation: str
    # FieldChange paths that triggered this proposal
    triggered_by_field_paths: list[str] = Field(default_factory=list)
    timestamp: datetime = Field(default_factory=datetime.utcnow)


# ---------------------------------------------------------------------------
# ConflictFlag — detected inconsistency between evidence sources
# ---------------------------------------------------------------------------


class ConflictFlag(BaseModel):
    """Signals where the evidence is contradictory or uncertain.

    Types of conflicts
    ------------------
    - confidence_inversion: confidence dropped >50% from prior → current on same field
    - evidence_disagreement: two distinct evidence sources imply opposite values
    - oscillation: field value reversed from a prior diff (up → down → up)
    - unresolved_growth: unresolved_questions list grew significantly
    """

    conflict_id: UUID = Field(default_factory=uuid4)
    conflict_type: str          # "confidence_inversion" | "evidence_disagreement" | "oscillation" | "unresolved_growth"
    description: str
    field_path: str
    evidence_a_ids: list[str] = Field(default_factory=list)
    evidence_b_ids: list[str] = Field(default_factory=list)
    resolution: str | None = None       # None = unresolved
    confidence_impact: float = Field(ge=0.0, le=1.0, default=0.1)
    detected_at: datetime = Field(default_factory=datetime.utcnow)


# ---------------------------------------------------------------------------
# EpisodeDiff — one comparison between two consecutive agent runs
# ---------------------------------------------------------------------------


class EpisodeDiff(BaseModel):
    """Complete diff between prior_run and current_run for one agent on one ticker.

    This is the primary artifact produced by the diff engine.
    """

    diff_id: UUID = Field(default_factory=uuid4)
    ticker: str
    agent_id: str
    episode_id: str | None = None       # optional link to ThesisEpisode UUID
    prior_run_id: str
    current_run_id: str
    prior_generated_at: datetime | None = None
    current_generated_at: datetime | None = None
    prior_evidence_ids: list[str] = Field(default_factory=list)
    current_evidence_ids: list[str] = Field(default_factory=list)
    field_changes: list[FieldChange] = Field(default_factory=list)
    assumption_proposals: list[AssumptionProposal] = Field(default_factory=list)
    conflict_flags: list[ConflictFlag] = Field(default_factory=list)
    computed_at: datetime = Field(default_factory=datetime.utcnow)
    has_material_changes: bool = False
    change_summary: str = ""

    @property
    def added(self) -> list[FieldChange]:
        return [c for c in self.field_changes if c.change_type == ChangeType.ADDED]

    @property
    def removed(self) -> list[FieldChange]:
        return [c for c in self.field_changes if c.change_type == ChangeType.REMOVED]

    @property
    def modified(self) -> list[FieldChange]:
        return [c for c in self.field_changes if c.change_type == ChangeType.MODIFIED]

    @property
    def unchanged(self) -> list[FieldChange]:
        return [c for c in self.field_changes if c.change_type == ChangeType.UNCHANGED]

    @property
    def high_materiality(self) -> list[FieldChange]:
        return [c for c in self.field_changes if c.materiality == DiffMateriality.HIGH]


# ---------------------------------------------------------------------------
# ChangeLog — accumulates EpisodeDiffs over time
# ---------------------------------------------------------------------------


class ChangeLog(BaseModel):
    """Append-only audit trail of diffs for one ticker + agent combination.

    Storage: companies/{ticker}/outputs/{episode_slug}/{change_log_id}_changelog.json
    """

    change_log_id: UUID = Field(default_factory=uuid4)
    ticker: str
    agent_id: str
    diffs: list[EpisodeDiff] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    @property
    def total_changes(self) -> int:
        return sum(
            len(d.field_changes) for d in self.diffs
            if d.field_changes and any(c.change_type != ChangeType.UNCHANGED for c in d.field_changes)
        )

    @property
    def material_changes(self) -> int:
        return sum(
            sum(
                1 for c in d.field_changes
                if c.materiality == DiffMateriality.HIGH
                and c.change_type != ChangeType.UNCHANGED
            )
            for d in self.diffs
        )

    @property
    def proposals_count(self) -> int:
        return sum(len(d.assumption_proposals) for d in self.diffs)

    def append_diff(self, diff: EpisodeDiff) -> None:
        """Append a new diff. Never removes or modifies existing diffs."""
        self.diffs.append(diff)
        self.updated_at = datetime.utcnow()
