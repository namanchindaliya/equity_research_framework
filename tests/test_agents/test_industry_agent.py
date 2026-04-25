"""Tests for IndustryAgent — structured output, Porter forces, evidence refs."""

from __future__ import annotations

import pytest

from equity_os.agents.industry import IndustryAgent
from equity_os.agents.models import (
    CycleStage,
    Finding,
    ForceLevel,
    IndustryAnalysis,
    MarketStructure,
    PorterForce,
)


@pytest.fixture(scope="module")
def result(aapl_evidence):
    return IndustryAgent().run("AAPL", aapl_evidence)


@pytest.fixture(scope="module")
def analysis(result) -> IndustryAnalysis:
    return IndustryAnalysis.model_validate(result.payload)


class TestIndustryAnalysisStructure:
    def test_ticker_set(self, analysis):
        assert analysis.ticker == "AAPL"

    def test_industry_label_non_empty(self, analysis):
        assert len(analysis.industry_label) > 0
        # Should detect consumer electronics / smartphone
        assert "electronics" in analysis.industry_label.lower() or "technology" in analysis.industry_label.lower()

    def test_market_structure_valid_enum(self, analysis):
        assert analysis.market_structure in MarketStructure

    def test_cycle_stage_valid_enum(self, analysis):
        assert analysis.cycle_stage in CycleStage

    def test_exactly_five_porter_forces(self, analysis):
        assert len(analysis.porter_forces) == 5

    def test_porter_force_names(self, analysis):
        names = {f.name for f in analysis.porter_forces}
        assert "Competitive Rivalry" in names
        assert "Supplier Power" in names
        assert "Buyer Power" in names
        assert "Threat of New Entry" in names
        assert "Threat of Substitutes" in names

    def test_porter_force_levels_valid(self, analysis):
        for force in analysis.porter_forces:
            assert force.level in ForceLevel

    def test_porter_force_confidence_in_range(self, analysis):
        for force in analysis.porter_forces:
            assert 0.0 <= force.confidence <= 1.0

    def test_overall_confidence_in_range(self, analysis):
        assert 0.0 <= analysis.overall_confidence <= 1.0

    def test_has_kpis(self, analysis):
        assert len(analysis.key_kpis) >= 1

    def test_kpi_trend_direction_valid(self, analysis):
        valid = {"increasing", "decreasing", "stable", "unknown"}
        for kpi in analysis.key_kpis:
            assert kpi.trend_direction in valid

    def test_has_regulatory_factors(self, analysis):
        # DMA mentioned in both filing and news
        assert len(analysis.regulatory_factors) >= 1

    def test_regulatory_jurisdiction_non_empty(self, analysis):
        for reg in analysis.regulatory_factors:
            assert len(reg.jurisdiction) > 0

    def test_competitive_dynamics_has_moat(self, analysis):
        assert len(analysis.competitive_dynamics.moat_type) >= 1

    def test_competitive_dynamics_has_basis(self, analysis):
        assert len(analysis.competitive_dynamics.basis_of_competition) >= 1

    def test_has_top_risks(self, analysis):
        assert len(analysis.top_risks) >= 1

    def test_risk_categories_valid(self, analysis):
        valid = {"regulatory", "competitive", "macro", "technology", "demand", "operational"}
        for risk in analysis.top_risks:
            assert risk.category in valid

    def test_unresolved_questions_is_list(self, analysis):
        assert isinstance(analysis.unresolved_questions, list)

    def test_evidence_ids_match_input(self, analysis, aapl_evidence):
        assert len(analysis.evidence_ids) == len(aapl_evidence)

    def test_no_validation_errors(self, result):
        assert result.validation_errors == []


class TestIndustryEvidenceRefs:
    def test_porter_rivalry_has_refs(self, analysis):
        rivalry = next(f for f in analysis.porter_forces if f.name == "Competitive Rivalry")
        assert len(rivalry.evidence_refs) >= 1

    def test_evidence_refs_have_chunk_id(self, analysis):
        for force in analysis.porter_forces:
            for ref in force.evidence_refs:
                assert len(ref.chunk_id) > 0
                assert "-" in ref.chunk_id

    def test_evidence_refs_quote_non_empty(self, analysis):
        for force in analysis.porter_forces:
            for ref in force.evidence_refs:
                assert len(ref.quote) > 0

    def test_kpi_refs_point_to_aapl_chunks(self, analysis):
        for kpi in analysis.key_kpis:
            for ref in kpi.finding.evidence_refs:
                assert ref.chunk_id.startswith("AAPL-")


class TestIndustryMarkdown:
    def test_memo_has_porter_section(self, result):
        assert "Porter" in result.memo

    def test_memo_has_regulatory_section(self, result):
        assert "Regulatory" in result.memo

    def test_memo_has_risks_section(self, result):
        assert "Risk" in result.memo

    def test_memo_has_confidence_stated(self, result):
        assert "Confidence" in result.memo or "confidence" in result.memo

    def test_memo_has_ticker(self, result):
        assert "AAPL" in result.memo

    def test_memo_no_valuation_language(self, result):
        forbidden = ["price target", "DCF", "intrinsic value", "fair value", "EV/EBITDA multiple"]
        for term in forbidden:
            assert term.lower() not in result.memo.lower(), f"Found forbidden term: {term}"

    def test_memo_no_management_quality_language(self, result):
        forbidden = ["management quality", "great management", "poor management", "competent CEO"]
        for term in forbidden:
            assert term.lower() not in result.memo.lower()


class TestIndustrySingleSource:
    """Agents must degrade gracefully when only one evidence type is present."""

    def test_filing_only_still_produces_output(self, filing_only):
        result = IndustryAgent().run("AAPL", filing_only)
        analysis = IndustryAnalysis.model_validate(result.payload)
        assert analysis.market_structure in MarketStructure
        assert len(analysis.porter_forces) == 5

    def test_transcript_only_still_produces_output(self, transcript_only):
        result = IndustryAgent().run("AAPL", transcript_only)
        analysis = IndustryAnalysis.model_validate(result.payload)
        assert len(analysis.porter_forces) == 5


class TestIndustryExpectedFindings:
    """Domain-specific: our fixture evidence should produce certain findings."""

    def test_detects_competitive_rivalry(self, analysis):
        rivalry = next(f for f in analysis.porter_forces if f.name == "Competitive Rivalry")
        # Fixture contains "Competition in the smartphone market is intense"
        assert rivalry.level in {ForceLevel.MEDIUM, ForceLevel.HIGH}

    def test_detects_regulatory_risk_dma(self, analysis):
        reg_names = [r.name for r in analysis.regulatory_factors]
        # DMA appears in both filing and news fixture
        assert any("Digital Markets" in n or "DMA" in n for n in reg_names)

    def test_detects_services_kpi(self, analysis):
        kpi_names = [k.name.lower() for k in analysis.key_kpis]
        assert any("revenue" in n or "subscriber" in n or "gross margin" in n for n in kpi_names)
