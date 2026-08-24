"""PredictionRecord and ResolutionRecord — explicit, resolvable forecasts."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, Field, model_validator

from .common import Confidence, SourceMetadata
from .enums import ComparisonOperator, MaterialityLevel, ResolutionStatus


class ResolutionRecord(BaseModel):
    """The factual outcome that closes a PredictionRecord.

    Kept as a separate sub-object so it can be attached without mutating
    the original prediction fields, and so it carries its own provenance.

    ``error_magnitude`` is signed: positive = overestimate, negative = underestimate.
    For non-numeric predictions set it to None.
    """

    id: UUID = Field(default_factory=uuid4)
    prediction_id: UUID
    resolved_at: datetime = Field(default_factory=datetime.utcnow)
    resolved_by: str                          # agent or analyst id
    resolved_status: ResolutionStatus
    actual_outcome: Any                        # raw observed value
    error_magnitude: float | None = None       # (actual - target) / |target|, if numeric
    notes: str
    source: SourceMetadata | None = None       # where the actual outcome came from


class PredictionRecord(BaseModel):
    """An explicit, falsifiable forecast attached to a thesis episode.

    Design rationale
    ----------------
    - ``metric`` is the machine-readable name of what will be measured
      (e.g. "aapl_services_revenue_usd_b_fy26").
    - ``threshold`` is the specific value the metric will be compared against.
    - ``operator`` defines the comparison (>, >=, ==, in_range, etc.).
    - ``probability`` is the analyst's assessed probability of hitting the
      threshold — distinct from ``confidence``, which measures how certain
      the analyst is in their probability estimate itself.
    - ``resolution_rule`` is a plain-language description of exactly how the
      outcome will be determined (prevents disputes at resolution time).
    - ``due_date`` is the hard deadline: if unresolved by then it is EXPIRED.
    - ``supporting_assumptions`` links back to the AssumptionRecord IDs this
      prediction depends on, so assumption revisions can flag affected predictions.
    """

    id: UUID = Field(default_factory=uuid4)
    description: str                           # plain-language claim
    metric: str                                # machine-readable metric name
    threshold: Any                             # value to compare against
    unit: str | None = None                    # e.g. "USD B", "%", "x"
    operator: ComparisonOperator = ComparisonOperator.GTE
    horizon: str                               # narrative label, e.g. "FY2026 earnings"
    due_date: date                             # hard resolution deadline
    probability: Confidence = 0.6              # analyst-assigned probability 0-1
    confidence: Confidence = 0.7              # confidence in the probability estimate
    materiality: MaterialityLevel = MaterialityLevel.MEDIUM
    resolution_rule: str                       # unambiguous rule for resolving
    resolution: ResolutionRecord | None = None
    supporting_assumptions: list[UUID] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    @property
    def is_resolved(self) -> bool:
        return self.resolution is not None

    @model_validator(mode="after")
    def resolved_status_consistent(self) -> PredictionRecord:
        """A resolved prediction must have its resolution before the due_date check."""
        if self.resolution is not None:
            if self.resolution.prediction_id != self.id:
                raise ValueError(
                    f"ResolutionRecord.prediction_id {self.resolution.prediction_id} "
                    f"does not match PredictionRecord.id {self.id}."
                )
        return self

    def resolve(
        self,
        resolved_status: ResolutionStatus,
        actual_outcome: Any,
        notes: str,
        resolved_by: str,
        source: SourceMetadata | None = None,
    ) -> PredictionRecord:
        """Return a copy of this prediction with a ResolutionRecord attached."""
        if self.is_resolved:
            raise ValueError(f"Prediction {self.id} is already resolved.")
        error: float | None = None
        if isinstance(self.threshold, (int, float)) and isinstance(actual_outcome, (int, float)):
            if self.threshold != 0:
                error = (actual_outcome - self.threshold) / abs(self.threshold)
        resolution = ResolutionRecord(
            prediction_id=self.id,
            resolved_status=resolved_status,
            actual_outcome=actual_outcome,
            error_magnitude=error,
            notes=notes,
            resolved_by=resolved_by,
            source=source,
        )
        return self.model_copy(
            update={"resolution": resolution, "updated_at": datetime.utcnow()}
        )
