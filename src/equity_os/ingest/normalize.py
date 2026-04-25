"""Text normalisation: raw file → clean plain text + frontmatter metadata.

Supported input formats (stdlib only — no external parsers):
  .txt   plain text
  .md    markdown (strip syntax, preserve structure)
  .html  HTML (stdlib html.parser; strips tags, extracts meta)
  .csv   tabular data (stdlib csv; joins as "field: value" lines)

Frontmatter format (YAML-lite, parsed without PyYAML):
  ---
  logical_type: earnings_transcript
  title: Apple Q1 FY2026 Earnings Call
  source_date: 2026-01-30
  source_name: Apple Inc.
  url: https://investor.apple.com/q1-2026
  reliability_score: 0.95
  ---
  <body text>

Any extra keys become extracted_metadata.
"""

from __future__ import annotations

import csv
import io
import re
import unicodedata
from html.parser import HTMLParser
from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------------
# Frontmatter
# ---------------------------------------------------------------------------

_FRONTMATTER_RE = re.compile(r"^---[ \t]*\r?\n(.*?)\r?\n---[ \t]*\r?\n", re.DOTALL)

_KNOWN_FRONT_KEYS = {
    "logical_type", "title", "source_date", "source_name",
    "url", "reliability_score",
}


def parse_frontmatter(raw: str) -> tuple[dict[str, Any], str]:
    """Return (metadata_dict, body_text).

    Recognised frontmatter keys are returned directly; unknown keys land in
    the dict under their original names so adapters can pick them up as
    extracted_metadata.
    """
    m = _FRONTMATTER_RE.match(raw)
    if not m:
        return {}, raw

    meta: dict[str, Any] = {}
    for line in m.group(1).splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if ":" not in line:
            continue
        key, _, value = line.partition(":")
        meta[key.strip()] = value.strip()

    body = raw[m.end():]
    return meta, body


# ---------------------------------------------------------------------------
# Unicode + whitespace normalisation
# ---------------------------------------------------------------------------

_SMART_QUOTES = str.maketrans({
    "‘": "'", "’": "'",
    "“": '"', "”": '"',
    "–": "-", "—": "--",
    " ": " ",              # non-breaking space
    "​": "",               # zero-width space
    "‌": "", "‍": "",
    "﻿": "",               # BOM
})


def normalize_unicode(text: str) -> str:
    """NFKC normalise, fix smart quotes, strip zero-width chars."""
    text = unicodedata.normalize("NFKC", text)
    return text.translate(_SMART_QUOTES)


def normalize_whitespace(text: str) -> str:
    """Collapse intra-paragraph whitespace; preserve paragraph breaks."""
    # Standardise line endings
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    # Collapse 3+ blank lines to exactly 2 (one paragraph break)
    text = re.sub(r"\n{3,}", "\n\n", text)
    # Collapse runs of spaces/tabs within a line to a single space
    lines = []
    for line in text.split("\n"):
        lines.append(re.sub(r"[ \t]+", " ", line).rstrip())
    return "\n".join(lines).strip()


def full_normalize(text: str) -> str:
    return normalize_whitespace(normalize_unicode(text))


# ---------------------------------------------------------------------------
# Format-specific extractors
# ---------------------------------------------------------------------------


def extract_txt(raw: str) -> tuple[dict[str, Any], str]:
    meta, body = parse_frontmatter(raw)
    return meta, full_normalize(body)


# -- Markdown ----------------------------------------------------------------

_MD_STRIP = [
    (re.compile(r"^#{1,6}\s+", re.MULTILINE), ""),   # headings
    (re.compile(r"!\[.*?\]\([^)]*\)"), ""),            # images
    (re.compile(r"\[([^\]]+)\]\([^)]*\)"), r"\1"),    # links → label
    (re.compile(r"(`{1,3})[^`]*\1"), ""),              # code spans/blocks
    (re.compile(r"^\s*```.*?```\s*$", re.DOTALL | re.MULTILINE), ""),
    (re.compile(r"[*_]{1,2}([^*_]+)[*_]{1,2}"), r"\1"), # bold/italic
    (re.compile(r"^\s*[-*+]\s+", re.MULTILINE), ""),  # unordered list markers
    (re.compile(r"^\s*\d+\.\s+", re.MULTILINE), ""),  # ordered list markers
    (re.compile(r"^\s*\|.*\|\s*$", re.MULTILINE), ""), # table rows
    (re.compile(r"^\s*[-|:]+\s*$", re.MULTILINE), ""), # table dividers
    (re.compile(r"^>\s+", re.MULTILINE), ""),          # blockquotes
]


def extract_md(raw: str) -> tuple[dict[str, Any], str]:
    meta, body = parse_frontmatter(raw)
    for pattern, repl in _MD_STRIP:
        body = pattern.sub(repl, body)
    return meta, full_normalize(body)


# -- HTML -------------------------------------------------------------------


class _TextExtractor(HTMLParser):
    _BLOCK_TAGS = frozenset(
        "p div h1 h2 h3 h4 h5 h6 li tr td th article section header footer "
        "blockquote pre".split()
    )
    _SKIP_TAGS = frozenset("script style head noscript svg".split())

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._parts: list[str] = []
        self._skip_depth = 0
        self._meta: dict[str, str] = {}

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag_l = tag.lower()
        if tag_l in self._SKIP_TAGS:
            self._skip_depth += 1
        if tag_l in self._BLOCK_TAGS:
            self._parts.append("\n")
        if tag_l == "meta":
            attr_d = dict(attrs)
            name = attr_d.get("name", "")
            content = attr_d.get("content", "")
            if name and content:
                self._meta[name] = content
        if tag_l == "br":
            self._parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() in self._SKIP_TAGS:
            self._skip_depth = max(0, self._skip_depth - 1)

    def handle_data(self, data: str) -> None:
        if self._skip_depth == 0:
            self._parts.append(data)

    def get_text(self) -> str:
        return "".join(self._parts)

    def get_meta(self) -> dict[str, str]:
        return self._meta


def extract_html(raw: str) -> tuple[dict[str, Any], str]:
    # Frontmatter before <html> tag (unlikely but supported)
    meta, body = parse_frontmatter(raw)
    extractor = _TextExtractor()
    extractor.feed(body if meta else raw)
    html_meta = extractor.get_meta()
    # Merge: frontmatter wins over HTML meta
    for k, v in html_meta.items():
        if k not in meta:
            meta[k] = v
    return meta, full_normalize(extractor.get_text())


# -- CSV --------------------------------------------------------------------


def extract_csv(raw: str) -> tuple[dict[str, Any], str]:
    """Convert CSV to 'field: value' plain text, one entry per row."""
    meta, body = parse_frontmatter(raw)
    reader = csv.DictReader(io.StringIO(body if meta else raw))
    lines: list[str] = []
    for i, row in enumerate(reader):
        parts = [f"{k.strip()}: {v.strip()}" for k, v in row.items() if v and v.strip()]
        if parts:
            lines.append("  ".join(parts))
    text = "\n".join(lines)
    return meta, full_normalize(text)


# ---------------------------------------------------------------------------
# Dispatcher
# ---------------------------------------------------------------------------

_EXTRACTORS = {
    ".txt":  extract_txt,
    ".md":   extract_md,
    ".html": extract_html,
    ".htm":  extract_html,
    ".csv":  extract_csv,
}

SUPPORTED_EXTENSIONS = frozenset(_EXTRACTORS)


def extract(path: Path) -> tuple[dict[str, Any], str]:
    """Read a file and return (metadata_dict, normalised_plain_text).

    Raises ValueError for unsupported extensions.
    """
    ext = path.suffix.lower()
    if ext not in _EXTRACTORS:
        raise ValueError(
            f"Unsupported file type {ext!r}. Supported: {sorted(SUPPORTED_EXTENSIONS)}"
        )
    raw = path.read_text(encoding="utf-8", errors="replace")
    return _EXTRACTORS[ext](raw)
