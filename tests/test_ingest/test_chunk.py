"""Tests for chunk.py: chunking logic, citation anchors, edge cases."""

from __future__ import annotations

import pytest

from equity_os.ingest.chunk import (
    MAX_CHARS,
    MIN_CHARS,
    TARGET_CHARS,
    chunk_text,
    _merge_short,
    _split_paragraph,
)


TICKER = "AAPL"
ID_PREFIX = "ab12cd34"


class TestSplitParagraph:
    def test_short_paragraph_unchanged(self):
        para = "Short paragraph under max chars."
        result = _split_paragraph(para)
        assert result == [para]

    def test_long_paragraph_split_at_sentences(self):
        # Build a paragraph that's clearly too long
        sentence = "This is a sentence that contributes to the length of the paragraph. "
        long_para = sentence * 30  # definitely > MAX_CHARS
        result = _split_paragraph(long_para)
        assert len(result) > 1
        for part in result:
            assert len(part) <= MAX_CHARS

    def test_very_long_single_sentence_force_split(self):
        # A single sentence with no punctuation that exceeds MAX_CHARS
        long = "x" * (MAX_CHARS + 100)
        result = _split_paragraph(long)
        assert len(result) >= 2
        for part in result:
            assert len(part) <= MAX_CHARS


class TestMergeShort:
    def test_merges_sub_minimum(self):
        passages = ["Tiny.", "Also tiny.", "This is long enough to stand alone as a real passage."]
        result = _merge_short(passages)
        # The two tiny ones should merge with the long one
        assert len(result) < len(passages)

    def test_all_above_min_unchanged(self):
        passages = ["X" * MIN_CHARS, "Y" * MIN_CHARS, "Z" * MIN_CHARS]
        result = _merge_short(passages)
        assert len(result) == 3

    def test_single_tiny_appended_to_last(self):
        passages = ["A solid paragraph here with enough content.", "Tiny."]
        result = _merge_short(passages)
        assert len(result) == 1
        assert "Tiny" in result[0]


class TestChunkText:
    def _sample_text(self, n_paragraphs: int = 5, words_per_para: int = 60) -> str:
        word = "information "
        para = word * words_per_para
        return "\n\n".join(para.strip() for _ in range(n_paragraphs))

    def test_produces_chunks(self):
        text = self._sample_text(5)
        chunks = chunk_text(text, TICKER, ID_PREFIX)
        assert len(chunks) >= 1

    def test_citation_anchors_format(self):
        text = self._sample_text(3)
        chunks = chunk_text(text, TICKER, ID_PREFIX)
        for chunk in chunks:
            assert chunk.chunk_id.startswith(f"{TICKER}-{ID_PREFIX}-")
            # Last part is a 4-digit index
            idx_str = chunk.chunk_id.split("-")[-1]
            assert idx_str.isdigit() and len(idx_str) == 4

    def test_chunk_indices_sequential(self):
        text = self._sample_text(5)
        chunks = chunk_text(text, TICKER, ID_PREFIX)
        for i, chunk in enumerate(chunks):
            assert chunk.index == i

    def test_char_offsets_within_text(self):
        text = self._sample_text(3)
        chunks = chunk_text(text, TICKER, ID_PREFIX)
        for chunk in chunks:
            assert 0 <= chunk.char_start < len(text)
            assert chunk.char_end <= len(text)
            assert chunk.char_start < chunk.char_end

    def test_chunk_text_matches_slice(self):
        text = self._sample_text(3)
        chunks = chunk_text(text, TICKER, ID_PREFIX)
        for chunk in chunks:
            slice_ = text[chunk.char_start:chunk.char_end]
            assert chunk.text == slice_

    def test_word_count_positive(self):
        text = self._sample_text(2)
        chunks = chunk_text(text, TICKER, ID_PREFIX)
        for chunk in chunks:
            assert chunk.word_count > 0

    def test_content_hash_hex_string(self):
        text = self._sample_text(2)
        chunks = chunk_text(text, TICKER, ID_PREFIX)
        for chunk in chunks:
            assert len(chunk.content_hash) == 64  # sha256 hex

    def test_each_chunk_under_max(self):
        sentence = "Revenue grew significantly across all product lines. "
        text = "\n\n".join(sentence * 40 for _ in range(3))
        chunks = chunk_text(text, TICKER, ID_PREFIX)
        for chunk in chunks:
            assert len(chunk.text) <= MAX_CHARS

    def test_empty_text_returns_empty(self):
        chunks = chunk_text("", TICKER, ID_PREFIX)
        assert chunks == []

    def test_single_short_paragraph(self):
        text = "Just one short paragraph with some useful content here."
        chunks = chunk_text(text, TICKER, ID_PREFIX)
        assert len(chunks) == 1
        assert chunks[0].text == text

    def test_no_noise_chunks(self):
        # Lines of whitespace / empty text should not produce chunks
        text = "\n\n\n\n\n"
        chunks = chunk_text(text, TICKER, ID_PREFIX)
        assert chunks == []

    def test_large_document_multiple_chunks(self):
        # Simulate a 10-page document
        sentence = "The company reported strong financial results for the quarter. "
        text = "\n\n".join((sentence * 25).strip() for _ in range(20))
        chunks = chunk_text(text, TICKER, ID_PREFIX)
        assert len(chunks) > 5

    def test_different_tickers_different_anchors(self):
        text = self._sample_text(2)
        aapl_chunks = chunk_text(text, "AAPL", ID_PREFIX)
        msft_chunks = chunk_text(text, "MSFT", ID_PREFIX)
        assert aapl_chunks[0].chunk_id.startswith("AAPL-")
        assert msft_chunks[0].chunk_id.startswith("MSFT-")
