"""Paragraph-first chunking with sentence-level overflow splitting.

Strategy
--------
1. Split on double newlines (paragraph boundaries).
2. Any paragraph > MAX_CHARS is split at sentence boundaries (`. `, `! `, `? `).
3. Any sentence > MAX_CHARS is hard-split at MAX_CHARS.
4. Paragraphs < MIN_CHARS are merged with the next paragraph until MIN_CHARS
   is reached or no more paragraphs remain (prevents noise-only chunks).
5. Each chunk gets a deterministic citation anchor:
     {ticker}-{evidence_id_prefix}-{index:04d}
   e.g.  AAPL-ab12cd34-0003

Constants
---------
MIN_CHARS   80    below this, merge with next chunk
TARGET_CHARS 800  soft target — try to keep chunks around this size
MAX_CHARS  1600   hard limit before a sentence is force-split

The target/max values are calibrated for analyst-sized document passages:
short enough to be self-contained, long enough to carry context.
"""

from __future__ import annotations

import hashlib
import re

from .models import TextChunk

MIN_CHARS = 80
TARGET_CHARS = 800
MAX_CHARS = 1600

_SENTENCE_END = re.compile(r"(?<=[.!?])\s+")


def _sentences(text: str) -> list[str]:
    """Split text into sentences; preserves trailing whitespace cues."""
    return [s.strip() for s in _SENTENCE_END.split(text) if s.strip()]


def _split_long(text: str, max_chars: int) -> list[str]:
    """Force-split a passage that exceeds max_chars."""
    parts: list[str] = []
    while len(text) > max_chars:
        parts.append(text[:max_chars])
        text = text[max_chars:].lstrip()
    if text:
        parts.append(text)
    return parts


def _split_paragraph(para: str) -> list[str]:
    """Split one paragraph into passages ≤ MAX_CHARS."""
    if len(para) <= MAX_CHARS:
        return [para]

    # Try sentence-level split first
    sentences = _sentences(para)
    passages: list[str] = []
    current: list[str] = []
    current_len = 0

    for sent in sentences:
        sent_len = len(sent)
        if sent_len > MAX_CHARS:
            # Flush current buffer, then force-split
            if current:
                passages.append(" ".join(current))
                current, current_len = [], 0
            passages.extend(_split_long(sent, MAX_CHARS))
        elif current_len + sent_len + 1 > MAX_CHARS:
            passages.append(" ".join(current))
            current, current_len = [sent], sent_len
        else:
            current.append(sent)
            current_len += sent_len + 1

    if current:
        passages.append(" ".join(current))

    return passages


def _merge_short(passages: list[str]) -> list[str]:
    """Merge passages shorter than MIN_CHARS into the next one."""
    merged: list[str] = []
    carry = ""
    for p in passages:
        combined = (carry + " " + p).strip() if carry else p
        if len(combined) < MIN_CHARS:
            carry = combined
        else:
            merged.append(combined)
            carry = ""
    if carry:
        if merged:
            merged[-1] = (merged[-1] + " " + carry).strip()
        else:
            merged.append(carry)
    return merged


def chunk_text(
    text: str,
    ticker: str,
    evidence_id_prefix: str,
) -> list[TextChunk]:
    """Produce citation-ready TextChunks from a normalised plain text string."""
    # Step 1: split on paragraph boundaries
    paragraphs = [p.strip() for p in re.split(r"\n{2,}", text) if p.strip()]

    # Step 2: split long paragraphs
    passages: list[str] = []
    for para in paragraphs:
        passages.extend(_split_paragraph(para))

    # Step 3: merge sub-minimum passages
    passages = _merge_short(passages)

    # Step 4: build TextChunk objects with character offsets
    chunks: list[TextChunk] = []
    cursor = 0
    for idx, passage in enumerate(passages):
        # Find where this passage starts in the full text (first occurrence from cursor)
        pos = text.find(passage, cursor)
        if pos == -1:
            pos = cursor  # fallback (shouldn't happen with clean splits)
        char_start = pos
        char_end = pos + len(passage)
        cursor = char_end

        chunk_id = f"{ticker}-{evidence_id_prefix}-{idx:04d}"
        content_hash = hashlib.sha256(passage.encode("utf-8")).hexdigest()
        word_count = len(passage.split())

        chunks.append(
            TextChunk(
                chunk_id=chunk_id,
                index=idx,
                text=passage,
                char_start=char_start,
                char_end=char_end,
                word_count=word_count,
                content_hash=content_hash,
            )
        )

    return chunks
