"""IndustryAgent — market structure, Porter forces, KPIs, regulatory, competitive dynamics.

Scope (enforced by design, not commentary)
------------------------------------------
- Market structure and cycle stage
- Porter's five forces (scored from evidence)
- Key industry KPIs (what to measure, not forecasts)
- Regulatory factors and jurisdictions
- Competitive dynamics (players, moat type, basis of competition)
- Industry-level risks

Out of scope (no output fields for these)
-----------------------------------------
- Company valuation
- Operating forecasts
- Management quality (only structural competitive dynamics)
"""

from __future__ import annotations

import re
from typing import Any

from equity_os.ingest.models import IngestedEvidence

from .base import BaseAgent
from .extraction import (
    avg_reliability,
    build_finding_from_scored,
    build_ref,
    compute_confidence,
    count_keyword_hits,
    extract_sentences_with_keywords,
    first_match,
    score_chunks,
)
from .models import (
    AnalysisStatus,
    AgentRunResult,
    CompetitiveDynamics,
    CycleStage,
    EvidenceRef,
    Finding,
    ForceLevel,
    IndustryAnalysis,
    IndustryKPI,
    IndustryRisk,
    MarketStructure,
    PorterForce,
    RegulatoryFactor,
)


# ---------------------------------------------------------------------------
# Keyword vocabularies
# ---------------------------------------------------------------------------

_RIVALRY_KW = [
    "competition", "competitive", "competitors", "rival", "rivalry",
    "market share", "intense", "price war", "undercutting",
]
_SUPPLIER_KW = [
    "supplier", "supply chain", "component", "semiconductor", "tsmc",
    "third-party manufacturer", "contract manufacturer", "input cost",
]
_BUYER_KW = [
    "customer", "switching cost", "lock-in", "churn", "retention",
    "customer concentration", "bargaining power", "buyer",
]
_ENTRY_KW = [
    "barrier", "entry barrier", "intellectual property", "patent",
    "brand loyalty", "ecosystem", "scale", "capital intensive",
]
_SUBSTITUTE_KW = [
    "substitute", "alternative", "disruptive", "disruption",
    "android", "other platforms", "competing platform", "cannibali",
]
_REGULATORY_KW = [
    "regulatory", "regulation", "compliance", "antitrust", "dma",
    "digital markets act", "gdpr", "ftc", "sec", "legislation", "law",
]
_GROWTH_KW = [
    "growing", "growth", "record", "increase", "expansion",
    "accelerating", "rising demand",
]
_DECLINE_KW = [
    "declining", "shrinking", "saturated", "saturation", "mature market",
    "peak", "contraction",
]
_OLIGOPOLY_KW = [
    "oligopoly", "concentrated", "few players", "duopoly",
    "dominant", "market leader",
]
_FRAGMENTED_KW = [
    "fragmented", "many players", "commoditized", "undifferentiated",
]
_KPI_KW = {
    "revenue_growth":       ["revenue grew", "revenue growth", "net sales", "top line"],
    "gross_margin":         ["gross margin", "gross profit margin"],
    "subscriber_count":     ["subscriber", "paid subscription", "active user"],
    "market_share":         ["market share", "share of"],
    "average_selling_price":["average selling price", "asp", "average price"],
}


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _force_level_from_hits(hits: int) -> ForceLevel:
    if hits >= 8:
        return ForceLevel.HIGH
    if hits >= 3:
        return ForceLevel.MEDIUM
    if hits >= 1:
        return ForceLevel.LOW
    return ForceLevel.UNKNOWN


def _extract_regulation(
    evidence: list[IngestedEvidence],
) -> list[RegulatoryFactor]:
    """Extract regulatory factors from evidence with citations."""
    REG_PATTERNS = [
        (r"Digital Markets Act|DMA", "EU Digital Markets Act", "European Union"),
        (r"GDPR|General Data Protection", "GDPR", "European Union"),
        (r"antitrust|anti-trust", "Antitrust Scrutiny", "Multiple jurisdictions"),
        (r"FTC|Federal Trade Commission", "FTC Review", "United States"),
        (r"sideloading", "App Sideloading Requirements", "European Union"),
        (r"privacy law|privacy regulation", "Privacy Regulation", "Multiple jurisdictions"),
        (r"tariff|trade restriction|import duty", "Trade Policy", "Global"),
        (r"CIK|SEC|EDGAR|Exchange Act", "SEC / EDGAR Reporting", "United States"),
    ]
    found: dict[str, RegulatoryFactor] = {}
    for ev in evidence:
        for chunk in ev.chunks:
            for pattern, name, jurisdiction in REG_PATTERNS:
                if name in found:
                    continue
                if re.search(pattern, chunk.text, re.IGNORECASE):
                    sents = extract_sentences_with_keywords(
                        chunk.text, [s.lower() for s in pattern.split("|")], 2
                    )
                    summary = sents[0] if sents else chunk.text[:200]
                    hits, _ = count_keyword_hits(evidence, pattern.split("|"))
                    conf = compute_confidence(
                        hits=hits,
                        source_count=1,
                        avg_reliability=ev.reliability_score,
                    )
                    found[name] = RegulatoryFactor(
                        name=name,
                        jurisdiction=jurisdiction,
                        impact_summary=summary,
                        severity="HIGH" if hits >= 3 else "MEDIUM",
                        finding=Finding(
                            text=summary,
                            confidence=conf,
                            evidence_refs=[build_ref(chunk, ev)],
                        ),
                    )
    return list(found.values())


def _extract_risks(evidence: list[IngestedEvidence]) -> list[IndustryRisk]:
    """Extract industry-level risks from risk-factor text."""
    RISK_PATTERNS = [
        (["competition", "competitive", "rival"], "Intense Competitive Rivalry", "competitive"),
        (["regulatory", "regulation", "compliance"], "Regulatory Headwinds", "regulatory"),
        (["supply chain", "supplier", "component"], "Supply Chain Concentration", "operational"),
        (["macroeconomic", "recession", "inflation", "interest rate"], "Macro Sensitivity", "macro"),
        (["technology", "disruptive", "obsolete"], "Technology Disruption", "technology"),
        (["demand", "consumer spending", "discretionary"], "Consumer Demand Cyclicality", "demand"),
        (["developer", "third-party developer", "ecosystem"], "Developer / Ecosystem Dependency", "competitive"),
    ]
    risks: list[IndustryRisk] = []
    seen: set[str] = set()
    for kws, name, category in RISK_PATTERNS:
        if name in seen:
            continue
        scored = score_chunks(evidence, kws, top_k=3)
        if not scored:
            continue
        conf, refs = build_finding_from_scored("", scored, evidence, kws)
        sents = extract_sentences_with_keywords(scored[0][0].text, kws, 2)
        text = sents[0] if sents else scored[0][0].text[:200]
        risks.append(IndustryRisk(
            name=name,
            category=category,
            finding=Finding(text=text, confidence=conf, evidence_refs=refs),
        ))
        seen.add(name)
    return risks[:6]


# ---------------------------------------------------------------------------
# IndustryAgent
# ---------------------------------------------------------------------------


class IndustryAgent(BaseAgent):
    """Analyses industry structure from ingested evidence.

    No company valuation. No management quality assessment unless directly
    evidence-based (e.g. competitive moat type from product description).
    """

    @property
    def agent_id(self) -> str:
        return "industry_v1"

    @property
    def agent_version(self) -> str:
        return "1.0"

    def required_inputs(self) -> list[str]:
        return ["filing", "earnings_transcript", "industry_note"]

    def minimum_required_input_count(self) -> int:
        # Industry structure should not be inferred from one company-controlled
        # source type. Require two distinct relevant source categories.
        return 2

    # ------------------------------------------------------------------
    # run()
    # ------------------------------------------------------------------

    def run(self, ticker: str, evidence: list[IngestedEvidence]) -> AgentRunResult:
        analysis = self._analyse(ticker, evidence)
        quality = self.assess_evidence_quality(
            evidence,
            analysis.model_dump(mode="json"),
        )
        if quality.status == AnalysisStatus.ABSTAINED:
            analysis = self._abstain(ticker, evidence, quality.abstention_reasons)
        else:
            analysis = analysis.model_copy(
                update={
                    "analysis_status": quality.status,
                    "evidence_quality": quality,
                    "abstention_reasons": [],
                }
            )
        memo = self.render_markdown(
            AgentRunResult(
                agent_id=self.agent_id,
                ticker=ticker,
                payload=analysis.model_dump(mode="json"),
                memo="",
            )
        )
        result = AgentRunResult(
            agent_id=self.agent_id,
            ticker=ticker,
            payload=analysis.model_dump(mode="json"),
            memo=memo,
            evidence_ids_consumed=[str(ev.evidence_id) for ev in evidence],
        )
        result.validation_errors = self.validate_output(result)
        return result

    def _abstain(
        self,
        ticker: str,
        evidence: list[IngestedEvidence],
        reasons: list[str],
    ) -> IndustryAnalysis:
        """Return a structurally valid result without unsupported conclusions."""
        text = "Agent abstained: " + " ".join(reasons)
        unknown_finding = Finding(text=text, confidence=0.0, evidence_refs=[])
        forces = [
            PorterForce(
                name=name,
                level=ForceLevel.UNKNOWN,
                summary=text,
                confidence=0.0,
                evidence_refs=[],
            )
            for name in (
                "Competitive Rivalry",
                "Supplier Power",
                "Buyer Power",
                "Threat of New Entry",
                "Threat of Substitutes",
            )
        ]
        quality = self.assess_evidence_quality(evidence, {})
        return IndustryAnalysis(
            ticker=ticker,
            analysis_status=AnalysisStatus.ABSTAINED,
            evidence_quality=quality,
            abstention_reasons=reasons,
            industry_label="Unknown",
            industry_label_finding=unknown_finding,
            market_structure=MarketStructure.UNKNOWN,
            market_structure_finding=unknown_finding,
            cycle_stage=CycleStage.UNKNOWN,
            cycle_stage_finding=unknown_finding,
            porter_forces=forces,
            key_kpis=[],
            regulatory_factors=[],
            competitive_dynamics=CompetitiveDynamics(
                concentration_finding=unknown_finding,
                moat_type=["unknown"],
                basis_of_competition=["unknown"],
                overall_confidence=0.0,
            ),
            top_risks=[],
            unresolved_questions=reasons,
            overall_confidence=0.0,
            evidence_ids=[str(ev.evidence_id) for ev in evidence],
        )

    # ------------------------------------------------------------------
    # Analysis logic
    # ------------------------------------------------------------------

    def _analyse(self, ticker: str, evidence: list[IngestedEvidence]) -> IndustryAnalysis:
        industry_label, industry_label_finding = self._infer_industry_label(evidence)

        # --- Market structure ---
        ms, ms_finding = self._market_structure(evidence)

        # --- Cycle stage ---
        cs, cs_finding = self._cycle_stage(evidence)

        # --- Porter forces ---
        forces = self._porter_forces(evidence)

        # --- KPIs ---
        kpis = self._key_kpis(evidence, ticker)

        # --- Regulatory ---
        regs = _extract_regulation(evidence)

        # --- Competitive dynamics ---
        dynamics = self._competitive_dynamics(evidence)

        # --- Risks ---
        risks = _extract_risks(evidence)

        # --- Unresolved ---
        unresolved = self._unresolved_questions(evidence)

        # --- Overall confidence ---
        all_confs = (
            [ms_finding.confidence, cs_finding.confidence, dynamics.overall_confidence]
            + [f.confidence for f in forces]
            + [k.finding.confidence for k in kpis]
        )
        overall = round(sum(all_confs) / max(len(all_confs), 1), 3)

        return IndustryAnalysis(
            ticker=ticker,
            industry_label=industry_label,
            industry_label_finding=industry_label_finding,
            market_structure=ms,
            market_structure_finding=ms_finding,
            cycle_stage=cs,
            cycle_stage_finding=cs_finding,
            porter_forces=forces,
            key_kpis=kpis,
            regulatory_factors=regs,
            competitive_dynamics=dynamics,
            top_risks=risks,
            unresolved_questions=unresolved,
            overall_confidence=overall,
            evidence_ids=[str(ev.evidence_id) for ev in evidence],
        )

    def _infer_industry_label(
        self,
        evidence: list[IngestedEvidence],
    ) -> tuple[str, Finding]:
        LABELS = [
            (["smartphone", "iphone", "handset"], "Consumer Electronics / Smartphone"),
            (["semiconductor", "chip", "processor"], "Semiconductors"),
            (["cloud", "saas", "software"], "Cloud / Software"),
            (["pharmaceutical", "drug", "fda"], "Pharmaceuticals"),
            (["bank", "lending", "deposit", "credit"], "Banking / Financial Services"),
            (["retail", "store", "e-commerce"], "Retail"),
            (["oil", "gas", "energy", "barrel"], "Energy"),
        ]
        scores = [
            (
                sum(count_keyword_hits(evidence, [keyword])[0] for keyword in keywords),
                label,
                keywords,
            )
            for keywords, label in LABELS
        ]
        ranked = sorted(scores, reverse=True)
        top_score, top_label, top_keywords = ranked[0]
        second_score = ranked[1][0]
        # Avoid a label based on an incidental word or an ambiguous tie.
        if top_score < 3 or (second_score > 0 and top_score < second_score * 1.25):
            return "Unknown", Finding(
                text="Industry label is ambiguous or insufficiently supported.",
                confidence=0.0,
                evidence_refs=[],
            )
        scored = score_chunks(evidence, top_keywords, top_k=4)
        confidence, refs = build_finding_from_scored(
            "",
            scored,
            evidence,
            top_keywords,
        )
        return top_label, Finding(
            text=f"Industry label supported by repeated {top_label} terminology.",
            confidence=confidence,
            evidence_refs=refs,
        )

    def _market_structure(
        self, evidence: list[IngestedEvidence]
    ) -> tuple[MarketStructure, Finding]:
        oligo_hits, oligo_ev = count_keyword_hits(evidence, _OLIGOPOLY_KW)
        frag_hits, frag_ev = count_keyword_hits(evidence, _FRAGMENTED_KW)

        scored = score_chunks(evidence, _RIVALRY_KW + _OLIGOPOLY_KW, top_k=4)
        if not scored:
            return MarketStructure.UNKNOWN, Finding(
                text="Insufficient evidence to determine market structure.",
                confidence=0.0,
            )

        conf, refs = build_finding_from_scored("", scored, evidence, _OLIGOPOLY_KW)
        sent = first_match(evidence, _OLIGOPOLY_KW + _RIVALRY_KW) or ""

        if oligo_hits >= frag_hits and oligo_hits > 0:
            ms = MarketStructure.OLIGOPOLY
            text = f"Evidence suggests oligopolistic market structure. {sent}".strip()
        elif frag_hits > oligo_hits:
            ms = MarketStructure.FRAGMENTED
            text = f"Evidence suggests fragmented market. {sent}".strip()
        else:
            ms = MarketStructure.COMPETITIVE
            text = f"Competitive market structure inferred from evidence. {sent}".strip()

        return ms, Finding(text=text, confidence=conf, evidence_refs=refs)

    def _cycle_stage(
        self, evidence: list[IngestedEvidence]
    ) -> tuple[CycleStage, Finding]:
        growth_hits, _ = count_keyword_hits(evidence, _GROWTH_KW)
        decline_hits, _ = count_keyword_hits(evidence, _DECLINE_KW)

        scored = score_chunks(evidence, _GROWTH_KW + _DECLINE_KW, top_k=4)
        if not scored or growth_hits + decline_hits < 2:
            return CycleStage.UNKNOWN, Finding(
                text="Insufficient evidence to determine industry cycle stage.",
                confidence=0.0,
                evidence_refs=[],
            )
        conf, refs = build_finding_from_scored("", scored, evidence, _GROWTH_KW)

        sent = first_match(evidence, _GROWTH_KW) or ""
        if growth_hits > decline_hits * 2:
            cs = CycleStage.GROWTH
            text = f"Industry is in a growth phase. {sent}".strip()
        elif decline_hits > growth_hits:
            cs = CycleStage.MATURE
            text = f"Industry shows signs of maturation or decline."
        else:
            cs = CycleStage.MATURE
            text = "Industry appears to be in a mature growth phase."
        return cs, Finding(text=text, confidence=conf, evidence_refs=refs)

    def _porter_force(
        self,
        name: str,
        keywords: list[str],
        evidence: list[IngestedEvidence],
        summary_template: str,
    ) -> PorterForce:
        hits, contributors = count_keyword_hits(evidence, keywords)
        level = _force_level_from_hits(hits)
        scored = score_chunks(evidence, keywords, top_k=3)
        conf, refs = build_finding_from_scored("", scored, evidence, keywords)
        sent = first_match(evidence, keywords)
        summary = summary_template.format(level=level.value, sent=sent or "")
        return PorterForce(
            name=name,
            level=level,
            summary=summary.strip(),
            confidence=conf,
            evidence_refs=refs,
        )

    def _porter_forces(self, evidence: list[IngestedEvidence]) -> list[PorterForce]:
        return [
            self._porter_force(
                "Competitive Rivalry",
                _RIVALRY_KW,
                evidence,
                "Competitive rivalry is {level}. {sent}",
            ),
            self._porter_force(
                "Supplier Power",
                _SUPPLIER_KW,
                evidence,
                "Supplier bargaining power is {level}. {sent}",
            ),
            self._porter_force(
                "Buyer Power",
                _BUYER_KW,
                evidence,
                "Buyer bargaining power is {level}. {sent}",
            ),
            self._porter_force(
                "Threat of New Entry",
                _ENTRY_KW,
                evidence,
                "Barriers to entry are {level}. {sent}",
            ),
            self._porter_force(
                "Threat of Substitutes",
                _SUBSTITUTE_KW,
                evidence,
                "Threat of substitutes is {level}. {sent}",
            ),
        ]

    def _key_kpis(
        self, evidence: list[IngestedEvidence], ticker: str
    ) -> list[IndustryKPI]:
        kpis: list[IndustryKPI] = []
        for kpi_name, kws in _KPI_KW.items():
            hits, contributors = count_keyword_hits(evidence, kws)
            if hits == 0:
                continue
            scored = score_chunks(evidence, kws, top_k=2)
            conf, refs = build_finding_from_scored("", scored, evidence, kws)
            sent = first_match(evidence, kws) or f"{kpi_name.replace('_', ' ').title()} mentioned in evidence."
            growth_hits, _ = count_keyword_hits(contributors, ["grew", "increase", "up", "record", "accelerat"])
            decline_hits, _ = count_keyword_hits(contributors, ["fell", "decline", "decrease", "down", "shrink"])
            direction = "increasing" if growth_hits > decline_hits else (
                "decreasing" if decline_hits > growth_hits else "stable"
            )
            kpis.append(IndustryKPI(
                name=kpi_name.replace("_", " ").title(),
                definition=f"Measure of {kpi_name.replace('_', ' ')} for the industry.",
                trend_direction=direction,
                finding=Finding(text=sent, confidence=conf, evidence_refs=refs),
            ))
        return kpis[:6]

    def _competitive_dynamics(
        self, evidence: list[IngestedEvidence]
    ) -> CompetitiveDynamics:
        # Concentration
        conc_scored = score_chunks(evidence, _OLIGOPOLY_KW + _RIVALRY_KW, top_k=4)
        conc_conf, conc_refs = build_finding_from_scored(
            "", conc_scored, evidence, _OLIGOPOLY_KW
        )
        conc_sent = first_match(evidence, _OLIGOPOLY_KW) or "Competitive landscape described in evidence."

        # Moat type detection
        MOAT_SIGNALS = {
            "switching_costs": ["switching cost", "lock-in", "ecosystem", "switching"],
            "brand":           ["brand", "brand loyalty", "premium brand", "brand recognition"],
            "network_effects": ["network effect", "platform", "user base"],
            "scale":           ["economies of scale", "scale advantage", "cost advantage"],
            "ip":              ["patent", "intellectual property", "proprietary"],
        }
        moats: list[str] = []
        for moat, kws in MOAT_SIGNALS.items():
            h, _ = count_keyword_hits(evidence, kws)
            if h >= 1:
                moats.append(moat)

        # Basis of competition
        BASIS_SIGNALS = {
            "ecosystem":     ["ecosystem", "platform"],
            "quality":       ["quality", "premium", "best-in-class"],
            "price":         ["price", "affordable", "cheaper", "low-cost"],
            "features":      ["feature", "innovation", "new product"],
            "distribution":  ["distribution", "retail", "channel"],
        }
        basis: list[str] = []
        for b, kws in BASIS_SIGNALS.items():
            h, _ = count_keyword_hits(evidence, kws)
            if h >= 1:
                basis.append(b)

        overall_conf = round(
            compute_confidence(
                hits=len(conc_scored),
                source_count=len({ev.evidence_id for _, ev, _ in conc_scored}),
                avg_reliability=avg_reliability(evidence),
            ), 3
        )
        return CompetitiveDynamics(
            concentration_finding=Finding(
                text=conc_sent,
                confidence=conc_conf,
                evidence_refs=conc_refs,
            ),
            moat_type=moats or ["unknown"],
            basis_of_competition=basis or ["unknown"],
            overall_confidence=overall_conf,
        )

    def _unresolved_questions(self, evidence: list[IngestedEvidence]) -> list[str]:
        questions: list[str] = []
        missing = self.missing_input_types(evidence)
        if "industry_note" in missing:
            questions.append(
                "No third-party industry research available; market structure assessment "
                "relies solely on company-reported disclosures."
            )
        if "channel_check_note" not in {ev.logical_type for ev in evidence}:
            questions.append(
                "No channel check data available; competitive sell-through dynamics unverified."
            )
        # Porter force gaps
        for name, kws in [("Supplier Power", _SUPPLIER_KW), ("Buyer Power", _BUYER_KW)]:
            hits, _ = count_keyword_hits(evidence, kws)
            if hits < 2:
                questions.append(
                    f"{name}: insufficient evidence to assign confidence — "
                    "suggest sourcing industry research or channel checks."
                )
        return questions

    # ------------------------------------------------------------------
    # validate_output
    # ------------------------------------------------------------------

    def validate_output(self, result: AgentRunResult) -> list[str]:
        errors: list[str] = []
        p = result.payload
        if not p.get("porter_forces"):
            errors.append("porter_forces is empty.")
        if len(p.get("porter_forces", [])) != 5:
            errors.append(f"Expected 5 Porter forces, got {len(p.get('porter_forces', []))}.")
        if not (0.0 <= p.get("overall_confidence", -1) <= 1.0):
            errors.append("overall_confidence out of range.")
        if "unresolved_questions" not in p:
            errors.append("unresolved_questions field missing.")
        if not p.get("industry_label"):
            errors.append("industry_label is empty.")
        if p.get("analysis_status") == AnalysisStatus.ABSTAINED.value and p.get("overall_confidence") != 0.0:
            errors.append("Abstained analysis must have zero overall confidence.")
        return errors

    # ------------------------------------------------------------------
    # render_markdown
    # ------------------------------------------------------------------

    def render_markdown(self, result: AgentRunResult) -> str:
        p = result.payload
        lines: list[str] = []
        conf_label = self._conf_label(p.get("overall_confidence", 0))

        lines += [
            f"# Industry Analysis — {p.get('ticker', result.ticker)}",
            f"",
            f"**Agent:** `{self.agent_id}` v{self.agent_version}  "
            f"**Status:** `{p.get('analysis_status', AnalysisStatus.COMPLETE.value)}`  "
            f"**Confidence:** {self._pct(p.get('overall_confidence', 0))} ({conf_label})  "
            f"**Generated:** {self._now()}",
            f"",
            f"> **Scope:** Market structure, Porter forces, KPIs, regulatory factors, competitive dynamics.  "
            f"No valuation. No operating forecast.",
            f"",
        ]

        quality = p.get("evidence_quality") or {}
        if p.get("analysis_status") != AnalysisStatus.COMPLETE.value:
            reasons = p.get("abstention_reasons") or quality.get("quality_flags", [])
            lines += [
                "> **Evidence gate:** " + (" ".join(reasons) if reasons else "Analysis is evidence-limited."),
                "",
            ]

        # Industry label + structure + cycle
        lines += [
            f"## Industry: {p.get('industry_label', 'N/A')}",
            f"",
            f"| Dimension | Finding | Confidence |",
            f"| --- | --- | --- |",
            f"| Market Structure | {p.get('market_structure', 'N/A')} | "
            f"{self._pct(p.get('market_structure_finding', {}).get('confidence', 0))} |",
            f"| Cycle Stage | {p.get('cycle_stage', 'N/A')} | "
            f"{self._pct(p.get('cycle_stage_finding', {}).get('confidence', 0))} |",
            f"",
        ]

        ms_text = p.get("market_structure_finding", {}).get("text", "")
        if ms_text:
            lines += [f"> {ms_text}", f""]
        cs_text = p.get("cycle_stage_finding", {}).get("text", "")
        if cs_text:
            lines += [f"> {cs_text}", f""]

        # Porter forces
        lines += ["## Porter's Five Forces", ""]
        lines += [
            "| Force | Intensity | Confidence | Summary |",
            "| --- | --- | --- | --- |",
        ]
        for force in p.get("porter_forces", []):
            lines.append(
                f"| {force['name']} | **{force['level']}** | "
                f"{self._pct(force['confidence'])} | {force['summary'][:80]}… |"
                if len(force.get("summary", "")) > 80
                else f"| {force['name']} | **{force['level']}** | "
                f"{self._pct(force['confidence'])} | {force.get('summary', '')} |"
            )
        lines.append("")

        # Regulatory factors
        regs = p.get("regulatory_factors", [])
        if regs:
            lines += [f"## Regulatory Factors ({len(regs)})", ""]
            for reg in regs:
                lines.append(
                    f"- **{reg['name']}** ({reg['jurisdiction']}) — "
                    f"Severity: {reg['severity']}  \n  "
                    f"_{reg.get('impact_summary', '')[:150]}_"
                )
            lines.append("")

        # Key KPIs
        kpis = p.get("key_kpis", [])
        if kpis:
            lines += ["## Key Industry KPIs", ""]
            for kpi in kpis:
                arrow = "↑" if kpi["trend_direction"] == "increasing" else (
                    "↓" if kpi["trend_direction"] == "decreasing" else "→"
                )
                lines.append(
                    f"- **{kpi['name']}** {arrow} _{kpi['trend_direction']}_  \n  "
                    f"{kpi['finding']['text'][:150]}"
                )
            lines.append("")

        # Competitive dynamics
        dyn = p.get("competitive_dynamics", {})
        if dyn:
            lines += [
                "## Competitive Dynamics",
                "",
                f"**Moat types detected:** {', '.join(dyn.get('moat_type', []))}",
                f"**Basis of competition:** {', '.join(dyn.get('basis_of_competition', []))}",
                f"**Confidence:** {self._pct(dyn.get('overall_confidence', 0))}",
                "",
                f"> {dyn.get('concentration_finding', {}).get('text', '')}",
                "",
            ]

        # Top risks
        risks = p.get("top_risks", [])
        if risks:
            lines += [f"## Top Industry Risks ({len(risks)})", ""]
            for risk in risks:
                conf = risk.get("finding", {}).get("confidence", 0)
                lines.append(
                    f"- **{risk['name']}** [{risk['category'].upper()}]  \n  "
                    f"_{risk.get('finding', {}).get('text', '')[:150]}_  \n  "
                    f"Confidence: {self._pct(conf)}"
                )
            lines.append("")

        # Unresolved
        unresolved = p.get("unresolved_questions", [])
        if unresolved:
            lines += ["## Unresolved Questions", ""]
            for q in unresolved:
                lines.append(f"- {q}")
            lines.append("")

        lines.append(f"---\n_Generated by `{self.agent_id}` on {self._now()}_")
        return "\n".join(lines)
