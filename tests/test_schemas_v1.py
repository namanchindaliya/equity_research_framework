"""Tests for v1 domain schemas: validation, round-trip JSON, business logic."""

from __future__ import annotations

import json
from datetime import date, datetime, timezone
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError

from equity_os.schemas import (
    AgentOutput,
    AgentType,
    AssumptionChange,
    AssumptionRecord,
    CompanyDossier,
    ComparisonOperator,
    ConflictItem,
    DecisionRecord,
    EpisodeStatus,
    EvidenceDirection,
    EvidenceItem,
    EvidenceType,
    FalsificationCondition,
    InferenceRecord,
    MaterialityLevel,
    MonitoringTrigger,
    ObservationRecord,
    OrchestratorDecision,
    Postmortem,
    PostmortemVerdict,
    PredictionRecord,
    Rating,
    ResolutionRecord,
    ResolutionStatus,
    RiskItem,
    SourceMetadata,
    SourceType,
    ThesisEpisode,
    TriggerAction,
    TriggerFrequency,
)

FIXTURES = Path(__file__).parent / "fixtures"


# ===========================================================================
# SourceMetadata
# ===========================================================================


class TestSourceMetadata:
    def test_defaults(self):
        s = SourceMetadata(source_type=SourceType.FILING, name="Apple 10-K FY2025")
        assert s.reliability_score == 0.8
        assert s.reference is None

    def test_round_trip(self):
        s = SourceMetadata(
            source_type=SourceType.EARNINGS_CALL,
            name="Q1 FY2026 call",
            published_at=date(2026, 1, 30),
            reliability_score=1.0,
        )
        s2 = SourceMetadata.model_validate_json(s.model_dump_json())
        assert s2.source_type == s.source_type
        assert s2.published_at == s.published_at
        assert s2.reliability_score == s.reliability_score

    def test_reliability_clamped(self):
        with pytest.raises(ValidationError, match="less than or equal to 1"):
            SourceMetadata(source_type=SourceType.OTHER, name="X", reliability_score=1.5)

    def test_reliability_negative(self):
        with pytest.raises(ValidationError, match="greater than or equal to 0"):
            SourceMetadata(source_type=SourceType.OTHER, name="X", reliability_score=-0.1)


# ===========================================================================
# EvidenceItem
# ===========================================================================


class TestEvidenceItem:
    def test_defaults(self):
        e = EvidenceItem(
            evidence_type=EvidenceType.FACT,
            direction=EvidenceDirection.SUPPORTING,
            content="Services revenue beat by $400M.",
        )
        assert e.confidence == 0.8
        assert e.tags == []

    def test_with_source(self):
        src = SourceMetadata(source_type=SourceType.EARNINGS_CALL, name="Q1 call")
        e = EvidenceItem(
            evidence_type=EvidenceType.DATA_POINT,
            direction=EvidenceDirection.SUPPORTING,
            content="Services $26.3B",
            source=src,
        )
        assert e.source is not None
        assert e.source.source_type == SourceType.EARNINGS_CALL

    def test_round_trip(self):
        e = EvidenceItem(
            evidence_type=EvidenceType.INFERENCE,
            direction=EvidenceDirection.CONTRADICTING,
            content="Management tone was cautious.",
            confidence=0.6,
            tags=["tone", "management"],
        )
        e2 = EvidenceItem.model_validate_json(e.model_dump_json())
        assert e2.direction == EvidenceDirection.CONTRADICTING
        assert e2.tags == ["tone", "management"]


# ===========================================================================
# AssumptionRecord + AssumptionChange
# ===========================================================================


class TestAssumptionRecord:
    def _make(self, **kw) -> AssumptionRecord:
        return AssumptionRecord(
            key="services_cagr",
            label="Services 3yr CAGR",
            value=0.13,
            unit="%",
            owner_agent="analyst_a",
            rationale="Install base compounding + ARPU expansion",
            **kw,
        )

    def test_defaults(self):
        a = self._make()
        assert a.version == 1
        assert a.history == []
        assert a.materiality == MaterialityLevel.MEDIUM
        assert a.status.value == "ACTIVE"

    def test_version_history_validator_happy(self):
        a = self._make()
        assert a.version == 1

    def test_version_history_mismatch_raises(self):
        with pytest.raises(ValidationError, match="history has 0 entries but version is 2"):
            AssumptionRecord(
                key="k",
                label="L",
                value=0.1,
                owner_agent="a",
                rationale="r",
                version=2,
                history=[],
            )

    def test_revise_creates_change_record(self):
        a = self._make(confidence=0.7)
        a2 = a.revise(
            new_value=0.15,
            new_confidence=0.8,
            reason="Q1 beat confirmed acceleration",
            changed_by="analyst_a",
        )
        assert a2.value == 0.15
        assert a2.version == 2
        assert len(a2.history) == 1
        change = a2.history[0]
        assert isinstance(change, AssumptionChange)
        assert change.previous_value == 0.13
        assert change.new_value == 0.15
        assert change.version == 2

    def test_revise_does_not_mutate_original(self):
        a = self._make()
        a2 = a.revise(new_value=0.20, new_confidence=0.8, reason="R", changed_by="a")
        assert a.value == 0.13
        assert a.version == 1

    def test_double_revision(self):
        a = self._make()
        a2 = a.revise(0.15, 0.8, "first", "a")
        a3 = a2.revise(0.17, 0.85, "second", "a")
        assert a3.version == 3
        assert len(a3.history) == 2

    def test_round_trip_json(self):
        a = self._make(materiality=MaterialityLevel.CRITICAL)
        a2 = AssumptionRecord.model_validate_json(a.model_dump_json())
        assert a2.key == a.key
        assert a2.materiality == MaterialityLevel.CRITICAL

    def test_with_dependencies(self):
        dep_id = uuid4()
        a = self._make(dependencies=[dep_id])
        assert a.dependencies[0] == dep_id


# ===========================================================================
# PredictionRecord + ResolutionRecord
# ===========================================================================


class TestPredictionRecord:
    def _make(self, **kw) -> PredictionRecord:
        return PredictionRecord(
            description="Services revenue exceeds $110B in FY2026",
            metric="aapl_services_revenue_b",
            threshold=110.0,
            unit="USD B",
            operator=ComparisonOperator.GTE,
            horizon="FY2026 full-year",
            due_date=date(2026, 11, 1),
            probability=0.65,
            resolution_rule="Using Apple FY2026 annual report total Services revenue.",
            **kw,
        )

    def test_defaults(self):
        p = self._make()
        assert p.resolution is None
        assert p.materiality == MaterialityLevel.MEDIUM
        assert not p.is_resolved

    def test_resolve_correct(self):
        p = self._make()
        p2 = p.resolve(
            resolved_status=ResolutionStatus.CORRECT,
            actual_outcome=112.5,
            notes="Beat by $2.5B",
            resolved_by="analyst_a",
        )
        assert p2.is_resolved
        assert p2.resolution.resolved_status == ResolutionStatus.CORRECT
        assert p2.resolution.actual_outcome == 112.5
        # error_magnitude = (112.5 - 110) / 110 ≈ 0.0227
        assert abs(p2.resolution.error_magnitude - (112.5 - 110.0) / 110.0) < 1e-9

    def test_resolve_incorrect_negative_error(self):
        p = self._make()
        p2 = p.resolve(
            resolved_status=ResolutionStatus.INCORRECT,
            actual_outcome=100.0,
            notes="Missed by $10B",
            resolved_by="analyst_a",
        )
        assert p2.resolution.error_magnitude == pytest.approx((100.0 - 110.0) / 110.0)

    def test_resolve_twice_raises(self):
        p = self._make()
        p2 = p.resolve(ResolutionStatus.CORRECT, 115.0, "Beat", "a")
        with pytest.raises(ValueError, match="already resolved"):
            p2.resolve(ResolutionStatus.INCORRECT, 90.0, "Nope", "a")

    def test_resolution_id_mismatch_raises(self):
        p = self._make()
        bad_resolution = ResolutionRecord(
            prediction_id=uuid4(),  # wrong id
            resolved_status=ResolutionStatus.CORRECT,
            actual_outcome=115.0,
            notes="ok",
            resolved_by="a",
        )
        with pytest.raises(ValidationError, match="does not match PredictionRecord.id"):
            PredictionRecord(
                description=p.description,
                metric=p.metric,
                threshold=p.threshold,
                horizon=p.horizon,
                due_date=p.due_date,
                probability=p.probability,
                confidence=p.confidence,
                resolution_rule=p.resolution_rule,
                resolution=bad_resolution,
            )

    def test_round_trip(self):
        p = self._make(supporting_assumptions=[uuid4()])
        p2 = PredictionRecord.model_validate_json(p.model_dump_json())
        assert p2.metric == p.metric
        assert p2.due_date == p.due_date
        assert len(p2.supporting_assumptions) == 1

    def test_confidence_out_of_range(self):
        with pytest.raises(ValidationError):
            self._make(confidence=1.5)


# ===========================================================================
# ThesisEpisode
# ===========================================================================


class TestThesisEpisode:
    def _make(self, **kw) -> ThesisEpisode:
        return ThesisEpisode(
            ticker="AAPL",
            title="FY2026 Initiation",
            thesis_statement="Services flywheel undervalued.",
            rating=Rating.BUY,
            price_target=230.0,
            **kw,
        )

    def test_defaults(self):
        ep = self._make()
        assert ep.status == EpisodeStatus.OPEN
        assert ep.version == 1
        assert ep.observations == []
        assert ep.orchestrator_decision is None

    def test_observation_inference_chain(self):
        obs = ObservationRecord(content="Services grew 14% YoY")
        inf = InferenceRecord(content="Flywheel accelerating", based_on=[obs.id])
        ep = self._make(observations=[obs], inferences=[inf])
        assert ep.inferences[0].based_on[0] == obs.id

    def test_pending_predictions_helper(self):
        p_pending = PredictionRecord(
            description="Revenue > $110B",
            metric="svc",
            threshold=110,
            horizon="FY26",
            due_date=date(2026, 11, 1),
            probability=0.6,
            confidence=0.7,
            resolution_rule="Annual report",
        )
        p_resolved = p_pending.resolve(ResolutionStatus.CORRECT, 115, "Beat", "a")
        ep = self._make(predictions=[p_pending, p_resolved])
        assert len(ep.pending_predictions()) == 1

    def test_open_assumption_records_helper(self):
        from equity_os.schemas import AssumptionStatus
        a_active = AssumptionRecord(
            key="k1", label="L1", value=0.1, owner_agent="a", rationale="r"
        )
        a_revised = AssumptionRecord(
            key="k2", label="L2", value=0.2, owner_agent="a", rationale="r",
            status=AssumptionStatus.REVISED,
        )
        ep = self._make(assumptions=[a_active, a_revised])
        assert len(ep.open_assumption_records()) == 1

    def test_round_trip_json(self):
        ep = self._make()
        ep2 = ThesisEpisode.model_validate_json(ep.model_dump_json())
        assert ep2.ticker == "AAPL"
        assert ep2.rating == Rating.BUY

    def test_fixture_loads(self):
        raw = (FIXTURES / "sample_thesis_episode.json").read_text()
        ep = ThesisEpisode.model_validate_json(raw)
        assert ep.ticker == "AAPL"
        assert len(ep.observations) == 1
        assert len(ep.assumptions) == 1
        assert ep.assumptions[0].materiality == MaterialityLevel.CRITICAL


# ===========================================================================
# AgentOutput
# ===========================================================================


class TestAgentOutput:
    def test_with_payload_only(self):
        out = AgentOutput(
            agent_type=AgentType.THESIS_BUILDER,
            agent_id="thesis_builder_v1",
            ticker="AAPL",
            payload={"rating": "BUY"},
            reasoning="Services undervalued.",
        )
        assert out.has_output()
        assert out.memo_path is None

    def test_with_memo_only(self):
        out = AgentOutput(
            agent_type=AgentType.RISK_ASSESSOR,
            agent_id="risk_v1",
            ticker="AAPL",
            memo_path="AAPL/memos/risk_v1.md",
            reasoning="Regulatory risk elevated.",
        )
        assert out.has_output()
        assert out.payload is None

    def test_confidence_clamped(self):
        with pytest.raises(ValidationError):
            AgentOutput(
                agent_type=AgentType.GENERAL,
                agent_id="x",
                ticker="AAPL",
                reasoning="r",
                confidence=2.0,
            )

    def test_round_trip(self):
        out = AgentOutput(
            agent_type=AgentType.ORCHESTRATOR,
            agent_id="orch_v1",
            ticker="MSFT",
            episode_id=uuid4(),
            payload={"foo": "bar"},
            reasoning="Synthesis done.",
            evidence_consumed=[uuid4()],
        )
        out2 = AgentOutput.model_validate_json(out.model_dump_json())
        assert out2.agent_id == "orch_v1"
        assert len(out2.evidence_consumed) == 1

    def test_fixture_loads(self):
        raw = (FIXTURES / "sample_agent_output.json").read_text()
        out = AgentOutput.model_validate_json(raw)
        assert out.agent_type == AgentType.THESIS_BUILDER
        assert out.confidence == 0.72


# ===========================================================================
# OrchestratorDecision
# ===========================================================================


class TestOrchestratorDecision:
    def _make(self, **kw) -> OrchestratorDecision:
        return OrchestratorDecision(
            episode_id=uuid4(),
            ticker="AAPL",
            thesis="Services flywheel undervalued.",
            rating=Rating.BUY,
            price_target=230.0,
            price_target_bear=175.0,
            price_target_bull=270.0,
            **kw,
        )

    def test_defaults(self):
        d = self._make()
        assert d.risks == []
        assert d.conflicts == []
        assert d.falsification_conditions == []
        assert d.version == 1

    def test_with_risk_and_conflict(self):
        risk = RiskItem(
            description="DMA forces sideloading",
            category="regulatory",
            severity="HIGH",
            probability=0.40,
            mitigants=["Apple One pricing offsets"],
        )
        conflict = ConflictItem(
            description="Analyst vs. risk agent on CAGR",
            between=["analyst", "risk_agent"],
            resolution="Blended 11% CAGR",
        )
        d = self._make(risks=[risk], conflicts=[conflict])
        assert d.risks[0].category == "regulatory"
        assert d.conflicts[0].resolution is not None

    def test_conflict_requires_at_least_two_parties(self):
        with pytest.raises(ValidationError, match="too_short"):
            ConflictItem(description="lone wolf", between=["only_one"])

    def test_falsification_condition(self):
        fc = FalsificationCondition(
            description="Services growth < 8% for 2 quarters",
            metric="svc_rev_yoy",
            threshold=0.08,
            check_by=date(2026, 8, 1),
        )
        d = self._make(falsification_conditions=[fc])
        assert d.falsification_conditions[0].check_by == date(2026, 8, 1)

    def test_round_trip(self):
        d = self._make()
        d2 = OrchestratorDecision.model_validate_json(d.model_dump_json())
        assert d2.ticker == "AAPL"
        assert d2.rating == Rating.BUY

    def test_fixture_loads(self):
        raw = (FIXTURES / "sample_orchestrator_decision.json").read_text()
        od = OrchestratorDecision.model_validate_json(raw)
        assert od.ticker == "AAPL"
        assert len(od.risks) == 1
        assert len(od.conflicts) == 1
        assert od.conflicts[0].resolution is not None
        assert len(od.falsification_conditions) == 1
        assert len(od.next_evidence_needed) == 3


# ===========================================================================
# MonitoringTrigger
# ===========================================================================


class TestMonitoringTrigger:
    def test_defaults(self):
        t = MonitoringTrigger(
            episode_id=uuid4(),
            label="Services growth trip-wire",
            description="Alert if services YoY drops below 8%",
            metric="svc_rev_yoy",
            operator="<",
            threshold=0.08,
        )
        assert t.active is True
        assert t.frequency == TriggerFrequency.EVENT_DRIVEN
        assert t.action == TriggerAction.ALERT
        assert t.triggered_at is None

    def test_round_trip(self):
        t = MonitoringTrigger(
            episode_id=uuid4(),
            label="L",
            description="D",
            metric="m",
            operator=">",
            threshold=100,
            frequency=TriggerFrequency.QUARTERLY,
            action=TriggerAction.RERUN_THESIS,
        )
        t2 = MonitoringTrigger.model_validate_json(t.model_dump_json())
        assert t2.frequency == TriggerFrequency.QUARTERLY
        assert t2.action == TriggerAction.RERUN_THESIS


# ===========================================================================
# CompanyDossier
# ===========================================================================


class TestCompanyDossier:
    def test_defaults(self):
        d = CompanyDossier(ticker="AAPL", name="Apple Inc.")
        assert d.current_rating == Rating.NOT_RATED
        assert d.episodes == []
        assert d.version == 1
        assert d.country == "US"

    def test_open_episodes_helper(self):
        ep_open = ThesisEpisode(
            ticker="AAPL",
            title="T1",
            thesis_statement="Thesis",
            rating=Rating.BUY,
            status=EpisodeStatus.OPEN,
        )
        ep_closed = ThesisEpisode(
            ticker="AAPL",
            title="T2",
            thesis_statement="Thesis",
            rating=Rating.HOLD,
            status=EpisodeStatus.CLOSED,
        )
        d = CompanyDossier(ticker="AAPL", name="Apple Inc.", episodes=[ep_open, ep_closed])
        assert len(d.open_episodes()) == 1

    def test_latest_episode_helper(self):
        ep1 = ThesisEpisode(
            ticker="AAPL", title="old", thesis_statement="T", rating=Rating.HOLD,
            created_at=datetime(2025, 1, 1),
        )
        ep2 = ThesisEpisode(
            ticker="AAPL", title="new", thesis_statement="T", rating=Rating.BUY,
            created_at=datetime(2026, 1, 1),
        )
        d = CompanyDossier(ticker="AAPL", name="Apple Inc.", episodes=[ep1, ep2])
        assert d.latest_episode().title == "new"

    def test_latest_episode_empty(self):
        d = CompanyDossier(ticker="AAPL", name="Apple Inc.")
        assert d.latest_episode() is None

    def test_round_trip(self):
        d = CompanyDossier(ticker="MSFT", name="Microsoft", tags=["cloud", "ai"])
        d2 = CompanyDossier.model_validate_json(d.model_dump_json())
        assert d2.tags == ["cloud", "ai"]

    def test_fixture_loads(self):
        raw = (FIXTURES / "aapl_company_dossier.json").read_text()
        d = CompanyDossier.model_validate_json(raw)
        assert d.ticker == "AAPL"
        assert "mag7" in d.tags
        assert d.current_rating == Rating.BUY


# ===========================================================================
# Postmortem
# ===========================================================================


class TestPostmortem:
    def _make(self, **kw) -> Postmortem:
        return Postmortem(
            episode_id=uuid4(),
            ticker="AAPL",
            verdict=PostmortemVerdict.THESIS_CORRECT,
            prediction_accuracy=0.75,
            authored_by="analyst_a",
            **kw,
        )

    def test_defaults(self):
        pm = self._make()
        assert pm.version == 1
        assert pm.what_went_right == []

    def test_verdict_accuracy_conflict_raises(self):
        with pytest.raises(ValidationError, match="prediction_accuracy < 0.5"):
            Postmortem(
                episode_id=uuid4(),
                ticker="AAPL",
                verdict=PostmortemVerdict.THESIS_CORRECT,
                prediction_accuracy=0.3,  # contradicts THESIS_CORRECT
                authored_by="a",
            )

    def test_verdict_incorrect_high_accuracy_raises(self):
        with pytest.raises(ValidationError, match="prediction_accuracy > 0.8"):
            Postmortem(
                episode_id=uuid4(),
                ticker="AAPL",
                verdict=PostmortemVerdict.THESIS_INCORRECT,
                prediction_accuracy=0.9,  # contradicts THESIS_INCORRECT
                authored_by="a",
            )

    def test_inconclusive_bypasses_validator(self):
        # INCONCLUSIVE verdict should not trigger either guard
        pm = Postmortem(
            episode_id=uuid4(),
            ticker="AAPL",
            verdict=PostmortemVerdict.INCONCLUSIVE,
            prediction_accuracy=0.4,
            authored_by="a",
        )
        assert pm.verdict == PostmortemVerdict.INCONCLUSIVE

    def test_round_trip(self):
        pm = self._make(
            what_went_right=["Thesis direction correct", "Key risk identified early"],
            what_went_wrong=["Underestimated regulatory timing"],
            lessons_learned=["Build DMA scenario into base earlier"],
        )
        pm2 = Postmortem.model_validate_json(pm.model_dump_json())
        assert pm2.lessons_learned == pm.lessons_learned


# ===========================================================================
# JSON schema generation smoke test
# ===========================================================================


class TestJsonSchemaExport:
    def test_all_schema_files_exist(self):
        generated = Path(__file__).parent.parent / "generated"
        expected = [
            "SourceMetadata.schema.json",
            "EvidenceItem.schema.json",
            "AssumptionRecord.schema.json",
            "AssumptionChange.schema.json",
            "PredictionRecord.schema.json",
            "ResolutionRecord.schema.json",
            "ThesisEpisode.schema.json",
            "AgentOutput.schema.json",
            "OrchestratorDecision.schema.json",
            "MonitoringTrigger.schema.json",
            "CompanyDossier.schema.json",
            "Postmortem.schema.json",
        ]
        for fname in expected:
            p = generated / fname
            assert p.exists(), f"Missing schema file: {fname}"

    def test_schema_files_are_valid_json(self):
        generated = Path(__file__).parent.parent / "generated"
        for p in generated.glob("*.schema.json"):
            data = json.loads(p.read_text())
            assert "title" in data or "$defs" in data or "properties" in data

    def test_assumption_record_schema_has_key_properties(self):
        generated = Path(__file__).parent.parent / "generated"
        schema = json.loads((generated / "AssumptionRecord.schema.json").read_text())
        props = schema.get("properties", {})
        for field in ("key", "label", "value", "confidence", "materiality", "history"):
            assert field in props, f"Expected field {field!r} in AssumptionRecord schema"
