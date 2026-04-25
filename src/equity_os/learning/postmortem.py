"""PostmortemReport generator — 6 structured narrative sections.

Answers
-------
1. What we believed         — thesis at time of predictions
2. Why we believed it       — key assumptions driving the predictions
3. What actually happened   — resolution summaries for each prediction
4. What broke               — failed predictions with error attribution
5. Which assumptions failed — assumption keys linked to failures
6. What the orchestrator should do differently — recommendations

Recommendations are generated from the dominant error bucket and
the pattern of failures.
"""

from __future__ import annotations

from .models import ErrorBucket, EpisodeScore, PostmortemReport, ScoredPrediction


# ---------------------------------------------------------------------------
# Recommendation templates per error bucket
# ---------------------------------------------------------------------------

_RECOMMENDATIONS: dict[ErrorBucket, list[str]] = {
    ErrorBucket.MACRO: [
        "Add macroeconomic scenario sensitivity bands to predictions "
        "(e.g. 'holds under base macro, conditionally on no recession').",
        "Ingest macro indicators as monitoring evidence before setting probability.",
        "Consider shorter horizons or lower probabilities during high macro uncertainty.",
    ],
    ErrorBucket.INDUSTRY: [
        "Strengthen IndustryAgent inputs with third-party industry research and channel checks.",
        "Add cycle-stage falsification conditions with shorter check intervals.",
        "Cross-validate IndustryAgent's Porter force scores against channel check notes.",
    ],
    ErrorBucket.STRATEGY: [
        "Increase weight on earnings transcript evidence for management priority assumptions.",
        "Add monitoring triggers for segment revenue beats/misses.",
        "Flag narrative shifts as high-priority evidence for the next episode.",
    ],
    ErrorBucket.VALUATION: [
        "Valuation assumptions are out of scope for the current specialist agents. "
        "Consider adding a ValuationAgent before making predictions linked to multiples.",
    ],
    ErrorBucket.TIMING: [
        "Extend prediction horizons — directional calls were correct but deadlines were too tight.",
        "Distinguish between directional conviction and timing conviction in probability assignment.",
        "Consider using rolling horizons rather than fixed due dates.",
    ],
    ErrorBucket.DATA_QUALITY: [
        "Add explicit source-of-truth references when logging predictions to prevent metric mismatch.",
        "Ensure resolution_rule is unambiguous before logging predictions.",
        "Link predictions to specific assumption keys to enable error attribution.",
    ],
}

_GENERAL_RECOMMENDATIONS = [
    "Log predictions with lower probabilities (0.4–0.6) to build a calibration history.",
    "Run score-company after each episode close to track Brier score trend over time.",
]


def _verdict_from_score(score: EpisodeScore) -> str:
    if score.scored_count == 0:
        return "INCONCLUSIVE"
    hr = score.hit_rate or 0.0
    if hr >= 0.75:
        return "THESIS_CORRECT"
    if hr <= 0.35:
        return "THESIS_INCORRECT"
    return "PARTIALLY_CORRECT"


def _build_belief_rationale(
    assumptions: list[dict],
    scored: list[ScoredPrediction],
) -> list[str]:
    """Explain why each prediction was made — which assumptions backed it."""
    rationale: list[str] = []
    all_linked = set()
    for sp in scored:
        all_linked.update(sp.linked_assumption_keys)

    for a in assumptions:
        key = a.get("key", "")
        if key in all_linked or a.get("materiality") in ("CRITICAL", "HIGH"):
            val = a.get("value", "?")
            conf = a.get("confidence", 0.0)
            label = a.get("label", key)
            rationale.append(
                f"Assumption '{label}' (key: `{key}`) = {val} "
                f"with {conf:.0%} confidence ({a.get('materiality', 'MEDIUM')} materiality)."
            )

    if not rationale:
        rationale.append("No assumptions were explicitly linked to the predictions in this episode.")

    return rationale


def _build_actual_outcomes(scored: list[ScoredPrediction]) -> list[str]:
    outcomes: list[str] = []
    for sp in scored:
        if sp.resolved_status is None:
            outcomes.append(f"`{sp.metric}`: UNRESOLVED — {sp.description[:80]}")
            continue
        status = sp.resolved_status
        actual = sp.actual_outcome if sp.actual_outcome is not None else "not recorded"
        mag_str = (
            f" (error: {sp.error_magnitude:+.1%})" if sp.error_magnitude is not None else ""
        )
        outcomes.append(
            f"`{sp.metric}`: **{status}** — actual = {actual}{mag_str}. {sp.resolution_notes[:100]}"
        )
    return outcomes


def _build_what_broke(scored: list[ScoredPrediction]) -> list[str]:
    broke: list[str] = []
    for sp in scored:
        if sp.is_excluded or sp.outcome_score is None:
            continue
        if sp.outcome_score >= 1.0:
            continue
        bucket = sp.error_bucket.value if sp.error_bucket else "unknown"
        prob_str = f"probability assigned: {sp.probability:.0%}"
        actual = sp.actual_outcome if sp.actual_outcome is not None else "?"
        broke.append(
            f"`{sp.metric}` [{sp.resolved_status}] — {sp.description[:80]}. "
            f"Actual: {actual}. {prob_str}. Error bucket: **{bucket}**."
        )
    return broke


def _build_failed_assumptions(
    assumptions: list[dict],
    scored: list[ScoredPrediction],
) -> list[str]:
    """Identify which assumptions were linked to failed predictions."""
    failed_keys: set[str] = set()
    for sp in scored:
        if sp.is_excluded or (sp.outcome_score is not None and sp.outcome_score >= 1.0):
            continue
        failed_keys.update(sp.linked_assumption_keys)

    result: list[str] = []
    for a in assumptions:
        key = a.get("key", "")
        if key in failed_keys:
            val = a.get("value", "?")
            label = a.get("label", key)
            result.append(
                f"Assumption `{key}` ({label}) = {val} was linked to failed prediction(s). "
                f"Review whether {val} was too optimistic/pessimistic given what we now know."
            )
    if not result and failed_keys:
        for key in sorted(failed_keys):
            result.append(
                f"Assumption key `{key}` was linked to failed predictions but not found in the ledger. "
                f"Ensure assumptions are logged before predictions are made."
            )
    return result


def _build_recommendations(score: EpisodeScore) -> list[str]:
    """Generate recommendations based on error attribution pattern."""
    recs: list[str] = []
    dominant = score.error_attribution.dominant_bucket()
    if dominant and dominant in _RECOMMENDATIONS:
        recs.extend(_RECOMMENDATIONS[dominant][:2])

    # Secondary bucket
    attr = score.error_attribution
    buckets = [
        (ErrorBucket.MACRO,         attr.macro),
        (ErrorBucket.INDUSTRY,      attr.industry),
        (ErrorBucket.STRATEGY,      attr.strategy),
        (ErrorBucket.TIMING,        attr.timing),
        (ErrorBucket.DATA_QUALITY,  attr.data_quality),
    ]
    secondary = sorted((b for b in buckets if b[1] > 0 and b[0] != dominant), key=lambda x: -x[1])
    if secondary:
        bucket, count = secondary[0]
        if count >= 2 and bucket in _RECOMMENDATIONS:
            recs.append(_RECOMMENDATIONS[bucket][0])

    # Calibration recommendation
    mce = score.mean_calibration_error
    if mce is not None and mce > 0.15:
        recs.append(
            f"Calibration error is {mce:.0%} — probability assignments are systematically off. "
            "Consider recalibrating by reviewing historical accuracy by probability bucket."
        )

    # Brier vs baseline
    if score.brier_vs_baseline is not None and score.brier_vs_baseline > 0:
        recs.append(
            f"Brier score ({score.brier_score:.3f}) is worse than the uninformative baseline (0.250). "
            "Consider reducing probability conviction until calibration improves."
        )

    recs.extend(_GENERAL_RECOMMENDATIONS[:1])
    return recs[:5]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def generate_postmortem(
    score: EpisodeScore,
    thesis_statement: str,
    assumptions: list[dict],
) -> PostmortemReport:
    """Generate a 6-section PostmortemReport from an EpisodeScore.

    Parameters
    ----------
    score            : EpisodeScore from scoring.score_episode()
    thesis_statement : the thesis that was active when predictions were made
    assumptions      : list of AssumptionRecord.model_dump() dicts
    """
    scored = score.scored_predictions

    return PostmortemReport(
        ticker=score.ticker,
        episode_slug=score.episode_slug,
        episode_score=score,
        thesis_at_time=thesis_statement,
        belief_rationale=_build_belief_rationale(assumptions, scored),
        actual_outcomes=_build_actual_outcomes(scored),
        what_broke=_build_what_broke(scored),
        failed_assumptions=_build_failed_assumptions(assumptions, scored),
        orchestrator_recommendations=_build_recommendations(score),
        verdict=_verdict_from_score(score),
    )
