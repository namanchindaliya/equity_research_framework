#!/usr/bin/env python3
"""End-to-end demo: Microsoft (MSFT) equity research coverage.

Demonstrates:
  1. Company initialisation
  2. Evidence ingestion (4 local documents, no external APIs)
  3. IndustryAgent run
  4. CompanyStrategyAgent run
  5. Orchestrator synthesis → decision + memo
  6. Episode 1: 3 predictions logged, 1 assumption tracked
  7. Episode 1: Resolve 1 prediction (CORRECT)
  8. Episode 2: Changed assumption (Azure growth revision) → diff generated
  9. Postmortem for Episode 1

Proves:
  ✓ Prior state is preserved (snapshots in companies/MSFT/)
  ✓ Updates create auditable diffs (diff/ directory)
  ✓ Orchestrator can be judged later (orchestrator/ directory)
  ✓ No external APIs required

All artifacts stored under demo/.
"""

from __future__ import annotations

import json
import shutil
import sys
from datetime import datetime
from pathlib import Path

REPO = Path(__file__).parent.parent
sys.path.insert(0, str(REPO / "src"))

DEMO = REPO / "demo"
COMPANIES = DEMO / "companies"
INPUTS = DEMO / "inputs"
AGENTS_DIR = DEMO / "agents"
ORCH_EP1 = DEMO / "orchestrator" / "ep1"
ORCH_EP2 = DEMO / "orchestrator" / "ep2"
DIFF_DIR = DEMO / "diff"
POSTMORTEM_DIR = DEMO / "postmortem"
TICKER = "MSFT"


def _banner(msg: str) -> None:
    bar = "=" * 60
    print(f"\n{bar}")
    print(f"  {msg}")
    print(bar)


def _step(msg: str) -> None:
    print(f"\n  ▶ {msg}")


def _ok(msg: str) -> None:
    print(f"    ✓ {msg}")


def _write(path: Path, data: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(data, encoding="utf-8")


def _write_json(path: Path, obj) -> None:
    _write(path, json.dumps(obj, indent=2, default=str))


# ===========================================================================
# Step 1: Initialise
# ===========================================================================

def step_init() -> None:
    _banner("STEP 1 — Initialise company")
    from equity_os.fs.layout import CompanyLayout
    from equity_os.schemas import CompanyDossier, Rating

    layout = CompanyLayout(COMPANIES, TICKER)
    if layout.exists():
        _step("Company already initialised — resetting for clean demo")
        shutil.rmtree(layout.root)

    layout.init_dirs()
    dossier = CompanyDossier(
        ticker=TICKER,
        name="Microsoft Corporation",
        sector="Technology",
        industry="Cloud Infrastructure / AI Software",
        exchange="NASDAQ",
        country="US",
        description=(
            "Microsoft develops and sells cloud services (Azure), productivity "
            "software (Microsoft 365, Office), and gaming (Xbox). AI is the "
            "primary growth vector through the OpenAI partnership and Copilot."
        ),
        tags=["mega-cap", "cloud", "ai-infrastructure", "enterprise-software"],
    )
    from equity_os.fs.io import write_json, write_md
    from equity_os.md_render import dossier_md
    write_json(layout.dossier_json, dossier)
    write_md(layout.dossier_md, dossier_md(dossier))
    _ok(f"Company created at {layout.root}")
    _ok(f"Dossier: {layout.dossier_json}")


# ===========================================================================
# Step 2: Ingest evidence
# ===========================================================================

def step_ingest() -> tuple[list, Path]:
    _banner("STEP 2 — Ingest local evidence documents")
    from equity_os.ingest.pipeline import ingest_dir

    ticker_inputs = INPUTS / TICKER
    ingested, skipped, failed = ingest_dir(ticker_inputs, TICKER, COMPANIES)
    if failed:
        for f in failed:
            print(f"  ERROR: {f}")
        sys.exit(1)

    _ok(f"Ingested {len(ingested)} documents  (skipped: {len(skipped)}, failed: {len(failed)})")
    for ev in ingested:
        _ok(f"  [{ev.logical_type}] {ev.title}  ({len(ev.chunks)} chunks)")

    ev_dir = COMPANIES / TICKER / "evidence"
    _ok(f"Evidence stored at {ev_dir}")
    return ingested, ev_dir


# ===========================================================================
# Step 3 & 4: Run agents
# ===========================================================================

def step_run_agents(evidence: list) -> tuple[dict, dict]:
    _banner("STEP 3 & 4 — Run IndustryAgent and CompanyStrategyAgent")
    from equity_os.agents.industry import IndustryAgent
    from equity_os.agents.strategy import CompanyStrategyAgent

    _step("IndustryAgent …")
    ind_result = IndustryAgent().run(TICKER, evidence)
    AGENTS_DIR.mkdir(parents=True, exist_ok=True)
    _write_json(AGENTS_DIR / "industry_analysis.json", ind_result.payload)
    _write(AGENTS_DIR / "industry_analysis.md", ind_result.memo)
    _ok(f"Confidence: {ind_result.payload['overall_confidence']:.0%}")
    _ok(f"Market structure: {ind_result.payload['market_structure']}")
    _ok(f"Cycle stage: {ind_result.payload['cycle_stage']}")
    _ok(f"Saved → {AGENTS_DIR / 'industry_analysis.json'}")

    _step("CompanyStrategyAgent …")
    str_result = CompanyStrategyAgent().run(TICKER, evidence)
    _write_json(AGENTS_DIR / "strategy_analysis.json", str_result.payload)
    _write(AGENTS_DIR / "strategy_analysis.md", str_result.memo)
    _ok(f"Confidence: {str_result.payload['overall_confidence']:.0%}")
    top_seg = (str_result.payload.get("segment_priorities") or [{}])[0].get("segment_name", "—")
    _ok(f"Top segment: {top_seg}")
    _ok(f"Saved → {AGENTS_DIR / 'strategy_analysis.json'}")

    return ind_result.payload, str_result.payload


# ===========================================================================
# Step 5: Orchestrator — Episode 1
# ===========================================================================

def step_orchestrate_ep1(industry: dict, strategy: dict) -> dict:
    _banner("STEP 5 — Orchestrator synthesis (Episode 1)")
    from equity_os.orchestrator.orchestrator import Orchestrator
    from equity_os.orchestrator.policy import OrchestratorPolicy
    from equity_os.orchestrator.renderer import render_decision

    policy = OrchestratorPolicy.load()
    orch = Orchestrator(policy=policy)

    assumptions = [
        {
            "key": "azure_revenue_growth",
            "label": "Azure Revenue Growth (YoY)",
            "value": 0.35,
            "unit": "%",
            "owner_agent": "analyst",
            "rationale": "FY2025 exit rate 35%, Q1 FY2026 reaccelerated to 38%",
            "confidence": 0.80,
            "materiality": "CRITICAL",
            "status": "ACTIVE",
            "version": 1,
            "history": [],
        },
        {
            "key": "ai_revenue_run_rate",
            "label": "AI Annualized Revenue Run Rate (USD B)",
            "value": 16.0,
            "unit": "USD B",
            "owner_agent": "analyst",
            "rationale": "Management guided $16B annualized run rate in Q1 FY2026 call",
            "confidence": 0.85,
            "materiality": "HIGH",
            "status": "ACTIVE",
            "version": 1,
            "history": [],
        },
        {
            "key": "capex_fy2026",
            "label": "FY2026 Capital Expenditure (USD B)",
            "value": 62.0,
            "unit": "USD B",
            "owner_agent": "analyst",
            "rationale": "Midpoint of $60-65B management guidance",
            "confidence": 0.90,
            "materiality": "HIGH",
            "status": "ACTIVE",
            "version": 1,
            "history": [],
        },
    ]

    decision = orch.run(
        ticker=TICKER,
        industry=industry,
        strategy=strategy,
        assumptions=assumptions,
    )

    ORCH_EP1.mkdir(parents=True, exist_ok=True)
    _write_json(ORCH_EP1 / "decision.json", decision.model_dump(mode="json"))
    _write(ORCH_EP1 / "decision.md", render_decision(decision))

    _ok(f"Thesis: {decision.inferences.thesis_statement[:120]}…")
    _ok(f"Rating stance: {decision.decisions.rating_stance.upper()}")
    _ok(f"Overall confidence: {decision.confidence_summary.overall:.0%}")
    _ok(f"Conflicts detected: {len(decision.inferences.agent_conflicts)}")
    _ok(f"Predictions in decision: {len(decision.decisions.predictions)}")
    _ok(f"Saved → {ORCH_EP1 / 'decision.json'}")

    return decision.model_dump(mode="json")


# ===========================================================================
# Step 6: Episode 1 — create episode, log assumptions and predictions
# ===========================================================================

def step_episode1(ind_payload: dict, str_payload: dict) -> str:
    _banner("STEP 6 — Episode 1: thesis, assumptions, predictions")
    from equity_os.fs.io import write_json, write_md
    from equity_os.fs.layout import CompanyLayout
    from equity_os.fs.naming import unique_episode_dir_name
    from equity_os.fs.readers import load_episode
    from equity_os.md_render import episode_md
    from equity_os.schemas import (
        AssumptionRecord, MaterialityLevel, PredictionRecord,
        Rating, ThesisEpisode,
    )
    from equity_os.schemas.enums import ComparisonOperator
    from datetime import date

    layout = CompanyLayout(COMPANIES, TICKER)

    slug = unique_episode_dir_name(
        "FY2026 Azure AI Initiation", layout.episodes_dir,
        created_at=date(2025, 11, 1),
    )
    layout.episode_dir(slug).mkdir(parents=True, exist_ok=True)

    # Assumptions
    a1 = AssumptionRecord(
        key="azure_revenue_growth",
        label="Azure Revenue Growth (YoY %)",
        value=0.35,
        unit="%",
        owner_agent="industry_v1",
        rationale="FY2025 exit rate 35%; Q1 FY2026 reaccelerated to 38%. Modelling conservatively at 35%.",
        confidence=0.80,
        materiality=MaterialityLevel.CRITICAL,
    )
    a2 = AssumptionRecord(
        key="ai_run_rate_usd_b",
        label="AI Revenue Annualized Run Rate (USD B)",
        value=16.0,
        unit="USD B",
        owner_agent="strategy_v1",
        rationale="Management disclosed $16B annualized run rate in Q1 FY2026 call.",
        confidence=0.85,
        materiality=MaterialityLevel.HIGH,
    )

    # Predictions (3 required by spec)
    p1 = PredictionRecord(
        description="Azure revenue grows at ≥32% YoY in Q2 FY2026 (Jan 2026 reporting)",
        metric="msft_azure_revenue_yoy_pct",
        threshold=0.32,
        unit="%",
        operator=ComparisonOperator.GTE,
        horizon="Q2 FY2026 earnings (Jan 2026)",
        due_date=date(2026, 2, 15),
        probability=0.75,
        confidence=0.80,
        resolution_rule="Azure revenue growth as reported in Q2 FY2026 earnings release.",
        supporting_assumptions=[a1.id],
    )
    p2 = PredictionRecord(
        description="AI annualized revenue run rate exceeds $20B by end of FY2026",
        metric="msft_ai_revenue_run_rate_usd_b",
        threshold=20.0,
        unit="USD B",
        operator=ComparisonOperator.GTE,
        horizon="FY2026 year-end (June 2026)",
        due_date=date(2026, 8, 1),
        probability=0.60,
        confidence=0.65,
        resolution_rule="AI run rate as disclosed in Q4 FY2026 earnings or press release.",
        supporting_assumptions=[a2.id],
    )
    p3 = PredictionRecord(
        description="FY2026 full-year operating margin ≥43%",
        metric="msft_operating_margin_fy2026",
        threshold=0.43,
        unit="%",
        operator=ComparisonOperator.GTE,
        horizon="FY2026 full-year",
        due_date=date(2026, 8, 15),
        probability=0.70,
        confidence=0.75,
        resolution_rule="Operating margin as reported in FY2026 annual results.",
        supporting_assumptions=[],
    )

    episode = ThesisEpisode(
        ticker=TICKER,
        title="FY2026 Azure AI Initiation",
        version=1,
        thesis_statement=(
            "Microsoft is at the epicentre of the enterprise AI adoption cycle. Azure's "
            "reaccelerating growth (35→38% YoY) driven by AI workloads, combined with a $16B "
            "AI run rate growing rapidly, positions MSFT as the primary beneficiary of enterprise "
            "AI spend. The services moat (Microsoft 365 + Azure + GitHub Copilot) creates a "
            "land-and-expand flywheel that is structurally underappreciated."
        ),
        rating=Rating.BUY,
        assumptions=[a1, a2],
        predictions=[p1, p2, p3],
    )

    write_json(layout.episode_json(slug), episode)
    write_md(layout.episode_md(slug), episode_md(episode))

    # Save prediction artifacts
    for pred in [p1, p2, p3]:
        pred_path = layout.prediction_json(slug, pred.metric, pred.id)
        write_json(pred_path, pred)

    _ok(f"Episode slug: {slug}")
    _ok(f"Thesis: {episode.thesis_statement[:100]}…")
    _ok(f"Assumptions: {len(episode.assumptions)}")
    _ok(f"Predictions: {len(episode.predictions)}")
    for p in episode.predictions:
        _ok(f"  [{p.metric}] p={p.probability:.0%}  threshold={p.threshold}{p.unit or ''}  due={p.due_date}")
    _ok(f"Saved → {layout.episode_json(slug)}")
    return slug


# ===========================================================================
# Step 7: Resolve prediction 1
# ===========================================================================

def step_resolve(ep1_slug: str) -> None:
    _banner("STEP 7 — Resolve prediction 1 (Azure Q2 FY2026 growth)")
    from equity_os.fs.io import write_json, write_md
    from equity_os.fs.layout import CompanyLayout
    from equity_os.fs.readers import load_episode, find_prediction_by_metric
    from equity_os.md_render import episode_md
    from equity_os.schemas.enums import ResolutionStatus

    layout = CompanyLayout(COMPANIES, TICKER)
    ep = load_episode(layout, ep1_slug)

    pred = find_prediction_by_metric(ep, "msft_azure_revenue_yoy_pct")
    # Simulate: Azure Q2 FY2026 came in at 35% — above the 32% threshold → CORRECT
    actual_growth = 0.35
    resolved = pred.resolve(
        resolved_status=ResolutionStatus.CORRECT,
        actual_outcome=actual_growth,
        notes=(
            "Azure reported 35% YoY growth in Q2 FY2026, above the 32% threshold. "
            "AI workloads drove reacceleration. Source: Microsoft Q2 FY2026 earnings release."
        ),
        resolved_by="analyst",
    )
    ep.predictions = [resolved if p.metric == "msft_azure_revenue_yoy_pct" else p for p in ep.predictions]
    ep = ep.model_copy(update={"updated_at": datetime.utcnow()})

    write_json(layout.episode_json(ep1_slug), ep)
    write_md(layout.episode_md(ep1_slug), episode_md(ep))
    write_json(layout.resolution_json(ep1_slug, "msft_azure_revenue_yoy_pct", pred.id), resolved.resolution)

    _ok(f"Prediction resolved: msft_azure_revenue_yoy_pct")
    _ok(f"Status: CORRECT  actual={actual_growth:.0%}  threshold={pred.threshold:.0%}")
    err = resolved.resolution.error_magnitude
    _ok(f"Error magnitude: {err:+.1%}" if err is not None else "Error magnitude: —")
    _ok(f"Episode updated: {layout.episode_json(ep1_slug)}")
    _ok(f"Resolution artifact: {layout.resolution_json(ep1_slug, 'msft_azure_revenue_yoy_pct', pred.id)}")


# ===========================================================================
# Step 8: Episode 2 — changed assumption, new episode, diff
# ===========================================================================

def step_episode2_and_diff(
    ind_payload: dict, str_payload: dict, ep1_slug: str
) -> str:
    _banner("STEP 8 — Episode 2: revised assumption + diff")
    from equity_os.agents.industry import IndustryAgent
    from equity_os.agents.strategy import CompanyStrategyAgent
    from equity_os.diff.engine import diff_payloads, new_change_log
    from equity_os.diff.renderer import render_episode_diff, render_change_log
    from equity_os.fs.io import write_json, write_md
    from equity_os.fs.layout import CompanyLayout
    from equity_os.fs.naming import unique_episode_dir_name
    from equity_os.fs.readers import load_episode
    from equity_os.md_render import episode_md
    from equity_os.orchestrator.orchestrator import Orchestrator
    from equity_os.orchestrator.policy import OrchestratorPolicy
    from equity_os.orchestrator.renderer import render_decision
    from equity_os.schemas import (
        AssumptionChange, AssumptionRecord, MaterialityLevel,
        PredictionRecord, Rating, ThesisEpisode,
    )
    from equity_os.schemas.enums import ComparisonOperator
    from datetime import date
    import copy

    layout = CompanyLayout(COMPANIES, TICKER)

    # -- Revised assumptions (azure growth revised UP after Q2 beat) --
    a1_revised = AssumptionRecord(
        key="azure_revenue_growth",
        label="Azure Revenue Growth (YoY %)",
        value=0.38,   # revised up from 0.35 after Q2 beat
        unit="%",
        owner_agent="industry_v1",
        rationale=(
            "Q2 FY2026 came in at 35%, above the 32% threshold. "
            "Q1 was 38%. Raising assumption to 38% to reflect sustained AI-driven reacceleration."
        ),
        confidence=0.82,
        materiality=MaterialityLevel.CRITICAL,
        version=2,
        history=[
            AssumptionChange(
                assumption_id=AssumptionRecord(
                    key="azure_revenue_growth", label="", value=0.35,
                    owner_agent="", rationale=""
                ).id,
                version=2,
                changed_by="analyst",
                previous_value=0.35,
                new_value=0.38,
                previous_confidence=0.80,
                new_confidence=0.82,
                reason="Q2 FY2026 print at 35% confirmed upward trend. Raising to 38%.",
            )
        ],
    )
    a2 = AssumptionRecord(
        key="ai_run_rate_usd_b",
        label="AI Revenue Annualized Run Rate (USD B)",
        value=20.0,   # management raised guidance after Q2
        unit="USD B",
        owner_agent="strategy_v1",
        rationale="Updated to $20B based on Q2 FY2026 call commentary.",
        confidence=0.80,
        materiality=MaterialityLevel.HIGH,
    )

    slug2 = unique_episode_dir_name(
        "FY2026 Azure AI — Q2 Follow-Up", layout.episodes_dir,
        created_at=date(2026, 2, 1),
    )
    layout.episode_dir(slug2).mkdir(parents=True, exist_ok=True)

    p1 = PredictionRecord(
        description="Azure revenue grows at ≥35% YoY in Q3 FY2026 (Apr 2026 reporting)",
        metric="msft_azure_q3_fy2026_yoy",
        threshold=0.35,
        unit="%",
        operator=ComparisonOperator.GTE,
        horizon="Q3 FY2026 earnings (Apr 2026)",
        due_date=date(2026, 5, 15),
        probability=0.65,
        confidence=0.72,
        resolution_rule="Azure revenue growth as reported in Q3 FY2026 earnings.",
        supporting_assumptions=[a1_revised.id],
    )
    p2 = PredictionRecord(
        description="AI run rate exceeds $22B by Q4 FY2026",
        metric="msft_ai_run_rate_q4_fy2026",
        threshold=22.0,
        unit="USD B",
        operator=ComparisonOperator.GTE,
        horizon="Q4 FY2026 (Jun 2026)",
        due_date=date(2026, 8, 15),
        probability=0.55,
        confidence=0.65,
        resolution_rule="AI run rate as disclosed in Q4 FY2026 results.",
        supporting_assumptions=[a2.id],
    )

    episode2 = ThesisEpisode(
        ticker=TICKER,
        title="FY2026 Azure AI — Q2 Follow-Up",
        version=2,
        thesis_statement=(
            "Q2 FY2026 results validated the Azure AI thesis. Azure grew 35% — above our 32% "
            "threshold. AI run rate tracking toward $20B. Raising our Azure growth assumption "
            "to 38% and maintaining a constructive stance with tighter falsification conditions."
        ),
        rating=Rating.BUY,
        assumptions=[a1_revised, a2],
        predictions=[p1, p2],
    )

    write_json(layout.episode_json(slug2), episode2)
    write_md(layout.episode_md(slug2), episode_md(episode2))
    for pred in [p1, p2]:
        write_json(layout.prediction_json(slug2, pred.metric, pred.id), pred)

    _ok(f"Episode 2 slug: {slug2}")
    _ok(f"azure_revenue_growth revised: 0.35 → 0.38")
    _ok(f"ai_run_rate_usd_b revised: 16.0 → 20.0")

    # -- Build modified strategy payload to reflect assumption change --
    str_modified = copy.deepcopy(str_payload)
    # Simulate: management priorities shifted slightly after Q2
    if str_modified.get("narrative_shifts"):
        str_modified["narrative_shifts"].append({
            "topic": "AI Revenue Acceleration",
            "old_framing": "AI is an emerging revenue contributor",
            "new_framing": "AI run rate at $20B and accelerating — material segment",
            "shift_type": "emphasis_increase",
            "confidence": 0.80,
            "old_evidence_refs": [],
            "new_evidence_refs": [],
        })
    str_modified["overall_confidence"] = min(
        float(str_modified.get("overall_confidence", 0.5)) + 0.08, 0.95
    )

    # -- Run orchestrator for ep2 --
    policy = OrchestratorPolicy.load()
    orch = Orchestrator(policy=policy)

    ep1_decision_path = ORCH_EP1 / "decision.json"
    prior_decision = json.loads(ep1_decision_path.read_text()) if ep1_decision_path.exists() else None

    assumptions_ep2 = [
        {
            "key": a1_revised.key, "label": a1_revised.label, "value": a1_revised.value,
            "unit": a1_revised.unit, "owner_agent": a1_revised.owner_agent,
            "rationale": a1_revised.rationale, "confidence": a1_revised.confidence,
            "materiality": a1_revised.materiality.value, "status": "ACTIVE",
            "version": a1_revised.version, "history": [],
        },
        {
            "key": a2.key, "label": a2.label, "value": a2.value,
            "unit": a2.unit, "owner_agent": a2.owner_agent,
            "rationale": a2.rationale, "confidence": a2.confidence,
            "materiality": a2.materiality.value, "status": "ACTIVE",
            "version": a2.version, "history": [],
        },
    ]

    decision2 = orch.run(
        ticker=TICKER,
        industry=ind_payload,
        strategy=str_modified,
        assumptions=assumptions_ep2,
        prior_thesis=prior_decision,
    )

    ORCH_EP2.mkdir(parents=True, exist_ok=True)
    _write_json(ORCH_EP2 / "decision.json", decision2.model_dump(mode="json"))
    _write(ORCH_EP2 / "decision.md", render_decision(decision2))
    _ok(f"Orchestrator ep2 confidence: {decision2.confidence_summary.overall:.0%}")

    # -- Diff ep1 vs ep2 industry payloads --
    ind_modified = copy.deepcopy(ind_payload)
    # Simulate industry agent seeing higher Azure growth in updated evidence
    ind_modified["cycle_stage"] = "GROWTH"  # stays same
    ind_modified["overall_confidence"] = min(float(ind_payload.get("overall_confidence", 0.3)) + 0.05, 0.95)

    ep1_ind = ind_payload
    ep2_ind = ind_modified

    ep1_ev_ids = ind_payload.get("evidence_ids", [])
    ep2_ev_ids = str_modified.get("evidence_ids", [])

    diff = diff_payloads(
        prior=ep1_ind,
        current=ep2_ind,
        agent_id="industry_v1",
        prior_run_id=str(ind_payload.get("run_id", "ep1-run")),
        current_run_id=str(ind_modified.get("run_id", "ep2-run")),
        ticker=TICKER,
        current_evidence_ids=ep2_ev_ids,
        prior_evidence_ids=ep1_ev_ids,
        episode_id=slug2,
    )

    log = new_change_log(TICKER, "industry_v1")
    log.append_diff(diff)

    DIFF_DIR.mkdir(parents=True, exist_ok=True)
    _write_json(DIFF_DIR / "industry_diff_ep1_ep2.json", diff.model_dump(mode="json"))
    _write(DIFF_DIR / "industry_diff_ep1_ep2.md", render_episode_diff(diff))
    _write_json(DIFF_DIR / "industry_changelog.json", log.model_dump(mode="json"))
    from equity_os.diff.renderer import render_change_log
    _write(DIFF_DIR / "industry_changelog.md", render_change_log(log))

    _ok(f"Diff: {len([c for c in diff.field_changes if c.change_type.value != 'UNCHANGED'])} fields changed")
    _ok(f"Assumption proposals: {len(diff.assumption_proposals)}")
    _ok(f"Conflicts: {len(diff.conflict_flags)}")
    _ok(f"Diff saved → {DIFF_DIR / 'industry_diff_ep1_ep2.md'}")

    return slug2


# ===========================================================================
# Step 9: Score + Postmortem for Episode 1
# ===========================================================================

def step_postmortem(ep1_slug: str) -> None:
    _banner("STEP 9 — Score Episode 1 + generate postmortem")
    from equity_os.fs.io import write_md
    from equity_os.fs.layout import CompanyLayout
    from equity_os.fs.readers import load_episode
    from equity_os.learning.postmortem import generate_postmortem
    from equity_os.learning.renderer import render_episode_score, render_postmortem
    from equity_os.learning.scoring import score_episode

    layout = CompanyLayout(COMPANIES, TICKER)
    ep = load_episode(layout, ep1_slug)

    predictions = [p.model_dump(mode="json") for p in ep.predictions]
    assumptions = [a.model_dump(mode="json") for a in ep.assumptions]

    score = score_episode(TICKER, ep1_slug, predictions, {})

    thesis = ep.thesis_statement
    report = generate_postmortem(score, thesis, assumptions)

    layout.scores_dir.mkdir(parents=True, exist_ok=True)
    layout.postmortems_dir.mkdir(parents=True, exist_ok=True)

    layout.score_json(ep1_slug).write_text(score.model_dump_json(indent=2), encoding="utf-8")
    write_md(layout.score_md(ep1_slug), render_episode_score(score))

    layout.postmortem_json(ep1_slug).write_text(report.model_dump_json(indent=2), encoding="utf-8")
    write_md(layout.postmortem_md(ep1_slug), render_postmortem(report))

    # Also copy into demo/postmortem/ for easy access
    POSTMORTEM_DIR.mkdir(parents=True, exist_ok=True)
    _write_json(POSTMORTEM_DIR / "ep1_score.json", score.model_dump(mode="json"))
    _write(POSTMORTEM_DIR / "ep1_score.md", render_episode_score(score))
    _write_json(POSTMORTEM_DIR / "ep1_postmortem.json", report.model_dump(mode="json"))
    _write(POSTMORTEM_DIR / "ep1_postmortem.md", render_postmortem(report))

    _ok(f"Verdict: {report.verdict}")
    _ok(f"Scored: {score.scored_count}/{score.total_predictions} predictions")
    if score.hit_rate is not None:
        _ok(f"Hit rate: {score.hit_rate:.0%}")
    if score.brier_score is not None:
        _ok(f"Brier score: {score.brier_score:.4f} (baseline 0.2500)")
    _ok(f"Postmortem → {POSTMORTEM_DIR / 'ep1_postmortem.md'}")


# ===========================================================================
# Step 10: Write demo/README.md
# ===========================================================================

def step_write_readme(ep1_slug: str, ep2_slug: str) -> None:
    _banner("STEP 10 — Write demo/README.md")
    readme = f"""# EQOS End-to-End Demo — MSFT

This directory contains all artifacts from a complete equity research coverage
cycle for **Microsoft Corporation (MSFT)**, generated by EQOS
without any external API calls.

## Quick navigation

| Artifact | Path |
| --- | --- |
| Company dossier | `companies/MSFT/core/dossier.json` |
| Dossier summary | `companies/MSFT/core/dossier.md` |
| Ingested evidence | `companies/MSFT/evidence/` |
| Industry analysis | `agents/industry_analysis.md` |
| Strategy analysis | `agents/strategy_analysis.md` |
| Orchestrator — Ep1 | `orchestrator/ep1/decision.md` |
| Orchestrator — Ep2 | `orchestrator/ep2/decision.md` |
| Ep1 episode | `companies/MSFT/episodes/{ep1_slug}/episode.json` |
| Ep2 episode | `companies/MSFT/episodes/{ep2_slug}/episode.json` |
| Ep1 assumptions | `companies/MSFT/assumptions/{ep1_slug}/` |
| Diff ep1→ep2 | `diff/industry_diff_ep1_ep2.md` |
| Change log | `diff/industry_changelog.md` |
| Ep1 score | `postmortem/ep1_score.md` |
| Ep1 postmortem | `postmortem/ep1_postmortem.md` |

## What this demo proves

### Prior state is preserved
Every write is preceded by a snapshot:
```
companies/MSFT/core/dossier.json       ← current
companies/MSFT/episodes/{ep1_slug}/episode.json   ← episode state
```
Each episode version is independent. Ep2 does not overwrite Ep1.

### Updates create auditable diffs
`diff/industry_diff_ep1_ep2.md` shows exactly what changed between
the Episode 1 and Episode 2 industry analysis runs, with materiality
labels and assumption update proposals.

### The orchestrator can be judged later
`orchestrator/ep1/decision.json` records the full synthesised view
at Episode 1 time, including:
- Thesis statement
- Key assumptions (with policy-adjusted confidence)
- Falsification conditions
- Monitoring triggers
- Next evidence needed

When Episode 2 runs, `orchestrator/ep2/decision.json` captures the
updated view. Comparing the two shows how the orchestrator's view evolved.

### No external APIs
All inputs are local documents under `inputs/MSFT/`:
- `filing_10k_fy2025.txt` — synthetic 10-K
- `earnings_transcript_q1_fy2026.md` — synthetic earnings call
- `industry_note_cloud_ai_2025.txt` — synthetic industry note
- `channel_check_azure_partners.csv` — synthetic channel checks

Evidence is chunked, deduplication-checked, and stored in
`companies/MSFT/evidence/` before any agent sees it.

## Regenerate

```bash
make demo
# or
uv run python scripts/run_demo.py
```
"""
    _write(DEMO / "README.md", readme)
    _ok(f"Demo README → {DEMO / 'README.md'}")


# ===========================================================================
# Main
# ===========================================================================

def main() -> None:
    print("\n" + "=" * 60)
    print("  EQOS End-to-End Demo — Microsoft (MSFT)")
    print("=" * 60)
    print(f"  Demo root: {DEMO}")
    print(f"  No external APIs — all documents are local synthetic files")

    step_init()
    evidence, _ = step_ingest()
    ind_payload, str_payload = step_run_agents(evidence)
    step_orchestrate_ep1(ind_payload, str_payload)
    ep1_slug = step_episode1(ind_payload, str_payload)
    step_resolve(ep1_slug)
    ep2_slug = step_episode2_and_diff(ind_payload, str_payload, ep1_slug)
    step_postmortem(ep1_slug)
    step_write_readme(ep1_slug, ep2_slug)

    _banner("DEMO COMPLETE")
    print(f"\n  All artifacts stored under: {DEMO}")
    print(f"\n  Key files to inspect:")
    print(f"    {DEMO}/README.md")
    print(f"    {DEMO}/agents/industry_analysis.md")
    print(f"    {DEMO}/agents/strategy_analysis.md")
    print(f"    {DEMO}/orchestrator/ep1/decision.md")
    print(f"    {DEMO}/orchestrator/ep2/decision.md")
    print(f"    {DEMO}/diff/industry_diff_ep1_ep2.md")
    print(f"    {DEMO}/postmortem/ep1_postmortem.md")
    print(f"    {DEMO}/companies/MSFT/episodes/  (all episode JSON)")
    print()


if __name__ == "__main__":
    main()
