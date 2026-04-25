"""Test repeated updates across multiple episodes in a ChangeLog."""

from __future__ import annotations

import copy

import pytest

from equity_os.diff.engine import diff_payloads, new_change_log
from equity_os.diff.models import ChangeType

from tests.test_diff.conftest import mutate


class TestRepeatedUpdates:
    """ChangeLog must accumulate diffs without losing history."""

    def test_three_diffs_all_stored(self, industry_payload, evidence_ids):
        log = new_change_log("AAPL", "industry_v1")
        stages = ["GROWTH", "MATURE", "DECLINE"]
        for i in range(len(stages) - 1):
            diff = diff_payloads(
                prior=mutate(industry_payload, cycle_stage=stages[i]),
                current=mutate(industry_payload, cycle_stage=stages[i + 1]),
                agent_id="industry_v1",
                prior_run_id=f"r{i}",
                current_run_id=f"r{i + 1}",
                ticker="AAPL",
                current_evidence_ids=evidence_ids,
            )
            log.append_diff(diff)
        assert len(log.diffs) == 2

    def test_proposals_accumulate_across_diffs(self, industry_payload, evidence_ids):
        log = new_change_log("AAPL", "industry_v1")
        for i, (stage, ms) in enumerate([
            ("GROWTH", "COMPETITIVE"),
            ("MATURE",  "OLIGOPOLY"),
            ("GROWTH",  "COMPETITIVE"),
        ]):
            prior_stage = ["GROWTH", "MATURE", "MATURE"][i]
            prior_ms    = ["COMPETITIVE", "COMPETITIVE", "OLIGOPOLY"][i]
            diff = diff_payloads(
                prior=mutate(industry_payload, cycle_stage=prior_stage, market_structure=prior_ms),
                current=mutate(industry_payload, cycle_stage=stage, market_structure=ms),
                agent_id="industry_v1",
                prior_run_id=f"r{i}",
                current_run_id=f"r{i + 1}",
                ticker="AAPL",
                current_evidence_ids=evidence_ids,
            )
            log.append_diff(diff)
        total = sum(len(d.assumption_proposals) for d in log.diffs)
        assert total >= 1

    def test_earlier_diffs_not_mutated_by_later_appends(self, industry_payload, evidence_ids):
        log = new_change_log("AAPL", "industry_v1")
        diff1 = diff_payloads(
            prior=industry_payload,
            current=mutate(industry_payload, cycle_stage="MATURE"),
            agent_id="industry_v1", prior_run_id="r1", current_run_id="r2",
            ticker="AAPL", current_evidence_ids=evidence_ids,
        )
        log.append_diff(diff1)
        first_diff_id = log.diffs[0].diff_id
        diff2 = diff_payloads(
            prior=mutate(industry_payload, cycle_stage="MATURE"),
            current=mutate(industry_payload, cycle_stage="GROWTH"),
            agent_id="industry_v1", prior_run_id="r2", current_run_id="r3",
            ticker="AAPL", current_evidence_ids=evidence_ids,
        )
        log.append_diff(diff2)
        # First diff unchanged
        assert log.diffs[0].diff_id == first_diff_id
        assert len(log.diffs) == 2

    def test_change_log_total_counts_non_unchanged(self, industry_payload, evidence_ids):
        log = new_change_log("AAPL", "industry_v1")
        for i in range(3):
            diff = diff_payloads(
                prior=mutate(industry_payload, cycle_stage="GROWTH"),
                current=mutate(industry_payload, cycle_stage="MATURE"),
                agent_id="industry_v1",
                prior_run_id=f"r{i}", current_run_id=f"r{i+1}",
                ticker="AAPL", current_evidence_ids=evidence_ids,
            )
            log.append_diff(diff)
        assert log.total_changes >= 3
        assert log.material_changes >= 3

    def test_no_op_diffs_do_not_increase_material_count(self, industry_payload, evidence_ids):
        log = new_change_log("AAPL", "industry_v1")
        for _ in range(3):
            diff = diff_payloads(
                prior=industry_payload, current=industry_payload,
                agent_id="industry_v1", prior_run_id="r1", current_run_id="r2",
                ticker="AAPL", current_evidence_ids=evidence_ids,
            )
            log.append_diff(diff)
        assert log.material_changes == 0

    def test_oscillation_across_two_diffs(self, industry_payload, evidence_ids):
        """Value goes GROWTH → MATURE → GROWTH. Second diff should detect the reversal."""
        log = new_change_log("AAPL", "industry_v1")
        diff1 = diff_payloads(
            prior=mutate(industry_payload, cycle_stage="GROWTH"),
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
        # Both diffs detected a cycle_stage change
        for d in log.diffs:
            changed = [c for c in d.field_changes if "cycle_stage" in c.field_path
                       and c.change_type == ChangeType.MODIFIED]
            assert len(changed) >= 1

    def test_json_round_trip(self, industry_payload, evidence_ids):
        """ChangeLog must serialize and deserialize cleanly."""
        from equity_os.diff.models import ChangeLog
        log = new_change_log("AAPL", "industry_v1")
        diff = diff_payloads(
            prior=industry_payload,
            current=mutate(industry_payload, cycle_stage="MATURE"),
            agent_id="industry_v1", prior_run_id="r1", current_run_id="r2",
            ticker="AAPL", current_evidence_ids=evidence_ids,
        )
        log.append_diff(diff)
        raw = log.model_dump_json()
        log2 = ChangeLog.model_validate_json(raw)
        assert len(log2.diffs) == 1
        assert log2.diffs[0].diff_id == log.diffs[0].diff_id

    def test_multi_agent_logs_independent(self, industry_payload, strategy_payload, evidence_ids):
        """Industry and strategy logs must not interfere."""
        ind_log = new_change_log("AAPL", "industry_v1")
        strat_log = new_change_log("AAPL", "strategy_v1")
        ind_diff = diff_payloads(
            prior=industry_payload,
            current=mutate(industry_payload, cycle_stage="MATURE"),
            agent_id="industry_v1", prior_run_id="r1", current_run_id="r2",
            ticker="AAPL", current_evidence_ids=evidence_ids,
        )
        strat_diff = diff_payloads(
            prior=strategy_payload, current=strategy_payload,
            agent_id="strategy_v1", prior_run_id="r1", current_run_id="r2",
            ticker="AAPL", current_evidence_ids=evidence_ids,
        )
        ind_log.append_diff(ind_diff)
        strat_log.append_diff(strat_diff)
        assert ind_log.agent_id == "industry_v1"
        assert strat_log.agent_id == "strategy_v1"
        assert len(ind_log.diffs) == 1
        assert len(strat_log.diffs) == 1
