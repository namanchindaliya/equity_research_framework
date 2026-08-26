"""Ingestion pipeline: file → IngestedEvidence stored under companies/{ticker}/evidence/.

Pipeline steps for a single file
---------------------------------
1. Detect file format and extract (normalize.extract)
2. Parse frontmatter for metadata
3. Determine logical_type (frontmatter → filename → explicit argument)
4. Compute document content_hash
5. Dedup check — skip if already ingested for this ticker
6. Chunk the normalized text (chunk.chunk_text)
7. Extract type-specific metadata (adapters.extract_metadata)
8. Build IngestedEvidence record
9. Write JSON to companies/{ticker}/evidence/{evidence_id}.json
10. Register in dedup index
11. Update _catalog.json

Returns
-------
  IngestedEvidence if newly ingested
  None            if duplicate (already in index)
"""

from __future__ import annotations

import json
import re
from datetime import date
from pathlib import Path
from typing import Any

from . import adapters, dedup
from .chunk import chunk_text
from .models import EvidenceManifestEntry, IngestedEvidence, RawDocument
from .normalize import extract

_CATALOG_FILE = "_catalog.json"


def _safe_file_component(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", Path(value).name)
    return cleaned[:180] or "document"


def _evidence_dir(companies_root: Path, ticker: str) -> Path:
    return companies_root / ticker.upper() / "evidence"


def _catalog_path(evidence_dir: Path) -> Path:
    return evidence_dir / _CATALOG_FILE


def _load_catalog(evidence_dir: Path) -> list[dict[str, Any]]:
    path = _catalog_path(evidence_dir)
    if not path.exists():
        return []
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []


def _save_catalog(evidence_dir: Path, entries: list[dict[str, Any]]) -> None:
    evidence_dir.mkdir(parents=True, exist_ok=True)
    tmp = _catalog_path(evidence_dir).with_suffix(".tmp")
    tmp.write_text(json.dumps(entries, indent=2, default=str), encoding="utf-8")
    tmp.rename(_catalog_path(evidence_dir))


def ingest_file(
    file_path: Path,
    ticker: str,
    companies_root: Path,
    logical_type: str | None = None,
    *,
    force: bool = False,
) -> IngestedEvidence | None:
    """Ingest one file. Returns the record, or None if it was a duplicate.

    Parameters
    ----------
    file_path     : absolute or cwd-relative path to the input document
    ticker        : company ticker (will be upper-cased)
    companies_root: root of the companies/ directory
    logical_type  : override; if None, inferred from frontmatter then filename
    force         : skip dedup check and re-ingest even if content matches
    """
    ticker = ticker.upper()
    ev_dir = _evidence_dir(companies_root, ticker)

    # --- Step 1: extract
    frontmatter_meta, text = extract(file_path)

    if not text.strip():
        raise ValueError(f"{file_path}: no extractable text content.")

    # --- Step 2: resolve logical_type
    if logical_type is None:
        logical_type = (
            frontmatter_meta.get("logical_type")
            or adapters.infer_logical_type_from_filename(file_path.name)
            or "news_note"  # safe default
        )
    if logical_type not in adapters.KNOWN_LOGICAL_TYPES:
        raise ValueError(
            f"Unknown logical_type {logical_type!r}. "
            f"Valid: {sorted(adapters.KNOWN_LOGICAL_TYPES)}"
        )

    # --- Step 3: dedup
    is_dup, doc_hash = dedup.is_duplicate(ev_dir, text)
    if is_dup and not force:
        return None  # already ingested

    # --- Step 4: build record
    from uuid import uuid4
    evidence_id = uuid4()
    id_prefix = str(evidence_id)[:8]

    chunks = chunk_text(text, ticker, id_prefix)

    meta = adapters.extract_metadata(logical_type, text, frontmatter_meta)

    # Resolve source_date from frontmatter (string → date)
    source_date: date | None = None
    raw_date = frontmatter_meta.get("source_date")
    if raw_date:
        try:
            from dateutil.parser import parse as parse_dt
            source_date = parse_dt(str(raw_date)).date()
        except Exception:
            meta["raw_source_date"] = raw_date

    reliability = float(
        frontmatter_meta.get("reliability_score", adapters.reliability_for(logical_type))
    )

    evidence = IngestedEvidence(
        evidence_id=evidence_id,
        ticker=ticker,
        logical_type=logical_type,
        source_type=adapters.source_type_for(logical_type),
        title=str(frontmatter_meta.get("title", file_path.stem)),
        source_date=source_date,
        source_name=str(frontmatter_meta.get("source_name", ticker)),
        url=frontmatter_meta.get("url"),
        reliability_score=reliability,
        text=text,
        extracted_metadata=meta,
        chunks=chunks,
        content_hash=doc_hash,
        file_path=str(file_path),
    )

    # --- Step 5: persist
    ev_dir.mkdir(parents=True, exist_ok=True)
    out_path = ev_dir / f"{evidence_id}.json"
    tmp = out_path.with_suffix(".tmp")
    tmp.write_text(evidence.model_dump_json(indent=2), encoding="utf-8")
    tmp.rename(out_path)

    # --- Step 6: register in dedup index
    dedup.register(ev_dir, doc_hash, evidence_id, str(file_path))

    # --- Step 7: update catalog
    catalog = _load_catalog(ev_dir)
    entry = evidence.manifest_entry()
    catalog.append(json.loads(entry.model_dump_json()))
    _save_catalog(ev_dir, catalog)

    return evidence


def ingest_document(
    document: RawDocument,
    companies_root: Path,
    *,
    store_raw: bool = True,
    raw_dir_name: str = "raw",
    force: bool = False,
) -> IngestedEvidence | None:
    """Ingest a typed connector document through the canonical evidence path."""
    ticker = document.ticker.upper()
    ev_dir = _evidence_dir(companies_root, ticker)
    if document.logical_type not in adapters.KNOWN_LOGICAL_TYPES:
        raise ValueError(
            f"Unknown logical_type {document.logical_type!r}. "
            f"Valid: {sorted(adapters.KNOWN_LOGICAL_TYPES)}"
        )
    if not document.text.strip():
        raise ValueError(f"{document.url}: no extractable text content.")

    existing = dedup.lookup_external(
        ev_dir,
        document.provider,
        document.external_id,
        document.document_id,
    )
    if existing and not force:
        return None

    doc_hash = dedup.content_hash(document.text)
    from uuid import uuid4

    evidence_id = uuid4()
    chunks = chunk_text(document.text, ticker, str(evidence_id)[:8])
    metadata = adapters.extract_metadata(document.logical_type, document.text, {})
    metadata.update(document.metadata)

    raw_content_path: str | None = None
    source_locator = document.url
    if store_raw:
        raw_dir = ev_dir / _safe_file_component(raw_dir_name)
        raw_dir.mkdir(parents=True, exist_ok=True)
        raw_name = _safe_file_component(
            f"{document.external_id}_{document.document_id}"
        )
        raw_path = raw_dir / raw_name
        temporary = raw_path.with_suffix(raw_path.suffix + ".tmp")
        temporary.write_bytes(document.raw_content)
        temporary.replace(raw_path)
        raw_content_path = str(raw_path)
        source_locator = str(raw_path)

    evidence = IngestedEvidence(
        evidence_id=evidence_id,
        ticker=ticker,
        logical_type=document.logical_type,
        source_type=adapters.source_type_for(document.logical_type),
        title=document.title,
        source_date=document.source_date,
        source_name=document.source_name,
        url=document.url,
        reliability_score=document.reliability_score,
        text=document.text,
        extracted_metadata=metadata,
        chunks=chunks,
        content_hash=doc_hash,
        file_path=source_locator,
        provider=document.provider,
        external_id=document.external_id,
        document_id=document.document_id,
        content_type=document.content_type,
        raw_content_path=raw_content_path,
        retrieved_at=document.retrieved_at,
    )

    ev_dir.mkdir(parents=True, exist_ok=True)
    out_path = ev_dir / f"{evidence_id}.json"
    temporary = out_path.with_suffix(".tmp")
    temporary.write_text(evidence.model_dump_json(indent=2), encoding="utf-8")
    temporary.replace(out_path)

    dedup.register(
        ev_dir,
        doc_hash,
        evidence_id,
        source_locator,
        provider=document.provider,
        external_id=document.external_id,
        document_id=document.document_id,
    )
    catalog = _load_catalog(ev_dir)
    catalog.append(json.loads(evidence.manifest_entry().model_dump_json()))
    _save_catalog(ev_dir, catalog)
    return evidence


def ingest_dir(
    inputs_dir: Path,
    ticker: str,
    companies_root: Path,
    logical_type: str | None = None,
    *,
    force: bool = False,
) -> tuple[list[IngestedEvidence], list[str], list[str]]:
    """Ingest all supported files from inputs_dir.

    Returns (ingested, skipped_duplicates, failed) where each is a list of
    file path strings.
    """
    from .normalize import SUPPORTED_EXTENSIONS

    ingested: list[IngestedEvidence] = []
    skipped: list[str] = []
    failed: list[str] = []

    files = sorted(
        f for f in inputs_dir.iterdir()
        if f.is_file() and f.suffix.lower() in SUPPORTED_EXTENSIONS
    )

    for f in files:
        try:
            result = ingest_file(
                f, ticker, companies_root, logical_type=logical_type, force=force
            )
            if result is None:
                skipped.append(str(f))
            else:
                ingested.append(result)
        except Exception as exc:
            failed.append(f"{f}: {exc}")

    return ingested, skipped, failed


def list_catalog(companies_root: Path, ticker: str) -> list[EvidenceManifestEntry]:
    """Load the evidence catalog for a ticker."""
    ev_dir = _evidence_dir(companies_root, ticker)
    entries = _load_catalog(ev_dir)
    return [EvidenceManifestEntry.model_validate(e) for e in entries]


def load_evidence(companies_root: Path, ticker: str, evidence_id: str) -> IngestedEvidence:
    """Load a single IngestedEvidence record by UUID string."""
    ev_dir = _evidence_dir(companies_root, ticker)
    path = ev_dir / f"{evidence_id}.json"
    if not path.exists():
        raise FileNotFoundError(f"Evidence {evidence_id!r} not found for {ticker}")
    return IngestedEvidence.model_validate_json(path.read_text(encoding="utf-8"))
