"""Tests for normalize.py: extraction, frontmatter, format-specific stripping."""

from __future__ import annotations

from pathlib import Path

import pytest

from equity_os.ingest.normalize import (
    extract,
    extract_csv,
    extract_html,
    extract_md,
    extract_txt,
    full_normalize,
    normalize_unicode,
    normalize_whitespace,
    parse_frontmatter,
)
from tests.test_ingest.conftest import AAPL_INPUTS


# ---------------------------------------------------------------------------
# Frontmatter parsing
# ---------------------------------------------------------------------------


class TestParseFrontmatter:
    def test_extracts_known_keys(self):
        raw = "---\ntitle: My Doc\nsource_date: 2026-01-01\n---\nbody text"
        meta, body = parse_frontmatter(raw)
        assert meta["title"] == "My Doc"
        assert meta["source_date"] == "2026-01-01"
        assert body.strip() == "body text"

    def test_no_frontmatter_returns_empty_meta(self):
        raw = "Just plain text\nno frontmatter"
        meta, body = parse_frontmatter(raw)
        assert meta == {}
        assert body == raw

    def test_unknown_keys_preserved(self):
        raw = "---\ncustom_field: hello\n---\ntext"
        meta, _ = parse_frontmatter(raw)
        assert meta["custom_field"] == "hello"

    def test_colon_in_value(self):
        raw = "---\nurl: https://example.com/path?a=1\n---\ntext"
        meta, _ = parse_frontmatter(raw)
        assert meta["url"] == "https://example.com/path?a=1"

    def test_empty_body_after_frontmatter(self):
        raw = "---\ntitle: T\n---\n"
        meta, body = parse_frontmatter(raw)
        assert meta["title"] == "T"
        assert body.strip() == ""


# ---------------------------------------------------------------------------
# Unicode normalisation
# ---------------------------------------------------------------------------


class TestNormalizeUnicode:
    def test_smart_quotes_replaced(self):
        text = "‘Hello’ and “world”"
        result = normalize_unicode(text)
        assert "'" in result and '"' in result
        assert "‘" not in result

    def test_em_dash_replaced(self):
        result = normalize_unicode("revenue—growth")
        assert "--" in result

    def test_nbspc_replaced(self):
        result = normalize_unicode("a b")
        assert " " in result and " " not in result

    def test_nfkc_normalises_ligatures(self):
        result = normalize_unicode("ﬁnancial")  # ﬁ ligature
        assert result == "financial"


class TestNormalizeWhitespace:
    def test_collapses_multiple_spaces(self):
        result = normalize_whitespace("foo   bar")
        assert result == "foo bar"

    def test_preserves_paragraph_breaks(self):
        result = normalize_whitespace("para one\n\npara two")
        assert "\n\n" in result

    def test_collapses_triple_newlines(self):
        result = normalize_whitespace("a\n\n\n\nb")
        assert result.count("\n\n") == 1

    def test_strips_trailing_spaces_on_lines(self):
        result = normalize_whitespace("hello   \nworld")
        assert "hello\nworld" == result


# ---------------------------------------------------------------------------
# Format extractors
# ---------------------------------------------------------------------------


class TestExtractTxt:
    def test_fixture_filing(self):
        meta, text = extract(AAPL_INPUTS / "filing_10k_fy2025.txt")
        assert meta["logical_type"] == "filing"
        assert meta["title"] == "Apple Inc. Annual Report on Form 10-K FY2025"
        assert "Apple Inc." in text
        assert "Services" in text

    def test_no_frontmatter_txt(self, tmp_path: Path):
        f = tmp_path / "plain.txt"
        f.write_text("Hello world.\n\nSecond paragraph.")
        meta, text = extract(f)
        assert meta == {}
        assert "Hello world" in text


class TestExtractMd:
    def test_fixture_transcript(self):
        meta, text = extract(AAPL_INPUTS / "earnings_transcript_q1_fy2026.md")
        assert meta["logical_type"] == "earnings_transcript"
        assert "Apple" in text
        assert meta["source_date"] == "2026-01-30"

    def test_strips_markdown_headers(self, tmp_path: Path):
        f = tmp_path / "doc.md"
        f.write_text("# Big Heading\n\n## Sub\n\nContent here.")
        meta, text = extract(f)
        assert "# Big Heading" not in text
        assert "Content here" in text

    def test_strips_bold_inline(self, tmp_path: Path):
        f = tmp_path / "doc.md"
        f.write_text("This is **important** text.")
        _, text = extract(f)
        assert "**" not in text
        assert "important" in text

    def test_strips_markdown_links(self, tmp_path: Path):
        f = tmp_path / "doc.md"
        f.write_text("See [this link](https://example.com) for details.")
        _, text = extract(f)
        assert "](https" not in text
        assert "this link" in text


class TestExtractHtml:
    def test_fixture_news(self):
        meta, text = extract(AAPL_INPUTS / "news_note_dma_ruling.html")
        assert "EU" in text or "Apple" in text
        assert "<p>" not in text
        assert "<h1>" not in text

    def test_html_meta_tags_extracted(self):
        meta, text = extract(AAPL_INPUTS / "news_note_dma_ruling.html")
        assert meta.get("logical_type") == "news_note"
        assert meta.get("source_name") == "Financial Times"

    def test_strips_script_content(self, tmp_path: Path):
        f = tmp_path / "page.html"
        f.write_text("<html><body><script>alert(1)</script><p>Real content</p></body></html>")
        _, text = extract(f)
        assert "alert" not in text
        assert "Real content" in text

    def test_strips_style_content(self, tmp_path: Path):
        f = tmp_path / "page.html"
        f.write_text("<html><body><style>.cls{color:red}</style><p>Visible</p></body></html>")
        _, text = extract(f)
        assert "color:red" not in text
        assert "Visible" in text


class TestExtractCsv:
    def test_fixture_channel_check(self):
        meta, text = extract(AAPL_INPUTS / "channel_check_q1_asia.csv")
        assert meta["logical_type"] == "channel_check_note"
        assert "India" in text or "China" in text

    def test_converts_rows_to_text(self, tmp_path: Path):
        f = tmp_path / "data.csv"
        f.write_text("name,value\nrevenue,100\ngrowth,0.14\n")
        _, text = extract(f)
        assert "revenue" in text
        assert "100" in text

    def test_csv_without_frontmatter(self, tmp_path: Path):
        f = tmp_path / "data.csv"
        f.write_text("key,val\na,b\nc,d\n")
        meta, text = extract(f)
        assert meta == {}
        assert "a" in text


class TestUnsupportedExtension:
    def test_raises_value_error(self, tmp_path: Path):
        f = tmp_path / "doc.pdf"
        f.write_text("content")
        with pytest.raises(ValueError, match="Unsupported file type"):
            extract(f)
