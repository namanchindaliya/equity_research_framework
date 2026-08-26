"""Content-hash deduplication for ingested evidence.

Dedup operates at the **document level**: if a file with the same full-text
SHA-256 has already been ingested for this ticker, it is skipped.

Index format — companies/{ticker}/evidence/_index.jsonl
  One JSON object per line: {"content_hash": "...", "evidence_id": "...",
                              "file_path": "...", "ingested_at": "..."}

The index is append-only (never re-written); stale entries are ignored at
lookup time (only the first match for a hash matters).
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path
from uuid import UUID

_INDEX_FILE = "_index.jsonl"


def content_hash(text: str) -> str:
    """SHA-256 of the UTF-8 encoded text, returned as a hex string."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _index_path(evidence_dir: Path) -> Path:
    return evidence_dir / _INDEX_FILE


def lookup(evidence_dir: Path, hash_: str) -> str | None:
    """Return the evidence_id string if this hash is already indexed, else None."""
    path = _index_path(evidence_dir)
    if not path.exists():
        return None
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
            if rec.get("content_hash") == hash_:
                return rec.get("evidence_id")
        except json.JSONDecodeError:
            continue
    return None


def lookup_external(
    evidence_dir: Path,
    provider: str,
    external_id: str,
    document_id: str,
) -> str | None:
    """Return an evidence ID for an already-ingested provider document."""
    path = _index_path(evidence_dir)
    if not path.exists():
        return None
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        if (
            record.get("provider") == provider
            and record.get("external_id") == external_id
            and record.get("document_id") == document_id
        ):
            return record.get("evidence_id")
    return None


def register(
    evidence_dir: Path,
    hash_: str,
    evidence_id: UUID,
    file_path: str,
    *,
    provider: str | None = None,
    external_id: str | None = None,
    document_id: str | None = None,
) -> None:
    """Append a new entry to the dedup index."""
    evidence_dir.mkdir(parents=True, exist_ok=True)
    entry = json.dumps(
        {
            "content_hash": hash_,
            "evidence_id": str(evidence_id),
            "file_path": file_path,
            "ingested_at": datetime.utcnow().isoformat(),
            "provider": provider,
            "external_id": external_id,
            "document_id": document_id,
        }
    )
    with _index_path(evidence_dir).open("a", encoding="utf-8") as fh:
        fh.write(entry + "\n")


def is_duplicate(evidence_dir: Path, text: str) -> tuple[bool, str]:
    """Return (is_dup, hash). If is_dup is True the document already exists."""
    h = content_hash(text)
    existing = lookup(evidence_dir, h)
    return (existing is not None, h)
