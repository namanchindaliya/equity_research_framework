"""Tests for the markdown renderer."""

from __future__ import annotations

import copy

import pytest

from equity_os.diff.engine import diff_payloads, new_change_log
from equity_os.diff.renderer import render_change_log, render_episode_diff

from tests.test_diff.conftest import mutate


class TestEpisodeDiffRenderer:
    def test_memo_has_title(self, industry_payload, evidence_ids):
        diff = diff_payloads(
            prior=industry_payload,
            current=mutate(industry_payload, cycle_stage="MATURE"),
            agent_id="industry_v1", prior_run_id="r1", current_run_id="r2",
            ticker="AAPL", current_evidence_ids=evidence_ids,
        )
        memo = render_episode_diff(diff)
        assert "What changed" in memo
        assert "why it changed" in memo.lower() or "Why It Changed" in memo
        assert "what it means" in memo.lower() or "What It Means" in memo

    def test_memo_has_three_sections(self, industry_payload, evidence_ids):
        diff = diff_payloads(
            prior=industry_payload,
            current=mutate(industry_payload, cycle_stage="MATURE"),
            agent_id="industry_v1", prior_run_id="r1", current_run_id="r2",
            ticker="AAPL", current_evidence_ids=evidence_ids,
        )
        memo = render_episode_diff(diff)
        assert "## 1." in memo
        assert "## 2." in memo
        assert "## 3." in memo

    def test_no_op_memo_states_no_changes(self, industry_payload, evidence_ids):
        diff = diff_payloads(
            prior=industry_payload, current=industry_payload,
            agent_id="industry_v1", prior_run_id="r1", current_run_id="r2",
            ticker="AAPL", current_evidence_ids=evidence_ids,
        )
        memo = render_episode_diff(diff)
        assert "No analytical changes" in memo

    def test_material_change_memo_has_warning(self, industry_payload, evidence_ids):
        diff = diff_payloads(
            prior=industry_payload,
            current=mutate(industry_payload, cycle_stage="MATURE"),
            agent_id="industry_v1", prior_run_id="r1", current_run_id="r2",
            ticker="AAPL", current_evidence_ids=evidence_ids,
        )
        memo = render_episode_diff(diff)
        assert "Material changes" in memo or "material" in memo.lower()

    def test_memo_contains_field_path(self, industry_payload, evidence_ids):
        diff = diff_payloads(
            prior=industry_payload,
            current=mutate(industry_payload, cycle_stage="MATURE"),
            agent_id="industry_v1", prior_run_id="r1", current_run_id="r2",
            ticker="AAPL", current_evidence_ids=evidence_ids,
        )
        memo = render_episode_diff(diff)
        assert "cycle_stage" in memo

    def test_memo_contains_proposal_section(self, industry_payload, evidence_ids):
        diff = diff_payloads(
            prior=industry_payload,
            current=mutate(industry_payload, cycle_stage="MATURE"),
            agent_id="industry_v1", prior_run_id="r1", current_run_id="r2",
            ticker="AAPL", current_evidence_ids=evidence_ids,
        )
        memo = render_episode_diff(diff)
        assert "Proposal" in memo

    def test_memo_contains_implication(self, industry_payload, evidence_ids):
        diff = diff_payloads(
            prior=industry_payload,
            current=mutate(industry_payload, cycle_stage="MATURE"),
            agent_id="industry_v1", prior_run_id="r1", current_run_id="r2",
            ticker="AAPL", current_evidence_ids=evidence_ids,
        )
        memo = render_episode_diff(diff)
        assert "Implication" in memo or "thesis" in memo.lower()

    def test_conflict_section_present_when_conflicts(self, industry_payload, evidence_ids):
        current = copy.deepcopy(industry_payload)
        current["unresolved_questions"] = list(current.get("unresolved_questions", [])) + ["New gap."]
        diff = diff_payloads(
            prior=industry_payload, current=current,
            agent_id="industry_v1", prior_run_id="r1", current_run_id="r2",
            ticker="AAPL", current_evidence_ids=evidence_ids, prior_evidence_ids=evidence_ids,
        )
        memo = render_episode_diff(diff)
        assert "Conflict" in memo or "conflict" in memo.lower()

    def test_no_conflict_section_when_none(self, industry_payload, evidence_ids):
        diff = diff_payloads(
            prior=industry_payload, current=industry_payload,
            agent_id="industry_v1", prior_run_id="r1", current_run_id="r2",
            ticker="AAPL", current_evidence_ids=evidence_ids,
        )
        memo = render_episode_diff(diff)
        assert "⚠️ Conflicts" not in memo


class TestChangeLogRenderer:
    def test_change_log_memo_has_header(self, industry_payload, evidence_ids):
        log = new_change_log("AAPL", "industry_v1")
        diff1 = diff_payloads(
            prior=industry_payload,
            current=mutate(industry_payload, cycle_stage="MATURE"),
            agent_id="industry_v1", prior_run_id="r1", current_run_id="r2",
            ticker="AAPL", current_evidence_ids=evidence_ids,
        )
        log.append_diff(diff1)
        memo = render_change_log(log)
        assert "Change Log" in memo
        assert "AAPL" in memo

    def test_change_log_memo_lists_each_diff(self, industry_payload, evidence_ids):
        log = new_change_log("AAPL", "industry_v1")
        for i in range(3):
            diff = diff_payloads(
                prior=industry_payload,
                current=mutate(industry_payload, overall_confidence=round(0.2 + i * 0.1, 2)),
                agent_id="industry_v1", prior_run_id=f"r{i}", current_run_id=f"r{i+1}",
                ticker="AAPL", current_evidence_ids=evidence_ids,
            )
            log.append_diff(diff)
        memo = render_change_log(log)
        assert "Diff #1" in memo
        assert "Diff #2" in memo
        assert "Diff #3" in memo
