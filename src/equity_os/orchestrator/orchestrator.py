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
from .models import OrchestratorDecision
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

        all_evidence_ids = list(
            dict.fromkeys(
                industry.get("evidence_ids", []) + strategy.get("evidence_ids", [])
            )
        )

        return OrchestratorDecision(
            ticker=ticker,
            policy_version=self.policy.version,
            observations=obs,
            inferences=inf,
            decisions=dec,
            confidence_summary=conf_summary,
            industry_run_id=str(industry.get("run_id", "")),
            strategy_run_id=str(strategy.get("run_id", "")),
            evidence_ids=all_evidence_ids,
        )
