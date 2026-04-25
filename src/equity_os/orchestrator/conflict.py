"""ConflictResolver — detects and resolves disagreements between specialist agents.

Detection
---------
Each dimension check compares the two agent outputs for a specific claim.
A HARD conflict means the agents assert contradictory facts.
A SOFT conflict means they emphasize different directions but are not mutually exclusive.

Resolution
----------
Every conflict is resolved by the policy's conflict_resolution table.
When the winner is "higher_confidence", the agent with the higher adjusted
confidence on that dimension is trusted.  The resolution is recorded verbatim
so the full audit trail is preserved.
"""

from __future__ import annotations

from typing import Any

from .models import AgentConflict
from .policy import OrchestratorPolicy


def _level_order(level: str) -> int:
    return {"HIGH": 3, "MEDIUM": 2, "LOW": 1, "UNKNOWN": 0}.get(str(level).upper(), 0)


def _severity_order(sev: str) -> int:
    return {"explicit": 3, "mentioned": 2, "implied": 1}.get(str(sev).lower(), 0)


def _find_porter_force(forces: list[dict[str, Any]], name: str) -> dict[str, Any] | None:
    for f in forces:
        if f.get("name", "").lower() == name.lower():
            return f
    return None


def _pick_winner(
    dimension: str,
    industry_conf: float,
    strategy_conf: float,
    policy: OrchestratorPolicy,
) -> tuple[str, str]:
    """Return (trusted_agent, resolution_basis)."""
    winner = policy.conflict_winner(dimension)
    if winner == "higher_confidence":
        trusted = "industry_v1" if industry_conf >= strategy_conf else "strategy_v1"
        basis = f"policy: conflict_resolution.{dimension} = higher_confidence → {trusted} (higher confidence)"
    else:
        trusted = winner
        basis = f"policy: conflict_resolution.{dimension} = {winner}"
    return trusted, basis


def detect_conflicts(
    industry: dict[str, Any],
    strategy: dict[str, Any],
    policy: OrchestratorPolicy,
) -> list[AgentConflict]:
    """Return all detected conflicts between IndustryAnalysis and CompanyStrategyAnalysis dicts."""
    conflicts: list[AgentConflict] = []
    ind_conf = float(industry.get("overall_confidence", 0.5))
    str_conf = float(strategy.get("overall_confidence", 0.5))

    # 1. Competitive intensity
    rivalry_force = _find_porter_force(industry.get("porter_forces", []), "Competitive Rivalry")
    rivalry_level = (rivalry_force or {}).get("level", "UNKNOWN")
    comp_risks = [r for r in strategy.get("risk_disclosures", []) if r.get("category") == "competitive"]
    comp_severity = max((_severity_order(r.get("severity_from_disclosure", "implied")) for r in comp_risks), default=0)
    # Conflict: industry says HIGH rivalry but strategy severity ≤ implied
    rivalry_order = _level_order(rivalry_level)
    if rivalry_order >= 3 and comp_severity <= 1:
        trusted, basis = _pick_winner("competitive_intensity", ind_conf, str_conf, policy)
        conf_after = max(ind_conf if trusted == "industry_v1" else str_conf, 0.0) - policy.penalty("conflict_soft_penalty")
        conflicts.append(AgentConflict(
            dimension="competitive_intensity",
            industry_view=f"Porter Competitive Rivalry = {rivalry_level}",
            strategy_view=f"Competitive risk severity = {'implied' if comp_severity <= 1 else 'mentioned'} in disclosures",
            conflict_severity="soft",
            resolution=f"Trusting {trusted}: {basis.split('→')[-1].strip() if '→' in basis else basis}",
            resolution_basis=basis,
            trusted_agent=trusted,
            confidence_after=max(round(conf_after, 3), 0.05),
        ))
    elif rivalry_order <= 1 and comp_severity >= 3:
        trusted, basis = _pick_winner("competitive_intensity", ind_conf, str_conf, policy)
        conf_after = max(ind_conf if trusted == "industry_v1" else str_conf, 0.0) - policy.penalty("conflict_soft_penalty")
        conflicts.append(AgentConflict(
            dimension="competitive_intensity",
            industry_view=f"Porter Competitive Rivalry = {rivalry_level}",
            strategy_view="Competitive risk explicitly disclosed",
            conflict_severity="soft",
            resolution=f"Trusting {trusted}",
            resolution_basis=basis,
            trusted_agent=trusted,
            confidence_after=max(round(conf_after, 3), 0.05),
        ))

    # 2. Regulatory risk
    ind_regs = industry.get("regulatory_factors", [])
    str_reg_risks = [r for r in strategy.get("risk_disclosures", []) if r.get("category") == "regulatory"]
    ind_has_reg = len(ind_regs) > 0
    str_has_reg = len(str_reg_risks) > 0
    str_explicit_reg = any(r.get("severity_from_disclosure") == "explicit" for r in str_reg_risks)
    if not ind_has_reg and str_explicit_reg:
        trusted, basis = _pick_winner("regulatory_risk", ind_conf, str_conf, policy)
        conf_after = max(ind_conf if trusted == "industry_v1" else str_conf, 0.0) - policy.penalty("conflict_hard_penalty")
        conflicts.append(AgentConflict(
            dimension="regulatory_risk",
            industry_view="No regulatory factors detected by IndustryAgent",
            strategy_view="Regulatory risk explicitly disclosed in company filings",
            conflict_severity="hard",
            resolution=f"Trusting {trusted}: company disclosures are primary-sourced",
            resolution_basis=basis,
            trusted_agent=trusted,
            confidence_after=max(round(conf_after, 3), 0.05),
        ))

    # 3. Growth / cycle alignment
    cycle_stage = industry.get("cycle_stage", "UNKNOWN")
    shifts = strategy.get("narrative_shifts", [])
    growth_shift_down = any(
        s.get("shift_type") == "emphasis_decrease" and "growth" in s.get("topic", "").lower()
        for s in shifts
    )
    growth_shift_up = any(
        s.get("shift_type") == "emphasis_increase" and "growth" in s.get("topic", "").lower()
        for s in shifts
    )
    if cycle_stage == "GROWTH" and growth_shift_down:
        trusted, basis = _pick_winner("industry_cycle", ind_conf, str_conf, policy)
        conf_after = max(ind_conf if trusted == "industry_v1" else str_conf, 0.0) - policy.penalty("conflict_soft_penalty")
        conflicts.append(AgentConflict(
            dimension="industry_cycle",
            industry_view="Industry cycle stage = GROWTH",
            strategy_view="Narrative shift detects declining emphasis on growth topics",
            conflict_severity="soft",
            resolution=f"Trusting {trusted}: cycle stage is macro observation; narrative shift may be localized",
            resolution_basis=basis,
            trusted_agent=trusted,
            confidence_after=max(round(conf_after, 3), 0.05),
        ))
    elif cycle_stage in ("MATURE", "DECLINE") and growth_shift_up:
        trusted, basis = _pick_winner("industry_cycle", ind_conf, str_conf, policy)
        conf_after = max(ind_conf if trusted == "industry_v1" else str_conf, 0.0) - policy.penalty("conflict_soft_penalty")
        conflicts.append(AgentConflict(
            dimension="industry_cycle",
            industry_view=f"Industry cycle stage = {cycle_stage}",
            strategy_view="Narrative shift detects increasing emphasis on growth topics",
            conflict_severity="soft",
            resolution=f"Trusting {trusted}: management may be aspirational; macro cycle data takes precedence",
            resolution_basis=basis,
            trusted_agent=trusted,
            confidence_after=max(round(conf_after, 3), 0.05),
        ))

    # 4. Moat type alignment
    ind_moats = set(industry.get("competitive_dynamics", {}).get("moat_type", []))
    str_moats = set(strategy.get("strategic_positioning", {}).get("moat_assessment", []))
    non_trivial_ind = ind_moats - {"unknown"}
    non_trivial_str = str_moats - {"unknown"}
    if non_trivial_ind and non_trivial_str and not (non_trivial_ind & non_trivial_str):
        # Completely disjoint, non-trivial assessments
        trusted, basis = _pick_winner("moat_type", ind_conf, str_conf, policy)
        conf_after = max(ind_conf if trusted == "industry_v1" else str_conf, 0.0) - policy.penalty("conflict_soft_penalty")
        conflicts.append(AgentConflict(
            dimension="moat_type",
            industry_view=f"Moat types: {', '.join(sorted(non_trivial_ind))}",
            strategy_view=f"Moat assessment: {', '.join(sorted(non_trivial_str))}",
            conflict_severity="soft",
            resolution=f"Trusting {trusted}: moats identified from distinct evidence bases; combined view may be valid",
            resolution_basis=basis,
            trusted_agent=trusted,
            confidence_after=max(round(conf_after, 3), 0.05),
        ))

    # 5. Confidence divergence — if agents are far apart on overall confidence
    threshold = policy.penalty("disagreement_threshold")
    if abs(ind_conf - str_conf) >= threshold:
        trusted, basis = _pick_winner("default", ind_conf, str_conf, policy)
        conf_after = max(min(ind_conf, str_conf), 0.05) - policy.penalty("conflict_soft_penalty")
        conflicts.append(AgentConflict(
            dimension="overall_confidence_divergence",
            industry_view=f"Overall confidence = {ind_conf:.0%}",
            strategy_view=f"Overall confidence = {str_conf:.0%}",
            conflict_severity="soft",
            resolution=f"Using lower confidence as base; trusting {trusted} where determinable",
            resolution_basis=basis,
            trusted_agent=trusted,
            confidence_after=max(round(conf_after, 3), 0.05),
        ))

    return conflicts
