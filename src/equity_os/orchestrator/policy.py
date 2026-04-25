"""OrchestratorPolicy — loads and exposes orchestrator_policy.yaml.

Uses a bespoke 2-level YAML parser so no external dependency (pyyaml) is needed.
The parser handles: top-level keys, 2-space-indented section keys, float/int/str scalars.
Lists are encoded as dict keys with prefix-numeric naming (e.g. days_30: 0.0).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

_DEFAULT_POLICY_PATH = Path(__file__).parent.parent.parent.parent.parent / "policy" / "orchestrator_policy.yaml"


# ---------------------------------------------------------------------------
# Minimal 2-level YAML parser (stdlib-only)
# ---------------------------------------------------------------------------


def _coerce(val: str) -> Any:
    """Try to parse a scalar string as int, float, or keep as str."""
    val = val.strip().strip('"').strip("'")
    try:
        return int(val)
    except ValueError:
        pass
    try:
        return float(val)
    except ValueError:
        pass
    return val


def _parse_yaml(text: str) -> dict[str, Any]:
    """Parse a simple 2-level YAML file."""
    result: dict[str, Any] = {}
    current_section: str | None = None

    for raw_line in text.splitlines():
        # Strip comments and blank lines
        line = raw_line.split("#")[0].rstrip()
        if not line.strip():
            continue

        indent = len(line) - len(line.lstrip())
        content = line.strip()
        if ":" not in content:
            continue

        key_part, _, val_part = content.partition(":")
        key = key_part.strip()
        val_str = val_part.strip()

        if indent == 0:
            if val_str:
                result[key] = _coerce(val_str)
                current_section = None
            else:
                result[key] = {}
                current_section = key
        elif indent >= 2 and current_section is not None:
            if val_str:
                result[current_section][key] = _coerce(val_str)
            # Sub-sections deeper than 2 levels: ignored (not needed by current policy)

    return result


# ---------------------------------------------------------------------------
# OrchestratorPolicy dataclass
# ---------------------------------------------------------------------------


@dataclass
class OrchestratorPolicy:
    """Typed view over orchestrator_policy.yaml."""

    version: str = "1.0"
    evidence_weighting: dict[str, float] = field(default_factory=lambda: {
        "industry_v1": 0.45,
        "strategy_v1": 0.55,
        "agreement_boost": 0.15,
    })
    confidence_adjustments: dict[str, float] = field(default_factory=lambda: {
        "missing_required_penalty": 0.20,
        "conflict_soft_penalty": 0.08,
        "conflict_hard_penalty": 0.15,
        "low_evidence_penalty": 0.12,
        "disagreement_threshold": 0.30,
    })
    freshness_penalties: dict[str, float] = field(default_factory=lambda: {
        "days_30": 0.00,
        "days_90": 0.10,
        "days_180": 0.20,
        "days_365": 0.35,
        "days_9999": 0.50,
    })
    conflict_resolution: dict[str, str] = field(default_factory=lambda: {
        "regulatory_risk": "industry_v1",
        "competitive_intensity": "industry_v1",
        "market_structure": "industry_v1",
        "industry_cycle": "industry_v1",
        "moat_type": "higher_confidence",
        "management_priorities": "strategy_v1",
        "capital_allocation": "strategy_v1",
        "segment_growth": "strategy_v1",
        "credibility": "strategy_v1",
        "default": "higher_confidence",
    })
    source_reliability_weights: dict[str, float] = field(default_factory=lambda: {
        "filing": 1.00,
        "earnings_transcript": 0.95,
        "management_commentary": 0.90,
        "investor_presentation_notes": 0.85,
        "channel_check_note": 0.70,
        "industry_note": 0.75,
        "news_note": 0.60,
        "default": 0.70,
    })
    synthesis_thresholds: dict[str, float] = field(default_factory=lambda: {
        "driver_min_confidence": 0.30,
        "prediction_min_confidence": 0.35,
        "falsification_min_confidence": 0.25,
        "monitoring_trigger_min_confidence": 0.20,
    })

    # ------------------------------------------------------------------
    # Lookup helpers
    # ------------------------------------------------------------------

    def agent_weight(self, agent_id: str) -> float:
        return float(self.evidence_weighting.get(agent_id, 0.5))

    def agreement_boost(self) -> float:
        return float(self.evidence_weighting.get("agreement_boost", 0.15))

    def penalty(self, key: str) -> float:
        return float(self.confidence_adjustments.get(key, 0.0))

    def freshness_penalty(self, days_old: float) -> float:
        """Return the freshness penalty for evidence that is `days_old` days old."""
        thresholds = []
        for k, v in self.freshness_penalties.items():
            m = re.match(r"days_(\d+)", k)
            if m:
                thresholds.append((int(m.group(1)), float(v)))
        thresholds.sort()
        penalty = 0.0
        for days_threshold, pen in thresholds:
            if days_old >= days_threshold:
                penalty = pen
        return penalty

    def conflict_winner(self, dimension: str) -> str:
        return self.conflict_resolution.get(dimension, self.conflict_resolution.get("default", "higher_confidence"))

    def source_reliability(self, logical_type: str) -> float:
        return float(self.source_reliability_weights.get(logical_type, self.source_reliability_weights.get("default", 0.70)))

    def threshold(self, key: str) -> float:
        return float(self.synthesis_thresholds.get(key, 0.30))

    @classmethod
    def load(cls, path: Path | None = None) -> OrchestratorPolicy:
        """Load policy from YAML file. Falls back to defaults if file not found."""
        policy_path = path or _DEFAULT_POLICY_PATH
        if not policy_path.exists():
            return cls()
        raw = _parse_yaml(policy_path.read_text(encoding="utf-8"))

        def _dict(key: str) -> dict:
            val = raw.get(key, {})
            return val if isinstance(val, dict) else {}

        return cls(
            version=str(raw.get("version", "1.0")),
            evidence_weighting=_dict("evidence_weighting"),
            confidence_adjustments=_dict("confidence_adjustments"),
            freshness_penalties=_dict("freshness_penalties"),
            conflict_resolution=_dict("conflict_resolution"),
            source_reliability_weights=_dict("source_reliability_weights"),
            synthesis_thresholds=_dict("synthesis_thresholds"),
        )
