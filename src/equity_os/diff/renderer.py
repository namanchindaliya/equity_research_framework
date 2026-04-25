"""Markdown renderer for ChangeLog and EpisodeDiff.

Produces a memo titled "What changed, why it changed, and what it means."
Each section answers one of the three parts:
  1. What changed — FieldChange table, organized by materiality
  2. Why it changed — rationale for each AssumptionProposal
  3. What it means — thesis and valuation implications

The renderer is pure: no I/O, no side effects.
"""

from __future__ import annotations

from datetime import datetime

from .models import (
    AssumptionProposal,
    ChangeLog,
    ChangeType,
    ConflictFlag,
    DiffMateriality,
    EpisodeDiff,
    FieldChange,
)

_EMOJI_BY_TYPE = {
    ChangeType.ADDED:     "➕",
    ChangeType.REMOVED:   "➖",
    ChangeType.MODIFIED:  "✏️",
    ChangeType.UNCHANGED: "·",
}
_EMOJI_BY_MAT = {
    DiffMateriality.HIGH:   "🔴",
    DiffMateriality.MEDIUM: "🟡",
    DiffMateriality.LOW:    "⚪",
}


def _now_utc() -> str:
    return datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")


def _pct(v: float) -> str:
    return f"{v * 100:.0f}%"


def _short(v: object, max_len: int = 60) -> str:
    s = str(v) if v is not None else "—"
    return s[:max_len] + "…" if len(s) > max_len else s


# ---------------------------------------------------------------------------
# Episode diff memo
# ---------------------------------------------------------------------------


def render_episode_diff(diff: EpisodeDiff) -> str:
    """Render one EpisodeDiff as a markdown memo."""
    lines: list[str] = []

    lines += [
        f"# What changed, why it changed, and what it means",
        f"",
        f"**Ticker:** {diff.ticker}  "
        f"**Agent:** `{diff.agent_id}`  "
        f"**Generated:** {_now_utc()}",
        f"",
        f"> {diff.change_summary}",
        f"",
    ]

    if diff.has_material_changes:
        lines += [
            "⚠️ **Material changes detected.** Review assumption proposals before updating the thesis.",
            "",
        ]

    # ------------------------------------------------------------------
    # Section 1: What changed
    # ------------------------------------------------------------------
    non_unchanged = [c for c in diff.field_changes if c.change_type != ChangeType.UNCHANGED]
    lines += ["---", "", "## 1. What Changed", ""]

    if not non_unchanged:
        lines += ["No analytical fields changed between these two runs.", ""]
    else:
        high = [c for c in non_unchanged if c.materiality == DiffMateriality.HIGH]
        medium = [c for c in non_unchanged if c.materiality == DiffMateriality.MEDIUM]
        low = [c for c in non_unchanged if c.materiality == DiffMateriality.LOW]

        for tier_label, tier_items in [
            ("HIGH-materiality changes", high),
            ("MEDIUM-materiality changes", medium),
            ("LOW-materiality changes", low),
        ]:
            if not tier_items:
                continue
            lines += [f"### {tier_label} ({len(tier_items)})", ""]
            lines += [
                "| # | Field | Change | Prior | Current | Magnitude |",
                "| --- | --- | --- | --- | --- | --- |",
            ]
            for i, c in enumerate(tier_items, 1):
                emoji = _EMOJI_BY_TYPE[c.change_type]
                mag = f"{c.change_magnitude:.1%}" if c.change_magnitude is not None else "—"
                lines.append(
                    f"| {i} | `{c.field_path}` | {emoji} {c.change_type.value} "
                    f"| {_short(c.prior_value)} | {_short(c.current_value)} | {mag} |"
                )
            lines.append("")

    # ------------------------------------------------------------------
    # Section 2: Why it changed — assumption proposals
    # ------------------------------------------------------------------
    lines += ["---", "", "## 2. Why It Changed — Assumption Proposals", ""]

    if not diff.assumption_proposals:
        lines += ["No assumption updates proposed for this diff.", ""]
    else:
        for i, prop in enumerate(diff.assumption_proposals, 1):
            mat_emoji = _EMOJI_BY_MAT[prop.materiality]
            lines += [
                f"### Proposal {i}: {prop.assumption_label}",
                f"",
                f"{mat_emoji} **Materiality:** {prop.materiality.value}  "
                f"**Confidence:** {_pct(prop.confidence)}  "
                f"**Change:** {prop.change_type.value}  "
                f"**Agent:** `{prop.owner_agent}`",
                f"",
                f"| | Value |",
                f"| --- | --- |",
                f"| Prior | `{_short(prop.prior_value)}` |",
                f"| Proposed | `{_short(prop.proposed_value)}` |",
                f"",
                f"**Rationale:**  ",
                f"{prop.rationale}",
                f"",
                f"**Triggered by:** {', '.join(f'`{p}`' for p in prop.triggered_by_field_paths)}",
                f"",
                f"**Downstream model fields:**  ",
                f"{', '.join(f'`{f}`' for f in prop.impacted_model_fields) or '—'}",
                f"",
            ]

    # ------------------------------------------------------------------
    # Section 3: What it means
    # ------------------------------------------------------------------
    lines += ["---", "", "## 3. What It Means", ""]

    if not diff.assumption_proposals:
        lines += ["No material implications to report.", ""]
    else:
        has_thesis = any(p.implication_for_thesis for p in diff.assumption_proposals)
        has_val = any(p.implication_for_valuation for p in diff.assumption_proposals)

        if has_thesis:
            lines += ["### Thesis Implications", ""]
            for prop in diff.assumption_proposals:
                if prop.implication_for_thesis:
                    mat_emoji = _EMOJI_BY_MAT[prop.materiality]
                    lines.append(
                        f"- {mat_emoji} **{prop.assumption_label}:** {prop.implication_for_thesis}"
                    )
            lines.append("")

        if has_val:
            lines += ["### Valuation Implications", ""]
            for prop in diff.assumption_proposals:
                if prop.implication_for_valuation:
                    mat_emoji = _EMOJI_BY_MAT[prop.materiality]
                    lines.append(
                        f"- {mat_emoji} **{prop.assumption_label}:** {prop.implication_for_valuation}"
                    )
            lines.append("")

    # ------------------------------------------------------------------
    # Conflicts
    # ------------------------------------------------------------------
    if diff.conflict_flags:
        lines += ["---", "", "## ⚠️ Conflicts and Inconsistencies", ""]
        for cf in diff.conflict_flags:
            lines += [
                f"- **{cf.conflict_type}** on `{cf.field_path}`  ",
                f"  {cf.description}  ",
                f"  Resolution: {cf.resolution or '_unresolved_'}",
                "",
            ]

    lines += [
        "---",
        f"_Generated by equity-os diff engine · {_now_utc()}_",
    ]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Change log memo (covers multiple diffs)
# ---------------------------------------------------------------------------


def render_change_log(log: ChangeLog) -> str:
    """Render a full ChangeLog (all EpisodeDiffs) as a summary memo."""
    lines: list[str] = []
    lines += [
        f"# Change Log — {log.ticker} / `{log.agent_id}`",
        f"",
        f"**Total diffs:** {len(log.diffs)}  "
        f"**Total changes:** {log.total_changes}  "
        f"**Material:** {log.material_changes}  "
        f"**Proposals:** {log.proposals_count}  "
        f"**Updated:** {log.updated_at.strftime('%Y-%m-%d')}",
        f"",
    ]

    for i, diff in enumerate(log.diffs, 1):
        non_unchanged = [c for c in diff.field_changes if c.change_type != ChangeType.UNCHANGED]
        high_count = sum(1 for c in non_unchanged if c.materiality == DiffMateriality.HIGH)
        badge = "🔴 MATERIAL" if diff.has_material_changes else ("✏️ MINOR" if non_unchanged else "· NO CHANGE")
        lines += [
            f"## Diff #{i} — {badge}",
            f"",
            f"**Runs:** `{diff.prior_run_id[:8]}` → `{diff.current_run_id[:8]}`  "
            f"**Changes:** {len(non_unchanged)} ({high_count} HIGH)  "
            f"**Computed:** {diff.computed_at.strftime('%Y-%m-%d')}",
            f"",
            f"> {diff.change_summary}",
            f"",
        ]
        if diff.assumption_proposals:
            lines += ["**Proposals:**"]
            for p in diff.assumption_proposals:
                lines.append(f"- {_EMOJI_BY_MAT[p.materiality]} `{p.assumption_key}`: {p.assumption_label} — {p.change_type.value}")
            lines.append("")
        if diff.conflict_flags:
            lines += ["**Conflicts:**"]
            for cf in diff.conflict_flags:
                lines.append(f"- ⚠️ {cf.conflict_type} on `{cf.field_path}`")
            lines.append("")

    lines += [
        "---",
        f"_Generated by equity-os diff engine · {_now_utc()}_",
    ]
    return "\n".join(lines)
