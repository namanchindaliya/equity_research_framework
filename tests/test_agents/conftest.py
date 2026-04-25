"""Shared fixtures for agent tests.

Uses the same 4 fixture documents as the ingest tests, ingested once per
test session into a temp directory.  This makes agent tests self-contained.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from equity_os.ingest.pipeline import ingest_dir
from equity_os.ingest.models import IngestedEvidence

FIXTURES_INPUTS = Path(__file__).parent.parent / "test_ingest" / "fixtures" / "inputs"
AAPL_INPUTS = FIXTURES_INPUTS / "AAPL"


@pytest.fixture(scope="session")
def aapl_evidence(tmp_path_factory) -> list[IngestedEvidence]:
    """Ingest all AAPL fixture documents once for the whole session."""
    companies = tmp_path_factory.mktemp("companies")
    (companies / "AAPL" / "evidence").mkdir(parents=True, exist_ok=True)
    ingested, _, failed = ingest_dir(AAPL_INPUTS, "AAPL", companies)
    assert not failed, f"Ingestion failures: {failed}"
    assert len(ingested) == 4, f"Expected 4 docs, got {len(ingested)}"
    return ingested


@pytest.fixture(scope="session")
def filing_only(aapl_evidence) -> list[IngestedEvidence]:
    return [ev for ev in aapl_evidence if ev.logical_type == "filing"]


@pytest.fixture(scope="session")
def transcript_only(aapl_evidence) -> list[IngestedEvidence]:
    return [ev for ev in aapl_evidence if ev.logical_type == "earnings_transcript"]
