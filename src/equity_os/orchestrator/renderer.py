"""Markdown renderer for OrchestratorDecision.

Produces a three-section memo:
  1. Observations  — what the agents reported
  2. Inferences    — what the orchestrator concludes
  3. Decisions     — what to do next

The section names appear verbatim as H2 headers so tests and readers can
locate them unambiguously.
"""

from __future__ import annotations

from datetime import datetime

from .models import OrchestratorDecision


def _now() -> str:
    return datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")


def _pct(v: float) -> str:
    return f"{v * 100:.0f}%"


def _conf_label(v: float) -> str:
    if v >= 0.75:
        return "HIGH"
    if v >= 0.45:
        return "MEDIUM"
    return "LOW"


def render_decision(decision: OrchestratorDecision) -> str:
    lines: list[str] = []

    lines += [
        f"# Orchestrator Decision — {decision.ticker}",
        f"",
        f"**Decision ID:** `{decision.decision_id}`  "
        f"**Policy:** v{decision.policy_version}  "
        f"**Status:** `{decision.synthesis_status.value}`  "
        f"**Generated:** {_now()}",
        f"",
        f"**Overall Confidence:** {_pct(decision.confidence_summary.overall)} "
        f"({_conf_label(decision.confidence_summary.overall)})  "
        f"**Rating Stance:** `{decision.decisions.rating_stance.upper()}`",
        f"",
        f"> {decision.confidence_summary.basis}",
        f"",
    ]

    if decision.abstention_reasons:
        lines += [
            "> **Synthesis gate:** " + " ".join(decision.abstention_reasons),
            "",
        ]

    # ==================================================================
    # Section 1: Observations
    # ==================================================================
    obs = decision.observations
    lines += ["---", "", "## 1. Observations", "", "_Raw facts from specialist agents. No interpretation._", ""]

    # Agent summaries table
    lines += [
        "| Agent | Status | Confidence | Freshness Penalty | Evidence Sources |",
        "| --- | --- | --- | --- | --- |",
    ]
    if obs.industry_observation:
        o = obs.industry_observation
        lines.append(
            f"| `{o.agent_id}` | {o.analysis_status} | {_pct(o.overall_confidence)} | -{_pct(o.freshness_penalty_applied)} | {o.evidence_id_count} |"
        )
    if obs.strategy_observation:
        o = obs.strategy_observation
        lines.append(
            f"| `{o.agent_id}` | {o.analysis_status} | {_pct(o.overall_confidence)} | -{_pct(o.freshness_penalty_applied)} | {o.evidence_id_count} |"
        )
    lines.append("")

    # Industry facts
    lines += [
        "### Industry Observations",
        "",
        f"- **Industry:** {obs.industry_label}",
        f"- **Market Structure:** {obs.market_structure}",
        f"- **Cycle Stage:** {obs.cycle_stage}",
    ]
    if obs.porter_forces_summary:
        lines.append("- **Porter Forces:**")
        for name, level in obs.porter_forces_summary.items():
            lines.append(f"  - {name}: `{level}`")
    if obs.regulatory_factors:
        lines.append(f"- **Regulatory Factors:** {', '.join(obs.regulatory_factors)}")
    if obs.industry_risks:
        lines.append(f"- **Industry Risks:** {', '.join(obs.industry_risks[:4])}")
    lines.append("")

    # Strategy facts
    lines += ["### Strategy Observations", ""]
    if obs.management_priorities_raw:
        lines.append("**Management Priorities:**")
        for i, p in enumerate(obs.management_priorities_raw[:4], 1):
            lines.append(f"  {i}. {p}")
        lines.append("")
    if obs.segment_priority_order:
        lines.append(f"**Segment Priority Order:** {' → '.join(obs.segment_priority_order)}")
    lines.append(f"**Target Market:** {obs.strategic_target_market}")
    if obs.strategic_moat:
        lines.append(f"**Moat Assessment:** {', '.join(obs.strategic_moat)}")
    if obs.narrative_shifts:
        lines.append("**Narrative Shifts:** " + "; ".join(obs.narrative_shifts[:3]))
    lines.append("")

    # Assumption ledger state
    lines += ["### Assumption Ledger State", ""]
    lines += [
        f"- **Active assumptions:** {obs.active_assumption_count}",
        f"- **Revised assumptions:** {obs.revised_assumption_count}",
    ]
    if obs.critical_assumptions:
        lines.append(f"- **CRITICAL keys:** {', '.join(f'`{k}`' for k in obs.critical_assumptions)}")
    if obs.recent_material_changes:
        lines.append("- **Recent material changes:**")
        for c in obs.recent_material_changes[:3]:
            lines.append(f"  - {c}")
    if obs.has_prior_thesis and obs.prior_thesis_statement:
        lines += [
            "",
            f"**Prior thesis:** _{obs.prior_thesis_statement[:200]}_",
        ]
    lines.append("")

    # ==================================================================
    # Section 2: Inferences
    # ==================================================================
    inf = decision.inferences
    lines += ["---", "", "## 2. Inferences", "", "_Orchestrator's synthesis across agent outputs._", ""]

    # Thesis
    lines += ["### Thesis Statement", "", f"> {inf.thesis_statement}", ""]

    # Variant view
    lines += ["### Variant View (Bear Case)", "", f"> {inf.variant_view}", ""]

    # Key assumptions
    if inf.key_assumptions:
        lines += [
            "### Key Assumptions",
            "",
            "| Key | Value | Base Conf | Adjusted Conf | Materiality | Source |",
            "| --- | --- | --- | --- | --- | --- |",
        ]
        for a in inf.key_assumptions:
            adj_str = _pct(a.adjusted_confidence)
            base_str = _pct(a.base_confidence)
            adj_note = " ↑" if a.adjusted_confidence > a.base_confidence else (" ↓" if a.adjusted_confidence < a.base_confidence else "")
            reasons = ", ".join(a.adjustment_reasons) if a.adjustment_reasons else "—"
            lines.append(
                f"| `{a.key}` | {a.value} | {base_str} | {adj_str}{adj_note} | {a.materiality} | {a.source} |"
            )
        lines.append("")

    # Top drivers
    if inf.top_drivers:
        lines += [f"### Top Drivers ({len(inf.top_drivers)})", ""]
        for i, d in enumerate(inf.top_drivers, 1):
            lines.append(
                f"{i}. **[{_pct(d.confidence)} confidence]** {d.text}"
                + (f"  \n   _↩ Dissent: {d.dissent_description}_" if d.dissent_description else "")
            )
        lines.append("")

    # Cross-validated findings
    if inf.cross_validated:
        lines += ["### Cross-Validated Findings (Both Agents Agree)", ""]
        for v in inf.cross_validated:
            lines.append(f"- ✓ {v}")
        lines.append("")

    # Conflict resolution
    if inf.agent_conflicts:
        lines += [f"### Conflict Resolution ({len(inf.agent_conflicts)} conflict(s))", ""]
        for c in inf.agent_conflicts:
            badge = "🔴 HARD" if c.conflict_severity == "hard" else "🟡 SOFT"
            lines += [
                f"#### {badge}: {c.dimension}",
                f"",
                f"| | View |",
                f"| --- | --- |",
                f"| `industry_v1` | {c.industry_view} |",
                f"| `strategy_v1` | {c.strategy_view} |",
                f"",
                f"**Resolution:** {c.resolution}  ",
                f"**Policy basis:** `{c.resolution_basis}`  ",
                f"**Confidence after resolution:** {_pct(c.confidence_after)}",
                f"",
            ]

    # Unresolved conflicts
    if inf.unresolved_conflicts:
        lines += [f"### Unresolved Questions ({len(inf.unresolved_conflicts)})", ""]
        for q in inf.unresolved_conflicts:
            lines.append(f"- {q}")
        lines.append("")

    # ==================================================================
    # Section 3: Decisions
    # ==================================================================
    dec = decision.decisions
    lines += ["---", "", "## 3. Decisions", "", "_What the analyst should do next._", ""]

    # Predictions
    if dec.predictions:
        lines += [f"### Explicit Predictions ({len(dec.predictions)})", ""]
        lines += [
            "| Description | Metric | Direction | Horizon | Probability | Confidence |",
            "| --- | --- | --- | --- | --- | --- |",
        ]
        for p in dec.predictions:
            lines.append(
                f"| {p.description[:60]}… | `{p.metric}` | {p.direction} | {p.horizon} "
                f"| {_pct(p.probability)} | {_pct(p.confidence)} |"
                if len(p.description) > 60
                else f"| {p.description} | `{p.metric}` | {p.direction} | {p.horizon} "
                f"| {_pct(p.probability)} | {_pct(p.confidence)} |"
            )
        lines.append("")

    # Falsification conditions
    if dec.falsification_conditions:
        lines += [f"### Falsification Conditions ({len(dec.falsification_conditions)})", ""]
        for fc in dec.falsification_conditions:
            lines.append(
                f"- **If** {fc.condition}  \n"
                f"  → Metric: `{fc.metric}` crosses `{fc.threshold}` by {fc.check_by}  \n"
                f"  → Invalidates assumption: `{fc.assumption_key}`"
            )
        lines.append("")

    # Monitoring triggers
    if dec.monitoring_triggers:
        lines += [f"### Monitoring Triggers ({len(dec.monitoring_triggers)})", ""]
        lines += [
            "| Metric | Condition | Action | Frequency |",
            "| --- | --- | --- | --- |",
        ]
        for t in dec.monitoring_triggers:
            lines.append(
                f"| `{t.metric}` | {t.condition[:60]}… | `{t.action}` | {t.frequency} |"
                if len(t.condition) > 60
                else f"| `{t.metric}` | {t.condition} | `{t.action}` | {t.frequency} |"
            )
        lines.append("")

    # Next evidence needed
    if dec.next_evidence_needed:
        lines += [f"### Next Evidence Needed ({len(dec.next_evidence_needed)})", ""]
        for i, e in enumerate(dec.next_evidence_needed, 1):
            lines.append(f"{i}. {e}")
        lines.append("")

    lines += [
        "---",
        f"_Generated by equity-os orchestrator · Policy v{decision.policy_version} · {_now()}_",
    ]
    return "\n".join(lines)
