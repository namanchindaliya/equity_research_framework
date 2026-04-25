"""Markdown rendering for v1 domain models.

Each function takes a domain object and returns a plain markdown string.
The CLI writes these strings to .md sidecar files alongside every JSON artifact.
"""

from __future__ import annotations

from datetime import datetime

from .schemas import (
    AssumptionRecord,
    AssumptionStatus,
    CompanyDossier,
    PredictionRecord,
    ThesisEpisode,
)


def _now_utc() -> str:
    return datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")


def _pt(value: float | None, currency: str) -> str:
    if value is None:
        return "N/A"
    return f"{value:,.2f} {currency}"


def _pct(value: float) -> str:
    return f"{value * 100:.0f}%"


# ---------------------------------------------------------------------------
# Assumption table row helper
# ---------------------------------------------------------------------------


def _assumption_rows(assumptions: list[AssumptionRecord]) -> list[str]:
    rows = []
    for a in assumptions:
        star = " ⬆" if a.status == AssumptionStatus.REVISED else ""
        hist = f"v{a.version}" + (f" ({len(a.history)} changes)" if a.history else "")
        rows.append(
            f"| `{a.key}` | {a.label} | {a.value} | {a.unit or '—'} "
            f"| {_pct(a.confidence)} | {a.materiality.value} | {a.status.value}{star} | {hist} |"
        )
    return rows


# ---------------------------------------------------------------------------
# Prediction table row helper
# ---------------------------------------------------------------------------


def _prediction_rows(predictions: list[PredictionRecord]) -> list[str]:
    rows = []
    for p in predictions:
        status = "✓ RESOLVED" if p.is_resolved else "⏳ PENDING"
        if p.is_resolved and p.resolution:
            status = f"{'✓' if 'CORRECT' in p.resolution.resolved_status.value else '✗'} {p.resolution.resolved_status.value}"
        rows.append(
            f"| `{p.metric}` | {p.description[:60]}… | "
            f"{p.threshold} {p.unit or ''} | {p.operator.value} | "
            f"{p.horizon} | {p.due_date} | {_pct(p.probability)} | {status} |"
        )
    return rows


# ---------------------------------------------------------------------------
# episode_md
# ---------------------------------------------------------------------------


def episode_md(episode: ThesisEpisode) -> str:
    """Full markdown representation of a ThesisEpisode."""
    lines: list[str] = []
    pt = _pt(episode.price_target, episode.currency)
    lines += [
        f"# {episode.ticker} — {episode.title}",
        f"",
        f"| Field | Value |",
        f"| --- | --- |",
        f"| ID | `{episode.id}` |",
        f"| Status | **{episode.status.value}** |",
        f"| Rating | **{episode.rating.value}** |",
        f"| Price Target | {pt} |",
        f"| Version | v{episode.version} |",
        f"| Created | {episode.created_at.strftime('%Y-%m-%d')} |",
    ]
    if episode.closed_at:
        lines.append(f"| Closed | {episode.closed_at.strftime('%Y-%m-%d')} |")
    lines += ["", "## Thesis", "", episode.thesis_statement, ""]

    # Assumptions
    lines += ["## Assumptions", ""]
    if episode.assumptions:
        lines += [
            "| Key | Label | Value | Unit | Confidence | Materiality | Status | Version |",
            "| --- | --- | --- | --- | --- | --- | --- | --- |",
        ]
        lines += _assumption_rows(episode.assumptions)
    else:
        lines.append("_No assumptions recorded._")
    lines.append("")

    # Predictions
    lines += ["## Predictions", ""]
    if episode.predictions:
        lines += [
            "| Metric | Description | Threshold | Op | Horizon | Due Date | Prob | Status |",
            "| --- | --- | --- | --- | --- | --- | --- | --- |",
        ]
        lines += _prediction_rows(episode.predictions)
    else:
        lines.append("_No predictions recorded._")
    lines.append("")

    # Observations
    if episode.observations:
        lines += [f"## Observations ({len(episode.observations)})", ""]
        for obs in episode.observations:
            src = f"  \n  _Source: {obs.source.name}_" if obs.source else ""
            lines.append(f"- {obs.content}{src}")
        lines.append("")

    # Inferences
    if episode.inferences:
        lines += [f"## Inferences ({len(episode.inferences)})", ""]
        for inf in episode.inferences:
            lines.append(f"- {inf.content} _(confidence: {_pct(inf.confidence)})_")
        lines.append("")

    # Decisions
    if episode.decisions:
        lines += [f"## Decisions ({len(episode.decisions)})", ""]
        for dec in episode.decisions:
            lines.append(
                f"- **{dec.decision_type}** by `{dec.made_by}` on "
                f"{dec.made_at.strftime('%Y-%m-%d')}: {dec.content}"
            )
        lines.append("")

    # Close note
    if episode.close_note:
        lines += ["## Close Note", "", episode.close_note, ""]

    lines.append(f"_Generated {_now_utc()}_")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# dossier_md
# ---------------------------------------------------------------------------


def dossier_md(dossier: CompanyDossier) -> str:
    """Markdown summary of a CompanyDossier (may include embedded episodes)."""
    lines: list[str] = []
    pt = _pt(dossier.current_price_target, dossier.currency)
    lines += [
        f"# {dossier.name} ({dossier.ticker}) — Coverage Summary",
        f"",
        f"| Field | Value |",
        f"| --- | --- |",
        f"| Rating | **{dossier.current_rating.value}** |",
        f"| Price Target | {pt} |",
        f"| Sector | {dossier.sector or '—'} |",
        f"| Industry | {dossier.industry or '—'} |",
        f"| Exchange | {dossier.exchange or '—'} |",
        f"| Country | {dossier.country} |",
        f"| Coverage since | {dossier.created_at.strftime('%Y-%m-%d')} |",
        f"| Dossier version | v{dossier.version} |",
        f"",
    ]
    if dossier.description:
        lines += [dossier.description, ""]
    if dossier.tags:
        lines += [f"**Tags:** {', '.join(f'`{t}`' for t in dossier.tags)}", ""]

    # Episodes table
    lines += [f"## Episodes ({len(dossier.episodes)})", ""]
    if dossier.episodes:
        lines += [
            "| Title | Rating | PT | Status | Assumptions | Predictions | Opened |",
            "| --- | --- | --- | --- | --- | --- | --- |",
        ]
        for ep in dossier.episodes:
            pt_ep = _pt(ep.price_target, ep.currency)
            n_open = sum(
                1 for a in ep.assumptions if a.status.value == "ACTIVE"
            )
            n_pending = sum(1 for p in ep.predictions if not p.is_resolved)
            lines.append(
                f"| {ep.title} | {ep.rating.value} | {pt_ep} | {ep.status.value} "
                f"| {n_open} active | {n_pending} pending | {ep.created_at.strftime('%Y-%m-%d')} |"
            )
    else:
        lines.append("_No episodes yet._")
    lines.append("")

    # Monitoring triggers
    if dossier.monitoring_triggers:
        lines += [
            f"## Company-Level Monitoring Triggers ({len(dossier.monitoring_triggers)})",
            "",
        ]
        for t in dossier.monitoring_triggers:
            lines.append(
                f"- **{t.label}**: `{t.metric} {t.operator} {t.threshold}` "
                f"→ {t.action.value} ({t.frequency.value})"
            )
        lines.append("")

    lines.append(f"_Generated {_now_utc()}_")
    return "\n".join(lines)
