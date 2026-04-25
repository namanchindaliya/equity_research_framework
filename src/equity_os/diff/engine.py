"""Diff engine: compare two agent run payloads, emit FieldChanges.

Algorithm
---------
1. Walk both payloads simultaneously by field path.
2. For scalar fields: compare equality; compute magnitude for numerics.
3. For list fields: match items by a canonical identity key, then recursively diff.
4. For dict fields: recurse.
5. Exclude meta-only fields (run_id, generated_at, evidence_ids) from diffing —
   they change on every run but carry no analytical signal.

Materiality rules
-----------------
Tier 1 (HIGH):  market_structure, cycle_stage, porter_forces.*.level (any direction),
                any ADDED/REMOVED regulatory factor, any ADDED/REMOVED top risk category
Tier 2 (MEDIUM): overall_confidence delta > 0.15, segment_priorities.*.priority_rank,
                 strategic_positioning.target_market, narrative_shifts
Tier 3 (LOW):   everything else, including confidence changes < 0.15
"""

from __future__ import annotations

import math
from datetime import datetime
from typing import Any

from .models import ChangeLog, ChangeType, DiffMateriality, EpisodeDiff, FieldChange

# ---------------------------------------------------------------------------
# Configuration: fields to skip entirely (infrastructure, not analytical)
# ---------------------------------------------------------------------------

_SKIP_PATHS: set[str] = {
    "run_id", "generated_at", "evidence_ids", "agent_id",
    "ticker", "change_id", "proposal_id", "diff_id",
}

# ---------------------------------------------------------------------------
# List identity keys: how to match items in a list across two runs
# ---------------------------------------------------------------------------

_LIST_IDENTITY_KEYS: dict[str, str] = {
    "porter_forces":            "name",
    "key_kpis":                 "name",
    "regulatory_factors":       "name",
    "top_risks":                "name",
    "risk_disclosures":         "name",
    "segment_priorities":       "segment_name",
    "capital_allocation":       "category",
    "narrative_shifts":         "topic",
    "mgmt_credibility_signals": "signal_type",
    "management_priorities":    "_text40",   # synthetic key: first 40 chars of text
}

# ---------------------------------------------------------------------------
# Materiality rules
# ---------------------------------------------------------------------------

# Field paths that are always HIGH materiality when changed
_HIGH_MATERIALITY_PATHS: set[str] = {
    "market_structure",
    "cycle_stage",
    "industry_label",
    "strategic_positioning.target_market",
}

# Prefix patterns for HIGH materiality
_HIGH_MATERIALITY_PREFIXES: tuple[str, ...] = (
    "porter_forces[",        # any Porter force level change is HIGH
    "regulatory_factors[",   # any regulatory change is HIGH (ADDED/REMOVED)
    "top_risks[",
)

_MEDIUM_MATERIALITY_PATHS: set[str] = {
    "overall_confidence",
    "strategic_positioning.moat_assessment",
    "strategic_positioning.differentiation_axes",
    "competitive_dynamics.moat_type",
}

_MEDIUM_MATERIALITY_PREFIXES: tuple[str, ...] = (
    "segment_priorities[",
    "narrative_shifts[",
    "mgmt_credibility_signals[",
)


def _compute_materiality(
    field_path: str,
    change_type: ChangeType,
    prior_value: Any,
    current_value: Any,
    change_magnitude: float | None,
) -> DiffMateriality:
    if field_path in _HIGH_MATERIALITY_PATHS:
        return DiffMateriality.HIGH
    if any(field_path.startswith(p) for p in _HIGH_MATERIALITY_PREFIXES):
        if change_type in (ChangeType.ADDED, ChangeType.REMOVED):
            return DiffMateriality.HIGH
        # Porter force: HIGH only when level changes to/from HIGH
        if "porter_forces[" in field_path and ".level" in field_path:
            vals = {str(prior_value).upper(), str(current_value).upper()}
            if "HIGH" in vals:
                return DiffMateriality.HIGH
            return DiffMateriality.MEDIUM
        return DiffMateriality.MEDIUM
    if field_path in _MEDIUM_MATERIALITY_PATHS:
        if change_magnitude is not None:
            # confidence fields are bounded [0,1]; use absolute delta, not relative
            if "confidence" in field_path:
                try:
                    abs_delta = abs(float(current_value) - float(prior_value))
                except (TypeError, ValueError):
                    abs_delta = 0.0
                if abs_delta > 0.20:
                    return DiffMateriality.HIGH
            elif change_magnitude > 0.15:
                return DiffMateriality.HIGH
        return DiffMateriality.MEDIUM
    if any(field_path.startswith(p) for p in _MEDIUM_MATERIALITY_PREFIXES):
        return DiffMateriality.MEDIUM
    return DiffMateriality.LOW


# ---------------------------------------------------------------------------
# Change magnitude
# ---------------------------------------------------------------------------


def _magnitude(prior: Any, current: Any) -> float | None:
    """Return relative change for numeric/boolean scalars; None for others."""
    if isinstance(prior, bool) or isinstance(current, bool):
        return None
    if isinstance(prior, (int, float)) and isinstance(current, (int, float)):
        denom = abs(prior) if prior != 0 else 1.0
        return abs(current - prior) / denom
    return None


# ---------------------------------------------------------------------------
# List identity key extraction
# ---------------------------------------------------------------------------


def _item_key(list_name: str, item: Any) -> str | None:
    """Return the identity key for a list item, or None if not keyed."""
    if not isinstance(item, dict):
        return None
    identity_field = _LIST_IDENTITY_KEYS.get(list_name)
    if identity_field == "_text40":
        # Synthetic key: first 40 chars of item["text"] or item["finding"]["text"]
        text = item.get("text") or (item.get("finding") or {}).get("text", "")
        return text[:40].strip().lower()
    if identity_field:
        val = item.get(identity_field)
        return str(val) if val is not None else None
    return None


# ---------------------------------------------------------------------------
# Core recursive differ
# ---------------------------------------------------------------------------


def _diff_values(
    field_path: str,
    prior: Any,
    current: Any,
    agent_id: str,
    evidence_ids: list[str],
    changes: list[FieldChange],
    list_name: str | None = None,
) -> None:
    """Recursively walk and diff two values, appending to `changes`."""
    last_segment = field_path.split(".")[-1].split("[")[0]
    if last_segment in _SKIP_PATHS:
        return

    # ---- dict: recurse into each key ---
    if isinstance(prior, dict) and isinstance(current, dict):
        all_keys = set(prior) | set(current)
        for k in sorted(all_keys):
            _diff_values(
                f"{field_path}.{k}" if field_path else k,
                prior.get(k),
                current.get(k),
                agent_id,
                evidence_ids,
                changes,
                list_name=k,
            )
        return

    # ---- list: keyed matching ---
    if isinstance(prior, list) and isinstance(current, list):
        # Try to use identity key
        lname = list_name or field_path.split(".")[-1]
        if _LIST_IDENTITY_KEYS.get(lname):
            _diff_lists(field_path, lname, prior, current, agent_id, evidence_ids, changes)
        else:
            # Positional diff for unkeyed lists (e.g. simple string lists)
            _diff_unkeyed_lists(field_path, prior, current, agent_id, evidence_ids, changes)
        return

    # ---- scalar ---
    if prior == current:
        mag = _magnitude(prior, current)
        mat = _compute_materiality(field_path, ChangeType.UNCHANGED, prior, current, mag)
        changes.append(FieldChange(
            field_path=field_path,
            change_type=ChangeType.UNCHANGED,
            prior_value=prior,
            current_value=current,
            change_magnitude=mag,
            materiality=mat,
            owner_agent=agent_id,
            evidence_ids=evidence_ids,
        ))
    else:
        mag = _magnitude(prior, current)
        ct = (
            ChangeType.ADDED if prior is None
            else ChangeType.REMOVED if current is None
            else ChangeType.MODIFIED
        )
        mat = _compute_materiality(field_path, ct, prior, current, mag)
        changes.append(FieldChange(
            field_path=field_path,
            change_type=ct,
            prior_value=prior,
            current_value=current,
            change_magnitude=mag,
            materiality=mat,
            owner_agent=agent_id,
            evidence_ids=evidence_ids,
        ))


def _diff_lists(
    base_path: str,
    list_name: str,
    prior_list: list[Any],
    current_list: list[Any],
    agent_id: str,
    evidence_ids: list[str],
    changes: list[FieldChange],
) -> None:
    """Diff two lists of dicts using their canonical identity key."""
    prior_by_key: dict[str, Any] = {}
    for item in prior_list:
        k = _item_key(list_name, item)
        if k is not None:
            prior_by_key[k] = item

    current_by_key: dict[str, Any] = {}
    for item in current_list:
        k = _item_key(list_name, item)
        if k is not None:
            current_by_key[k] = item

    all_keys = sorted(set(prior_by_key) | set(current_by_key))
    for key in all_keys:
        item_path = f"{base_path}[{key}]"
        if key in prior_by_key and key in current_by_key:
            # Both present — recurse into the item's fields
            _diff_values(
                item_path, prior_by_key[key], current_by_key[key],
                agent_id, evidence_ids, changes, list_name=list_name,
            )
        elif key in prior_by_key:
            # Removed
            mat = _compute_materiality(item_path, ChangeType.REMOVED, prior_by_key[key], None, None)
            changes.append(FieldChange(
                field_path=item_path,
                change_type=ChangeType.REMOVED,
                prior_value=prior_by_key[key],
                current_value=None,
                materiality=mat,
                owner_agent=agent_id,
                evidence_ids=evidence_ids,
            ))
        else:
            # Added
            mat = _compute_materiality(item_path, ChangeType.ADDED, None, current_by_key[key], None)
            changes.append(FieldChange(
                field_path=item_path,
                change_type=ChangeType.ADDED,
                prior_value=None,
                current_value=current_by_key[key],
                materiality=mat,
                owner_agent=agent_id,
                evidence_ids=evidence_ids,
            ))


def _diff_unkeyed_lists(
    base_path: str,
    prior_list: list[Any],
    current_list: list[Any],
    agent_id: str,
    evidence_ids: list[str],
    changes: list[FieldChange],
) -> None:
    """Positional diff for simple value lists (e.g. list[str])."""
    prior_set = set(str(v) for v in prior_list)
    current_set = set(str(v) for v in current_list)
    for v in sorted(prior_set - current_set):
        mat = _compute_materiality(f"{base_path}[{v}]", ChangeType.REMOVED, v, None, None)
        changes.append(FieldChange(
            field_path=f"{base_path}[{v}]",
            change_type=ChangeType.REMOVED,
            prior_value=v,
            current_value=None,
            materiality=mat,
            owner_agent=agent_id,
            evidence_ids=evidence_ids,
        ))
    for v in sorted(current_set - prior_set):
        mat = _compute_materiality(f"{base_path}[{v}]", ChangeType.ADDED, None, v, None)
        changes.append(FieldChange(
            field_path=f"{base_path}[{v}]",
            change_type=ChangeType.ADDED,
            prior_value=None,
            current_value=v,
            materiality=mat,
            owner_agent=agent_id,
            evidence_ids=evidence_ids,
        ))
    for v in sorted(prior_set & current_set):
        mat = _compute_materiality(f"{base_path}[{v}]", ChangeType.UNCHANGED, v, v, None)
        changes.append(FieldChange(
            field_path=f"{base_path}[{v}]",
            change_type=ChangeType.UNCHANGED,
            prior_value=v,
            current_value=v,
            materiality=mat,
            owner_agent=agent_id,
            evidence_ids=evidence_ids,
        ))


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def diff_payloads(
    prior: dict[str, Any],
    current: dict[str, Any],
    agent_id: str,
    prior_run_id: str,
    current_run_id: str,
    ticker: str,
    current_evidence_ids: list[str],
    prior_evidence_ids: list[str] | None = None,
    episode_id: str | None = None,
) -> EpisodeDiff:
    """Compare two agent run payloads and return a fully annotated EpisodeDiff.

    Parameters
    ----------
    prior               : payload dict from the previous run
    current             : payload dict from the current run
    agent_id            : e.g. "industry_v1"
    prior_run_id        : UUID string of the prior AgentRunResult
    current_run_id      : UUID string of the current AgentRunResult
    ticker              : company ticker
    current_evidence_ids: evidence IDs used in the current run
    prior_evidence_ids  : evidence IDs used in the prior run (for conflict detection)
    episode_id          : optional ThesisEpisode UUID to link this diff
    """
    from .proposer import propose_updates
    from .models import ConflictFlag

    changes: list[FieldChange] = []
    _diff_values(
        field_path="",
        prior=prior,
        current=current,
        agent_id=agent_id,
        evidence_ids=current_evidence_ids,
        changes=changes,
        list_name=None,
    )

    # Remove UNCHANGED noise from top-level empty path (artifact of recursion start)
    changes = [c for c in changes if c.field_path]

    proposals, conflicts = propose_updates(
        changes=changes,
        prior_payload=prior,
        current_payload=current,
        agent_id=agent_id,
        current_evidence_ids=current_evidence_ids,
        prior_evidence_ids=prior_evidence_ids or [],
    )

    non_unchanged = [c for c in changes if c.change_type != ChangeType.UNCHANGED]
    has_material = any(c.materiality == DiffMateriality.HIGH for c in non_unchanged)

    summary = _build_summary(changes, proposals, conflicts)

    return EpisodeDiff(
        ticker=ticker,
        agent_id=agent_id,
        episode_id=episode_id,
        prior_run_id=prior_run_id,
        current_run_id=current_run_id,
        prior_generated_at=_parse_dt(prior.get("generated_at")),
        current_generated_at=_parse_dt(current.get("generated_at")),
        prior_evidence_ids=prior_evidence_ids or [],
        current_evidence_ids=current_evidence_ids,
        field_changes=changes,
        assumption_proposals=proposals,
        conflict_flags=conflicts,
        has_material_changes=has_material,
        change_summary=summary,
    )


def append_diff_to_log(log: ChangeLog, diff: EpisodeDiff) -> ChangeLog:
    """Append a new EpisodeDiff to an existing ChangeLog. Returns the updated log."""
    log.append_diff(diff)
    return log


def new_change_log(ticker: str, agent_id: str) -> ChangeLog:
    """Create a fresh ChangeLog for a ticker + agent combination."""
    return ChangeLog(ticker=ticker, agent_id=agent_id)


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


def _build_summary(
    changes: list[FieldChange],
    proposals: list,
    conflicts: list,
) -> str:
    non_unchanged = [c for c in changes if c.change_type != ChangeType.UNCHANGED]
    if not non_unchanged:
        return "No analytical changes detected between the two runs."
    high = sum(1 for c in non_unchanged if c.materiality == DiffMateriality.HIGH)
    med = sum(1 for c in non_unchanged if c.materiality == DiffMateriality.MEDIUM)
    parts = [f"{len(non_unchanged)} field(s) changed"]
    if high:
        parts.append(f"{high} HIGH-materiality")
    if med:
        parts.append(f"{med} MEDIUM-materiality")
    if proposals:
        parts.append(f"{len(proposals)} assumption update(s) proposed")
    if conflicts:
        parts.append(f"{len(conflicts)} conflict(s) flagged")
    return ". ".join(parts) + "."
