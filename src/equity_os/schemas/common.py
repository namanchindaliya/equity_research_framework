"""Shared primitive models: SourceMetadata, EvidenceItem."""

from __future__ import annotations

from datetime import date, datetime
from typing import Annotated
from uuid import UUID, uuid4

from pydantic import BaseModel, Field

from .enums import EvidenceDirection, EvidenceType, SourceType

# Reusable type alias for confidence / probability / reliability — all 0-1 floats.
Confidence = Annotated[float, Field(ge=0.0, le=1.0)]


class SourceMetadata(BaseModel):
    """Provenance record for any piece of information entering the system."""

    id: UUID = Field(default_factory=uuid4)
    source_type: SourceType
    name: str                         # e.g. "Apple 10-K FY2025", "Expert call transcript"
    reference: str | None = None      # URL, EDGAR accession, Bloomberg ID, etc.
    published_at: date | None = None
    accessed_at: datetime = Field(default_factory=datetime.utcnow)
    # 0 = unreliable / unverified, 1 = primary authoritative source
    reliability_score: Confidence = 0.8
    notes: str | None = None


class EvidenceItem(BaseModel):
    """A discrete piece of evidence that supports or contradicts a thesis element.

    Keeping evidence separate from the claim it supports lets the orchestrator
    reason about evidence quality independently of how it was used.
    """

    id: UUID = Field(default_factory=uuid4)
    evidence_type: EvidenceType
    direction: EvidenceDirection
    content: str                       # the verbatim or paraphrased evidence
    source: SourceMetadata | None = None
    confidence: Confidence = 0.8       # confidence that content is accurate
    tags: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=datetime.utcnow)
