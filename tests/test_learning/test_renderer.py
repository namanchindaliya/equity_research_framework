"""Tests for the learning loop markdown renderer."""

from __future__ import annotations

import pytest

from equity_os.learning.postmortem import generate_postmortem
from equity_os.learning.renderer import render_episode_score, render_postmortem
from equity_os.learning.scoring import score_episode

THESIS = "Services growth drives the thesis."


def _score(predictions):
    return score_episode("AAPL", "test-ep", predictions, {})


def _report(predictions, assumptions=None):
    score = _score(predictions)
    return generate_postmortem(score, THESIS, assumptions or [])


class TestScoreRenderer:
    def test_score_memo_has_header(self, scenario_b):
        md = render_episode_score(_score(scenario_b))
        assert "Episode Score" in md
        assert "AAPL" in md

    def test_score_memo_has_brier(self, scenario_b):
        md = render_episode_score(_score(scenario_b))
        assert "Brier" in md

    def test_score_memo_has_hit_rate(self, scenario_b):
        md = render_episode_score(_score(scenario_b))
        assert "Hit rate" in md or "hit_rate" in md.lower()

    def test_score_memo_has_calibration_table(self, scenario_b):
        md = render_episode_score(_score(scenario_b))
        assert "Calibration" in md

    def test_score_memo_has_error_attribution(self, scenario_e_attribution):
        md = render_episode_score(_score(scenario_e_attribution))
        assert "Error Attribution" in md

    def test_score_memo_has_prediction_detail(self, scenario_b):
        md = render_episode_score(_score(scenario_b))
        assert "Prediction Detail" in md

    def test_score_memo_no_scoring_for_excluded(self, scenario_d):
        md = render_episode_score(_score(scenario_d))
        assert "excluded" in md.lower() or "EXPIRED" in md or "WITHDRAWN" in md


class TestPostmortemRenderer:
    def test_postmortem_has_six_sections(self, scenario_b):
        md = render_postmortem(_report(scenario_b))
        assert "## 1. What We Believed" in md
        assert "## 2. Why We Believed It" in md
        assert "## 3. What Actually Happened" in md
        assert "## 4. What Broke" in md
        assert "## 5. Which Assumptions Failed" in md
        assert "## 6. What the Orchestrator Should Do Differently" in md

    def test_postmortem_sections_in_order(self, scenario_b):
        md = render_postmortem(_report(scenario_b))
        positions = [md.index(f"## {i}.") for i in range(1, 7)]
        assert positions == sorted(positions)

    def test_postmortem_has_verdict(self, scenario_a):
        md = render_postmortem(_report(scenario_a))
        assert "THESIS_CORRECT" in md or "PARTIALLY_CORRECT" in md or "INCONCLUSIVE" in md

    def test_postmortem_thesis_quoted(self, scenario_b):
        md = render_postmortem(_report(scenario_b))
        assert THESIS in md

    def test_postmortem_has_score_summary(self, scenario_b):
        md = render_postmortem(_report(scenario_b))
        assert "Score Summary" in md

    def test_postmortem_all_correct_nothing_broke(self, scenario_a):
        md = render_postmortem(_report(scenario_a))
        assert "No prediction failures" in md

    def test_postmortem_broken_predictions_mentioned(self, scenario_b):
        md = render_postmortem(_report(scenario_b))
        # m4 and m5 are INCORRECT
        assert "m4" in md or "m5" in md

    def test_postmortem_recommendations_listed(self, scenario_b):
        md = render_postmortem(_report(scenario_b))
        assert "## 6." in md
        # Should have at least one numbered recommendation
        assert any(line.strip().startswith("1.") for line in md.splitlines())
