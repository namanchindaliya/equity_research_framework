"""Scoring functions for the learning loop.

All functions are pure (no I/O) and operate on ScoredPrediction lists so they
are easy to unit-test with synthetic data.

Brier Score
-----------
B = (1/N) * Σ(p_i - o_i)²   where N = scored (non-excluded) predictions
o_i = 1.0  for CORRECT
      0.5  for PARTIALLY_CORRECT
      0.0  for INCORRECT

EXPIRED, WITHDRAWN, INCONCLUSIVE predictions are excluded from the score.
EXPIRED predictions where the direction was correct are re-classified as TIMING.

Calibration
-----------
Group by probability bucket (0.0–0.2, 0.2–0.4, ..., 0.8–1.0).
For each bucket: compare mean assigned probability vs actual frequency.

Error Attribution
-----------------
Map linked assumption keys to error buckets via keyword table.
TIMING is assigned when a prediction EXPIRED but direction was correct.
DATA_QUALITY is the default when no assumption key matches.
"""

from __future__ import annotations

import math
from typing import Any

from equity_os.schemas.enums import ResolutionStatus

from .models import (
    CalibrationBin,
    ErrorAttributionSummary,
    ErrorBucket,
    EpisodeScore,
    ScoredPrediction,
)

# ---------------------------------------------------------------------------
# Error bucket keyword mapping
# ---------------------------------------------------------------------------

_BUCKET_KEYWORDS: dict[ErrorBucket, list[str]] = {
    ErrorBucket.MACRO: [
        "macro", "recession", "inflation", "interest_rate", "fx", "currency",
        "gdp", "employment", "fed", "central_bank",
    ],
    ErrorBucket.INDUSTRY: [
        "industry_cycle", "market_structure", "cycle_stage", "porter",
        "competitive_intensity", "entry_barriers", "substitute_threat",
        "supplier_power", "buyer_power", "regulatory", "dma", "antitrust",
    ],
    ErrorBucket.STRATEGY: [
        "management_priorities", "capital_allocation", "segment_priority",
        "strategic_positioning", "target_market", "moat", "credibility",
        "narrative_shift", "guidance",
    ],
    ErrorBucket.VALUATION: [
        "valuation", "multiple", "pe_ratio", "ev_ebitda", "price_target",
        "discount_rate", "wacc", "terminal_value",
    ],
}


def classify_error_bucket(
    linked_assumption_keys: list[str],
    resolved_status: str,
    actual_outcome: Any,
    threshold: Any,
    operator: str,
) -> ErrorBucket:
    """Classify the root cause of a prediction failure.

    TIMING is assigned when the prediction EXPIRED but the direction was correct
    (actual > threshold for '>=' operator, etc.).
    """
    # EXPIRED + directionally correct → timing
    if resolved_status == ResolutionStatus.EXPIRED.value:
        if _direction_correct(actual_outcome, threshold, operator):
            return ErrorBucket.TIMING

    # Search assumption keys for bucket keywords
    all_keys = " ".join(k.lower() for k in linked_assumption_keys)
    for bucket, keywords in _BUCKET_KEYWORDS.items():
        if any(kw in all_keys for kw in keywords):
            return bucket

    return ErrorBucket.DATA_QUALITY


def _direction_correct(actual: Any, threshold: Any, operator: str) -> bool:
    """True if the actual outcome satisfies the prediction direction."""
    try:
        a, t = float(actual), float(threshold)
        return {
            ">":  a > t,
            ">=": a >= t,
            "<":  a < t,
            "<=": a <= t,
            "==": a == t,
        }.get(operator, False)
    except (TypeError, ValueError):
        return False


# ---------------------------------------------------------------------------
# Outcome score
# ---------------------------------------------------------------------------

_OUTCOME_SCORES: dict[str, float] = {
    ResolutionStatus.CORRECT.value:           1.0,
    ResolutionStatus.PARTIALLY_CORRECT.value: 0.5,
    ResolutionStatus.INCORRECT.value:         0.0,
}

_EXCLUDED_STATUSES: set[str] = {
    ResolutionStatus.EXPIRED.value,
    ResolutionStatus.WITHDRAWN.value,
    ResolutionStatus.INCONCLUSIVE.value,
}

_MATERIALITY_WEIGHTS: dict[str, float] = {
    "CRITICAL": 4.0,
    "HIGH": 2.0,
    "MEDIUM": 1.0,
    "LOW": 0.5,
}


def outcome_score(resolved_status: str) -> float | None:
    """Return o_i for Brier scoring, or None if excluded."""
    return _OUTCOME_SCORES.get(resolved_status)


# ---------------------------------------------------------------------------
# Brier score
# ---------------------------------------------------------------------------


def brier_score(scored: list[ScoredPrediction]) -> float | None:
    """Compute Brier score from a list of ScoredPredictions.

    Returns None if no scoreable predictions exist.
    Lower is better; 0.25 = uninformative (always predict 50%).
    """
    scoreable = [s for s in scored if not s.is_excluded and s.brier_contribution is not None]
    if not scoreable:
        return None
    weighted_sum = sum(
        s.brier_contribution * s.score_weight for s in scoreable  # type: ignore[operator]
    )
    total_weight = sum(s.score_weight for s in scoreable)
    return round(weighted_sum / total_weight, 6)


# ---------------------------------------------------------------------------
# Hit rate
# ---------------------------------------------------------------------------


def hit_rate(scored: list[ScoredPrediction]) -> float | None:
    """Fraction of scored predictions that are CORRECT + 0.5 * PARTIALLY_CORRECT."""
    scoreable = [s for s in scored if not s.is_excluded and s.outcome_score is not None]
    if not scoreable:
        return None
    weighted_sum = sum(
        s.outcome_score * s.score_weight for s in scoreable  # type: ignore[operator]
    )
    total_weight = sum(s.score_weight for s in scoreable)
    return round(weighted_sum / total_weight, 4)


# ---------------------------------------------------------------------------
# Calibration
# ---------------------------------------------------------------------------

_BINS: list[tuple[float, float, str]] = [
    (0.0, 0.2,  "0.0–0.2"),
    (0.2, 0.4,  "0.2–0.4"),
    (0.4, 0.6,  "0.4–0.6"),
    (0.6, 0.8,  "0.6–0.8"),
    (0.8, 1.01, "0.8–1.0"),
]


def calibration_bins(scored: list[ScoredPrediction]) -> list[CalibrationBin]:
    """Group non-excluded predictions into probability buckets and compute calibration."""
    scoreable = [s for s in scored if not s.is_excluded and s.outcome_score is not None]
    bins: list[CalibrationBin] = []
    for lo, hi, label in _BINS:
        group = [s for s in scoreable if lo <= s.probability < hi]
        if not group:
            continue
        pred_avg = sum(s.probability for s in group) / len(group)
        actual_freq = sum(s.outcome_score for s in group) / len(group)  # type: ignore[operator]
        bins.append(CalibrationBin(
            label=label, low=lo, high=hi,
            count=len(group),
            predicted_avg=round(pred_avg, 4),
            actual_freq=round(actual_freq, 4),
            calibration_error=round(abs(pred_avg - actual_freq), 4),
        ))
    return bins


def mean_calibration_error(bins: list[CalibrationBin]) -> float | None:
    if not bins:
        return None
    weighted = sum(b.calibration_error * b.count for b in bins)
    total = sum(b.count for b in bins)
    return round(weighted / total, 4) if total else None


# ---------------------------------------------------------------------------
# Error attribution summary
# ---------------------------------------------------------------------------


def error_attribution(scored: list[ScoredPrediction]) -> ErrorAttributionSummary:
    """Count failures by error bucket.

    TIMING-classified EXPIRED predictions are counted even though they are
    excluded from Brier scoring — they represent a systematic timing failure
    and should drive timing-specific recommendations.
    """
    summary = ErrorAttributionSummary()
    for s in scored:
        if s.is_excluded:
            # Include TIMING bucket even for excluded predictions
            if s.error_bucket == ErrorBucket.TIMING:
                summary.timing += 1
                summary.total_failed += 1
            continue
        if s.outcome_score is None or s.outcome_score >= 1.0:
            continue
        summary.total_failed += 1
        bucket = s.error_bucket or ErrorBucket.DATA_QUALITY
        match bucket:
            case ErrorBucket.MACRO:         summary.macro += 1
            case ErrorBucket.INDUSTRY:      summary.industry += 1
            case ErrorBucket.STRATEGY:      summary.strategy += 1
            case ErrorBucket.VALUATION:     summary.valuation += 1
            case ErrorBucket.TIMING:        summary.timing += 1
            case _:                         summary.data_quality += 1
    return summary


# ---------------------------------------------------------------------------
# Build ScoredPrediction from domain objects
# ---------------------------------------------------------------------------


def build_scored_prediction(
    prediction: dict,
    resolution: dict | None,
) -> ScoredPrediction:
    """Build a ScoredPrediction from raw dicts (prediction + optional resolution)."""
    sp = ScoredPrediction(
        prediction_id=prediction["id"],
        metric=prediction.get("metric", ""),
        description=prediction.get("description", ""),
        horizon=prediction.get("horizon", ""),
        due_date=prediction.get("due_date"),
        probability=float(prediction.get("probability", 0.5)),
        threshold=prediction.get("threshold"),
        operator=prediction.get("operator", ">="),
        linked_assumption_keys=prediction.get("supporting_assumptions", []),
        materiality=str(prediction.get("materiality", "MEDIUM")),
        score_weight=_MATERIALITY_WEIGHTS.get(str(prediction.get("materiality", "MEDIUM")), 1.0),
    )

    if resolution is None:
        sp.exclusion_reason = "unresolved"
        sp.is_excluded = True
        return sp

    status = resolution.get("resolved_status", "")
    sp.resolved_status = status
    sp.actual_outcome = resolution.get("actual_outcome")
    sp.error_magnitude = resolution.get("error_magnitude")
    sp.resolution_notes = resolution.get("notes", "")
    sp.source_of_truth = (resolution.get("source") or {}).get("reference") if isinstance(resolution.get("source"), dict) else None
    if sp.operator in {">", ">=", "<", "<=", "=="}:
        try:
            float(sp.actual_outcome)
            float(sp.threshold)
        except (TypeError, ValueError):
            pass
        else:
            sp.direction_correct = _direction_correct(
                sp.actual_outcome,
                sp.threshold,
                sp.operator,
            )

    if status in _EXCLUDED_STATUSES:
        sp.is_excluded = True
        sp.exclusion_reason = status.lower()
        # EXPIRED with correct direction → classify as TIMING
        if status == ResolutionStatus.EXPIRED.value:
            sp.error_bucket = classify_error_bucket(
                sp.linked_assumption_keys, status,
                sp.actual_outcome, sp.threshold, sp.operator,
            )
        return sp

    o_i = outcome_score(status)
    if o_i is None:
        sp.is_excluded = True
        sp.exclusion_reason = f"unknown_status:{status}"
        return sp

    sp.outcome_score = o_i
    sp.brier_contribution = round((sp.probability - o_i) ** 2, 6)

    if o_i < 1.0:
        sp.error_bucket = classify_error_bucket(
            sp.linked_assumption_keys, status,
            sp.actual_outcome, sp.threshold, sp.operator,
        )

    return sp


# ---------------------------------------------------------------------------
# Public: score_episode
# ---------------------------------------------------------------------------


def score_episode(
    ticker: str,
    episode_slug: str,
    predictions: list[dict],
    resolutions_by_metric: dict[str, dict],
) -> EpisodeScore:
    """Score all predictions for one episode.

    Parameters
    ----------
    predictions           : list of PredictionRecord.model_dump() dicts
    resolutions_by_metric : metric → ResolutionRecord.model_dump() dict
    """
    scored: list[ScoredPrediction] = []
    for pred in predictions:
        metric = pred.get("metric", "")
        # Support both resolution embedded in prediction dict or via separate dict
        resolution = None
        if pred.get("resolution"):
            resolution = pred["resolution"]
        elif metric in resolutions_by_metric:
            resolution = resolutions_by_metric[metric]
        scored.append(build_scored_prediction(pred, resolution))

    excluded = [s for s in scored if s.is_excluded]
    scoreable = [s for s in scored if not s.is_excluded]
    unresolved_count = sum(1 for s in scored if s.resolved_status is None)
    resolved_count = sum(1 for s in scored if s.resolved_status is not None)
    total = len(predictions)
    resolution_coverage = resolved_count / total if total else 0.0
    scoreable_coverage = len(scoreable) / total if total else 0.0

    minimum_verdict_coverage = 2 / 3
    minimum_verdict_sample = 3
    ineligibility_reasons: list[str] = []
    if len(scoreable) < minimum_verdict_sample:
        ineligibility_reasons.append(
            f"Only {len(scoreable)} scoreable prediction(s); at least {minimum_verdict_sample} are required."
        )
    if scoreable_coverage < minimum_verdict_coverage:
        ineligibility_reasons.append(
            f"Scoreable coverage is {scoreable_coverage:.0%}; at least {minimum_verdict_coverage:.0%} is required."
        )

    b = brier_score(scored)
    hr = hit_rate(scored)
    cb = calibration_bins(scored)
    mce = mean_calibration_error(cb)
    ea = error_attribution(scored)
    direction_values = [s.direction_correct for s in scoreable if s.direction_correct is not None]
    directional_accuracy = (
        round(sum(bool(value) for value in direction_values) / len(direction_values), 4)
        if direction_values
        else None
    )
    magnitudes = [
        abs(s.error_magnitude)
        for s in scoreable
        if s.error_magnitude is not None and math.isfinite(s.error_magnitude)
    ]
    mean_absolute_magnitude_error = (
        round(sum(magnitudes) / len(magnitudes), 6) if magnitudes else None
    )
    minimum_calibration_sample = 5

    return EpisodeScore(
        ticker=ticker,
        episode_slug=episode_slug,
        total_predictions=len(predictions),
        resolved_count=resolved_count,
        excluded_count=len(excluded),
        scored_count=len(scoreable),
        unresolved_count=unresolved_count,
        resolution_coverage=round(resolution_coverage, 4),
        scoreable_coverage=round(scoreable_coverage, 4),
        minimum_verdict_coverage=minimum_verdict_coverage,
        minimum_verdict_sample=minimum_verdict_sample,
        verdict_eligible=not ineligibility_reasons,
        verdict_ineligibility_reasons=ineligibility_reasons,
        brier_score=b,
        brier_vs_baseline=round(b - 0.25, 6) if b is not None else None,
        hit_rate=hr,
        directional_accuracy=directional_accuracy,
        mean_absolute_magnitude_error=mean_absolute_magnitude_error,
        timing_error_count=ea.timing,
        calibration_bins=cb,
        mean_calibration_error=mce,
        minimum_calibration_sample=minimum_calibration_sample,
        calibration_is_reliable=len(scoreable) >= minimum_calibration_sample,
        error_attribution=ea,
        scored_predictions=scored,
    )
