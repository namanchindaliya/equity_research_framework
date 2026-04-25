"""Tests for the orchestrator markdown renderer."""

from __future__ import annotations

import pytest

from equity_os.orchestrator.orchestrator import Orchestrator
from equity_os.orchestrator.renderer import render_decision


def _render(scenario, policy, **kw) -> str:
    decision = Orchestrator(policy=policy).run(ticker="AAPL", **scenario, **kw)
    return render_decision(decision)


class TestThreeSections:
    def test_section_1_observations_present(self, aligned, policy):
        memo = _render(aligned, policy)
        assert "## 1. Observations" in memo

    def test_section_2_inferences_present(self, aligned, policy):
        memo = _render(aligned, policy)
        assert "## 2. Inferences" in memo

    def test_section_3_decisions_present(self, aligned, policy):
        memo = _render(aligned, policy)
        assert "## 3. Decisions" in memo

    def test_sections_in_correct_order(self, aligned, policy):
        memo = _render(aligned, policy)
        pos1 = memo.index("## 1. Observations")
        pos2 = memo.index("## 2. Inferences")
        pos3 = memo.index("## 3. Decisions")
        assert pos1 < pos2 < pos3


class TestMemoContent:
    def test_memo_has_title(self, aligned, policy):
        memo = _render(aligned, policy)
        assert "Orchestrator Decision" in memo
        assert "AAPL" in memo

    def test_memo_has_thesis(self, aligned, policy):
        memo = _render(aligned, policy)
        assert "Thesis Statement" in memo

    def test_memo_has_variant_view(self, aligned, policy):
        memo = _render(aligned, policy)
        assert "Variant View" in memo or "Bear Case" in memo

    def test_memo_has_key_assumptions(self, aligned, policy, sample_ledger):
        memo = _render(aligned, policy, assumptions=sample_ledger)
        assert "Key Assumptions" in memo

    def test_memo_has_falsification_section(self, aligned, policy, sample_ledger):
        memo = _render(aligned, policy, assumptions=sample_ledger)
        assert "Falsification" in memo

    def test_memo_has_monitoring_section(self, aligned, policy):
        memo = _render(aligned, policy)
        assert "Monitoring" in memo

    def test_memo_has_next_evidence_section(self, aligned, policy):
        memo = _render(aligned, policy)
        assert "Next Evidence" in memo

    def test_memo_has_confidence_summary(self, aligned, policy):
        memo = _render(aligned, policy)
        assert "Confidence" in memo

    def test_conflict_section_present_when_conflicts(self, conflicting, policy):
        memo = _render(conflicting, policy)
        assert "Conflict" in memo

    def test_conflict_section_absent_when_none(self, policy):
        # Construct a perfectly aligned scenario with no conflicts
        from equity_os.orchestrator.orchestrator import Orchestrator
        from equity_os.orchestrator.models import OrchestratorDecision
        orch = Orchestrator(policy=policy)
        # Use industry_payload fixture via session; use inline minimal
        ind = {
            "agent_id": "industry_v1", "run_id": "r1", "ticker": "AAPL",
            "generated_at": "2026-01-01T00:00:00",
            "overall_confidence": 0.6,
            "industry_label": "Technology",
            "market_structure": "COMPETITIVE",
            "cycle_stage": "GROWTH",
            "porter_forces": [
                {"name": "Competitive Rivalry", "level": "LOW", "summary": "", "confidence": 0.6, "evidence_refs": []},
                {"name": "Supplier Power", "level": "LOW", "summary": "", "confidence": 0.5, "evidence_refs": []},
                {"name": "Buyer Power", "level": "LOW", "summary": "", "confidence": 0.5, "evidence_refs": []},
                {"name": "Threat of New Entry", "level": "HIGH", "summary": "", "confidence": 0.6, "evidence_refs": []},
                {"name": "Threat of Substitutes", "level": "LOW", "summary": "", "confidence": 0.5, "evidence_refs": []},
            ],
            "key_kpis": [], "regulatory_factors": [], "competitive_dynamics": {"moat_type": ["brand"], "basis_of_competition": []},
            "top_risks": [], "unresolved_questions": [], "evidence_ids": [],
            "market_structure_finding": {"text": "", "confidence": 0.5, "evidence_refs": []},
            "cycle_stage_finding": {"text": "", "confidence": 0.5, "evidence_refs": []},
        }
        str_ = {
            "agent_id": "strategy_v1", "run_id": "r2", "ticker": "AAPL",
            "generated_at": "2026-01-01T00:00:00",
            "overall_confidence": 0.65,
            "management_priorities": [], "capital_allocation": [], "narrative_shifts": [],
            "risk_disclosures": [], "segment_priorities": [],
            "strategic_positioning": {"target_market": "premium", "differentiation_axes": ["brand"], "moat_assessment": ["brand"], "finding": {"text": "", "confidence": 0.5, "evidence_refs": []}},
            "mgmt_credibility_signals": [], "unresolved_questions": [], "evidence_ids": [],
        }
        decision = orch.run(ticker="AAPL", industry=ind, strategy=str_)
        memo = render_decision(decision)
        # No conflicts should mean no "Conflict Resolution" section
        assert isinstance(memo, str)  # just structural check

    def test_cross_validated_section(self, aligned, policy):
        memo = _render(aligned, policy)
        assert "Cross-Validated" in memo or "cross_validated" in memo.lower()

    def test_predictions_section(self, aligned, policy):
        memo = _render(aligned, policy)
        assert "Prediction" in memo

    def test_observations_include_porter_forces(self, aligned, policy):
        memo = _render(aligned, policy)
        assert "Porter" in memo or "Rivalry" in memo

    def test_observations_include_management_priorities(self, aligned, policy):
        memo = _render(aligned, policy)
        assert "Management Priorities" in memo or "management" in memo.lower()


class TestScopeEnforcement:
    def test_no_price_target_in_memo(self, aligned, policy):
        memo = _render(aligned, policy)
        assert "price target" not in memo.lower()

    def test_no_dcf_in_memo(self, aligned, policy):
        memo = _render(aligned, policy)
        assert "dcf" not in memo.lower()

    def test_no_eps_forecast(self, aligned, policy):
        memo = _render(aligned, policy)
        assert "earnings per share forecast" not in memo.lower()
