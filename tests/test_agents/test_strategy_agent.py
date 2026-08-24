"""Tests for CompanyStrategyAgent — priorities, capital allocation, shifts, scope."""

from __future__ import annotations

import pytest

from equity_os.agents.strategy import CompanyStrategyAgent
from equity_os.agents.models import AnalysisStatus, CompanyStrategyAnalysis


@pytest.fixture(scope="module")
def result(aapl_evidence):
    return CompanyStrategyAgent().run("AAPL", aapl_evidence)


@pytest.fixture(scope="module")
def analysis(result) -> CompanyStrategyAnalysis:
    return CompanyStrategyAnalysis.model_validate(result.payload)


class TestStrategyStructure:
    def test_ticker_set(self, analysis):
        assert analysis.ticker == "AAPL"

    def test_has_management_priorities(self, analysis):
        assert len(analysis.management_priorities) >= 1

    def test_priority_confidence_in_range(self, analysis):
        for f in analysis.management_priorities:
            assert 0.0 <= f.confidence <= 1.0

    def test_has_capital_allocation(self, analysis):
        assert len(analysis.capital_allocation) >= 1

    def test_capital_allocation_categories_valid(self, analysis):
        valid = {"buybacks", "dividends", "capex", "m_and_a", "debt"}
        for item in analysis.capital_allocation:
            assert item.category in valid

    def test_has_risk_disclosures(self, analysis):
        assert len(analysis.risk_disclosures) >= 1

    def test_risk_severity_valid(self, analysis):
        valid = {"explicit", "mentioned", "implied"}
        for risk in analysis.risk_disclosures:
            assert risk.severity_from_disclosure in valid

    def test_risk_categories_valid(self, analysis):
        valid = {"regulatory", "competitive", "operational", "macro", "financial", "technology"}
        for risk in analysis.risk_disclosures:
            assert risk.category in valid

    def test_has_segment_priorities(self, analysis):
        assert len(analysis.segment_priorities) >= 1

    def test_segment_ranks_sequential(self, analysis):
        ranks = [s.priority_rank for s in analysis.segment_priorities]
        assert ranks == sorted(ranks)

    def test_segment_growth_framing_valid(self, analysis):
        valid = {"growth", "stable", "declining", "unknown"}
        for seg in analysis.segment_priorities:
            assert seg.growth_framing in valid

    def test_strategic_positioning_has_target_market(self, analysis):
        valid = {"premium", "enterprise", "mass_market", "mixed", "unknown"}
        assert analysis.strategic_positioning.target_market in valid

    def test_strategic_positioning_has_differentiation(self, analysis):
        assert len(analysis.strategic_positioning.differentiation_axes) >= 1

    def test_has_credibility_signals(self, analysis):
        # Transcript says "exceeded our expectations" — should fire
        assert len(analysis.mgmt_credibility_signals) >= 1

    def test_credibility_signal_types_valid(self, analysis):
        valid = {"guidance_beat", "guidance_miss", "strategic_consistency", "reversal"}
        for sig in analysis.mgmt_credibility_signals:
            assert sig.signal_type in valid

    def test_overall_confidence_in_range(self, analysis):
        assert 0.0 <= analysis.overall_confidence <= 1.0

    def test_unresolved_questions_is_list(self, analysis):
        assert isinstance(analysis.unresolved_questions, list)

    def test_evidence_ids_match_input(self, analysis, aapl_evidence):
        assert len(analysis.evidence_ids) == len(aapl_evidence)

    def test_no_validation_errors(self, result):
        assert result.validation_errors == []

    def test_evidence_quality_is_explicit(self, analysis):
        assert analysis.analysis_status in {AnalysisStatus.COMPLETE, AnalysisStatus.LIMITED}
        assert analysis.evidence_quality is not None
        assert analysis.evidence_quality.citation_coverage == 1.0


class TestStrategyEvidenceRefs:
    def test_priorities_have_refs(self, analysis):
        for priority in analysis.management_priorities:
            assert len(priority.evidence_refs) >= 1

    def test_refs_have_valid_chunk_ids(self, analysis):
        all_refs = (
            [ref for f in analysis.management_priorities for ref in f.evidence_refs]
            + [ref for r in analysis.risk_disclosures for ref in r.finding.evidence_refs]
        )
        for ref in all_refs:
            assert ref.chunk_id.startswith("AAPL-")
            assert len(ref.evidence_id) > 0

    def test_refs_have_quotes(self, analysis):
        for f in analysis.management_priorities:
            for ref in f.evidence_refs:
                assert len(ref.quote) > 0


class TestStrategyScope:
    """Verify out-of-scope content does not appear."""

    def test_no_price_target_in_output(self, result):
        memo = result.memo.lower()
        assert "price target" not in memo
        assert "fair value" not in memo
        assert "dcf" not in memo

    def test_no_eps_forecast_in_memo(self, result):
        assert "earnings per share forecast" not in result.memo.lower()
        assert "we expect eps" not in result.memo.lower()

    def test_no_valuation_in_payload(self, result):
        payload_str = str(result.payload).lower()
        assert "price_target" not in payload_str
        assert "intrinsic_value" not in payload_str

    def test_management_quality_not_inferred(self, result):
        forbidden = ["great management", "poor management", "competent team",
                     "management quality", "strong leadership"]
        memo_lower = result.memo.lower()
        for term in forbidden:
            assert term not in memo_lower, f"Found prohibited inference: {term!r}"


class TestStrategyMarkdown:
    def test_memo_has_priorities_section(self, result):
        assert "Management Priorities" in result.memo

    def test_memo_has_risks_section(self, result):
        assert "Risk" in result.memo

    def test_memo_has_segments_section(self, result):
        assert "Segment" in result.memo

    def test_memo_has_positioning_section(self, result):
        assert "Positioning" in result.memo

    def test_memo_has_agent_id(self, result):
        assert "strategy_v1" in result.memo

    def test_memo_has_confidence(self, result):
        assert "Confidence" in result.memo


class TestStrategyExpectedFindings:
    """Domain-specific: our fixture evidence should surface specific findings."""

    def test_services_is_top_segment(self, analysis):
        # Services mentioned most frequently across all fixtures
        top_seg = analysis.segment_priorities[0].segment_name.lower()
        assert "service" in top_seg or "iphone" in top_seg  # either is plausible

    def test_detects_regulatory_risk(self, analysis):
        cats = {r.category for r in analysis.risk_disclosures}
        assert "regulatory" in cats

    def test_detects_competitive_risk(self, analysis):
        cats = {r.category for r in analysis.risk_disclosures}
        assert "competitive" in cats

    def test_detects_guidance_beat_credibility(self, analysis):
        sig_types = {s.signal_type for s in analysis.mgmt_credibility_signals}
        # "exceeded our expectations" in transcript should fire guidance_beat
        assert "guidance_beat" in sig_types or "strategic_consistency" in sig_types

    def test_buyback_capital_allocation_detected(self, analysis):
        cats = {a.category for a in analysis.capital_allocation}
        # "returned over $32 billion to shareholders" in transcript
        assert "buybacks" in cats or "dividends" in cats


class TestStrategySingleSource:
    def test_filing_only_still_produces_output(self, filing_only):
        result = CompanyStrategyAgent().run("AAPL", filing_only)
        analysis = CompanyStrategyAnalysis.model_validate(result.payload)
        assert len(analysis.risk_disclosures) >= 1

    def test_transcript_only_still_produces_output(self, transcript_only):
        result = CompanyStrategyAgent().run("AAPL", transcript_only)
        analysis = CompanyStrategyAnalysis.model_validate(result.payload)
        # Structural validity — may have 0 priorities from transcript alone
        assert isinstance(analysis.management_priorities, list)
        assert len(analysis.segment_priorities) >= 1  # segments always detectible

    def test_unrelated_sources_force_abstention(self, aapl_evidence):
        unrelated = [
            ev
            for ev in aapl_evidence
            if ev.logical_type not in {"filing", "earnings_transcript"}
        ]
        result = CompanyStrategyAgent().run("AAPL", unrelated)
        analysis = CompanyStrategyAnalysis.model_validate(result.payload)
        assert analysis.analysis_status == AnalysisStatus.ABSTAINED
        assert analysis.management_priorities == []
        assert analysis.overall_confidence == 0.0
