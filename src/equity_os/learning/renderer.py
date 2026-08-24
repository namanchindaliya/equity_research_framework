"""Markdown rendering for EpisodeScore and PostmortemReport."""

from __future__ import annotations

from datetime import datetime

from .models import CalibrationBin, EpisodeScore, PostmortemReport


def _now() -> str:
    return datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")


def _pct(v: float) -> str:
    return f"{v * 100:.1f}%"


def _brier_label(b: float) -> str:
    if b < 0.10:
        return "EXCELLENT"
    if b < 0.15:
        return "GOOD"
    if b < 0.20:
        return "FAIR"
    if b < 0.25:
        return "POOR"
    return "WORSE THAN BASELINE"


# ---------------------------------------------------------------------------
# Episode score memo
# ---------------------------------------------------------------------------


def render_episode_score(score: EpisodeScore) -> str:
    lines: list[str] = []
    lines += [
        f"# Episode Score — {score.ticker} / {score.episode_slug}",
        f"",
        f"**Scored:** {score.scored_at.strftime('%Y-%m-%d')}  "
        f"**Ticker:** {score.ticker}",
        f"",
    ]

    # Summary table
    brier_str = f"{score.brier_score:.4f} ({_brier_label(score.brier_score)})" if score.brier_score is not None else "—"
    baseline_str = (f"{score.brier_vs_baseline:+.4f}" if score.brier_vs_baseline is not None else "—")
    hr_str = _pct(score.hit_rate) if score.hit_rate is not None else "—"
    mce_str = _pct(score.mean_calibration_error) if score.mean_calibration_error is not None else "—"

    lines += [
        "## Summary",
        "",
        "| Metric | Value |",
        "| --- | --- |",
        f"| Total predictions | {score.total_predictions} |",
        f"| Resolved | {score.resolved_count} |",
        f"| Unresolved | {score.unresolved_count} |",
        f"| Resolution coverage | {_pct(score.resolution_coverage)} |",
        f"| Scoreable coverage | {_pct(score.scoreable_coverage)} |",
        f"| Verdict eligible | {'yes' if score.verdict_eligible else 'no'} |",
        f"| Scored (incl. in Brier) | {score.scored_count} |",
        f"| Excluded (expired/withdrawn) | {score.excluded_count} |",
        f"| **Brier score** | **{brier_str}** |",
        f"| Brier vs baseline (0.250) | {baseline_str} |",
        f"| **Hit rate** | **{hr_str}** |",
        f"| Directional accuracy | {_pct(score.directional_accuracy) if score.directional_accuracy is not None else '—'} |",
        f"| Mean absolute magnitude error | {_pct(score.mean_absolute_magnitude_error) if score.mean_absolute_magnitude_error is not None else '—'} |",
        f"| Timing errors | {score.timing_error_count} |",
        f"| Mean calibration error | {mce_str} |",
        f"| Calibration sample reliable | {'yes' if score.calibration_is_reliable else 'no'} |",
        f"",
    ]

    if score.verdict_ineligibility_reasons:
        lines += [
            "> **Verdict withheld:** " + " ".join(score.verdict_ineligibility_reasons),
            "",
        ]

    # Calibration table
    if score.calibration_bins:
        lines += [
            "## Calibration",
            "",
            "| Bucket | Count | Predicted avg | Actual freq | Error |",
            "| --- | --- | --- | --- | --- |",
        ]
        for b in score.calibration_bins:
            err_badge = "⚠️" if b.calibration_error > 0.15 else ""
            lines.append(
                f"| {b.label} | {b.count} | {_pct(b.predicted_avg)} | "
                f"{_pct(b.actual_freq)} | {_pct(b.calibration_error)} {err_badge} |"
            )
        lines.append("")

    # Error attribution
    attr = score.error_attribution
    if attr.total_failed > 0:
        lines += [
            "## Error Attribution",
            "",
            "| Bucket | Count | Fraction |",
            "| --- | --- | --- |",
        ]
        for name, count in [
            ("macro", attr.macro),
            ("industry", attr.industry),
            ("strategy", attr.strategy),
            ("valuation", attr.valuation),
            ("timing", attr.timing),
            ("data_quality", attr.data_quality),
        ]:
            if count > 0:
                frac = _pct(count / attr.total_failed)
                lines.append(f"| {name} | {count} | {frac} |")
        lines.append("")

    # Prediction detail
    lines += ["## Prediction Detail", ""]
    lines += [
        "| Metric | Materiality | Weight | Prob | Status | Outcome | Brier contrib | Error bucket |",
        "| --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for sp in score.scored_predictions:
        status = sp.resolved_status or "UNRESOLVED"
        actual = str(sp.actual_outcome) if sp.actual_outcome is not None else "—"
        brier_c = f"{sp.brier_contribution:.4f}" if sp.brier_contribution is not None else ("excluded" if sp.is_excluded else "—")
        bucket = sp.error_bucket.value if sp.error_bucket else "—"
        lines.append(
            f"| `{sp.metric}` | {sp.materiality} | {sp.score_weight:g} | {_pct(sp.probability)} | {status} | {actual} | {brier_c} | {bucket} |"
        )
    lines.append("")
    lines.append(f"_Generated by equity-os learning loop · {_now()}_")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Postmortem memo
# ---------------------------------------------------------------------------


def render_postmortem(report: PostmortemReport) -> str:
    lines: list[str] = []
    score = report.episode_score

    lines += [
        f"# Postmortem — {report.ticker} / {report.episode_slug}",
        f"",
        f"**Verdict:** `{report.verdict}`  "
        f"**Coverage:** {_pct(score.scoreable_coverage)}  "
        f"**Hit rate:** {_pct(score.hit_rate) if score.hit_rate is not None else '—'}  "
        f"**Brier:** {f'{score.brier_score:.4f}' if score.brier_score is not None else '—'}  "
        f"**Generated:** {_now()}",
        f"",
        f"> This postmortem answers six questions about what the orchestrator believed, why, "
        f"what happened, what broke, which assumptions failed, and what to do differently.",
        f"",
        "---",
        "",
    ]

    # 1. What we believed
    lines += [
        "## 1. What We Believed",
        "",
        f"> {report.thesis_at_time}",
        "",
    ]

    # 2. Why we believed it
    lines += ["## 2. Why We Believed It", ""]
    if report.belief_rationale:
        for r in report.belief_rationale:
            lines.append(f"- {r}")
    else:
        lines.append("_No assumptions were explicitly linked to predictions._")
    lines.append("")

    # 3. What actually happened
    lines += ["## 3. What Actually Happened", ""]
    if report.actual_outcomes:
        for o in report.actual_outcomes:
            lines.append(f"- {o}")
    else:
        lines.append("_No predictions were resolved._")
    lines.append("")

    # 4. What broke
    lines += ["## 4. What Broke", ""]
    if report.what_broke:
        for b in report.what_broke:
            lines.append(f"- {b}")
    else:
        lines.append("_No prediction failures to report._")
    lines.append("")

    # 5. Which assumptions failed
    lines += ["## 5. Which Assumptions Failed", ""]
    if report.failed_assumptions:
        for f in report.failed_assumptions:
            lines.append(f"- {f}")
    else:
        lines.append("_No assumption failures identified._")
    lines.append("")

    # 6. What the orchestrator should do differently
    lines += ["## 6. What the Orchestrator Should Do Differently", ""]
    if report.orchestrator_recommendations:
        for i, rec in enumerate(report.orchestrator_recommendations, 1):
            lines.append(f"{i}. {rec}")
    else:
        lines.append("_No specific recommendations generated._")
    lines.append("")

    # Embedded score summary
    lines += [
        "---",
        "## Score Summary",
        "",
        f"Brier: {f'{score.brier_score:.4f}' if score.brier_score is not None else '—'}  "
        f"Hit rate: {_pct(score.hit_rate) if score.hit_rate is not None else '—'}  "
        f"Scored: {score.scored_count}/{score.total_predictions}",
        "",
        f"_Generated by equity-os postmortem engine · {_now()}_",
    ]
    return "\n".join(lines)
