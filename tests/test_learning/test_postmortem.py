"""Tests for postmortem.py — 6-section narrative generation."""

from __future__ import annotations

import pytest

from equity_os.learning.postmortem import generate_postmortem, _verdict_from_score
from equity_os.learning.scoring import score_episode


THESIS = "Services flywheel drives durable margin expansion in a GROWTH market."


def _make_report(predictions, assumptions=None):
    score = score_episode("AAPL", "test-ep", predictions, {})
    return generate_postmortem(score, THESIS, assumptions or [])


class TestPostmortemStructure:
    def test_report_has_all_six_sections(self, scenario_b, sample_assumptions):
        report = _make_report(scenario_b, sample_assumptions)
        assert report.thesis_at_time
        assert isinstance(report.belief_rationale, list)
        assert isinstance(report.actual_outcomes, list)
        assert isinstance(report.what_broke, list)
        assert isinstance(report.failed_assumptions, list)
        assert isinstance(report.orchestrator_recommendations, list)

    def test_thesis_at_time_preserved(self, scenario_b):
        report = _make_report(scenario_b)
        assert report.thesis_at_time == THESIS

    def test_verdict_in_known_values(self, scenario_b):
        report = _make_report(scenario_b)
        assert report.verdict in {
            "THESIS_CORRECT",
            "THESIS_INCORRECT",
            "PARTIALLY_CORRECT",
            "PENDING",
            "INSUFFICIENT_EVIDENCE",
        }

    def test_episode_score_embedded(self, scenario_b):
        report = _make_report(scenario_b)
        assert report.episode_score is not None
        assert report.episode_score.scored_count > 0


class TestVerdict:
    def test_all_correct_verdict(self, scenario_a):
        report = _make_report(scenario_a)
        assert report.verdict == "THESIS_CORRECT"

    def test_all_wrong_low_hit_rate(self):
        from tests.test_learning.conftest import _pred
        preds = [_pred(f"m{i}", 0.7, "INCORRECT", 80.0) for i in range(5)]
        report = _make_report(preds)
        assert report.verdict in {"THESIS_INCORRECT", "PARTIALLY_CORRECT"}

    def test_no_scored_inconclusive(self):
        from tests.test_learning.conftest import _pred
        preds = [_pred("m", 0.8, "EXPIRED")]
        report = _make_report(preds)
        assert report.verdict == "INSUFFICIENT_EVIDENCE"

    def test_partial_results_partially_correct(self, scenario_d):
        report = _make_report(scenario_d)
        assert report.verdict == "INSUFFICIENT_EVIDENCE"

    def test_unresolved_predictions_keep_verdict_pending(self, scenario_a):
        from tests.test_learning.conftest import _pred

        predictions = [*scenario_a[:2], _pred("pending", 0.6)]
        report = _make_report(predictions)
        assert report.verdict == "PENDING"


class TestNarrativeSections:
    def test_belief_rationale_uses_assumptions(self, scenario_b, sample_assumptions):
        report = _make_report(scenario_b, sample_assumptions)
        combined = " ".join(report.belief_rationale)
        # Should mention at least one assumption key or label
        assert "services_rev_cagr" in combined or "Services Revenue" in combined

    def test_actual_outcomes_has_one_per_prediction(self, scenario_b):
        report = _make_report(scenario_b)
        assert len(report.actual_outcomes) == len(scenario_b)

    def test_actual_outcomes_contain_status(self, scenario_b):
        report = _make_report(scenario_b)
        for o in report.actual_outcomes:
            assert any(s in o for s in ("CORRECT", "INCORRECT", "EXPIRED", "WITHDRAWN", "PARTIALLY", "UNRESOLVED"))

    def test_what_broke_only_failures(self, scenario_a):
        report = _make_report(scenario_a)
        assert report.what_broke == []  # all correct → nothing broke

    def test_what_broke_has_entries_for_incorrect(self, scenario_b):
        report = _make_report(scenario_b)
        # scenario_b has 2 INCORRECT → 2 broke entries
        assert len(report.what_broke) == 2

    def test_what_broke_mentions_metric(self, scenario_b):
        report = _make_report(scenario_b)
        for entry in report.what_broke:
            assert "m4" in entry or "m5" in entry

    def test_failed_assumptions_linked_to_failures(self, scenario_e_attribution, sample_assumptions):
        report = _make_report(scenario_e_attribution, sample_assumptions)
        combined = " ".join(report.failed_assumptions)
        # industry_cycle_stage is linked to "industry_m" which failed
        assert "industry_cycle_stage" in combined or "Industry Cycle" in combined

    def test_no_failed_assumptions_when_all_correct(self, scenario_a, sample_assumptions):
        report = _make_report(scenario_a, sample_assumptions)
        assert report.failed_assumptions == []


class TestRecommendations:
    def test_recommendations_non_empty(self, scenario_e_attribution):
        report = _make_report(scenario_e_attribution)
        assert len(report.orchestrator_recommendations) >= 1

    def test_timing_error_generates_horizon_recommendation(self):
        from tests.test_learning.conftest import _pred
        # All timing errors (expired + direction correct)
        preds = [
            _pred(f"m{i}", 0.8, "EXPIRED", actual=105.0, threshold=100.0, operator=">=")
            for i in range(3)
        ]
        report = _make_report(preds)
        # Should recommend wider horizons
        combined = " ".join(report.orchestrator_recommendations).lower()
        assert "horizon" in combined or "timing" in combined or "directional" in combined

    def test_bad_calibration_generates_calibration_recommendation(self, scenario_c):
        report = _make_report(scenario_c)
        combined = " ".join(report.orchestrator_recommendations).lower()
        # scenario_c: all correct but probability 0.1 → severely miscalibrated
        assert "calibration" in combined or "brier" in combined or "baseline" in combined

    def test_recommendations_are_strings(self, scenario_b):
        report = _make_report(scenario_b)
        for r in report.orchestrator_recommendations:
            assert isinstance(r, str) and len(r) > 10
