"""Tests for the proposer: AssumptionProposal generation and ConflictFlag detection."""

from __future__ import annotations

import copy
from typing import Any

import pytest

from equity_os.diff.engine import diff_payloads
from equity_os.diff.models import ChangeType, ConflictFlag, DiffMateriality
from equity_os.diff.proposer import _is_accel, _is_decel, propose_updates

from tests.test_diff.conftest import mutate


class TestProposalGeneration:
    def test_cycle_stage_change_generates_proposal(self, industry_payload, evidence_ids):
        current = mutate(industry_payload, cycle_stage="MATURE")
        diff = diff_payloads(
            prior=industry_payload, current=current,
            agent_id="industry_v1", prior_run_id="r1", current_run_id="r2",
            ticker="AAPL", current_evidence_ids=evidence_ids,
        )
        keys = [p.assumption_key for p in diff.assumption_proposals]
        assert "industry_cycle_stage" in keys

    def test_market_structure_change_generates_proposal(self, industry_payload, evidence_ids):
        ms = industry_payload["market_structure"]
        new_ms = "OLIGOPOLY" if ms != "OLIGOPOLY" else "COMPETITIVE"
        current = mutate(industry_payload, market_structure=new_ms)
        diff = diff_payloads(
            prior=industry_payload, current=current,
            agent_id="industry_v1", prior_run_id="r1", current_run_id="r2",
            ticker="AAPL", current_evidence_ids=evidence_ids,
        )
        keys = [p.assumption_key for p in diff.assumption_proposals]
        assert "market_structure" in keys

    def test_no_proposal_for_unchanged_payload(self, industry_payload, evidence_ids):
        diff = diff_payloads(
            prior=industry_payload, current=industry_payload,
            agent_id="industry_v1", prior_run_id="r1", current_run_id="r2",
            ticker="AAPL", current_evidence_ids=evidence_ids,
        )
        assert diff.assumption_proposals == []

    def test_proposal_confidence_in_range(self, industry_payload, evidence_ids):
        current = mutate(industry_payload, cycle_stage="MATURE")
        diff = diff_payloads(
            prior=industry_payload, current=current,
            agent_id="industry_v1", prior_run_id="r1", current_run_id="r2",
            ticker="AAPL", current_evidence_ids=evidence_ids,
        )
        for prop in diff.assumption_proposals:
            assert 0.0 <= prop.confidence <= 1.0

    def test_proposal_triggered_by_non_empty(self, industry_payload, evidence_ids):
        current = mutate(industry_payload, cycle_stage="MATURE")
        diff = diff_payloads(
            prior=industry_payload, current=current,
            agent_id="industry_v1", prior_run_id="r1", current_run_id="r2",
            ticker="AAPL", current_evidence_ids=evidence_ids,
        )
        for prop in diff.assumption_proposals:
            assert len(prop.triggered_by_field_paths) >= 1

    def test_proposal_change_type_matches_field(self, industry_payload, evidence_ids):
        current = mutate(industry_payload, cycle_stage="MATURE")
        diff = diff_payloads(
            prior=industry_payload, current=current,
            agent_id="industry_v1", prior_run_id="r1", current_run_id="r2",
            ticker="AAPL", current_evidence_ids=evidence_ids,
        )
        prop = next(p for p in diff.assumption_proposals if p.assumption_key == "industry_cycle_stage")
        assert prop.change_type == ChangeType.MODIFIED

    def test_multiple_changes_deduplicated_by_assumption_key(self, industry_payload, evidence_ids):
        # Change both cycle_stage finding AND cycle_stage — both should map to same proposal
        current = copy.deepcopy(industry_payload)
        current["cycle_stage"] = "MATURE"
        if "cycle_stage_finding" in current:
            current["cycle_stage_finding"]["text"] = "Now mature."
        diff = diff_payloads(
            prior=industry_payload, current=current,
            agent_id="industry_v1", prior_run_id="r1", current_run_id="r2",
            ticker="AAPL", current_evidence_ids=evidence_ids,
        )
        stage_props = [p for p in diff.assumption_proposals if p.assumption_key == "industry_cycle_stage"]
        assert len(stage_props) == 1  # deduplicated

    def test_strategy_segment_priority_generates_proposal(self, strategy_payload, evidence_ids):
        current = copy.deepcopy(strategy_payload)
        if current.get("segment_priorities"):
            current["segment_priorities"][0]["priority_rank"] = 99
        diff = diff_payloads(
            prior=strategy_payload, current=current,
            agent_id="strategy_v1", prior_run_id="r1", current_run_id="r2",
            ticker="AAPL", current_evidence_ids=evidence_ids,
        )
        keys = [p.assumption_key for p in diff.assumption_proposals]
        assert any("segment_priority" in k for k in keys)

    def test_regulatory_factor_added_generates_proposal(self, industry_payload, evidence_ids):
        current = copy.deepcopy(industry_payload)
        current.setdefault("regulatory_factors", []).append({
            "name": "New Carbon Tax",
            "jurisdiction": "Global",
            "impact_summary": "Carbon tax imposed on hardware manufacturing.",
            "severity": "MEDIUM",
            "finding": {"text": "Carbon tax impacts.", "confidence": 0.5, "evidence_refs": []},
        })
        diff = diff_payloads(
            prior=industry_payload, current=current,
            agent_id="industry_v1", prior_run_id="r1", current_run_id="r2",
            ticker="AAPL", current_evidence_ids=evidence_ids,
        )
        added = [c for c in diff.field_changes if c.change_type == ChangeType.ADDED]
        assert any("regulatory_factors[New Carbon Tax]" in c.field_path for c in added)
        keys = [p.assumption_key for p in diff.assumption_proposals]
        assert any("regulatory_risk" in k for k in keys)


class TestConflictDetection:
    """Conflicting evidence and edge cases."""

    def test_no_conflicts_on_no_op(self, industry_payload, evidence_ids):
        diff = diff_payloads(
            prior=industry_payload, current=industry_payload,
            agent_id="industry_v1", prior_run_id="r1", current_run_id="r2",
            ticker="AAPL", current_evidence_ids=evidence_ids,
        )
        assert diff.conflict_flags == []

    def test_confidence_inversion_detected(self, industry_payload, evidence_ids):
        current = copy.deepcopy(industry_payload)
        # Slash confidence on a Porter force
        for force in current.get("porter_forces", []):
            if force.get("confidence", 0) > 0.2:
                force["confidence"] = round(force["confidence"] * 0.3, 3)
                break
        diff = diff_payloads(
            prior=industry_payload, current=current,
            agent_id="industry_v1", prior_run_id="r1", current_run_id="r2",
            ticker="AAPL", current_evidence_ids=evidence_ids,
            prior_evidence_ids=evidence_ids,
        )
        conf_inv = [cf for cf in diff.conflict_flags if cf.conflict_type == "confidence_inversion"]
        assert len(conf_inv) >= 1

    def test_evidence_disagreement_on_high_materiality_change(self, industry_payload, evidence_ids):
        new_ev = evidence_ids + ["new-evidence-uuid-9999"]
        current = mutate(industry_payload, cycle_stage="MATURE")
        diff = diff_payloads(
            prior=industry_payload, current=current,
            agent_id="industry_v1", prior_run_id="r1", current_run_id="r2",
            ticker="AAPL", current_evidence_ids=new_ev, prior_evidence_ids=evidence_ids,
        )
        ev_disag = [cf for cf in diff.conflict_flags if cf.conflict_type == "evidence_disagreement"]
        assert len(ev_disag) >= 1

    def test_unresolved_growth_detected(self, industry_payload, evidence_ids):
        current = copy.deepcopy(industry_payload)
        current["unresolved_questions"] = list(current.get("unresolved_questions", [])) + [
            "New gap: no sell-through data for emerging markets."
        ]
        diff = diff_payloads(
            prior=industry_payload, current=current,
            agent_id="industry_v1", prior_run_id="r1", current_run_id="r2",
            ticker="AAPL", current_evidence_ids=evidence_ids, prior_evidence_ids=evidence_ids,
        )
        ur = [cf for cf in diff.conflict_flags if cf.conflict_type == "unresolved_growth"]
        assert len(ur) == 1

    def test_conflict_has_confidence_impact(self, industry_payload, evidence_ids):
        current = copy.deepcopy(industry_payload)
        current["unresolved_questions"] = list(current.get("unresolved_questions", [])) + ["New gap."]
        diff = diff_payloads(
            prior=industry_payload, current=current,
            agent_id="industry_v1", prior_run_id="r1", current_run_id="r2",
            ticker="AAPL", current_evidence_ids=evidence_ids, prior_evidence_ids=evidence_ids,
        )
        for cf in diff.conflict_flags:
            assert 0.0 <= cf.confidence_impact <= 1.0

    def test_conflict_has_field_path(self, industry_payload, evidence_ids):
        current = copy.deepcopy(industry_payload)
        current["unresolved_questions"] = list(current.get("unresolved_questions", [])) + ["New gap."]
        diff = diff_payloads(
            prior=industry_payload, current=current,
            agent_id="industry_v1", prior_run_id="r1", current_run_id="r2",
            ticker="AAPL", current_evidence_ids=evidence_ids, prior_evidence_ids=evidence_ids,
        )
        for cf in diff.conflict_flags:
            assert len(cf.field_path) > 0


class TestImplicationLogic:
    def test_growth_to_mature_thesis_implication(self):
        from equity_os.diff.proposer import _FIELD_TO_ASSUMPTION
        rule = _FIELD_TO_ASSUMPTION["cycle_stage"]
        impl = rule["thesis_impl_fn"]("GROWTH", "MATURE")
        assert "maturing" in impl.lower() or "growth" in impl.lower()

    def test_mature_to_growth_thesis_implication(self):
        from equity_os.diff.proposer import _FIELD_TO_ASSUMPTION
        rule = _FIELD_TO_ASSUMPTION["cycle_stage"]
        impl = rule["thesis_impl_fn"]("MATURE", "GROWTH")
        assert "re-accelerat" in impl.lower() or "conservative" in impl.lower()

    def test_oligopoly_market_structure_positive(self):
        from equity_os.diff.proposer import _FIELD_TO_ASSUMPTION
        rule = _FIELD_TO_ASSUMPTION["market_structure"]
        impl = rule["thesis_impl_fn"]("COMPETITIVE", "OLIGOPOLY")
        assert "pricing power" in impl.lower() or "oligopoly" in impl.lower()

    def test_is_decel_logic(self):
        assert _is_decel("GROWTH", "MATURE")
        assert _is_decel("EARLY_GROWTH", "DECLINE")
        assert not _is_decel("MATURE", "GROWTH")

    def test_is_accel_logic(self):
        assert _is_accel("MATURE", "GROWTH")
        assert not _is_accel("GROWTH", "MATURE")
