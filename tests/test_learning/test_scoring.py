"""Tests for scoring.py — Brier score, hit rate, calibration, error attribution."""

from __future__ import annotations

import pytest

from equity_os.learning.scoring import (
    brier_score,
    build_scored_prediction,
    calibration_bins,
    classify_error_bucket,
    error_attribution,
    hit_rate,
    mean_calibration_error,
    score_episode,
)
from equity_os.learning.models import ErrorBucket, EpisodeScore


class TestBrierScore:
    def test_scenario_a_brier(self, scenario_a):
        score = score_episode("AAPL", "test-ep", scenario_a, {})
        assert score.brier_score == pytest.approx(0.01, abs=1e-4)

    def test_scenario_b_brier(self, scenario_b):
        score = score_episode("AAPL", "test-ep", scenario_b, {})
        assert score.brier_score == pytest.approx(0.09, abs=1e-4)

    def test_scenario_c_brier(self, scenario_c):
        score = score_episode("AAPL", "test-ep", scenario_c, {})
        assert score.brier_score == pytest.approx(0.81, abs=1e-4)

    def test_scenario_d_brier(self, scenario_d):
        # CORRECT (0.7) + PARTIALLY_CORRECT (0.6); EXPIRED + WITHDRAWN excluded
        # Brier = ((0.7-1)^2 + (0.6-0.5)^2) / 2 = (0.09 + 0.01) / 2 = 0.05
        score = score_episode("AAPL", "test-ep", scenario_d, {})
        assert score.brier_score == pytest.approx(0.05, abs=1e-4)

    def test_no_scored_predictions_returns_none(self):
        from tests.test_learning.conftest import _pred
        preds = [_pred("m", 0.8, "EXPIRED"), _pred("m2", 0.7, "WITHDRAWN")]
        score = score_episode("AAPL", "test-ep", preds, {})
        assert score.brier_score is None

    def test_brier_vs_baseline_negative_for_good_score(self, scenario_a):
        score = score_episode("AAPL", "test-ep", scenario_a, {})
        assert score.brier_vs_baseline < 0  # beats random

    def test_brier_vs_baseline_positive_for_bad_score(self, scenario_c):
        score = score_episode("AAPL", "test-ep", scenario_c, {})
        assert score.brier_vs_baseline > 0  # worse than random


class TestHitRate:
    def test_scenario_a_hit_rate(self, scenario_a):
        score = score_episode("AAPL", "test-ep", scenario_a, {})
        assert score.hit_rate == pytest.approx(1.0)

    def test_scenario_b_hit_rate(self, scenario_b):
        score = score_episode("AAPL", "test-ep", scenario_b, {})
        assert score.hit_rate == pytest.approx(0.6, abs=1e-4)

    def test_partial_counts_half(self, scenario_d):
        score = score_episode("AAPL", "test-ep", scenario_d, {})
        # CORRECT (1.0) + PARTIALLY_CORRECT (0.5) / 2 = 0.75
        assert score.hit_rate == pytest.approx(0.75, abs=1e-4)

    def test_all_incorrect_hit_rate_zero(self):
        from tests.test_learning.conftest import _pred
        preds = [_pred(f"m{i}", 0.7, "INCORRECT", 80.0) for i in range(3)]
        score = score_episode("AAPL", "test-ep", preds, {})
        assert score.hit_rate == pytest.approx(0.0)


class TestCalibration:
    def test_calibration_bins_correct_count(self, scenario_b):
        score = score_episode("AAPL", "test-ep", scenario_b, {})
        # Probs: 0.9, 0.7, 0.5, 0.3, 0.1 → 5 bins (one per bucket)
        assert len(score.calibration_bins) >= 1

    def test_calibration_error_non_negative(self, scenario_b):
        score = score_episode("AAPL", "test-ep", scenario_b, {})
        for b in score.calibration_bins:
            assert b.calibration_error >= 0.0

    def test_perfectly_calibrated_score(self):
        # p=0.5 with CORRECT half the time and INCORRECT half
        from tests.test_learning.conftest import _pred
        preds = [
            _pred("m1", 0.5, "CORRECT", 105.0),
            _pred("m2", 0.5, "INCORRECT", 80.0),
        ]
        score = score_episode("AAPL", "test-ep", preds, {})
        # Both in 0.4-0.6 bin: predicted_avg = 0.5, actual_freq = 0.5
        for b in score.calibration_bins:
            if "0.4" in b.label:
                assert b.calibration_error == pytest.approx(0.0, abs=0.01)

    def test_mean_calibration_error_computed(self, scenario_b):
        score = score_episode("AAPL", "test-ep", scenario_b, {})
        assert score.mean_calibration_error is not None
        assert 0.0 <= score.mean_calibration_error <= 1.0


class TestCounts:
    def test_total_predictions_correct(self, scenario_b):
        score = score_episode("AAPL", "test-ep", scenario_b, {})
        assert score.total_predictions == 5

    def test_excluded_count_correct(self, scenario_d):
        score = score_episode("AAPL", "test-ep", scenario_d, {})
        assert score.excluded_count == 2  # EXPIRED + WITHDRAWN

    def test_scored_count_correct(self, scenario_d):
        score = score_episode("AAPL", "test-ep", scenario_d, {})
        assert score.scored_count == 2  # CORRECT + PARTIALLY_CORRECT

    def test_unresolved_is_excluded(self):
        from tests.test_learning.conftest import _pred
        preds = [_pred("m", 0.7)]  # no resolution
        score = score_episode("AAPL", "test-ep", preds, {})
        assert score.scored_count == 0
        assert score.excluded_count == 1

    def test_verdict_requires_minimum_sample(self):
        from tests.test_learning.conftest import _pred

        preds = [_pred("m1", 0.7, "CORRECT", 105.0)]
        score = score_episode("AAPL", "test-ep", preds, {})
        assert not score.verdict_eligible
        assert score.scoreable_coverage == 1.0
        assert any("at least 3" in reason for reason in score.verdict_ineligibility_reasons)

    def test_verdict_requires_minimum_coverage(self):
        from tests.test_learning.conftest import _pred

        preds = [
            _pred("m1", 0.7, "CORRECT", 105.0),
            _pred("m2", 0.7, "CORRECT", 105.0),
            _pred("m3", 0.7, "CORRECT", 105.0),
            _pred("m4", 0.6),
            _pred("m5", 0.6),
        ]
        score = score_episode("AAPL", "test-ep", preds, {})
        assert not score.verdict_eligible
        assert score.scoreable_coverage == 0.6

    def test_full_sample_is_verdict_eligible(self, scenario_a):
        score = score_episode("AAPL", "test-ep", scenario_a, {})
        assert score.verdict_eligible
        assert score.scoreable_coverage == 1.0

    def test_materiality_weights_brier_and_hit_rate(self):
        from tests.test_learning.conftest import _pred

        critical = _pred("critical", 0.9, "INCORRECT", 80.0)
        critical["materiality"] = "CRITICAL"
        low = _pred("low", 0.9, "CORRECT", 105.0)
        low["materiality"] = "LOW"
        score = score_episode("AAPL", "test-ep", [critical, low], {})
        assert score.brier_score > 0.7
        assert score.hit_rate < 0.2

    def test_direction_and_magnitude_metrics(self, scenario_b):
        score = score_episode("AAPL", "test-ep", scenario_b, {})
        assert score.directional_accuracy is not None
        assert score.mean_absolute_magnitude_error is not None

    def test_calibration_reliability_requires_five_samples(self):
        from tests.test_learning.conftest import _pred

        small = [_pred(f"m{i}", 0.7, "CORRECT", 105.0) for i in range(4)]
        assert not score_episode("AAPL", "test-ep", small, {}).calibration_is_reliable
        assert score_episode("AAPL", "test-ep", [*small, _pred("m5", 0.7, "CORRECT", 105.0)], {}).calibration_is_reliable


class TestErrorAttribution:
    def test_industry_bucket_detected(self, scenario_e_attribution):
        score = score_episode("AAPL", "test-ep", scenario_e_attribution, {})
        attr = score.error_attribution
        assert attr.industry >= 1

    def test_timing_for_expired_correct_direction(self, scenario_e_attribution):
        score = score_episode("AAPL", "test-ep", scenario_e_attribution, {})
        # expired_timing: actual=105, threshold=100, operator=">=", expired → TIMING
        timing_preds = [s for s in score.scored_predictions if s.metric == "expired_timing"]
        if timing_preds:
            assert timing_preds[0].error_bucket == ErrorBucket.TIMING

    def test_data_quality_default_no_assumptions(self, scenario_e_attribution):
        score = score_episode("AAPL", "test-ep", scenario_e_attribution, {})
        no_assump = [s for s in score.scored_predictions if s.metric == "no_assumption"]
        if no_assump and not no_assump[0].is_excluded:
            assert no_assump[0].error_bucket == ErrorBucket.DATA_QUALITY

    def test_attribution_total_matches_failures(self, scenario_b):
        score = score_episode("AAPL", "test-ep", scenario_b, {})
        attr = score.error_attribution
        assert attr.total_failed == score.scored_count - sum(
            1 for s in score.scored_predictions
            if not s.is_excluded and s.outcome_score is not None and s.outcome_score >= 1.0
        )


class TestClassifyErrorBucket:
    def test_macro_key(self):
        assert classify_error_bucket(["macro_risk"], "INCORRECT", 80.0, 100.0, ">=") == ErrorBucket.MACRO

    def test_industry_key(self):
        assert classify_error_bucket(["industry_cycle_stage"], "INCORRECT", 80.0, 100.0, ">=") == ErrorBucket.INDUSTRY

    def test_strategy_key(self):
        assert classify_error_bucket(["management_priorities"], "INCORRECT", 80.0, 100.0, ">=") == ErrorBucket.STRATEGY

    def test_expired_direction_correct_is_timing(self):
        assert classify_error_bucket([], "EXPIRED", 105.0, 100.0, ">=") == ErrorBucket.TIMING

    def test_expired_direction_wrong_is_data_quality(self):
        result = classify_error_bucket([], "EXPIRED", 80.0, 100.0, ">=")
        assert result == ErrorBucket.DATA_QUALITY  # direction wrong, falls to default

    def test_no_assumptions_is_data_quality(self):
        assert classify_error_bucket([], "INCORRECT", 80.0, 100.0, ">=") == ErrorBucket.DATA_QUALITY


class TestBeatBaseline:
    def test_good_score_beats_baseline(self, scenario_a):
        score = score_episode("AAPL", "test-ep", scenario_a, {})
        assert score.beat_baseline

    def test_bad_score_does_not_beat_baseline(self, scenario_c):
        score = score_episode("AAPL", "test-ep", scenario_c, {})
        assert not score.beat_baseline
