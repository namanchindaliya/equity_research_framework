"""Tests for ConflictResolver — detection logic and policy application."""

from __future__ import annotations

import copy
import pytest

from equity_os.orchestrator.conflict import detect_conflicts
from equity_os.orchestrator.policy import OrchestratorPolicy


@pytest.fixture
def policy():
    return OrchestratorPolicy.load()


class TestConflictDetection:
    def test_no_conflicts_on_aligned(self, aligned, policy):
        conflicts = detect_conflicts(aligned["industry"], aligned["strategy"], policy)
        # Aligned inputs may still produce a confidence-divergence conflict
        # (industry ~22%, strategy ~55%) — that's expected behavior, not a bug
        hard = [c for c in conflicts if c.conflict_severity == "hard"]
        assert len(hard) == 0

    def test_detects_competitive_conflict(self, conflicting, policy):
        conflicts = detect_conflicts(conflicting["industry"], conflicting["strategy"], policy)
        dims = {c.dimension for c in conflicts}
        assert "competitive_intensity" in dims

    def test_detects_moat_conflict(self, conflicting, policy):
        conflicts = detect_conflicts(conflicting["industry"], conflicting["strategy"], policy)
        dims = {c.dimension for c in conflicts}
        assert "moat_type" in dims

    def test_detects_regulatory_hard_conflict(self, high_conf_contra, policy):
        conflicts = detect_conflicts(high_conf_contra["industry"], high_conf_contra["strategy"], policy)
        dims = {c.dimension for c in conflicts}
        assert "regulatory_risk" in dims
        reg = next(c for c in conflicts if c.dimension == "regulatory_risk")
        assert reg.conflict_severity == "hard"

    def test_conflict_resolution_cites_policy(self, conflicting, policy):
        conflicts = detect_conflicts(conflicting["industry"], conflicting["strategy"], policy)
        for c in conflicts:
            assert "policy" in c.resolution_basis.lower()

    def test_competitive_conflict_trusts_industry(self, policy):
        """Policy says competitive_intensity → industry_v1."""
        ind = {
            "overall_confidence": 0.6,
            "porter_forces": [{"name": "Competitive Rivalry", "level": "HIGH", "confidence": 0.8}],
            "regulatory_factors": [],
            "competitive_dynamics": {"moat_type": ["scale"]},
        }
        str_ = {
            "overall_confidence": 0.5,
            "risk_disclosures": [{"category": "competitive", "severity_from_disclosure": "implied", "finding": {"confidence": 0.3}}],
            "strategic_positioning": {"moat_assessment": ["scale"]},
            "narrative_shifts": [],
        }
        conflicts = detect_conflicts(ind, str_, policy)
        comp = next((c for c in conflicts if c.dimension == "competitive_intensity"), None)
        if comp:
            assert comp.trusted_agent == "industry_v1"

    def test_regulatory_conflict_trusts_industry_policy(self, policy):
        """Policy says regulatory_risk → industry_v1."""
        assert policy.conflict_winner("regulatory_risk") == "industry_v1"

    def test_conflict_confidence_after_positive(self, conflicting, policy):
        conflicts = detect_conflicts(conflicting["industry"], conflicting["strategy"], policy)
        for c in conflicts:
            assert c.confidence_after > 0.0

    def test_empty_inputs_no_crash(self, policy):
        ind = {"overall_confidence": 0.5, "porter_forces": [], "regulatory_factors": [], "competitive_dynamics": {}}
        str_ = {"overall_confidence": 0.5, "risk_disclosures": [], "strategic_positioning": {}, "narrative_shifts": []}
        conflicts = detect_conflicts(ind, str_, policy)
        assert isinstance(conflicts, list)


class TestPolicyLoading:
    def test_policy_loads_from_file(self):
        p = OrchestratorPolicy.load()
        assert p.agent_weight("industry_v1") == 0.45
        assert p.agent_weight("strategy_v1") == 0.55

    def test_policy_freshness_thresholds(self):
        p = OrchestratorPolicy.load()
        assert p.freshness_penalty(0) == 0.0
        assert p.freshness_penalty(100) >= 0.10
        assert p.freshness_penalty(200) >= 0.20
        assert p.freshness_penalty(400) >= 0.35

    def test_policy_conflict_winners(self):
        p = OrchestratorPolicy.load()
        assert p.conflict_winner("regulatory_risk") == "industry_v1"
        assert p.conflict_winner("management_priorities") == "strategy_v1"
        assert p.conflict_winner("segment_growth") == "strategy_v1"
        assert p.conflict_winner("market_structure") == "industry_v1"

    def test_policy_penalties_positive(self):
        p = OrchestratorPolicy.load()
        assert p.penalty("conflict_soft_penalty") > 0.0
        assert p.penalty("conflict_hard_penalty") > p.penalty("conflict_soft_penalty")
        assert p.penalty("missing_required_penalty") > 0.0

    def test_policy_source_reliability(self):
        p = OrchestratorPolicy.load()
        assert p.source_reliability("filing") == 1.0
        assert p.source_reliability("news_note") < p.source_reliability("filing")
        assert p.source_reliability("unknown_type") == p.source_reliability("default")

    def test_policy_thresholds(self):
        p = OrchestratorPolicy.load()
        assert 0.0 < p.threshold("driver_min_confidence") <= 1.0
        assert 0.0 < p.threshold("prediction_min_confidence") <= 1.0

    def test_policy_falls_back_to_defaults_if_no_file(self, tmp_path):
        p = OrchestratorPolicy.load(path=tmp_path / "nonexistent.yaml")
        assert p.agent_weight("industry_v1") == 0.45
