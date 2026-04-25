"""Schemas for locally-ingested document evidence.

IngestedEvidence is the raw-document record; it is NOT the same as
EvidenceItem (which is the domain object used in a ThesisEpisode).
An analyst later selects specific IngestedEvidence chunks and promotes
them into EvidenceItems with a thesis direction (SUPPORTING / CONTRADICTING).

Storage path: companies/{ticker}/evidence/{evidence_id}.json
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


class TextChunk(BaseModel):
    """A contiguous passage of text within a document, with a citation anchor.

    chunk_id format: {ticker}-{evidence_id_prefix}-{index:04d}
    Example: AAPL-ab12cd34-0003
    """

    chunk_id: str                 # citation anchor — stable, human-readable
    index: int                    # 0-based position in document
    text: str                     # the chunk text (normalized)
    char_start: int               # character offset into IngestedEvidence.text
    char_end: int
    word_count: int
    content_hash: str             # sha256 of normalized chunk text


class EvidenceManifestEntry(BaseModel):
    """Lightweight catalog entry written to _catalog.json."""

    evidence_id: UUID
    ticker: str
    logical_type: str
    title: str
    source_date: date | None
    source_name: str
    content_hash: str
    chunk_count: int
    ingested_at: datetime
    file_path: str


class IngestedEvidence(BaseModel):
    """A normalized document ingested from inputs/{ticker}/."""

    evidence_id: UUID = Field(default_factory=uuid4)
    ticker: str
    logical_type: str             # "filing" | "earnings_transcript" | etc.
    source_type: str              # SourceType enum value
    title: str
    source_date: date | None = None
    source_name: str
    url: str | None = None
    reliability_score: float = Field(ge=0.0, le=1.0, default=0.8)
    text: str                     # full normalized plain text
    extracted_metadata: dict[str, Any] = Field(default_factory=dict)
    chunks: list[TextChunk] = Field(default_factory=list)
    content_hash: str             # sha256 of full normalized text
    file_path: str                # original input path (relative to repo root)
    ingested_at: datetime = Field(default_factory=datetime.utcnow)

    def manifest_entry(self) -> EvidenceManifestEntry:
        return EvidenceManifestEntry(
            evidence_id=self.evidence_id,
            ticker=self.ticker,
            logical_type=self.logical_type,
            title=self.title,
            source_date=self.source_date,
            source_name=self.source_name,
            content_hash=self.content_hash,
            chunk_count=len(self.chunks),
            ingested_at=self.ingested_at,
            file_path=self.file_path,
        )
