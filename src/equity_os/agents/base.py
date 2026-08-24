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
from datetime import date, datetime

from equity_os.ingest.models import IngestedEvidence

from .models import AnalysisStatus, AgentRunResult, EvidenceFreshness, EvidenceQuality


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

    def minimum_required_input_count(self) -> int:
        """Minimum distinct required input types needed to avoid abstaining."""
        return 1

    def max_evidence_age_days(self) -> int:
        """Age after which a dated source is explicitly marked stale."""
        return 180

    def assess_evidence_quality(
        self,
        evidence: list[IngestedEvidence],
        payload: dict,
    ) -> EvidenceQuality:
        """Assess source coverage and claim-level citation support.

        A material claim is any nested object with a positive ``confidence`` and
        an ``evidence_refs`` field. High-confidence claims require citations from
        at least two distinct evidence documents.
        """
        required = self.required_inputs()
        present = sorted({ev.logical_type for ev in evidence})
        present_required = sorted(set(required) & set(present))
        missing = [kind for kind in required if kind not in present]
        coverage = len(present_required) / len(required) if required else 1.0

        dated = [ev.source_date for ev in evidence if ev.source_date is not None]
        newest_source_date = max(dated) if dated else None
        stale_document_count = sum(
            1
            for source_date in dated
            if (date.today() - source_date).days > self.max_evidence_age_days()
        )
        undated_document_count = len(evidence) - len(dated)
        if not dated:
            freshness_status = EvidenceFreshness.UNDATED
        elif stale_document_count == len(dated) and undated_document_count == 0:
            freshness_status = EvidenceFreshness.STALE
        elif stale_document_count > 0 or undated_document_count > 0:
            freshness_status = EvidenceFreshness.MIXED
        else:
            freshness_status = EvidenceFreshness.FRESH

        claims = list(self._claim_dicts(payload))
        material = [claim for claim in claims if float(claim.get("confidence", 0.0)) > 0.0]
        cited = [claim for claim in material if claim.get("evidence_refs")]
        citation_coverage = len(cited) / len(material) if material else 1.0

        high_confidence = [
            claim for claim in material if float(claim.get("confidence", 0.0)) >= 0.75
        ]
        cross_source = [
            claim
            for claim in high_confidence
            if len({ref.get("evidence_id") for ref in claim.get("evidence_refs", []) if ref.get("evidence_id")}) >= 2
        ]

        flags: list[str] = []
        abstention_reasons: list[str] = []
        if not evidence:
            abstention_reasons.append("No evidence documents were provided.")
        if len(present_required) < self.minimum_required_input_count():
            abstention_reasons.append(
                "Required source coverage is below the minimum: "
                f"{len(present_required)}/{self.minimum_required_input_count()} distinct required types."
            )
        if missing:
            flags.append(f"Missing required source types: {', '.join(missing)}.")
        if len(evidence) == 1:
            flags.append("Only one evidence document is available; cross-source validation is impossible.")
        if freshness_status == EvidenceFreshness.STALE:
            flags.append(
                f"All dated evidence is older than {self.max_evidence_age_days()} days."
            )
        elif freshness_status == EvidenceFreshness.MIXED:
            flags.append("Evidence freshness is mixed; one or more documents are stale or undated.")
        elif freshness_status == EvidenceFreshness.UNDATED and evidence:
            flags.append("Evidence is undated; freshness cannot be verified.")
        if not material:
            abstention_reasons.append("No cited material claims could be extracted from the evidence.")
        if citation_coverage < 1.0:
            abstention_reasons.append(
                f"Citation coverage is {citation_coverage:.0%}; every material claim should be cited."
            )
        if len(cross_source) < len(high_confidence):
            abstention_reasons.append(
                "One or more high-confidence claims lack cross-source confirmation."
            )

        if abstention_reasons:
            status = AnalysisStatus.ABSTAINED
        elif flags:
            status = AnalysisStatus.LIMITED
        else:
            status = AnalysisStatus.COMPLETE

        return EvidenceQuality(
            status=status,
            document_count=len(evidence),
            required_types=required,
            present_types=present,
            missing_required_types=missing,
            required_type_coverage=round(coverage, 3),
            freshness_status=freshness_status,
            newest_source_date=newest_source_date,
            stale_document_count=stale_document_count,
            undated_document_count=undated_document_count,
            material_claim_count=len(material),
            cited_material_claim_count=len(cited),
            citation_coverage=round(citation_coverage, 3),
            high_confidence_claim_count=len(high_confidence),
            cross_source_high_confidence_claim_count=len(cross_source),
            quality_flags=flags,
            abstention_reasons=abstention_reasons,
        )

    def _claim_dicts(self, value: object):
        """Yield nested claim dictionaries that expose confidence and citations."""
        if isinstance(value, dict):
            if "confidence" in value and "evidence_refs" in value:
                yield value
            for child in value.values():
                yield from self._claim_dicts(child)
        elif isinstance(value, list):
            for child in value:
                yield from self._claim_dicts(child)

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
