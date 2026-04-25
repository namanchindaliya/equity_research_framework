"""AssumptionRecord and AssumptionChange — versioned, owner-attributed assumptions."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, Field, model_validator

from .common import Confidence, EvidenceItem
from .enums import AssumptionStatus, MaterialityLevel


class AssumptionChange(BaseModel):
    """Immutable record of a single revision to an AssumptionRecord.

    Never deleted — the history list on AssumptionRecord is append-only.
    """

    id: UUID = Field(default_factory=uuid4)
    assumption_id: UUID
    version: int                          # version number *after* this change
    changed_by: str                       # agent name or analyst id
    changed_at: datetime = Field(default_factory=datetime.utcnow)
    previous_value: Any
    new_value: Any
    previous_confidence: Confidence
    new_confidence: Confidence
    reason: str                           # why the assumption was revised


class AssumptionRecord(BaseModel):
    """A first-class assumption with owner, confidence, materiality, and full history.

    Design rationale
    ----------------
    - ``key`` is a machine-readable slug (e.g. "services_rev_cagr_3yr").
    - ``label`` is the human-readable display name.
    - ``version`` starts at 1 and increments with every revision.
    - ``dependencies`` lists other AssumptionRecord IDs whose values this
      assumption is derived from or sensitive to.  The orchestrator uses this
      graph to propagate confidence changes.
    - ``materiality`` indicates thesis sensitivity: CRITICAL means a meaningful
      miss on this assumption invalidates the thesis outright.
    - ``history`` is append-only; the current value is always the top-level field.
    """

    id: UUID = Field(default_factory=uuid4)
    key: str                              # machine slug, unique within an episode
    label: str                            # display name
    value: Any
    unit: str | None = None               # e.g. "%", "USD B", "x"
    owner_agent: str                      # agent or analyst responsible for this assumption
    rationale: str                        # why this value was chosen
    confidence: Confidence = 0.7
    materiality: MaterialityLevel = MaterialityLevel.MEDIUM
    dependencies: list[UUID] = Field(default_factory=list)  # other AssumptionRecord IDs
    supporting_evidence: list[EvidenceItem] = Field(default_factory=list)
    status: AssumptionStatus = AssumptionStatus.ACTIVE
    version: int = 1
    history: list[AssumptionChange] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    @model_validator(mode="after")
    def history_versions_consistent(self) -> AssumptionRecord:
        """History length must be version - 1 (one entry per past revision)."""
        if len(self.history) != self.version - 1:
            raise ValueError(
                f"Assumption {self.id}: history has {len(self.history)} entries "
                f"but version is {self.version} (expected {self.version - 1} history entries)."
            )
        return self

    def revise(
        self,
        new_value: Any,
        new_confidence: Confidence,
        reason: str,
        changed_by: str,
        unit: str | None = None,
    ) -> AssumptionRecord:
        """Return a new AssumptionRecord with updated value and appended history.

        Does not mutate self — callers replace the record in the episode list.
        """
        change = AssumptionChange(
            assumption_id=self.id,
            version=self.version + 1,
            changed_by=changed_by,
            previous_value=self.value,
            new_value=new_value,
            previous_confidence=self.confidence,
            new_confidence=new_confidence,
            reason=reason,
        )
        return self.model_copy(
            update={
                "value": new_value,
                "unit": unit if unit is not None else self.unit,
                "confidence": new_confidence,
                "version": self.version + 1,
                "history": [*self.history, change],
                "updated_at": datetime.utcnow(),
            }
        )
