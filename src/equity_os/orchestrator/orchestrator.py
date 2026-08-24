"""Orchestrator — entry point for the synthesis layer.

Usage
-----
    from equity_os.orchestrator.orchestrator import Orchestrator
    from equity_os.orchestrator.policy import OrchestratorPolicy

    policy = OrchestratorPolicy.load()
    orch = Orchestrator(policy=policy)
    decision = orch.run(
        ticker="AAPL",
        industry=industry_result.payload,
        strategy=strategy_result.payload,
        assumptions=[a.model_dump() for a in ledger],
        prior_thesis=prior_episode.model_dump() if prior_episode else None,
        change_log=log.model_dump() if log else None,
    )
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .conflict import detect_conflicts
from .models import OrchestratorDecision, SynthesisStatus
from .policy import OrchestratorPolicy
from .synthesis import (
    build_confidence_summary,
    build_decision_layer,
    build_inference_layer,
    build_observation_layer,
    compute_freshness_penalty,
)


class Orchestrator:
    """Synthesises specialist agent outputs into an OrchestratorDecision.

    The orchestrator does NOT call agents directly — it consumes their already-run
    payload dicts.  This keeps it testable without running the full agent stack.
    """

    MIN_SYNTHESIS_CONFIDENCE = 0.25

    def __init__(self, policy: OrchestratorPolicy | None = None) -> None:
        self.policy = policy or OrchestratorPolicy.load()

    def run(
        self,
        ticker: str,
        industry: dict[str, Any],
        strategy: dict[str, Any],
        assumptions: list[dict[str, Any]] | None = None,
        prior_thesis: dict[str, Any] | None = None,
        change_log: dict[str, Any] | None = None,
    ) -> OrchestratorDecision:
        """Run synthesis and return a full OrchestratorDecision.

        Parameters
        ----------
        ticker       : company ticker symbol
        industry     : IndustryAnalysis.model_dump(mode="json")
        strategy     : CompanyStrategyAnalysis.model_dump(mode="json")
        assumptions  : list of AssumptionRecord.model_dump() — the current ledger
        prior_thesis : ThesisEpisode.model_dump() from the prior episode, if any
        change_log   : ChangeLog.model_dump() from the diff engine, if any
        """
        assumptions = assumptions or []

        # --- Freshness penalties (applied before weighting) ---
        ind_freshness = compute_freshness_penalty(industry, self.policy)
        str_freshness = compute_freshness_penalty(strategy, self.policy)

        # --- Adjusted agent confidences ---
        ind_base = float(industry.get("overall_confidence", 0.5))
        str_base = float(strategy.get("overall_confidence", 0.5))
        ind_adj = max(ind_base - ind_freshness, 0.05)
        str_adj = max(str_base - str_freshness, 0.05)

        # --- Cross-agent conflict detection ---
        conflicts = detect_conflicts(industry, strategy, self.policy)

        # --- Layer 1: Observations ---
        obs = build_observation_layer(
            industry=industry,
            strategy=strategy,
            assumptions=assumptions,
            prior_thesis=prior_thesis,
            change_log=change_log,
            policy=self.policy,
            ind_freshness_penalty=ind_freshness,
            str_freshness_penalty=str_freshness,
        )

        # --- Layer 2: Inferences ---
        inf = build_inference_layer(
            obs=obs,
            industry=industry,
            strategy=strategy,
            assumptions=assumptions,
            conflicts=conflicts,
            policy=self.policy,
            ind_adj_conf=ind_adj,
            str_adj_conf=str_adj,
        )

        # --- Confidence summary ---
        conf_summary = build_confidence_summary(
            ind_base=ind_base,
            str_base=str_base,
            ind_freshness=ind_freshness,
            str_freshness=str_freshness,
            conflicts=conflicts,
            policy=self.policy,
            assumptions=assumptions,
        )

        # --- Layer 3: Decisions ---
        dec = build_decision_layer(
            obs=obs,
            inf=inf,
            industry=industry,
            strategy=strategy,
            policy=self.policy,
            overall_conf=conf_summary.overall,
        )

        synthesis_status, abstention_reasons = self._synthesis_gate(
            industry=industry,
            strategy=strategy,
            overall_confidence=conf_summary.overall,
            freshness_penalty=conf_summary.freshness_penalty,
            has_conflicts=bool(conflicts),
        )
        if synthesis_status == SynthesisStatus.ABSTAINED:
            message = "Insufficient evidence to synthesize an investment thesis."
            inf = inf.model_copy(
                update={
                    "thesis_statement": message,
                    "variant_view": "Not assessed because the evidence gate did not pass.",
                    "top_drivers": [],
                    "cross_validated": [],
                    "unresolved_conflicts": list(
                        dict.fromkeys([*abstention_reasons, *inf.unresolved_conflicts])
                    ),
                }
            )
            dec = dec.model_copy(
                update={
                    "current_thesis": message,
                    "rating_stance": "not_rated",
                    "predictions": [],
                    "falsification_conditions": [],
                    "monitoring_triggers": [],
                    "next_evidence_needed": list(
                        dict.fromkeys([*abstention_reasons, *dec.next_evidence_needed])
                    ),
                    "unresolved_conflicts": list(
                        dict.fromkeys([*abstention_reasons, *dec.unresolved_conflicts])
                    ),
                }
            )

        all_evidence_ids = list(
            dict.fromkeys(
                industry.get("evidence_ids", []) + strategy.get("evidence_ids", [])
            )
        )

        return OrchestratorDecision(
            ticker=ticker,
            policy_version=self.policy.version,
            synthesis_status=synthesis_status,
            abstention_reasons=abstention_reasons,
            observations=obs,
            inferences=inf,
            decisions=dec,
            confidence_summary=conf_summary,
            industry_run_id=str(industry.get("run_id", "")),
            strategy_run_id=str(strategy.get("run_id", "")),
            evidence_ids=all_evidence_ids,
        )

    def _synthesis_gate(
        self,
        industry: dict[str, Any],
        strategy: dict[str, Any],
        overall_confidence: float,
        freshness_penalty: float,
        has_conflicts: bool,
    ) -> tuple[SynthesisStatus, list[str]]:
        """Prevent thesis synthesis when a specialist or confidence gate fails."""
        reasons: list[str] = []
        statuses = {
            "industry": str(industry.get("analysis_status", "COMPLETE")),
            "strategy": str(strategy.get("analysis_status", "COMPLETE")),
        }

        for name, payload in (("industry", industry), ("strategy", strategy)):
            inferred_abstention = (
                not payload.get("evidence_ids")
                and float(payload.get("overall_confidence", 0.0)) <= 0.05
            )
            if statuses[name] == "ABSTAINED" or inferred_abstention:
                reasons.append(f"The {name} analysis abstained due to insufficient evidence.")
                reasons.extend(str(reason) for reason in payload.get("abstention_reasons", []))

        if str(industry.get("industry_label", "")).lower() in {"", "unknown"}:
            reasons.append("The industry label is unresolved.")
        if str(industry.get("market_structure", "UNKNOWN")) == "UNKNOWN":
            reasons.append("Market structure is unresolved.")
        if str(industry.get("cycle_stage", "UNKNOWN")) == "UNKNOWN":
            reasons.append("Industry cycle stage is unresolved.")

        positioning = strategy.get("strategic_positioning", {})
        if (
            not strategy.get("management_priorities")
            and str(positioning.get("target_market", "unknown")).lower() in {"", "unknown"}
        ):
            reasons.append("Company strategy and positioning are unresolved.")

        if overall_confidence < self.MIN_SYNTHESIS_CONFIDENCE:
            reasons.append(
                f"Overall confidence {overall_confidence:.0%} is below the "
                f"{self.MIN_SYNTHESIS_CONFIDENCE:.0%} synthesis threshold."
            )

        if reasons:
            return SynthesisStatus.ABSTAINED, list(dict.fromkeys(reasons))

        if (
            "LIMITED" in statuses.values()
            or freshness_penalty >= 0.10
            or has_conflicts
        ):
            return SynthesisStatus.LIMITED, []
        return SynthesisStatus.COMPLETE, []
