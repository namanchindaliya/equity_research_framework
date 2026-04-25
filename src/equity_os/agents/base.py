"""BaseAgent — abstract base class for all specialist agents.

Contract
--------
Every concrete agent must implement:

    required_inputs() -> list[str]
        Logical evidence types this agent needs (e.g. ["filing", "earnings_transcript"]).
        The runner warns when required types are missing but still calls run().

    run(ticker, evidence) -> AgentRunResult
        Execute analysis over the provided evidence and return a structured result.
        Must be deterministic: same evidence → same structure.

    validate_output(result) -> list[str]
        Check the result for schema / business-logic problems.
        Return [] if valid, list of error strings otherwise.

    render_markdown(result) -> str
        Convert the result payload into a human-readable markdown memo.
        Must be called INSIDE run() — the AgentRunResult.memo field is populated here.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime

from equity_os.ingest.models import IngestedEvidence

from .models import AgentRunResult


class BaseAgent(ABC):
    """Abstract specialist agent."""

    @property
    @abstractmethod
    def agent_id(self) -> str:
        """Machine-readable agent identifier, e.g. 'industry_v1'."""
        ...

    @property
    @abstractmethod
    def agent_version(self) -> str:
        """Semantic version string, e.g. '1.0'."""
        ...

    @abstractmethod
    def required_inputs(self) -> list[str]:
        """Logical evidence types this agent needs to function well.

        The runner will WARN (not error) if required types are absent,
        so agents must degrade gracefully when evidence is sparse.
        """
        ...

    @abstractmethod
    def run(self, ticker: str, evidence: list[IngestedEvidence]) -> AgentRunResult:
        """Execute analysis and return an AgentRunResult.

        Must:
        - Call render_markdown() and store result in AgentRunResult.memo
        - Call validate_output() and store errors in AgentRunResult.validation_errors
        - Populate evidence_ids_consumed from the evidence list
        - Be deterministic: same inputs → same output structure
        """
        ...

    @abstractmethod
    def validate_output(self, result: AgentRunResult) -> list[str]:
        """Validate the result. Return [] if valid, error strings otherwise.

        Common checks:
        - Required payload keys are present
        - All confidence values in [0, 1]
        - evidence_ids_consumed is non-empty if evidence was provided
        - unresolved_questions is a list (may be empty)
        """
        ...

    @abstractmethod
    def render_markdown(self, result: AgentRunResult) -> str:
        """Render a human-readable markdown memo from the result payload."""
        ...

    # ------------------------------------------------------------------
    # Utility helpers available to all agents
    # ------------------------------------------------------------------

    def missing_input_types(self, evidence: list[IngestedEvidence]) -> list[str]:
        """Return required types that are absent from the evidence list."""
        present = {ev.logical_type for ev in evidence}
        return [t for t in self.required_inputs() if t not in present]

    def _now(self) -> str:
        return datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")

    def _pct(self, value: float) -> str:
        return f"{value * 100:.0f}%"

    def _conf_label(self, confidence: float) -> str:
        if confidence >= 0.75:
            return "HIGH"
        if confidence >= 0.45:
            return "MEDIUM"
        return "LOW"
