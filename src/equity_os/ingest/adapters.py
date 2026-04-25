"""Logical source type adapters.

Maps each logical_type to:
  - the corresponding SourceType enum value
  - a default reliability_score
  - a metadata_extractor function (parses extracted text for type-specific fields)

Filename-prefix detection table lets the pipeline infer logical_type from
the raw filename when no frontmatter is present.

Logical types
-------------
  filing                    SEC/regulatory document (10-K, 10-Q, 8-K, proxy)
  earnings_transcript       Full earnings call transcript
  investor_presentation_notes  Investor day / conference notes
  industry_note             Sector/industry research note
  news_note                 Curated news summary or clipping
  management_commentary     CEO/CFO written commentary or letter
  channel_check_note        Primary research from supply chain / customers
"""

from __future__ import annotations

import re
from typing import Any

# SourceType values (string, avoids importing schemas here)
_SOURCE_TYPES: dict[str, str] = {
    "filing":                       "FILING",
    "earnings_transcript":          "EARNINGS_CALL",
    "investor_presentation_notes":  "RESEARCH_REPORT",
    "industry_note":                "RESEARCH_REPORT",
    "news_note":                    "NEWS_ARTICLE",
    "management_commentary":        "EARNINGS_CALL",
    "channel_check_note":           "CHANNEL_CHECK",
}

_RELIABILITY: dict[str, float] = {
    "filing":                       1.00,
    "earnings_transcript":          0.95,
    "management_commentary":        0.90,
    "investor_presentation_notes":  0.85,
    "channel_check_note":           0.70,
    "industry_note":                0.75,
    "news_note":                    0.60,
}

KNOWN_LOGICAL_TYPES = frozenset(_SOURCE_TYPES)

# Filename prefix → logical_type (longest match wins)
_PREFIX_MAP: list[tuple[str, str]] = sorted(
    [
        ("filing", "filing"),
        ("earnings_transcript", "earnings_transcript"),
        ("earnings", "earnings_transcript"),
        ("transcript", "earnings_transcript"),
        ("investor_presentation", "investor_presentation_notes"),
        ("investor_pres", "investor_presentation_notes"),
        ("industry_note", "industry_note"),
        ("industry", "industry_note"),
        ("news_note", "news_note"),
        ("news", "news_note"),
        ("management_commentary", "management_commentary"),
        ("management", "management_commentary"),
        ("ceo_letter", "management_commentary"),
        ("channel_check", "channel_check_note"),
        ("channel", "channel_check_note"),
        ("check", "channel_check_note"),
    ],
    key=lambda x: -len(x[0]),  # longest prefix first
)


def infer_logical_type_from_filename(filename: str) -> str | None:
    """Try to infer logical_type from the filename stem (case-insensitive)."""
    stem = filename.lower().rsplit(".", 1)[0]
    for prefix, ltype in _PREFIX_MAP:
        if stem.startswith(prefix):
            return ltype
    return None


def source_type_for(logical_type: str) -> str:
    return _SOURCE_TYPES.get(logical_type, "OTHER")


def reliability_for(logical_type: str) -> float:
    return _RELIABILITY.get(logical_type, 0.70)


# ---------------------------------------------------------------------------
# Metadata extractors
# ---------------------------------------------------------------------------


def _extract_filing_meta(text: str, meta: dict[str, Any]) -> dict[str, Any]:
    """Try to pull filing type and period from text."""
    out: dict[str, Any] = {}
    filing_types = re.findall(
        r"\b(10-K|10-Q|8-K|DEF 14A|S-1|20-F|6-K|proxy statement)\b",
        text, re.IGNORECASE
    )
    if filing_types:
        out["detected_filing_types"] = list(dict.fromkeys(
            ft.upper() for ft in filing_types
        ))
    cik = re.search(r"\bCIK[:\s#]*(\d{7,10})\b", text)
    if cik:
        out["cik"] = cik.group(1)
    periods = re.findall(
        r"(?:fiscal year|FY|quarter|Q[1-4])\s+(?:ended|ending)?\s*"
        r"(?:January|February|March|April|May|June|July|August|September|October|November|December)?\s*"
        r"\d{4}",
        text, re.IGNORECASE
    )
    if periods:
        out["periods_mentioned"] = periods[:5]
    return out


def _extract_earnings_meta(text: str, meta: dict[str, Any]) -> dict[str, Any]:
    """Extract quarter/year and speaker names from transcript text."""
    out: dict[str, Any] = {}
    qmatch = re.search(r"\b(Q[1-4])\s+(?:FY)?(\d{4})\b", text, re.IGNORECASE)
    if qmatch:
        out["quarter"] = qmatch.group(1).upper()
        out["fiscal_year"] = int(qmatch.group(2))
    # Rough speaker detection: lines like "TIM COOK:" or "Operator:"
    speakers = re.findall(r"^([A-Z][A-Za-z\s]{2,40}):\s", text, re.MULTILINE)
    if speakers:
        out["detected_speakers"] = list(dict.fromkeys(speakers[:10]))
    return out


def _extract_channel_check_meta(text: str, meta: dict[str, Any]) -> dict[str, Any]:
    """Extract geography, product area from channel check notes."""
    out: dict[str, Any] = {}
    geos = re.findall(
        r"\b(US|Europe|EMEA|Asia|China|Japan|India|Latin America|APAC)\b",
        text, re.IGNORECASE
    )
    if geos:
        out["geographies"] = list(dict.fromkeys(g.upper() for g in geos[:8]))
    contact_types = re.findall(
        r"\b(reseller|distributor|retailer|supplier|OEM|VAR|channel partner)\b",
        text, re.IGNORECASE
    )
    if contact_types:
        out["contact_types"] = list(dict.fromkeys(ct.lower() for ct in contact_types[:5]))
    return out


def _extract_generic_meta(text: str, meta: dict[str, Any]) -> dict[str, Any]:
    """Generic stats applicable to all types."""
    return {
        "word_count": len(text.split()),
        "char_count": len(text),
        "line_count": text.count("\n") + 1,
    }


_EXTRACTORS: dict[str, Any] = {
    "filing":                       _extract_filing_meta,
    "earnings_transcript":          _extract_earnings_meta,
    "management_commentary":        _extract_earnings_meta,
    "channel_check_note":           _extract_channel_check_meta,
}


def extract_metadata(
    logical_type: str,
    text: str,
    frontmatter_meta: dict[str, Any],
) -> dict[str, Any]:
    """Run type-specific + generic metadata extraction.

    Returns a merged dict of discovered metadata. Frontmatter-supplied values
    are not repeated here; they're stored in the top-level IngestedEvidence fields.
    Unknown frontmatter keys ARE included so nothing is silently dropped.
    """
    meta: dict[str, Any] = _extract_generic_meta(text, frontmatter_meta)

    # Run type-specific extractor
    specific = _EXTRACTORS.get(logical_type)
    if specific:
        meta.update(specific(text, frontmatter_meta))

    # Include any frontmatter keys that aren't top-level IngestedEvidence fields
    _top_level = {"logical_type", "title", "source_date", "source_name",
                  "url", "reliability_score"}
    for k, v in frontmatter_meta.items():
        if k not in _top_level:
            meta.setdefault(f"frontmatter_{k}", v)

    return meta
