"""Snapshot test for generated markdown.

On first run (or when EQOS_UPDATE_SNAPSHOTS=1): writes the golden file and passes.
On subsequent runs: diffs the rendered output against the golden.

The snapshot uses a fixed CompanyDossier fixture so the rendered markdown
is deterministic (no timestamps, no random IDs).
"""

from __future__ import annotations

import os
import re
from datetime import datetime
from pathlib import Path
from uuid import UUID

import pytest

from equity_os.md_render import dossier_md, episode_md
from equity_os.schemas import (
    AssumptionRecord,
    CompanyDossier,
    EpisodeStatus,
    MaterialityLevel,
    PredictionRecord,
    Rating,
    ResolutionRecord,
    ResolutionStatus,
    ThesisEpisode,
)

SNAPSHOTS_DIR = Path(__file__).parent / "snapshots"
UPDATE = os.environ.get("EQOS_UPDATE_SNAPSHOTS", "0") == "1"

# Fixed UUIDs and timestamps for determinism
_DOSSIER_ID = UUID("a0000000-0000-0000-0000-000000000001")
_EPISODE_ID = UUID("e0000000-0000-0000-0000-000000000001")
_ASSUMPTION_ID = UUID("a1000000-0000-0000-0000-000000000001")
_PREDICTION_ID = UUID("d0000000-0000-0000-0000-000000000001")
_RESOLUTION_ID = UUID("f0000000-0000-0000-0000-000000000001")
_TS = datetime(2026, 1, 31, 9, 0, 0)
_DUE = _TS.date().replace(month=11, day=1)


def _make_assumption() -> AssumptionRecord:
    return AssumptionRecord(
        id=_ASSUMPTION_ID,
        key="services_rev_cagr",
        label="Services Revenue 3yr CAGR",
        value=0.13,
        unit="%",
        owner_agent="financial_analyst_v1",
        rationale="Install base growing 8% pa, ARPU +5% pa → ~13% blended.",
        confidence=0.72,
        materiality=MaterialityLevel.CRITICAL,
        version=1,
        history=[],
        created_at=_TS,
        updated_at=_TS,
    )


def _make_prediction() -> PredictionRecord:
    return PredictionRecord(
        id=_PREDICTION_ID,
        description="Apple services revenue exceeds $110B in FY2026",
        metric="aapl_services_revenue",
        threshold=110.0,
        unit="USD B",
        horizon="FY2026 full-year",
        due_date=_DUE,
        probability=0.65,
        confidence=0.70,
        resolution_rule="Apple FY2026 annual report total Services revenue.",
        created_at=_TS,
        updated_at=_TS,
    )


def _make_episode() -> ThesisEpisode:
    return ThesisEpisode(
        id=_EPISODE_ID,
        ticker="AAPL",
        title="FY2026 Services Flywheel Initiation",
        version=1,
        thesis_statement=(
            "Apple's services segment is entering a durable high-margin growth phase "
            "driven by install-base monetisation, which the market is systematically undervaluing."
        ),
        rating=Rating.BUY,
        price_target=230.0,
        currency="USD",
        status=EpisodeStatus.OPEN,
        assumptions=[_make_assumption()],
        predictions=[_make_prediction()],
        created_at=_TS,
        updated_at=_TS,
    )


def _make_dossier() -> CompanyDossier:
    return CompanyDossier(
        id=_DOSSIER_ID,
        ticker="AAPL",
        name="Apple Inc.",
        sector="Technology",
        industry="Consumer Electronics",
        exchange="NASDAQ",
        country="US",
        description="Designs, manufactures, and markets consumer electronics worldwide.",
        current_rating=Rating.BUY,
        current_price_target=230.0,
        currency="USD",
        episodes=[_make_episode()],
        tags=["mag7", "consumer-tech"],
        version=1,
        created_at=_TS,
        updated_at=_TS,
    )


def _strip_generated_timestamp(md: str) -> str:
    """Remove the trailing 'Generated ...' line so snapshots don't drift by clock."""
    return re.sub(r"_Generated \d{4}-\d{2}-\d{2} \d{2}:\d{2} UTC_", "_Generated <TIMESTAMP>_", md)


def _snapshot_path(name: str) -> Path:
    return SNAPSHOTS_DIR / f"{name}.md"


def _assert_snapshot(name: str, rendered: str) -> None:
    rendered = _strip_generated_timestamp(rendered)
    path = _snapshot_path(name)
    if UPDATE or not path.exists():
        SNAPSHOTS_DIR.mkdir(exist_ok=True)
        path.write_text(rendered, encoding="utf-8")
        if UPDATE:
            pytest.skip(f"Snapshot updated: {path}")
        return  # first-run write → pass
    golden = path.read_text(encoding="utf-8")
    assert rendered == golden, (
        f"Snapshot mismatch for {name!r}.\n"
        f"Run with EQOS_UPDATE_SNAPSHOTS=1 to refresh the golden file.\n"
        f"Diff (first differing line):\n"
        + _first_diff(golden, rendered)
    )


def _first_diff(a: str, b: str) -> str:
    for i, (la, lb) in enumerate(zip(a.splitlines(), b.splitlines()), 1):
        if la != lb:
            return f"  line {i}:\n    golden:   {la!r}\n    rendered: {lb!r}"
    return "(different number of lines)"


# ===========================================================================
# Snapshot tests
# ===========================================================================


def test_episode_md_snapshot():
    """episode_md() output must match golden snapshot."""
    ep = _make_episode()
    rendered = episode_md(ep)
    _assert_snapshot("episode_fy2026_initiation", rendered)


def test_dossier_md_snapshot():
    """dossier_md() output must match golden snapshot."""
    dossier = _make_dossier()
    rendered = dossier_md(dossier)
    _assert_snapshot("dossier_aapl", rendered)


# ===========================================================================
# Structural correctness (non-snapshot)
# ===========================================================================


def test_episode_md_contains_key_sections():
    ep = _make_episode()
    md = episode_md(ep)
    assert "## Thesis" in md
    assert "## Assumptions" in md
    assert "## Predictions" in md
    assert "services_rev_cagr" in md
    assert "aapl_services_revenue" in md


def test_dossier_md_contains_episode_table():
    dossier = _make_dossier()
    md = dossier_md(dossier)
    assert "FY2026 Services Flywheel Initiation" in md
    assert "1 active" in md
    assert "1 pending" in md


def test_episode_md_resolved_prediction_shows_status():
    ep = _make_episode()
    pred = ep.predictions[0]
    resolved = pred.resolve(
        resolved_status=ResolutionStatus.CORRECT,
        actual_outcome=112.5,
        notes="Beat by 2.5B",
        resolved_by="analyst",
    )
    ep = ep.model_copy(update={"predictions": [resolved]})
    md = episode_md(ep)
    assert "CORRECT" in md


def test_dossier_md_with_no_episodes():
    d = CompanyDossier(ticker="MSFT", name="Microsoft", created_at=_TS, updated_at=_TS)
    md = dossier_md(d)
    assert "No episodes yet" in md
