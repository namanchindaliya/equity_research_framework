"""Fixtures for orchestrator tests.

Five scenarios:
  aligned          — both agents agree, fresh evidence, clean ledger
  conflicting      — agents disagree on competitive intensity AND moat type
  sparse           — only industry agent, empty strategy output, no ledger
  stale            — agents ran >180 days ago (freshness penalty applies)
  high_conf_contra — high-confidence agents but contradictory on regulatory
"""

from __future__ import annotations

import copy
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from equity_os.agents.industry import IndustryAgent
from equity_os.agents.strategy import CompanyStrategyAgent
from equity_os.ingest.pipeline import ingest_dir
from equity_os.orchestrator.policy import OrchestratorPolicy

FIXTURES_INPUTS = Path(__file__).parent.parent / "test_ingest" / "fixtures" / "inputs"
AAPL_INPUTS = FIXTURES_INPUTS / "AAPL"


@pytest.fixture(scope="session")
def policy() -> OrchestratorPolicy:
    return OrchestratorPolicy.load()


@pytest.fixture(scope="session")
def aapl_evidence(tmp_path_factory):
    companies = tmp_path_factory.mktemp("companies_orch")
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
def sample_ledger() -> list[dict[str, Any]]:
    return [
        {
            "key": "services_rev_cagr",
            "label": "Services Revenue CAGR",
            "value": 0.13,
            "unit": "%",
            "owner_agent": "analyst",
            "rationale": "Based on Q1 FY2026 earnings trend.",
            "confidence": 0.72,
            "materiality": "CRITICAL",
            "status": "ACTIVE",
            "version": 1,
            "history": [],
        },
        {
            "key": "regulatory_cost_exposure",
            "label": "EU Regulatory Cost Exposure",
            "value": 1.0,
            "unit": "USD B",
            "owner_agent": "analyst",
            "rationale": "Goldman estimates $0.8-1.2B annual impact from DMA.",
            "confidence": 0.55,
            "materiality": "HIGH",
            "status": "ACTIVE",
            "version": 1,
            "history": [],
        },
    ]


# ---------------------------------------------------------------------------
# Scenario payloads
# ---------------------------------------------------------------------------

def _set_ts(payload: dict, days_ago: float) -> dict:
    p = copy.deepcopy(payload)
    p["generated_at"] = (datetime.utcnow() - timedelta(days=days_ago)).isoformat()
    return p


@pytest.fixture(scope="session")
def aligned(industry_payload, strategy_payload):
    """Aligned: both agents agree, fresh output."""
    return {
        "industry": copy.deepcopy(industry_payload),
        "strategy": copy.deepcopy(strategy_payload),
    }


@pytest.fixture(scope="session")
def conflicting(industry_payload, strategy_payload):
    """Conflicting: industry sees HIGH rivalry, strategy sees LOW competitive risk;
    and moat types are completely disjoint."""
    ind = copy.deepcopy(industry_payload)
    str_ = copy.deepcopy(strategy_payload)

    # Force HIGH rivalry in industry
    for force in ind.get("porter_forces", []):
        if "Rivalry" in force.get("name", ""):
            force["level"] = "HIGH"
            force["confidence"] = 0.85

    # Force 'implied' competitive risk in strategy (very soft)
    for risk in str_.get("risk_disclosures", []):
        if risk.get("category") == "competitive":
            risk["severity_from_disclosure"] = "implied"
            risk["finding"]["confidence"] = 0.30

    # Force disjoint moat types
    ind["competitive_dynamics"]["moat_type"] = ["scale", "ip"]
    str_["strategic_positioning"]["moat_assessment"] = ["brand", "switching_costs"]

    return {"industry": ind, "strategy": str_}


@pytest.fixture(scope="session")
def sparse(industry_payload):
    """Sparse: only industry agent, empty strategy output, no ledger."""
    empty_strategy: dict[str, Any] = {
        "agent_id": "strategy_v1",
        "run_id": "00000000-0000-0000-0000-000000000001",
        "ticker": "AAPL",
        "generated_at": datetime.utcnow().isoformat(),
        "management_priorities": [],
        "capital_allocation": [],
        "narrative_shifts": [],
        "risk_disclosures": [],
        "segment_priorities": [],
        "strategic_positioning": {
            "target_market": "unknown",
            "differentiation_axes": [],
            "moat_assessment": ["unknown"],
            "finding": {"text": "No evidence.", "confidence": 0.0, "evidence_refs": []},
        },
        "mgmt_credibility_signals": [],
        "unresolved_questions": ["No strategy evidence available."],
        "overall_confidence": 0.05,
        "evidence_ids": [],
    }
    return {"industry": copy.deepcopy(industry_payload), "strategy": empty_strategy}


@pytest.fixture(scope="session")
def stale(industry_payload, strategy_payload):
    """Stale: both agents ran 200 days ago (freshness penalty = 0.20)."""
    return {
        "industry": _set_ts(industry_payload, 200),
        "strategy": _set_ts(strategy_payload, 200),
    }


@pytest.fixture(scope="session")
def high_conf_contra(industry_payload, strategy_payload):
    """High-confidence contradictory: industry says no regulatory factors,
    strategy explicitly discloses regulatory risk with high confidence."""
    ind = copy.deepcopy(industry_payload)
    str_ = copy.deepcopy(strategy_payload)

    # Industry: boost confidence but remove all regulatory factors
    ind["overall_confidence"] = 0.88
    ind["regulatory_factors"] = []

    # Strategy: boost confidence, make regulatory risk explicit
    str_["overall_confidence"] = 0.85
    for risk in str_.get("risk_disclosures", []):
        if risk.get("category") == "regulatory":
            risk["severity_from_disclosure"] = "explicit"
            risk["finding"]["confidence"] = 0.90
    if not any(r.get("category") == "regulatory" for r in str_.get("risk_disclosures", [])):
        str_.setdefault("risk_disclosures", []).append({
            "name": "Regulatory Risk",
            "category": "regulatory",
            "severity_from_disclosure": "explicit",
            "finding": {"text": "Regulatory risk explicitly disclosed.", "confidence": 0.90, "evidence_refs": []},
        })

    return {"industry": ind, "strategy": str_}
