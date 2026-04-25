"""Deterministic file-naming conventions.

All names are derived from domain properties, never from random state,
so the same inputs always produce the same path.
"""

from __future__ import annotations

import re
from datetime import date
from pathlib import Path
from uuid import UUID


def slugify(text: str) -> str:
    """Lower-case, hyphen-separated, filesystem-safe slug, capped at 48 chars."""
    text = text.lower().strip()
    text = re.sub(r"[^\w\s-]", "", text)
    text = re.sub(r"[\s_-]+", "-", text)
    return text.strip("-")[:48]


def episode_dir_name(title: str, created_at: date | None = None) -> str:
    """e.g. '2026-01-31_fy2026-services-initiation'"""
    d = created_at or date.today()
    return f"{d.isoformat()}_{slugify(title)}"


def unique_episode_dir_name(
    title: str, episodes_dir: Path, created_at: date | None = None
) -> str:
    """Like episode_dir_name but appends a counter if the dir already exists."""
    base = episode_dir_name(title, created_at)
    candidate = base
    counter = 1
    while (episodes_dir / candidate).exists():
        candidate = f"{base}-{counter}"
        counter += 1
    return candidate


def assumption_filename(key: str, version: int) -> str:
    """e.g. 'services_cagr_v003.json'"""
    return f"{key}_v{version:03d}.json"


def assumption_changes_filename(key: str) -> str:
    """Append-only change log: 'services_cagr_changes.jsonl'"""
    return f"{key}_changes.jsonl"


def prediction_filename(metric: str, prediction_id: UUID) -> str:
    """e.g. 'services-revenue_ab12cd34.json'"""
    return f"{slugify(metric)}_{str(prediction_id)[:8]}.json"


def resolution_filename(metric: str, prediction_id: UUID) -> str:
    """e.g. 'services-revenue_ab12cd34_resolution.json'"""
    return f"{slugify(metric)}_{str(prediction_id)[:8]}_resolution.json"
