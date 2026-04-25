"""Tests for the diff engine: no-op, small change, material change."""

from __future__ import annotations

import copy
from typing import Any

import pytest

from equity_os.diff.engine import diff_payloads, new_change_log
from equity_os.diff.models import ChangeType, DiffMateriality, EpisodeDiff

from tests.test_diff.conftest import mutate


class TestNoOpDiff:
    """Identical prior and current → no changes except UNCHANGED."""

    def test_no_non_unchanged_fields(self, industry_payload, evidence_ids):
        diff = diff_payloads(
            prior=industry_payload,
            current=industry_payload,
            agent_id="industry_v1",
            prior_run_id="aaaa",
            current_run_id="bbbb",
            ticker="AAPL",
            current_evidence_ids=evidence_ids,
        )
        non_unchanged = [c for c in diff.field_changes if c.change_type != ChangeType.UNCHANGED]
        assert non_unchanged == [], f"Expected no changes, got: {[c.field_path for c in non_unchanged]}"

    def test_no_assumption_proposals(self, industry_payload, evidence_ids):
        diff = diff_payloads(
            prior=industry_payload,
            current=industry_payload,
            agent_id="industry_v1",
            prior_run_id="aaaa",
            current_run_id="bbbb",
            ticker="AAPL",
            current_evidence_ids=evidence_ids,
        )
        assert diff.assumption_proposals == []

    def test_has_material_changes_false(self, industry_payload, evidence_ids):
        diff = diff_payloads(
            prior=industry_payload,
            current=industry_payload,
            agent_id="industry_v1",
            prior_run_id="aaaa",
            current_run_id="bbbb",
            ticker="AAPL",
            current_evidence_ids=evidence_ids,
        )
        assert not diff.has_material_changes

    def test_change_summary_indicates_no_change(self, industry_payload, evidence_ids):
        diff = diff_payloads(
            prior=industry_payload,
            current=industry_payload,
            agent_id="industry_v1",
            prior_run_id="aaaa",
            current_run_id="bbbb",
            ticker="AAPL",
            current_evidence_ids=evidence_ids,
        )
        assert "No analytical changes" in diff.change_summary

    def test_no_conflict_flags(self, industry_payload, evidence_ids):
        diff = diff_payloads(
            prior=industry_payload,
            current=industry_payload,
            agent_id="industry_v1",
            prior_run_id="aaaa",
            current_run_id="bbbb",
            ticker="AAPL",
            current_evidence_ids=evidence_ids,
        )
        assert diff.conflict_flags == []

    def test_strategy_no_op(self, strategy_payload, evidence_ids):
        diff = diff_payloads(
            prior=strategy_payload,
            current=strategy_payload,
            agent_id="strategy_v1",
            prior_run_id="aaaa",
            current_run_id="bbbb",
            ticker="AAPL",
            current_evidence_ids=evidence_ids,
        )
        non_unchanged = [c for c in diff.field_changes if c.change_type != ChangeType.UNCHANGED]
        assert non_unchanged == []


class TestSmallChange:
    """LOW-materiality change: overall_confidence shifts slightly."""

    def _run(self, industry_payload, evidence_ids, new_conf):
        prior = industry_payload
        current = mutate(industry_payload, overall_confidence=new_conf)
        return diff_payloads(
            prior=prior,
            current=current,
            agent_id="industry_v1",
            prior_run_id="aaaa",
            current_run_id="bbbb",
            ticker="AAPL",
            current_evidence_ids=evidence_ids,
        )

    def test_detects_confidence_change(self, industry_payload, evidence_ids):
        prior_conf = industry_payload["overall_confidence"]
        new_conf = round(prior_conf + 0.05, 3)
        diff = self._run(industry_payload, evidence_ids, new_conf)
        modified = [c for c in diff.field_changes if c.change_type == ChangeType.MODIFIED]
        conf_changes = [c for c in modified if "overall_confidence" in c.field_path]
        assert len(conf_changes) == 1

    def test_small_confidence_change_is_medium_or_lower(self, industry_payload, evidence_ids):
        prior_conf = industry_payload["overall_confidence"]
        new_conf = round(prior_conf + 0.05, 3)
        diff = self._run(industry_payload, evidence_ids, new_conf)
        conf_change = next(
            c for c in diff.field_changes
            if c.change_type == ChangeType.MODIFIED and "overall_confidence" in c.field_path
        )
        assert conf_change.materiality in {DiffMateriality.LOW, DiffMateriality.MEDIUM}

    def test_small_change_has_magnitude(self, industry_payload, evidence_ids):
        prior_conf = industry_payload["overall_confidence"]
        new_conf = round(prior_conf + 0.1, 3)
        diff = self._run(industry_payload, evidence_ids, new_conf)
        conf_change = next(
            c for c in diff.field_changes
            if c.change_type == ChangeType.MODIFIED and "overall_confidence" in c.field_path
        )
        assert conf_change.change_magnitude is not None
        assert conf_change.change_magnitude > 0

    def test_small_change_has_no_material_flag(self, industry_payload, evidence_ids):
        prior_conf = industry_payload["overall_confidence"]
        new_conf = round(prior_conf + 0.05, 3)
        diff = self._run(industry_payload, evidence_ids, new_conf)
        assert not diff.has_material_changes


class TestMaterialChange:
    """HIGH-materiality change: cycle_stage or market_structure flips."""

    def test_cycle_stage_change_is_high_materiality(self, industry_payload, evidence_ids):
        current = mutate(industry_payload, cycle_stage="MATURE")
        diff = diff_payloads(
            prior=industry_payload,
            current=current,
            agent_id="industry_v1",
            prior_run_id="aaaa",
            current_run_id="bbbb",
            ticker="AAPL",
            current_evidence_ids=evidence_ids,
        )
        cycle_changes = [c for c in diff.field_changes
                         if "cycle_stage" in c.field_path and c.change_type == ChangeType.MODIFIED]
        assert any(c.materiality == DiffMateriality.HIGH for c in cycle_changes)

    def test_cycle_stage_change_sets_material_flag(self, industry_payload, evidence_ids):
        current = mutate(industry_payload, cycle_stage="MATURE")
        diff = diff_payloads(
            prior=industry_payload,
            current=current,
            agent_id="industry_v1",
            prior_run_id="aaaa",
            current_run_id="bbbb",
            ticker="AAPL",
            current_evidence_ids=evidence_ids,
        )
        assert diff.has_material_changes

    def test_cycle_stage_change_produces_proposal(self, industry_payload, evidence_ids):
        prior_stage = industry_payload["cycle_stage"]
        new_stage = "MATURE" if prior_stage != "MATURE" else "GROWTH"
        current = mutate(industry_payload, cycle_stage=new_stage)
        diff = diff_payloads(
            prior=industry_payload,
            current=current,
            agent_id="industry_v1",
            prior_run_id="aaaa",
            current_run_id="bbbb",
            ticker="AAPL",
            current_evidence_ids=evidence_ids,
        )
        keys = [p.assumption_key for p in diff.assumption_proposals]
        assert "industry_cycle_stage" in keys

    def test_proposal_has_prior_and_proposed(self, industry_payload, evidence_ids):
        prior_stage = industry_payload["cycle_stage"]
        new_stage = "MATURE" if prior_stage != "MATURE" else "GROWTH"
        current = mutate(industry_payload, cycle_stage=new_stage)
        diff = diff_payloads(
            prior=industry_payload,
            current=current,
            agent_id="industry_v1",
            prior_run_id="aaaa",
            current_run_id="bbbb",
            ticker="AAPL",
            current_evidence_ids=evidence_ids,
        )
        prop = next(p for p in diff.assumption_proposals if p.assumption_key == "industry_cycle_stage")
        assert prop.prior_value == prior_stage
        assert prop.proposed_value == new_stage

    def test_proposal_has_downstream_fields(self, industry_payload, evidence_ids):
        current = mutate(industry_payload, cycle_stage="MATURE")
        diff = diff_payloads(
            prior=industry_payload,
            current=current,
            agent_id="industry_v1",
            prior_run_id="aaaa",
            current_run_id="bbbb",
            ticker="AAPL",
            current_evidence_ids=evidence_ids,
        )
        prop = next(p for p in diff.assumption_proposals if p.assumption_key == "industry_cycle_stage")
        assert len(prop.impacted_model_fields) >= 1

    def test_proposal_has_thesis_implication(self, industry_payload, evidence_ids):
        current = mutate(industry_payload, cycle_stage="MATURE")
        diff = diff_payloads(
            prior=industry_payload,
            current=current,
            agent_id="industry_v1",
            prior_run_id="aaaa",
            current_run_id="bbbb",
            ticker="AAPL",
            current_evidence_ids=evidence_ids,
        )
        prop = next(p for p in diff.assumption_proposals if p.assumption_key == "industry_cycle_stage")
        assert len(prop.implication_for_thesis) > 10

    def test_proposal_has_valuation_implication(self, industry_payload, evidence_ids):
        current = mutate(industry_payload, cycle_stage="MATURE")
        diff = diff_payloads(
            prior=industry_payload,
            current=current,
            agent_id="industry_v1",
            prior_run_id="aaaa",
            current_run_id="bbbb",
            ticker="AAPL",
            current_evidence_ids=evidence_ids,
        )
        prop = next(p for p in diff.assumption_proposals if p.assumption_key == "industry_cycle_stage")
        assert len(prop.implication_for_valuation) > 10

    def test_market_structure_change_is_high(self, industry_payload, evidence_ids):
        prior_ms = industry_payload["market_structure"]
        new_ms = "OLIGOPOLY" if prior_ms != "OLIGOPOLY" else "COMPETITIVE"
        current = mutate(industry_payload, market_structure=new_ms)
        diff = diff_payloads(
            prior=industry_payload,
            current=current,
            agent_id="industry_v1",
            prior_run_id="aaaa",
            current_run_id="bbbb",
            ticker="AAPL",
            current_evidence_ids=evidence_ids,
        )
        ms_changes = [c for c in diff.field_changes
                      if "market_structure" in c.field_path and c.change_type == ChangeType.MODIFIED]
        assert any(c.materiality == DiffMateriality.HIGH for c in ms_changes)

    def test_proposal_has_evidence_ids(self, industry_payload, evidence_ids):
        current = mutate(industry_payload, cycle_stage="MATURE")
        diff = diff_payloads(
            prior=industry_payload,
            current=current,
            agent_id="industry_v1",
            prior_run_id="aaaa",
            current_run_id="bbbb",
            ticker="AAPL",
            current_evidence_ids=evidence_ids,
        )
        prop = next(p for p in diff.assumption_proposals if p.assumption_key == "industry_cycle_stage")
        assert len(prop.evidence_ids) >= 1

    def test_proposal_has_rationale(self, industry_payload, evidence_ids):
        current = mutate(industry_payload, cycle_stage="MATURE")
        diff = diff_payloads(
            prior=industry_payload,
            current=current,
            agent_id="industry_v1",
            prior_run_id="aaaa",
            current_run_id="bbbb",
            ticker="AAPL",
            current_evidence_ids=evidence_ids,
        )
        prop = next(p for p in diff.assumption_proposals if p.assumption_key == "industry_cycle_stage")
        assert len(prop.rationale) > 20

    def test_proposal_has_timestamp(self, industry_payload, evidence_ids):
        current = mutate(industry_payload, cycle_stage="MATURE")
        diff = diff_payloads(
            prior=industry_payload,
            current=current,
            agent_id="industry_v1",
            prior_run_id="aaaa",
            current_run_id="bbbb",
            ticker="AAPL",
            current_evidence_ids=evidence_ids,
        )
        prop = next(p for p in diff.assumption_proposals if p.assumption_key == "industry_cycle_stage")
        assert prop.timestamp is not None

    def test_strategy_material_change(self, strategy_payload, evidence_ids):
        """Changing target_market on strategy payload should be material."""
        prior_tm = strategy_payload.get("strategic_positioning", {}).get("target_market", "premium")
        new_tm = "mass_market" if prior_tm != "mass_market" else "premium"
        current = copy.deepcopy(strategy_payload)
        current["strategic_positioning"]["target_market"] = new_tm
        diff = diff_payloads(
            prior=strategy_payload,
            current=current,
            agent_id="strategy_v1",
            prior_run_id="aaaa",
            current_run_id="bbbb",
            ticker="AAPL",
            current_evidence_ids=evidence_ids,
        )
        assert diff.has_material_changes or any(
            c.materiality in {DiffMateriality.HIGH, DiffMateriality.MEDIUM}
            for c in diff.field_changes if c.change_type != ChangeType.UNCHANGED
        )


class TestChangeLog:
    def test_new_change_log_empty(self):
        log = new_change_log("AAPL", "industry_v1")
        assert log.diffs == []
        assert log.total_changes == 0

    def test_append_diff_accumulates(self, industry_payload, evidence_ids):
        log = new_change_log("AAPL", "industry_v1")
        diff1 = diff_payloads(
            prior=industry_payload,
            current=mutate(industry_payload, cycle_stage="MATURE"),
            agent_id="industry_v1", prior_run_id="r1", current_run_id="r2",
            ticker="AAPL", current_evidence_ids=evidence_ids,
        )
        diff2 = diff_payloads(
            prior=mutate(industry_payload, cycle_stage="MATURE"),
            current=mutate(industry_payload, cycle_stage="GROWTH"),
            agent_id="industry_v1", prior_run_id="r2", current_run_id="r3",
            ticker="AAPL", current_evidence_ids=evidence_ids,
        )
        log.append_diff(diff1)
        log.append_diff(diff2)
        assert len(log.diffs) == 2

    def test_change_log_totals(self, industry_payload, evidence_ids):
        log = new_change_log("AAPL", "industry_v1")
        diff = diff_payloads(
            prior=industry_payload,
            current=mutate(industry_payload, cycle_stage="MATURE"),
            agent_id="industry_v1", prior_run_id="r1", current_run_id="r2",
            ticker="AAPL", current_evidence_ids=evidence_ids,
        )
        log.append_diff(diff)
        assert log.total_changes >= 1
        assert log.material_changes >= 1
