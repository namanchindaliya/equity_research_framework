"""Synthetic prediction fixtures with known analytic properties.

Scenario A — all correct, high probability
  5 predictions all CORRECT at probability 0.9
  Brier = (0.9-1)^2 * 5 / 5 = 0.01   hit_rate = 1.0

Scenario B — mixed calibration
  probs: [0.9, 0.7, 0.5, 0.3, 0.1]
  outcomes: [CORRECT, CORRECT, CORRECT, INCORRECT, INCORRECT]
  Brier = ((0.1)^2 + (0.3)^2 + (0.5)^2 + (0.3)^2 + (0.1)^2) / 5
        = (0.01 + 0.09 + 0.25 + 0.09 + 0.01) / 5 = 0.45 / 5 = 0.09
  hit_rate = 3/5 = 0.60

Scenario C — all incorrect, low probability (overconfident shorts)
  probs: [0.1, 0.1, 0.1]  outcomes: [CORRECT, CORRECT, CORRECT]
  Brier = (0.9^2) * 3 / 3 = 0.81

Scenario D — partial + expired + withdrawn (excluded)
  1 CORRECT (p=0.7), 1 PARTIALLY_CORRECT (p=0.6), 1 EXPIRED, 1 WITHDRAWN
  Scored: 2  Brier = ((0.7-1)^2 + (0.6-0.5)^2) / 2 = (0.09 + 0.01) / 2 = 0.05

Scenario E — error attribution (industry + timing)
  3 INCORRECT with assumption keys mapped to industry/timing/data_quality
  1 EXPIRED with direction correct (= timing)
"""

from __future__ import annotations

from datetime import date, datetime
from uuid import uuid4

import pytest


def _pred(
    metric: str,
    probability: float,
    status: str | None = None,
    actual: object = None,
    threshold: float = 100.0,
    operator: str = ">=",
    assumption_keys: list[str] | None = None,
    partial: bool = False,
) -> dict:
    pred_id = str(uuid4())
    p: dict = {
        "id": pred_id,
        "description": f"Prediction for {metric}",
        "metric": metric,
        "threshold": threshold,
        "unit": "USD B",
        "operator": operator,
        "horizon": "FY2026",
        "due_date": "2026-12-31",
        "probability": probability,
        "confidence": 0.7,
        "resolution_rule": "Annual report.",
        "supporting_assumptions": assumption_keys or [],
        "created_at": datetime.utcnow().isoformat(),
        "updated_at": datetime.utcnow().isoformat(),
        "resolution": None,
    }
    if status is not None:
        error = None
        if actual is not None and status not in ("EXPIRED", "WITHDRAWN", "INCONCLUSIVE"):
            try:
                error = (float(actual) - float(threshold)) / abs(float(threshold))
            except (TypeError, ValueError):
                pass
        p["resolution"] = {
            "id": str(uuid4()),
            "prediction_id": pred_id,
            "resolved_at": datetime.utcnow().isoformat(),
            "resolved_by": "analyst",
            "resolved_status": status,
            "actual_outcome": actual,
            "error_magnitude": error,
            "notes": f"Resolved as {status}",
            "source": None,
        }
    return p


# ---------------------------------------------------------------------------
# Scenario fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def scenario_a():
    """All correct at 0.9 — Brier = 0.01, hit_rate = 1.0"""
    return [_pred(f"metric_{i}", 0.9, "CORRECT", 105.0) for i in range(5)]


@pytest.fixture
def scenario_b():
    """Mixed — Brier = 0.09, hit_rate = 0.60"""
    data = [
        ("m1", 0.9, "CORRECT", 105.0),
        ("m2", 0.7, "CORRECT", 105.0),
        ("m3", 0.5, "CORRECT", 105.0),
        ("m4", 0.3, "INCORRECT", 90.0),
        ("m5", 0.1, "INCORRECT", 80.0),
    ]
    return [_pred(m, p, s, a) for m, p, s, a in data]


@pytest.fixture
def scenario_c():
    """All correct but low probability — Brier = 0.81"""
    return [_pred(f"metric_{i}", 0.1, "CORRECT", 105.0) for i in range(3)]


@pytest.fixture
def scenario_d():
    """Mixed statuses including excluded — Brier = 0.05, hit_rate = 0.75"""
    return [
        _pred("m1", 0.7, "CORRECT", 105.0),
        _pred("m2", 0.6, "PARTIALLY_CORRECT", 98.0),
        _pred("m3", 0.8, "EXPIRED"),
        _pred("m4", 0.5, "WITHDRAWN"),
    ]


@pytest.fixture
def scenario_e_attribution():
    """Error attribution: industry, timing, data_quality"""
    return [
        _pred("industry_m", 0.7, "INCORRECT", 80.0,
              assumption_keys=["industry_cycle_stage", "market_structure"]),
        _pred("expired_timing", 0.8, "EXPIRED",
              actual=105.0, threshold=100.0, operator=">=",
              assumption_keys=["cycle_stage"]),
        _pred("no_assumption", 0.6, "INCORRECT", 70.0,
              assumption_keys=[]),
    ]


@pytest.fixture
def sample_assumptions():
    return [
        {
            "key": "services_rev_cagr",
            "label": "Services Revenue CAGR",
            "value": 0.13,
            "materiality": "CRITICAL",
            "confidence": 0.72,
            "status": "ACTIVE",
            "owner_agent": "analyst",
        },
        {
            "key": "industry_cycle_stage",
            "label": "Industry Cycle Stage",
            "value": "GROWTH",
            "materiality": "HIGH",
            "confidence": 0.60,
            "status": "ACTIVE",
            "owner_agent": "industry_v1",
        },
    ]
