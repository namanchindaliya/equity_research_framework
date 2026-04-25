"""Text extraction utilities shared across agents.

All functions are pure (no I/O, no randomness) so agents are deterministic.

Core pattern
------------
1. score_chunks()  — rank chunks by keyword density
2. build_ref()     — build an EvidenceRef from a chunk + its parent evidence
3. compute_confidence()  — consistent scoring formula used by all agents
4. extract_sentences_with_keywords()  — pull verbatim sentences that match terms
"""

from __future__ import annotations

import re
from typing import Sequence

from equity_os.ingest.models import IngestedEvidence, TextChunk

from .models import EvidenceRef


# ---------------------------------------------------------------------------
# Chunk scoring
# ---------------------------------------------------------------------------


def score_chunk(chunk: TextChunk, keywords: Sequence[str]) -> float:
    """Return keyword density score for one chunk: hits / (word_count + ε)."""
    text_lower = chunk.text.lower()
    hits = sum(
        len(re.findall(r"\b" + re.escape(kw.lower()) + r"\b", text_lower))
        for kw in keywords
    )
    return hits / max(chunk.word_count, 1)


def score_chunks(
    evidence_list: list[IngestedEvidence],
    keywords: Sequence[str],
    top_k: int = 6,
    logical_types: list[str] | None = None,
) -> list[tuple[TextChunk, IngestedEvidence, float]]:
    """Return (chunk, parent_evidence, score) for the top_k most relevant chunks.

    Parameters
    ----------
    evidence_list  : all IngestedEvidence records for this ticker
    keywords       : terms that indicate relevance to the analytical dimension
    top_k          : how many chunks to return
    logical_types  : if set, restrict to evidence of these logical types
    """
    scored: list[tuple[TextChunk, IngestedEvidence, float]] = []
    for ev in evidence_list:
        if logical_types and ev.logical_type not in logical_types:
            continue
        for chunk in ev.chunks:
            s = score_chunk(chunk, keywords)
            if s > 0:
                scored.append((chunk, ev, s))
    scored.sort(key=lambda x: x[2], reverse=True)
    return scored[:top_k]


# ---------------------------------------------------------------------------
# Evidence reference builder
# ---------------------------------------------------------------------------


def build_ref(chunk: TextChunk, ev: IngestedEvidence, max_quote: int = 250) -> EvidenceRef:
    """Create a citation reference from a chunk and its parent document."""
    return EvidenceRef(
        chunk_id=chunk.chunk_id,
        evidence_id=str(ev.evidence_id),
        source_title=ev.title,
        quote=chunk.text[:max_quote],
    )


# ---------------------------------------------------------------------------
# Confidence computation
# ---------------------------------------------------------------------------


def compute_confidence(
    hits: int,
    source_count: int,
    avg_reliability: float,
    *,
    hit_weight: float = 0.12,
    breadth_bonus: float = 0.15,
    max_conf: float = 0.95,
) -> float:
    """Consistent confidence formula used by all agents.

    confidence = min(max_conf, hits * hit_weight + breadth_bonus * (source_count > 1) * avg_reliability)

    - hits: total number of keyword matches across relevant chunks
    - source_count: distinct IngestedEvidence documents that contributed
    - avg_reliability: mean reliability_score of contributing sources
    """
    base = min(hits * hit_weight, 0.75)
    breadth = breadth_bonus if source_count > 1 else 0.0
    raw = (base + breadth) * avg_reliability
    return round(min(raw, max_conf), 3)


def avg_reliability(evidence_list: list[IngestedEvidence]) -> float:
    if not evidence_list:
        return 0.5
    return sum(e.reliability_score for e in evidence_list) / len(evidence_list)


# ---------------------------------------------------------------------------
# Keyword counting across evidence
# ---------------------------------------------------------------------------


def count_keyword_hits(
    evidence_list: list[IngestedEvidence],
    keywords: Sequence[str],
    logical_types: list[str] | None = None,
) -> tuple[int, list[IngestedEvidence]]:
    """Return (total_hits, list_of_contributing_evidence)."""
    total = 0
    contributors: list[IngestedEvidence] = []
    for ev in evidence_list:
        if logical_types and ev.logical_type not in logical_types:
            continue
        ev_hits = 0
        for chunk in ev.chunks:
            ev_hits += sum(
                len(re.findall(r"\b" + re.escape(kw.lower()) + r"\b", chunk.text.lower()))
                for kw in keywords
            )
        if ev_hits > 0:
            total += ev_hits
            contributors.append(ev)
    return total, contributors


# ---------------------------------------------------------------------------
# Sentence-level extraction
# ---------------------------------------------------------------------------


_SENT_SPLIT = re.compile(r"(?<=[.!?])\s+")


def extract_sentences_with_keywords(
    text: str,
    keywords: Sequence[str],
    max_results: int = 5,
) -> list[str]:
    """Return sentences that contain at least one keyword."""
    sentences = _SENT_SPLIT.split(text)
    pattern = re.compile(
        r"\b(" + "|".join(re.escape(kw) for kw in keywords) + r")\b",
        re.IGNORECASE,
    )
    hits = [s.strip() for s in sentences if pattern.search(s)]
    return hits[:max_results]


def first_match(
    evidence_list: list[IngestedEvidence],
    keywords: Sequence[str],
    logical_types: list[str] | None = None,
) -> str | None:
    """Return the first sentence from any chunk that contains a keyword."""
    for ev in evidence_list:
        if logical_types and ev.logical_type not in logical_types:
            continue
        for chunk in ev.chunks:
            sents = extract_sentences_with_keywords(chunk.text, keywords, 1)
            if sents:
                return sents[0]
    return None


# ---------------------------------------------------------------------------
# Dollar amount extraction
# ---------------------------------------------------------------------------


_DOLLAR_PATTERN = re.compile(
    r"\$\s*[\d,]+(?:\.\d+)?\s*(?:billion|million|B|M|bn|mm)?",
    re.IGNORECASE,
)


def extract_dollar_amounts(text: str) -> list[str]:
    return _DOLLAR_PATTERN.findall(text)


# ---------------------------------------------------------------------------
# Percentage extraction
# ---------------------------------------------------------------------------


_PCT_PATTERN = re.compile(r"(?<!\w)([\d.]+)\s*%")


def extract_percentages(text: str) -> list[str]:
    return [f"{m}%" for m in _PCT_PATTERN.findall(text)]


# ---------------------------------------------------------------------------
# Helpers for building Findings with refs
# ---------------------------------------------------------------------------


def build_finding_from_scored(
    text: str,
    scored: list[tuple[TextChunk, IngestedEvidence, float]],
    all_evidence: list[IngestedEvidence],
    keywords: Sequence[str],
) -> tuple[float, list[EvidenceRef]]:
    """Compute confidence and build refs from a scored chunk list."""
    if not scored:
        return 0.0, []

    refs = [build_ref(chunk, ev) for chunk, ev, _ in scored]
    contributing_ev = list({ev.evidence_id: ev for _, ev, _ in scored}.values())
    hits, _ = count_keyword_hits(all_evidence, keywords)
    conf = compute_confidence(
        hits=hits,
        source_count=len(contributing_ev),
        avg_reliability=avg_reliability(contributing_ev),
    )
    return conf, refs
