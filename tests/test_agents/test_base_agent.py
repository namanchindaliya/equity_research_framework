"""Tests for BaseAgent contract: required_inputs, missing_input_types, etc."""

from __future__ import annotations

import pytest

from equity_os.agents.industry import IndustryAgent
from equity_os.agents.strategy import CompanyStrategyAgent
from equity_os.ingest.models import IngestedEvidence


class TestBaseAgentContract:
    def test_industry_agent_id(self):
        assert IndustryAgent().agent_id == "industry_v1"

    def test_strategy_agent_id(self):
        assert CompanyStrategyAgent().agent_id == "strategy_v1"

    def test_industry_required_inputs(self):
        req = IndustryAgent().required_inputs()
        assert "filing" in req
        assert "earnings_transcript" in req

    def test_strategy_required_inputs(self):
        req = CompanyStrategyAgent().required_inputs()
        assert "filing" in req
        assert "earnings_transcript" in req

    def test_missing_input_types_all_present(self, aapl_evidence):
        agent = IndustryAgent()
        missing = agent.missing_input_types(aapl_evidence)
        # We have filing, earnings_transcript, channel_check
        # industry_note is missing from fixtures
        assert "filing" not in missing
        assert "earnings_transcript" not in missing

    def test_missing_input_types_absent_type(self, aapl_evidence):
        agent = IndustryAgent()
        missing = agent.missing_input_types(aapl_evidence)
        assert "industry_note" in missing

    def test_run_returns_agent_run_result_type(self, aapl_evidence):
        from equity_os.agents.models import AgentRunResult
        result = IndustryAgent().run("AAPL", aapl_evidence)
        assert isinstance(result, AgentRunResult)

    def test_run_populates_memo(self, aapl_evidence):
        result = IndustryAgent().run("AAPL", aapl_evidence)
        assert len(result.memo) > 100
        assert "AAPL" in result.memo

    def test_run_populates_evidence_ids(self, aapl_evidence):
        result = IndustryAgent().run("AAPL", aapl_evidence)
        assert len(result.evidence_ids_consumed) == 4

    def test_run_returns_no_validation_errors(self, aapl_evidence):
        result = IndustryAgent().run("AAPL", aapl_evidence)
        assert result.validation_errors == [], result.validation_errors

    def test_empty_evidence_degrades_gracefully(self):
        result = IndustryAgent().run("AAPL", [])
        assert result is not None
        assert isinstance(result.payload, dict)

    def test_determinism(self, aapl_evidence):
        """Same evidence → same payload structure and key values."""
        r1 = IndustryAgent().run("AAPL", aapl_evidence)
        r2 = IndustryAgent().run("AAPL", aapl_evidence)
        assert r1.payload["market_structure"] == r2.payload["market_structure"]
        assert r1.payload["cycle_stage"] == r2.payload["cycle_stage"]
        assert len(r1.payload["porter_forces"]) == len(r2.payload["porter_forces"])
