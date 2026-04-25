"""Tests for synthesis functions — thesis, variant, drivers, confidence summary."""

from __future__ import annotations

import copy
from datetime import datetime, timedelta

import pytest

from equity_os.orchestrator.orchestrator import Orchestrator
from equity_os.orchestrator.policy import OrchestratorPolicy
from equity_os.orchestrator.synthesis import (
    build_confidence_summary,
    compute_freshness_penalty,
)


@pytest.fixture
def policy():
    return OrchestratorPolicy.load()


def _orch(scenario, policy, **kw):
    return Orchestrator(policy=policy).run(ticker="AAPL", **scenario, **kw)


class TestThesisSynthesis:
    def test_thesis_mentions_ticker(self, aligned, policy):
        d = _orch(aligned, policy)
        assert "AAPL" in d.inferences.thesis_statement

    def test_thesis_mentions_industry_label(self, aligned, policy):
        d = _orch(aligned, policy)
        ind_label = aligned["industry"].get("industry_label", "")
        first_word = ind_label.split()[0].lower() if ind_label else ""
        # Thesis should reference the industry or cycle
        assert first_word in d.inferences.thesis_statement.lower() or "cycle" in d.inferences.thesis_statement.lower()

    def test_thesis_non_empty_for_all_scenarios(self, aligned, conflicting, sparse, stale, policy):
        for scenario in [aligned, conflicting, sparse, stale]:
            d = Orchestrator(policy=policy).run(ticker="AAPL", **scenario)
            assert len(d.inferences.thesis_statement) > 20

    def test_variant_view_references_risk(self, aligned, policy):
        d = _orch(aligned, policy)
        memo_lower = d.inferences.variant_view.lower()
        assert any(w in memo_lower for w in ["risk", "regulatory", "competition", "maturation", "case", "uncertain"])


class TestVariantView:
    def test_variant_highlights_regulatory_when_present(self, aligned, policy):
        d = _orch(aligned, policy)
        # Our AAPL fixtures include regulatory factors
        if d.observations.regulatory_factors:
            assert any(
                word in d.inferences.variant_view.lower()
                for word in ["regulat", "dma", "headwind", "constrain"]
            )

    def test_variant_non_empty_sparse(self, sparse, policy):
        d = _orch(sparse, policy)
        assert len(d.inferences.variant_view) > 10


class TestDrivers:
    def test_top_drivers_non_empty(self, aligned, policy):
        d = _orch(aligned, policy)
        assert len(d.inferences.top_drivers) >= 1

    def test_driver_confidence_in_range(self, aligned, policy):
        d = _orch(aligned, policy)
        for dr in d.inferences.top_drivers:
            assert 0.0 <= dr.confidence <= 1.0

    def test_driver_has_based_on(self, aligned, policy):
        d = _orch(aligned, policy)
        for dr in d.inferences.top_drivers:
            assert len(dr.based_on) >= 1

    def test_driver_text_non_empty(self, aligned, policy):
        d = _orch(aligned, policy)
        for dr in d.inferences.top_drivers:
            assert len(dr.text) > 10


class TestKeyAssumptions:
    def test_key_assumptions_non_empty(self, aligned, policy, sample_ledger):
        d = _orch(aligned, policy, assumptions=sample_ledger)
        assert len(d.inferences.key_assumptions) >= 1

    def test_adjusted_confidence_in_range(self, aligned, policy, sample_ledger):
        d = _orch(aligned, policy, assumptions=sample_ledger)
        for a in d.inferences.key_assumptions:
            assert 0.0 <= a.adjusted_confidence <= 1.0

    def test_ledger_assumptions_included(self, aligned, policy, sample_ledger):
        d = _orch(aligned, policy, assumptions=sample_ledger)
        keys = [a.key for a in d.inferences.key_assumptions]
        assert "services_rev_cagr" in keys

    def test_synthesized_assumptions_present_without_ledger(self, aligned, policy):
        d = _orch(aligned, policy, assumptions=[])
        keys = [a.key for a in d.inferences.key_assumptions]
        assert "industry_cycle_stage" in keys
        assert "market_structure" in keys


class TestConfidenceSummary:
    def test_overall_confidence_bounded(self, aligned, policy):
        d = _orch(aligned, policy)
        assert 0.05 <= d.confidence_summary.overall <= 0.95

    def test_stale_has_higher_freshness_penalty(self, stale, aligned, policy):
        d_stale = Orchestrator(policy=policy).run(ticker="AAPL", **stale)
        d_fresh = Orchestrator(policy=policy).run(ticker="AAPL", **aligned)
        assert d_stale.confidence_summary.freshness_penalty > d_fresh.confidence_summary.freshness_penalty

    def test_conflict_penalty_increases_for_hard_conflict(self, high_conf_contra, aligned, policy):
        d_conflict = Orchestrator(policy=policy).run(ticker="AAPL", **high_conf_contra)
        d_aligned = Orchestrator(policy=policy).run(ticker="AAPL", **aligned)
        assert d_conflict.confidence_summary.conflict_penalty >= d_aligned.confidence_summary.conflict_penalty

    def test_freshness_penalty_computation(self):
        p = OrchestratorPolicy.load()
        old_payload = {"generated_at": (datetime.utcnow() - timedelta(days=200)).isoformat()}
        fresh_payload = {"generated_at": datetime.utcnow().isoformat()}
        assert compute_freshness_penalty(old_payload, p) >= 0.10
        assert compute_freshness_penalty(fresh_payload, p) == 0.0

    def test_confidence_summary_has_basis(self, aligned, policy):
        d = _orch(aligned, policy)
        assert len(d.confidence_summary.basis) > 20
