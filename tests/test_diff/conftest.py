"""Shared fixtures for diff engine tests.

Uses real IndustryAgent and CompanyStrategyAgent outputs over the AAPL fixture
corpus so diffs are grounded in realistic payloads.
"""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

import pytest

from equity_os.agents.industry import IndustryAgent
from equity_os.agents.strategy import CompanyStrategyAgent
from equity_os.ingest.pipeline import ingest_dir

FIXTURES_INPUTS = Path(__file__).parent.parent / "test_ingest" / "fixtures" / "inputs"
AAPL_INPUTS = FIXTURES_INPUTS / "AAPL"


@pytest.fixture(scope="session")
def aapl_evidence(tmp_path_factory):
    companies = tmp_path_factory.mktemp("companies_diff")
    (companies / "AAPL" / "evidence").mkdir(parents=True, exist_ok=True)
    ingested, _, _ = ingest_dir(AAPL_INPUTS, "AAPL", companies)
    return ingested


@pytest.fixture(scope="session")
def industry_payload(aapl_evidence) -> dict[str, Any]:
    return IndustryAgent().run("AAPL", aapl_evidence).payload


@pytest.fixture(scope="session")
def strategy_payload(aapl_evidence) -> dict[str, Any]:
    return CompanyStrategyAgent().run("AAPL", aapl_evidence).payload


@pytest.fixture(scope="session")
def industry_run_id(aapl_evidence) -> str:
    return str(IndustryAgent().run("AAPL", aapl_evidence).run_id)


@pytest.fixture(scope="session")
def strategy_run_id(aapl_evidence) -> str:
    return str(CompanyStrategyAgent().run("AAPL", aapl_evidence).run_id)


@pytest.fixture(scope="session")
def evidence_ids(aapl_evidence) -> list[str]:
    return [str(ev.evidence_id) for ev in aapl_evidence]


def mutate(payload: dict[str, Any], **overrides: Any) -> dict[str, Any]:
    """Return a deep copy of payload with top-level fields overridden."""
    p = copy.deepcopy(payload)
    p.update(overrides)
    return p
