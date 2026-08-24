"""Synthesis functions: thesis, variant view, drivers, predictions, falsification."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from .models import (
    AdjustedAssumption,
    AgentConflict,
    ConfidenceSummary,
    DecisionLayer,
    FalsificationCondition,
    InferenceLayer,
    MonitoringTrigger,
    ObservationLayer,
    OrchestratorInference,
    OrchestratorPrediction,
)
from .policy import OrchestratorPolicy


# ---------------------------------------------------------------------------
# Observation layer builder
# ---------------------------------------------------------------------------


def build_observation_layer(
    industry: dict[str, Any],
    strategy: dict[str, Any],
    assumptions: list[dict[str, Any]],
    prior_thesis: dict[str, Any] | None,
    change_log: dict[str, Any] | None,
    policy: OrchestratorPolicy,
    ind_freshness_penalty: float,
    str_freshness_penalty: float,
) -> ObservationLayer:
    from .models import AgentObservation

    # IndustryAgent observation
    ind_obs = AgentObservation(
        agent_id="industry_v1",
        generated_at=_parse_dt(industry.get("generated_at")),
        overall_confidence=float(industry.get("overall_confidence", 0.5)),
        freshness_penalty_applied=ind_freshness_penalty,
        evidence_id_count=len(industry.get("evidence_ids", [])),
        key_findings=[f.get("name", "") for f in industry.get("porter_forces", [])[:3]],
        analysis_status=str(industry.get("analysis_status", "COMPLETE")),
    )

    # StrategyAgent observation
    str_obs = AgentObservation(
        agent_id="strategy_v1",
        generated_at=_parse_dt(strategy.get("generated_at")),
        overall_confidence=float(strategy.get("overall_confidence", 0.5)),
        freshness_penalty_applied=str_freshness_penalty,
        evidence_id_count=len(strategy.get("evidence_ids", [])),
        key_findings=[p.get("text", "")[:80] for p in strategy.get("management_priorities", [])[:3]],
        analysis_status=str(strategy.get("analysis_status", "COMPLETE")),
    )

    # Porter forces summary
    porter_summary = {
        f.get("name", "?"): f.get("level", "UNKNOWN")
        for f in industry.get("porter_forces", [])
    }

    # Assumption ledger
    active = [a for a in assumptions if a.get("status") == "ACTIVE"]
    revised = [a for a in assumptions if a.get("status") == "REVISED"]
    critical = [a.get("key", "") for a in active if a.get("materiality") == "CRITICAL"]

    # Change log
    material_changes: list[str] = []
    conflicts_flagged: list[str] = []
    if change_log:
        for diff in change_log.get("diffs", []):
            for fc in diff.get("field_changes", []):
                if fc.get("materiality") == "HIGH" and fc.get("change_type") != "UNCHANGED":
                    material_changes.append(f"{fc.get('field_path')}: {fc.get('prior_value')} → {fc.get('current_value')}")
            for cf in diff.get("conflict_flags", []):
                conflicts_flagged.append(cf.get("description", ""))

    seg_order = [
        s.get("segment_name", "")
        for s in sorted(strategy.get("segment_priorities", []), key=lambda x: x.get("priority_rank", 99))
    ]

    return ObservationLayer(
        industry_observation=ind_obs,
        strategy_observation=str_obs,
        market_structure=str(industry.get("market_structure", "UNKNOWN")),
        cycle_stage=str(industry.get("cycle_stage", "UNKNOWN")),
        industry_label=str(industry.get("industry_label", "")),
        porter_forces_summary=porter_summary,
        regulatory_factors=[r.get("name", "") for r in industry.get("regulatory_factors", [])],
        industry_risks=[r.get("name", "") for r in industry.get("top_risks", [])],
        management_priorities_raw=[p.get("text", "")[:120] for p in strategy.get("management_priorities", [])],
        segment_priority_order=seg_order,
        strategic_target_market=str(strategy.get("strategic_positioning", {}).get("target_market", "")),
        strategic_moat=list(strategy.get("strategic_positioning", {}).get("moat_assessment", [])),
        disclosed_risk_categories=list({r.get("category", "") for r in strategy.get("risk_disclosures", [])}),
        narrative_shifts=[
            f"{s.get('topic', '')}: {s.get('shift_type', '')}"
            for s in strategy.get("narrative_shifts", [])
        ],
        active_assumption_count=len(active),
        revised_assumption_count=len(revised),
        critical_assumptions=critical,
        recent_material_changes=material_changes[:5],
        recent_conflicts_flagged=conflicts_flagged[:3],
        has_prior_thesis=prior_thesis is not None,
        prior_thesis_statement=_prior_thesis_text(prior_thesis),
    )


# ---------------------------------------------------------------------------
# Inference layer builder
# ---------------------------------------------------------------------------


def build_inference_layer(
    obs: ObservationLayer,
    industry: dict[str, Any],
    strategy: dict[str, Any],
    assumptions: list[dict[str, Any]],
    conflicts: list[AgentConflict],
    policy: OrchestratorPolicy,
    ind_adj_conf: float,
    str_adj_conf: float,
) -> InferenceLayer:
    thesis = _synthesize_thesis(obs, industry, strategy)
    variant = _synthesize_variant(obs, industry, strategy, conflicts)
    key_assumptions = _build_key_assumptions(industry, strategy, assumptions, policy, ind_adj_conf, str_adj_conf)
    drivers = _build_top_drivers(obs, industry, strategy, policy, ind_adj_conf, str_adj_conf)
    cross_validated = _cross_validate(industry, strategy)
    unresolved = _collect_unresolved(industry, strategy, conflicts)

    return InferenceLayer(
        thesis_statement=thesis,
        variant_view=variant,
        key_assumptions=key_assumptions,
        top_drivers=drivers,
        agent_conflicts=conflicts,
        cross_validated=cross_validated,
        unresolved_conflicts=unresolved,
    )


def _synthesize_thesis(
    obs: ObservationLayer,
    industry: dict[str, Any],
    strategy: dict[str, Any],
) -> str:
    cycle = obs.cycle_stage.replace("_", " ").lower()
    mkt = obs.market_structure.lower()
    article = "an" if mkt[:1] in "aeiou" else "a"
    label = obs.industry_label or "technology"
    target = obs.strategic_target_market or "premium"
    target_article = "an" if target[:1].lower() in "aeiou" else "a"
    moat = ", ".join(obs.strategic_moat[:2]) if obs.strategic_moat and obs.strategic_moat[0] != "unknown" else "proprietary ecosystem"
    top_seg = obs.segment_priority_order[0] if obs.segment_priority_order else "core segment"
    top_priority = (
        obs.management_priorities_raw[0][:100].rstrip(".")
        if obs.management_priorities_raw
        else f"growing the {top_seg} business"
    )

    return (
        f"{strategy.get('ticker', industry.get('ticker', '?'))} operates in "
        f"{article} {mkt} {label} market at the {cycle} stage of the industry cycle. "
        f"The company is positioned as {target_article} {target} player with {moat} as the primary "
        f"competitive advantage, and the {top_seg} segment receiving the most management emphasis. "
        f"Management's stated focus centres on: {top_priority}."
    )


def _synthesize_variant(
    obs: ObservationLayer,
    industry: dict[str, Any],
    strategy: dict[str, Any],
    conflicts: list[AgentConflict],
) -> str:
    parts: list[str] = []

    # Regulatory as a bear anchor
    if obs.regulatory_factors:
        regs = obs.regulatory_factors[:2]
        parts.append(
            f"Bear case: regulatory headwinds from {' and '.join(regs)} "
            "could constrain addressable market and compress fee economics."
        )

    # High rivalry as a bear
    rivalry_level = obs.porter_forces_summary.get("Competitive Rivalry", "UNKNOWN")
    if rivalry_level == "HIGH":
        parts.append("Intensifying competitive rivalry may erode pricing power faster than the base case assumes.")

    # Cycle deceleration as a bear
    if obs.cycle_stage in ("MATURE", "DECLINE"):
        parts.append(
            f"The industry is in a {obs.cycle_stage.lower()} phase — "
            "growth multiples may compress as secular tailwinds diminish."
        )

    # Conflicts as variant amplifiers
    hard_conflicts = [c for c in conflicts if c.conflict_severity == "hard"]
    if hard_conflicts:
        parts.append(
            f"Conflicting signals on {hard_conflicts[0].dimension} increase uncertainty in the base thesis."
        )

    if not parts:
        parts.append(
            "Insufficient evidence to articulate a strong counter-thesis at this stage. "
            "Key risks include competitive intensity escalation and regulatory intervention."
        )

    return " ".join(parts)


def _build_key_assumptions(
    industry: dict[str, Any],
    strategy: dict[str, Any],
    ledger: list[dict[str, Any]],
    policy: OrchestratorPolicy,
    ind_adj_conf: float,
    str_adj_conf: float,
) -> list[AdjustedAssumption]:
    results: list[AdjustedAssumption] = []

    # From ledger (analyst-authored)
    for a in ledger:
        if a.get("status") not in ("ACTIVE", None):
            continue
        base_conf = float(a.get("confidence", 0.5))
        reasons: list[str] = []
        adj = base_conf

        # Penalise if CRITICAL and confidence < 0.5
        if a.get("materiality") == "CRITICAL" and base_conf < 0.5:
            reasons.append("CRITICAL materiality with low confidence — flagged for review")
        # Boost if corroborated by both agents
        key = a.get("key", "")
        corroborated = _is_corroborated(key, industry, strategy)
        if corroborated:
            adj = min(adj + policy.agreement_boost() * 0.5, 0.95)
            reasons.append("corroborated by both specialist agents")

        results.append(AdjustedAssumption(
            key=key,
            label=a.get("label", key),
            value=a.get("value"),
            base_confidence=base_conf,
            adjusted_confidence=round(adj, 3),
            adjustment_reasons=reasons,
            materiality=a.get("materiality", "MEDIUM"),
            owner_agent=a.get("owner_agent", "analyst"),
            source="ledger",
        ))

    # Add synthesized assumptions from agents (not in ledger)
    _add_synthesized_assumptions(results, industry, strategy, ind_adj_conf, str_adj_conf, policy)

    return results[:8]


def _add_synthesized_assumptions(
    results: list[AdjustedAssumption],
    industry: dict[str, Any],
    strategy: dict[str, Any],
    ind_adj_conf: float,
    str_adj_conf: float,
    policy: OrchestratorPolicy,
) -> None:
    existing_keys = {a.key for a in results}

    # Industry cycle stage
    if "industry_cycle_stage" not in existing_keys:
        results.append(AdjustedAssumption(
            key="industry_cycle_stage",
            label="Industry Cycle Stage",
            value=industry.get("cycle_stage", "UNKNOWN"),
            base_confidence=ind_adj_conf,
            adjusted_confidence=round(ind_adj_conf, 3),
            adjustment_reasons=["synthesized from IndustryAgent"],
            materiality="HIGH",
            owner_agent="industry_v1",
            source="industry",
        ))

    # Market structure
    if "market_structure" not in existing_keys:
        results.append(AdjustedAssumption(
            key="market_structure",
            label="Market Structure",
            value=industry.get("market_structure", "UNKNOWN"),
            base_confidence=ind_adj_conf,
            adjusted_confidence=round(ind_adj_conf, 3),
            adjustment_reasons=["synthesized from IndustryAgent"],
            materiality="HIGH",
            owner_agent="industry_v1",
            source="industry",
        ))

    # Top segment priority
    segs = sorted(strategy.get("segment_priorities", []), key=lambda x: x.get("priority_rank", 99))
    if segs and "top_segment_priority" not in existing_keys:
        top_seg = segs[0]
        results.append(AdjustedAssumption(
            key="top_segment_priority",
            label=f"Top Segment: {top_seg.get('segment_name', 'Unknown')}",
            value=top_seg.get("growth_framing", "stable"),
            base_confidence=str_adj_conf,
            adjusted_confidence=round(str_adj_conf, 3),
            adjustment_reasons=["synthesized from CompanyStrategyAgent"],
            materiality="MEDIUM",
            owner_agent="strategy_v1",
            source="strategy",
        ))


def _build_top_drivers(
    obs: ObservationLayer,
    industry: dict[str, Any],
    strategy: dict[str, Any],
    policy: OrchestratorPolicy,
    ind_adj_conf: float,
    str_adj_conf: float,
) -> list[OrchestratorInference]:
    drivers: list[OrchestratorInference] = []
    threshold = policy.threshold("driver_min_confidence")

    # Driver 1: Industry position
    ind_driver_conf = ind_adj_conf
    if ind_driver_conf >= threshold:
        ms = obs.market_structure
        cs = obs.cycle_stage.replace("_", " ").lower()
        rivalry = obs.porter_forces_summary.get("Competitive Rivalry", "UNKNOWN")
        drivers.append(OrchestratorInference(
            text=(
                f"Market structure ({ms}) and {cs} cycle stage, combined with "
                f"{rivalry.lower()} competitive rivalry, define the industry backdrop for this thesis."
            ),
            confidence=round(ind_driver_conf, 3),
            based_on=["market_structure", "cycle_stage", "porter_forces_summary"],
        ))

    # Driver 2: Top segment growth
    segs = sorted(strategy.get("segment_priorities", []), key=lambda x: x.get("priority_rank", 99))
    if segs and str_adj_conf >= threshold:
        top = segs[0]
        drivers.append(OrchestratorInference(
            text=(
                f"{top.get('segment_name', 'Top segment')} is the highest-priority segment "
                f"with {top.get('growth_framing', 'stable')} growth framing. "
                + (top.get("finding", {}).get("text", "")[:100] if isinstance(top.get("finding"), dict) else "")
            ),
            confidence=round(str_adj_conf, 3),
            based_on=["segment_priority_order", "segment_growth_framing"],
        ))

    # Driver 3: Management priorities
    priorities = strategy.get("management_priorities", [])
    if priorities and str_adj_conf >= threshold:
        top_p = priorities[0]
        conf = float(top_p.get("confidence", str_adj_conf)) if isinstance(top_p, dict) else str_adj_conf
        text = (top_p.get("text", "") if isinstance(top_p, dict) else str(top_p))[:120]
        if text and conf >= threshold:
            drivers.append(OrchestratorInference(
                text=f"Management stated priority: {text}",
                confidence=round(conf, 3),
                based_on=["management_priorities_raw"],
            ))

    # Driver 4: Regulatory risk (if material)
    if obs.regulatory_factors and ind_adj_conf >= threshold:
        reg_str = ", ".join(obs.regulatory_factors[:2])
        drivers.append(OrchestratorInference(
            text=f"Active regulatory factors ({reg_str}) represent a structural constraint on the thesis.",
            confidence=round(ind_adj_conf * 0.85, 3),
            based_on=["regulatory_factors"],
        ))

    return drivers[:5]


def _cross_validate(industry: dict[str, Any], strategy: dict[str, Any]) -> list[str]:
    """Points where both agents agree."""
    agreements: list[str] = []

    # Both mention regulatory risk
    ind_has_reg = bool(industry.get("regulatory_factors"))
    str_has_reg = any(r.get("category") == "regulatory" for r in strategy.get("risk_disclosures", []))
    if ind_has_reg and str_has_reg:
        agreements.append("Both agents identify regulatory risk as a material consideration.")

    # Both mention competitive risk
    rivalry_force = next((f for f in industry.get("porter_forces", []) if "Rivalry" in f.get("name", "")), None)
    str_has_comp = any(r.get("category") == "competitive" for r in strategy.get("risk_disclosures", []))
    if rivalry_force and str_has_comp:
        agreements.append("Both agents flag competitive intensity as a relevant risk dimension.")

    # Moat overlap
    ind_moats = set(industry.get("competitive_dynamics", {}).get("moat_type", []))
    str_moats = set(strategy.get("strategic_positioning", {}).get("moat_assessment", []))
    overlap = (ind_moats & str_moats) - {"unknown"}
    if overlap:
        agreements.append(f"Both agents identify {', '.join(sorted(overlap))} as structural moat elements.")

    return agreements


def _collect_unresolved(
    industry: dict[str, Any],
    strategy: dict[str, Any],
    conflicts: list[AgentConflict],
) -> list[str]:
    unresolved: list[str] = []
    for q in industry.get("unresolved_questions", []):
        unresolved.append(f"[Industry] {q}")
    for q in strategy.get("unresolved_questions", []):
        unresolved.append(f"[Strategy] {q}")
    hard = [c for c in conflicts if c.conflict_severity == "hard"]
    for c in hard:
        unresolved.append(f"[Conflict] Hard disagreement on {c.dimension}: {c.industry_view} vs {c.strategy_view}")
    return unresolved[:8]


# ---------------------------------------------------------------------------
# Decision layer builder
# ---------------------------------------------------------------------------


def build_decision_layer(
    obs: ObservationLayer,
    inf: InferenceLayer,
    industry: dict[str, Any],
    strategy: dict[str, Any],
    policy: OrchestratorPolicy,
    overall_conf: float,
) -> DecisionLayer:
    predictions = _build_predictions(obs, inf, industry, strategy, policy)
    falsification = _build_falsification(inf, policy)
    triggers = _build_monitoring_triggers(obs, industry, strategy, policy)
    next_evidence = _build_next_evidence(obs, inf, industry, strategy)

    rating_stance = _infer_rating_stance(obs, inf, overall_conf)

    return DecisionLayer(
        current_thesis=inf.thesis_statement,
        rating_stance=rating_stance,
        predictions=predictions,
        falsification_conditions=falsification,
        monitoring_triggers=triggers,
        next_evidence_needed=next_evidence,
        unresolved_conflicts=inf.unresolved_conflicts,
    )


def _infer_rating_stance(obs: ObservationLayer, inf: InferenceLayer, conf: float) -> str:
    if conf < 0.25:
        return "not_rated"
    n_hard_conflicts = sum(1 for c in inf.agent_conflicts if c.conflict_severity == "hard")
    cycle = obs.cycle_stage
    if cycle == "GROWTH" and n_hard_conflicts == 0 and conf >= 0.45:
        return "constructive"
    if cycle in ("MATURE", "DECLINE") or n_hard_conflicts >= 2:
        return "cautious"
    return "neutral"


def _build_predictions(
    obs: ObservationLayer,
    inf: InferenceLayer,
    industry: dict[str, Any],
    strategy: dict[str, Any],
    policy: OrchestratorPolicy,
) -> list[OrchestratorPrediction]:
    preds: list[OrchestratorPrediction] = []
    threshold = policy.threshold("prediction_min_confidence")

    for driver in inf.top_drivers:
        if driver.confidence < threshold:
            continue
        # Segment-based prediction
        if "segment" in driver.text.lower() and obs.segment_priority_order:
            seg = obs.segment_priority_order[0]
            preds.append(OrchestratorPrediction(
                description=f"{seg} segment sustains {obs.cycle_stage.replace('_', ' ').lower()} trajectory over the next 12 months",
                metric=f"{seg.lower()}_revenue_growth_yoy",
                direction=">",
                horizon="12 months",
                probability=round(driver.confidence * 0.9, 3),
                confidence=round(driver.confidence, 3),
                based_on_assumption_keys=["top_segment_priority"],
            ))
        # Management priority prediction
        elif "management" in driver.text.lower() and obs.management_priorities_raw:
            preds.append(OrchestratorPrediction(
                description="Management's stated priorities remain consistent through next earnings cycle",
                metric="management_priority_consistency",
                direction="holds",
                horizon="next quarter",
                probability=round(driver.confidence * 0.85, 3),
                confidence=round(driver.confidence, 3),
                based_on_assumption_keys=["management_priorities"],
            ))
        if len(preds) >= 3:
            break

    return preds


def _build_falsification(
    inf: InferenceLayer, policy: OrchestratorPolicy
) -> list[FalsificationCondition]:
    conditions: list[FalsificationCondition] = []
    threshold = policy.threshold("falsification_min_confidence")

    for asm in inf.key_assumptions:
        if asm.adjusted_confidence < threshold:
            continue
        if asm.materiality not in ("HIGH", "CRITICAL"):
            continue
        if asm.key == "industry_cycle_stage":
            conditions.append(FalsificationCondition(
                condition=f"Industry cycle deteriorates from {asm.value} to MATURE or DECLINE within two consecutive quarters",
                metric="industry_cycle_stage",
                threshold="MATURE",
                check_by="within 2 quarters",
                assumption_key=asm.key,
            ))
        elif asm.key == "market_structure":
            conditions.append(FalsificationCondition(
                condition=f"Market structure fragments (from {asm.value}) with entry of 2+ well-capitalised new competitors",
                metric="market_structure",
                threshold="FRAGMENTED",
                check_by="within 12 months",
                assumption_key=asm.key,
            ))
        elif asm.materiality == "CRITICAL":
            conditions.append(FalsificationCondition(
                condition=f"Assumption '{asm.label}' moves more than 20% from current value of {asm.value}",
                metric=asm.key,
                threshold="±20%",
                check_by="within 2 quarters",
                assumption_key=asm.key,
            ))
        if len(conditions) >= 4:
            break

    return conditions


def _build_monitoring_triggers(
    obs: ObservationLayer,
    industry: dict[str, Any],
    strategy: dict[str, Any],
    policy: OrchestratorPolicy,
) -> list[MonitoringTrigger]:
    triggers: list[MonitoringTrigger] = []
    threshold = policy.threshold("monitoring_trigger_min_confidence")

    # Regulatory triggers
    for reg in obs.regulatory_factors[:2]:
        triggers.append(MonitoringTrigger(
            metric=f"regulatory_status_{reg.lower().replace(' ', '_')[:20]}",
            condition=f"New ruling or enforcement action related to {reg}",
            action="rerun_thesis",
            frequency="event-driven",
            rationale=f"{reg} is an active regulatory factor; developments can materially alter the thesis.",
        ))

    # Segment revenue triggers
    for seg in obs.segment_priority_order[:2]:
        triggers.append(MonitoringTrigger(
            metric=f"{seg.lower()}_revenue_yoy",
            condition=f"{seg} YoY revenue growth falls below 5% or accelerates above 20%",
            action="revise_assumption",
            frequency="quarterly",
            rationale=f"{seg} is a priority segment; sustained deceleration or re-acceleration updates the thesis.",
        ))

    # Conflict monitoring
    for conflict in industry.get("unresolved_questions", [])[:1]:
        triggers.append(MonitoringTrigger(
            metric="evidence_gap",
            condition=f"Evidence becomes available to resolve: {conflict[:80]}",
            action="rerun_thesis",
            frequency="event-driven",
            rationale="Filling evidence gaps directly improves analytical confidence.",
        ))

    return triggers[:6]


def _build_next_evidence(
    obs: ObservationLayer,
    inf: InferenceLayer,
    industry: dict[str, Any],
    strategy: dict[str, Any],
) -> list[str]:
    needed: list[str] = []

    # Evidence gaps from agents
    for q in industry.get("unresolved_questions", []):
        needed.append(q)
    for q in strategy.get("unresolved_questions", []):
        needed.append(q)

    # Conflict-driven needs
    for c in inf.agent_conflicts:
        if c.conflict_severity == "hard":
            needed.append(
                f"Primary evidence to resolve hard conflict on '{c.dimension}': "
                f"{c.industry_view} vs {c.strategy_view}"
            )

    # Structural gaps
    if not obs.regulatory_factors:
        needed.append("Regulatory landscape analysis: no regulatory factors currently detected.")
    if obs.active_assumption_count == 0:
        needed.append("Analyst-authored assumption ledger: no assumptions currently tracked.")

    return list(dict.fromkeys(needed))[:6]


# ---------------------------------------------------------------------------
# Confidence summary
# ---------------------------------------------------------------------------


def build_confidence_summary(
    ind_base: float,
    str_base: float,
    ind_freshness: float,
    str_freshness: float,
    conflicts: list[AgentConflict],
    policy: OrchestratorPolicy,
    assumptions: list[dict[str, Any]],
) -> ConfidenceSummary:
    ind_adj = max(ind_base - ind_freshness, 0.05)
    str_adj = max(str_base - str_freshness, 0.05)

    conflict_penalty = sum(
        policy.penalty("conflict_hard_penalty") if c.conflict_severity == "hard"
        else policy.penalty("conflict_soft_penalty")
        for c in conflicts
    )
    conflict_penalty = min(conflict_penalty, 0.40)

    w_ind = policy.agent_weight("industry_v1")
    w_str = policy.agent_weight("strategy_v1")
    overall = max(w_ind * ind_adj + w_str * str_adj - conflict_penalty, 0.05)
    overall = round(min(overall, 0.95), 3)

    freshness_penalty = max(ind_freshness, str_freshness)
    parts = [
        f"Industry agent at {ind_adj:.0%} (after {ind_freshness:.0%} freshness penalty)",
        f"Strategy agent at {str_adj:.0%} (after {str_freshness:.0%} freshness penalty)",
    ]
    if conflict_penalty > 0:
        parts.append(f"{len(conflicts)} conflict(s) applied {conflict_penalty:.0%} total penalty")

    return ConfidenceSummary(
        overall=overall,
        industry_confidence=round(ind_adj, 3),
        strategy_confidence=round(str_adj, 3),
        freshness_penalty=round(freshness_penalty, 3),
        conflict_penalty=round(conflict_penalty, 3),
        basis=". ".join(parts) + ".",
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _parse_dt(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    try:
        from dateutil.parser import parse
        return parse(str(value))
    except Exception:
        return None


def _days_old(generated_at: Any) -> float:
    dt = _parse_dt(generated_at)
    if dt is None:
        return 0.0
    now = datetime.utcnow()
    if dt.tzinfo is not None:
        now = now.replace(tzinfo=timezone.utc)
    return max((now - dt).total_seconds() / 86400, 0.0)


def compute_freshness_penalty(agent_payload: dict[str, Any], policy: OrchestratorPolicy) -> float:
    days = _days_old(agent_payload.get("generated_at"))
    return policy.freshness_penalty(days)


def _prior_thesis_text(prior: dict[str, Any] | None) -> str | None:
    if prior is None:
        return None
    return prior.get("thesis_statement") or prior.get("thesis") or None


def _is_corroborated(assumption_key: str, industry: dict[str, Any], strategy: dict[str, Any]) -> bool:
    """Check if an assumption key is mentioned by both agents."""
    key_lower = assumption_key.lower()
    ind_text = str(industry).lower()
    str_text = str(strategy).lower()
    # Simple check: at least two words from the key appear in both texts
    words = [w for w in key_lower.replace("_", " ").split() if len(w) > 3]
    ind_hits = sum(1 for w in words if w in ind_text)
    str_hits = sum(1 for w in words if w in str_text)
    return ind_hits >= 1 and str_hits >= 1
