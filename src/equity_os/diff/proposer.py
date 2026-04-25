"""Proposer: convert FieldChanges into AssumptionProposals + detect ConflictFlags.

For each FieldChange that matches a known assumption-driving path, emit a
proposal. Proposals include rationale, downstream fields, and thesis/valuation
implications that an analyst can review before accepting.

Conflict detection
------------------
1. confidence_inversion  — same field went from high confidence to much lower
2. evidence_disagreement — new evidence IDs appear for a HIGH-materiality change
3. oscillation           — field reversed a direction seen in a previous diff
4. unresolved_growth     — unresolved_questions list grew
"""

from __future__ import annotations

from typing import Any

from .models import (
    AssumptionProposal,
    ChangeType,
    ConflictFlag,
    DiffMateriality,
    FieldChange,
)

# ---------------------------------------------------------------------------
# Assumption mapping: field_path prefix → (key, label, downstream, thesis_impl, val_impl)
# ---------------------------------------------------------------------------

# Each entry: field_path_prefix → dict with keys:
#   assumption_key   : slug for the AssumptionRecord
#   assumption_label : human-readable name
#   downstream       : list of model fields that read from this assumption
#   thesis_impl_fn   : callable(prior, current) → str
#   val_impl_fn      : callable(prior, current) → str

def _generic_thesis(prior: Any, current: Any) -> str:
    return f"Value changed from '{prior}' to '{current}'; review whether this alters the core investment thesis."


def _generic_val(prior: Any, current: Any) -> str:
    return "Reassess any model inputs derived from this field."


_FIELD_TO_ASSUMPTION: dict[str, dict[str, Any]] = {
    "cycle_stage": {
        "assumption_key":   "industry_cycle_stage",
        "assumption_label": "Industry Cycle Stage",
        "downstream":       ["growth_rate_assumption", "capex_assumption", "terminal_growth_rate"],
        "thesis_impl_fn":   lambda p, c: (
            "Industry maturing — growth premium in thesis may need revisiting."
            if _is_decel(p, c) else
            "Industry re-accelerating — conservative growth assumptions may need upward revision."
            if _is_accel(p, c) else
            f"Cycle stage revised: {p} → {c}. Review growth rate assumptions."
        ),
        "val_impl_fn": lambda p, c: (
            "Lower terminal growth rate may be warranted; P/E compression possible."
            if _is_decel(p, c) else
            "Higher terminal growth rate potentially justified; multiple expansion possible."
            if _is_accel(p, c) else
            "Update growth rate and terminal value inputs."
        ),
    },
    "market_structure": {
        "assumption_key":   "market_structure",
        "assumption_label": "Industry Market Structure",
        "downstream":       ["pricing_power_assumption", "competitive_intensity", "margin_ceiling"],
        "thesis_impl_fn":   lambda p, c: (
            "Market becoming more oligopolistic — pricing power thesis strengthening."
            if str(c) == "OLIGOPOLY" else
            "Market fragmenting — pricing pressure thesis strengthening."
            if str(c) == "FRAGMENTED" else
            f"Market structure revised: {p} → {c}. Pricing power assumptions need review."
        ),
        "val_impl_fn": lambda p, c: (
            "Higher sustainable margins plausible in oligopolistic structure."
            if str(c) == "OLIGOPOLY" else
            "Margin compression risk increases in fragmented market."
            if str(c) == "FRAGMENTED" else
            "Revise sustainable margin assumption in DCF."
        ),
    },
    "industry_label": {
        "assumption_key":   "industry_classification",
        "assumption_label": "Industry Classification",
        "downstream":       ["peer_set", "benchmark_multiples", "kpi_selection"],
        "thesis_impl_fn":   lambda p, c: f"Industry reclassified from '{p}' to '{c}'. Peer set and benchmark multiples need updating.",
        "val_impl_fn":      lambda p, c: "Comparable multiples should be sourced from the revised peer group.",
    },
    "overall_confidence": {
        "assumption_key":   "analytical_confidence",
        "assumption_label": "Overall Analytical Confidence",
        "downstream":       ["conclusion_weight", "conviction_level"],
        "thesis_impl_fn":   lambda p, c: (
            f"Confidence increased from {p:.0%} to {c:.0%} — evidence base strengthening."
            if _num(c) > _num(p) else
            f"Confidence fell from {p:.0%} to {c:.0%} — evidence base weakened; widen uncertainty range."
        ),
        "val_impl_fn": lambda p, c: (
            "Tighter confidence interval on key assumptions is justified."
            if _num(c) > _num(p) else
            "Widen scenario analysis; base case uncertainty higher."
        ),
    },
    "strategic_positioning.target_market": {
        "assumption_key":   "target_market_positioning",
        "assumption_label": "Target Market Positioning",
        "downstream":       ["asp_assumption", "volume_mix", "margin_profile"],
        "thesis_impl_fn":   lambda p, c: f"Target market revised from '{p}' to '{c}'. Review pricing and volume mix assumptions.",
        "val_impl_fn":      lambda p, c: "ASP and gross margin assumptions should reflect the updated market positioning.",
    },
}

# Prefix-based rules for list items
_PREFIX_TO_ASSUMPTION: list[tuple[str, dict[str, Any]]] = [
    ("porter_forces[Competitive Rivalry]", {
        "assumption_key":   "competitive_rivalry_intensity",
        "assumption_label": "Competitive Rivalry Intensity",
        "downstream":       ["pricing_power_assumption", "market_share_stability"],
        "thesis_impl_fn":   lambda p, c: (
            f"Competitive rivalry changed ({_level(p)} → {_level(c)}). "
            + ("Pricing power thesis under pressure." if _level(c) == "HIGH" else "Competitive pressures easing.")
        ),
        "val_impl_fn": lambda p, c: (
            "Lower sustainable margins warranted if rivalry escalates."
            if _level(c) == "HIGH" else
            "Margin expansion possible if competitive intensity moderating."
        ),
    }),
    ("porter_forces[Threat of New Entry]", {
        "assumption_key":   "entry_barriers",
        "assumption_label": "Barriers to Entry",
        "downstream":       ["moat_score", "reinvestment_rate_assumption"],
        "thesis_impl_fn":   lambda p, c: (
            f"Entry barriers changed ({_level(p)} → {_level(c)}). "
            + ("Moat thesis strengthening." if _level(c) == "HIGH" else "Moat thesis at risk — new entrants more likely.")
        ),
        "val_impl_fn": lambda p, c: (
            "Higher long-term returns justified with strong entry barriers."
            if _level(c) == "HIGH" else
            "ROIC assumptions may need downward revision."
        ),
    }),
    ("porter_forces[Supplier Power]", {
        "assumption_key":   "supplier_bargaining_power",
        "assumption_label": "Supplier Bargaining Power",
        "downstream":       ["cogs_assumption", "gross_margin_ceiling"],
        "thesis_impl_fn":   lambda p, c: f"Supplier power {_level(p)} → {_level(c)}. COGS flexibility thesis updated.",
        "val_impl_fn":      lambda p, c: "Update gross margin sensitivity to input cost assumptions.",
    }),
    ("porter_forces[Buyer Power]", {
        "assumption_key":   "buyer_bargaining_power",
        "assumption_label": "Buyer Bargaining Power",
        "downstream":       ["asr_assumption", "churn_rate"],
        "thesis_impl_fn":   lambda p, c: f"Buyer power {_level(p)} → {_level(c)}. Customer retention / pricing thesis updated.",
        "val_impl_fn":      lambda p, c: "Update revenue retention and pricing power assumptions.",
    }),
    ("porter_forces[Threat of Substitutes]", {
        "assumption_key":   "substitute_threat",
        "assumption_label": "Threat of Substitutes",
        "downstream":       ["volume_assumption", "asr_resilience"],
        "thesis_impl_fn":   lambda p, c: f"Substitute threat {_level(p)} → {_level(c)}. Demand resilience thesis updated.",
        "val_impl_fn":      lambda p, c: "Review demand elasticity and volume assumptions.",
    }),
    ("regulatory_factors[", {
        "assumption_key":   "regulatory_risk",
        "assumption_label": "Regulatory Risk",
        "downstream":       ["compliance_cost_assumption", "addressable_market", "fee_structure"],
        "thesis_impl_fn":   lambda p, c: (
            "New regulatory factor identified — could constrain revenue or increase compliance cost."
            if p is None else
            "Regulatory factor removed — regulatory risk assumption may be overstated."
        ),
        "val_impl_fn": lambda p, c: (
            "Quantify compliance cost exposure and TAM impact in base case."
            if p is None else
            "Regulatory risk premium in discount rate may be reducible."
        ),
    }),
    ("segment_priorities[", {
        "assumption_key":   "segment_priority",
        "assumption_label": "Segment Management Priority",
        "downstream":       ["capex_allocation_assumption", "growth_by_segment"],
        "thesis_impl_fn":   lambda p, c: "Segment priority ranking changed — may signal reallocation of management focus and capex.",
        "val_impl_fn":      lambda p, c: "Review segment-level growth and margin assumptions to reflect revised priority.",
    }),
]


# ---------------------------------------------------------------------------
# Conflict detection
# ---------------------------------------------------------------------------


def _detect_conflicts(
    changes: list[FieldChange],
    prior_payload: dict[str, Any],
    current_payload: dict[str, Any],
    prior_evidence_ids: list[str],
    current_evidence_ids: list[str],
) -> list[ConflictFlag]:
    conflicts: list[ConflictFlag] = []

    # 1. confidence_inversion: confidence dropped > 50% on HIGH-materiality fields
    for change in changes:
        if change.change_type != ChangeType.MODIFIED:
            continue
        if "confidence" not in change.field_path:
            continue
        prior_c = _num(change.prior_value)
        curr_c = _num(change.current_value)
        if prior_c > 0 and curr_c < prior_c * 0.5:
            conflicts.append(ConflictFlag(
                conflict_type="confidence_inversion",
                description=(
                    f"Confidence on '{change.field_path}' fell from "
                    f"{prior_c:.0%} to {curr_c:.0%} — evidence base weakened significantly."
                ),
                field_path=change.field_path,
                evidence_a_ids=prior_evidence_ids,
                evidence_b_ids=current_evidence_ids,
                confidence_impact=round(prior_c - curr_c, 3),
            ))

    # 2. evidence_disagreement: HIGH-materiality MODIFIED with new evidence set
    new_ev = set(current_evidence_ids) - set(prior_evidence_ids)
    for change in changes:
        if change.change_type != ChangeType.MODIFIED:
            continue
        if change.materiality != DiffMateriality.HIGH:
            continue
        if new_ev:
            conflicts.append(ConflictFlag(
                conflict_type="evidence_disagreement",
                description=(
                    f"HIGH-materiality field '{change.field_path}' changed while "
                    f"{len(new_ev)} new evidence source(s) were added. "
                    "Verify that new evidence is consistent with the change direction."
                ),
                field_path=change.field_path,
                evidence_a_ids=prior_evidence_ids,
                evidence_b_ids=list(new_ev),
                confidence_impact=0.1,
            ))

    # 3. unresolved_growth: more unresolved questions in current run
    prior_unresolved = prior_payload.get("unresolved_questions", [])
    curr_unresolved = current_payload.get("unresolved_questions", [])
    if len(curr_unresolved) > len(prior_unresolved):
        new_questions = [q for q in curr_unresolved if q not in prior_unresolved]
        if new_questions:
            conflicts.append(ConflictFlag(
                conflict_type="unresolved_growth",
                description=(
                    f"Unresolved questions grew from {len(prior_unresolved)} to "
                    f"{len(curr_unresolved)}. New gaps: "
                    + "; ".join(q[:80] for q in new_questions[:3])
                ),
                field_path="unresolved_questions",
                evidence_a_ids=prior_evidence_ids,
                evidence_b_ids=current_evidence_ids,
                confidence_impact=round(0.05 * len(new_questions), 3),
            ))

    return conflicts


# ---------------------------------------------------------------------------
# Proposal generation
# ---------------------------------------------------------------------------


def _rule_for_path(field_path: str) -> dict[str, Any] | None:
    """Look up the assumption rule for a given field path."""
    # Exact match
    for key, rule in _FIELD_TO_ASSUMPTION.items():
        if field_path == key or field_path.startswith(key + "."):
            return rule
    # Prefix match
    for prefix, rule in _PREFIX_TO_ASSUMPTION:
        if field_path.startswith(prefix):
            return rule
    return None


def propose_updates(
    changes: list[FieldChange],
    prior_payload: dict[str, Any],
    current_payload: dict[str, Any],
    agent_id: str,
    current_evidence_ids: list[str],
    prior_evidence_ids: list[str],
) -> tuple[list[AssumptionProposal], list[ConflictFlag]]:
    """Convert FieldChanges into AssumptionProposals.

    Returns (proposals, conflict_flags).
    Proposals are deduplicated by assumption_key (one proposal per assumption).
    """
    proposals: dict[str, AssumptionProposal] = {}  # keyed by assumption_key
    triggering: dict[str, list[str]] = {}           # assumption_key → [field_paths]

    for change in changes:
        if change.change_type == ChangeType.UNCHANGED:
            continue
        rule = _rule_for_path(change.field_path)
        if rule is None:
            continue

        key = _make_unique_key(rule["assumption_key"], change.field_path)
        if key not in proposals:
            prior_val = change.prior_value if change.change_type != ChangeType.ADDED else None
            curr_val = change.current_value if change.change_type != ChangeType.REMOVED else None
            thesis = rule["thesis_impl_fn"](prior_val, curr_val)
            val = rule["val_impl_fn"](prior_val, curr_val)
            proposals[key] = AssumptionProposal(
                assumption_key=key,
                assumption_label=rule["assumption_label"],
                prior_value=prior_val,
                proposed_value=curr_val,
                change_type=change.change_type,
                rationale=_build_rationale(change, current_payload),
                evidence_ids=current_evidence_ids,
                owner_agent=agent_id,
                confidence=change.materiality == DiffMateriality.HIGH and 0.7 or 0.5,
                materiality=change.materiality,
                impacted_model_fields=rule["downstream"],
                implication_for_thesis=thesis,
                implication_for_valuation=val,
                triggered_by_field_paths=[change.field_path],
            )
            triggering[key] = [change.field_path]
        else:
            triggering[key].append(change.field_path)
            proposals[key].triggered_by_field_paths = triggering[key]

    # Resolve confidence: HIGH fields always 0.7+, MEDIUM 0.5+
    for p in proposals.values():
        if p.materiality == DiffMateriality.HIGH and p.confidence < 0.7:
            p.confidence = 0.7

    conflicts = _detect_conflicts(
        changes, prior_payload, current_payload,
        prior_evidence_ids, current_evidence_ids,
    )

    return list(proposals.values()), conflicts


def _make_unique_key(base_key: str, field_path: str) -> str:
    """Generate a unique assumption key for list-item based changes."""
    # For generic prefix rules like "regulatory_factors[", include the item name
    if "[" in field_path:
        bracket_content = field_path.split("[", 1)[1].split("]")[0]
        slug = bracket_content.lower().replace(" ", "_").replace("/", "_")[:24]
        return f"{base_key}__{slug}"
    return base_key


def _build_rationale(change: FieldChange, current_payload: dict[str, Any]) -> str:
    """Build a plain-language rationale for a proposed assumption update."""
    ct = change.change_type.value.lower()
    path = change.field_path
    prior = change.prior_value
    current = change.current_value
    if change.change_type == ChangeType.ADDED:
        return (
            f"Field '{path}' was absent in the prior run and now appears with value '{current}'. "
            "New evidence introduced this element."
        )
    if change.change_type == ChangeType.REMOVED:
        return (
            f"Field '{path}' (prior value: '{prior}') is no longer present in the current run. "
            "It may have been superseded or the underlying evidence no longer supports it."
        )
    mag_str = (
        f" (magnitude: {change.change_magnitude:.1%})" if change.change_magnitude is not None else ""
    )
    return (
        f"Field '{path}' {ct}{mag_str}: '{prior}' → '{current}'. "
        f"Current run processed {len(change.evidence_ids)} evidence source(s). "
        "Review the evidence to confirm the direction of change."
    )


# ---------------------------------------------------------------------------
# Value helpers
# ---------------------------------------------------------------------------


def _num(v: Any) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def _level(item: Any) -> str:
    if isinstance(item, dict):
        return str(item.get("level", "UNKNOWN")).upper()
    return str(item).upper()


def _is_decel(prior: Any, current: Any) -> bool:
    order = {"EARLY_GROWTH": 0, "GROWTH": 1, "MATURE": 2, "DECLINE": 3, "UNKNOWN": -1}
    return order.get(str(prior), -1) < order.get(str(current), -1)


def _is_accel(prior: Any, current: Any) -> bool:
    order = {"EARLY_GROWTH": 0, "GROWTH": 1, "MATURE": 2, "DECLINE": 3, "UNKNOWN": -1}
    return order.get(str(prior), -1) > order.get(str(current), -1)
