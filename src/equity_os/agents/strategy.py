"""CompanyStrategyAgent — management priorities, capital allocation, narrative shifts.

Scope (enforced by design)
--------------------------
- Management stated priorities (from disclosed material)
- Capital allocation: buybacks, dividends, capex, M&A — only from disclosures
- Narrative shifts: how messaging changed over time across evidence
- Risk disclosures: from risk factor sections
- Segment priorities: revenue emphasis and management framing
- Strategic positioning: moat type, target market, differentiation
- Management credibility signals: evidence-based only (guidance beat/miss)

Out of scope (no output fields)
--------------------------------
- Operating forecasts
- Valuation / price targets
- Inferred management quality beyond disclosed material
"""

from __future__ import annotations

import re
from collections import defaultdict
from datetime import datetime, timezone

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
    AgentRunResult,
    CapitalAllocationItem,
    CredibilitySignal,
    DisclosedRisk,
    EvidenceRef,
    Finding,
    NarrativeShift,
    SegmentPriority,
    StrategicPositioning,
    CompanyStrategyAnalysis,
)


# ---------------------------------------------------------------------------
# Keyword vocabularies
# ---------------------------------------------------------------------------

_BUYBACK_KW = ["repurchase", "buyback", "share repurchase", "buy back", "returned to shareholders"]
_DIVIDEND_KW = ["dividend", "dividends", "dividend payment"]
_CAPEX_KW = ["capital expenditure", "capex", "capital investment", "property plant", "infrastructure spend"]
_MA_KW = ["acquisition", "acquire", "merger", "inorganic growth", "m&a"]
_DEBT_KW = ["debt", "bond", "leverage", "borrowing", "long-term note"]

_MGMT_PRIORITY_KW = [
    "strategic priority", "focus", "invest in", "committed to",
    "our priority", "long-term growth", "strategic initiative",
    "structural driver", "we expect", "confident in",
    "continue to grow", "double-digit", "growth opportunity",
    "we're pleased", "record revenue", "all-time record",
    "expanding", "priorit", "key initiative",
]

_RISK_CATEGORIES = {
    "regulatory":   ["regulatory", "regulation", "compliance", "dma", "antitrust", "legislation"],
    "competitive":  ["competition", "competitive", "rival", "market share", "pricing pressure"],
    "operational":  ["supply chain", "supplier", "manufacturing", "operational", "third-party"],
    "macro":        ["macroeconomic", "recession", "inflation", "interest rate", "currency", "fx"],
    "financial":    ["liquidity", "credit", "debt", "capital market", "interest expense"],
    "technology":   ["technology", "disruption", "obsolete", "platform risk"],
}

_SEGMENT_NAMES = {
    "iphone":     ["iphone", "smartphone"],
    "services":   ["services", "subscription", "app store", "apple music", "icloud"],
    "mac":        ["mac", "macbook", "desktop"],
    "ipad":       ["ipad", "tablet"],
    "wearables":  ["apple watch", "airpods", "wearables", "watch"],
}

_CREDIBILITY_SIGNALS = {
    "guidance_beat":   ["exceeded", "beat", "above expectations", "surpassed", "better than expected"],
    "guidance_miss":   ["below", "missed", "shortfall", "fell short", "disappointed"],
    "strategic_consistency": ["continued", "as planned", "consistent with", "on track"],
    "reversal":        ["pivot", "change in direction", "revised strategy", "no longer", "discontinued"],
}

_STRATEGIC_MARKET = {
    "premium":       ["premium", "high-end", "luxury", "best-in-class"],
    "enterprise":    ["enterprise", "business customer", "corporate", "b2b"],
    "mass_market":   ["affordable", "mainstream", "budget", "mass market"],
}
_DIFFERENTIATION = {
    "ecosystem":            ["ecosystem", "platform", "app store", "services bundle"],
    "brand":                ["brand", "brand loyalty", "brand recognition"],
    "vertical_integration": ["in-house", "proprietary chip", "m-series", "silicon", "vertical"],
    "quality":              ["quality", "premium hardware", "build quality"],
    "price":                ["competitive pricing", "price cut", "aggressive price"],
}


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _extract_mgmt_priorities(evidence: list[IngestedEvidence]) -> list[Finding]:
    """Pull stated management priorities from earnings transcripts and filings."""
    findings: list[Finding] = []
    seen: set[str] = set()
    scored = score_chunks(
        evidence, _MGMT_PRIORITY_KW, top_k=10,
        logical_types=["earnings_transcript", "management_commentary"],
    )
    for chunk, ev, score in scored:
        sents = extract_sentences_with_keywords(chunk.text, _MGMT_PRIORITY_KW, 2)
        for sent in sents:
            key = sent[:60].lower()
            if key in seen or len(sent.strip()) < 30:
                continue
            seen.add(key)
            hits, _ = count_keyword_hits([ev], _MGMT_PRIORITY_KW)
            conf = compute_confidence(hits, 1, ev.reliability_score)
            findings.append(Finding(
                text=sent.strip(),
                confidence=conf,
                evidence_refs=[build_ref(chunk, ev)],
            ))
    # Always also pull from filing to supplement transcript
    if len(findings) < 3:
        scored_f = score_chunks(evidence, _MGMT_PRIORITY_KW, top_k=5, logical_types=["filing"])
        for chunk, ev, _ in scored_f:
            sents = extract_sentences_with_keywords(chunk.text, _MGMT_PRIORITY_KW, 1)
            for sent in sents:
                key = sent[:60].lower()
                if key in seen:
                    continue
                seen.add(key)
                hits, _ = count_keyword_hits([ev], _MGMT_PRIORITY_KW)
                findings.append(Finding(
                    text=sent.strip(),
                    confidence=compute_confidence(hits, 1, ev.reliability_score) * 0.8,
                    evidence_refs=[build_ref(chunk, ev)],
                ))
    return findings[:6]


def _extract_capital_allocation(evidence: list[IngestedEvidence]) -> list[CapitalAllocationItem]:
    items: list[CapitalAllocationItem] = []
    CATS = [
        ("buybacks",  _BUYBACK_KW,  "Share repurchases"),
        ("dividends", _DIVIDEND_KW, "Dividend payments"),
        ("capex",     _CAPEX_KW,    "Capital expenditure"),
        ("m_and_a",   _MA_KW,       "M&A / acquisitions"),
        ("debt",      _DEBT_KW,     "Debt / leverage"),
    ]
    for category, kws, label in CATS:
        hits, contributors = count_keyword_hits(evidence, kws)
        if hits == 0:
            continue
        scored = score_chunks(evidence, kws, top_k=3)
        conf, refs = build_finding_from_scored("", scored, evidence, kws)
        sent = first_match(evidence, kws) or f"{label} mentioned in disclosures."
        # Try to extract a dollar figure
        from .extraction import extract_dollar_amounts
        amounts: list[str] = []
        for chunk, ev, _ in scored:
            amounts.extend(extract_dollar_amounts(chunk.text))
        mag = amounts[0] if amounts else "not quantified"
        items.append(CapitalAllocationItem(
            category=category,
            finding=Finding(text=sent, confidence=conf, evidence_refs=refs),
            magnitude_hint=mag,
        ))
    return items


def _extract_narrative_shifts(evidence: list[IngestedEvidence]) -> list[NarrativeShift]:
    """Compare topic emphasis between the oldest and newest evidence."""
    if len(evidence) < 2:
        return []

    def _safe_date(ev: IngestedEvidence):
        return ev.source_date or ev.ingested_at.date()

    sorted_ev = sorted(evidence, key=_safe_date)
    old_ev = sorted_ev[:max(1, len(sorted_ev) // 2)]
    new_ev = sorted_ev[len(sorted_ev) // 2:]

    TOPICS = {
        "services_growth":  ["services", "subscription", "services revenue"],
        "india_expansion":  ["india", "emerging market"],
        "regulatory_risk":  ["regulation", "dma", "regulatory"],
        "ai_investment":    ["ai", "artificial intelligence", "machine learning"],
        "margin_expansion": ["gross margin", "margin expansion", "operating leverage"],
    }
    shifts: list[NarrativeShift] = []
    for topic, kws in TOPICS.items():
        old_hits, _ = count_keyword_hits(old_ev, kws)
        new_hits, _ = count_keyword_hits(new_ev, kws)
        if old_hits == 0 and new_hits == 0:
            continue

        # Normalize by word count
        old_words = sum(len(chunk.text.split()) for ev in old_ev for chunk in ev.chunks)
        new_words = sum(len(chunk.text.split()) for ev in new_ev for chunk in ev.chunks)
        old_density = old_hits / max(old_words / 1000, 0.1)
        new_density = new_hits / max(new_words / 1000, 0.1)

        ratio = new_density / max(old_density, 0.001)
        if ratio > 1.5:
            shift_type = "emphasis_increase"
        elif ratio < 0.5:
            shift_type = "emphasis_decrease"
        else:
            continue  # not a meaningful shift

        old_sent = first_match(old_ev, kws) or f"{topic} mentioned in older evidence."
        new_sent = first_match(new_ev, kws) or f"{topic} mentioned in newer evidence."

        old_scored = score_chunks(old_ev, kws, top_k=2)
        new_scored = score_chunks(new_ev, kws, top_k=2)
        old_refs = [build_ref(c, e) for c, e, _ in old_scored]
        new_refs = [build_ref(c, e) for c, e, _ in new_scored]

        conf = round(min(0.85, abs(ratio - 1.0) * 0.4 + 0.30), 3)
        shifts.append(NarrativeShift(
            topic=topic.replace("_", " ").title(),
            old_framing=old_sent[:200],
            new_framing=new_sent[:200],
            shift_type=shift_type,
            confidence=conf,
            old_evidence_refs=old_refs,
            new_evidence_refs=new_refs,
        ))
    return shifts[:5]


def _extract_disclosed_risks(evidence: list[IngestedEvidence]) -> list[DisclosedRisk]:
    risks: list[DisclosedRisk] = []
    seen: set[str] = set()
    for category, kws in _RISK_CATEGORIES.items():
        scored = score_chunks(evidence, kws, top_k=3)
        if not scored:
            continue
        conf, refs = build_finding_from_scored("", scored, evidence, kws)
        sent = first_match(evidence, kws) or f"{category.title()} risk mentioned."
        key = sent[:50].lower()
        if key in seen:
            continue
        seen.add(key)

        # Assess severity from proximity to strong language
        chunk_text = scored[0][0].text.lower()
        severe_words = ["significant", "material", "substantial", "major", "severe", "could adversely"]
        severity = "explicit" if any(w in chunk_text for w in severe_words) else "mentioned"
        risks.append(DisclosedRisk(
            name=f"{category.title()} Risk",
            category=category,
            severity_from_disclosure=severity,
            finding=Finding(text=sent, confidence=conf, evidence_refs=refs),
        ))
    return risks[:7]


def _extract_segment_priorities(evidence: list[IngestedEvidence]) -> list[SegmentPriority]:
    segment_hits: dict[str, tuple[int, list]] = {}
    for seg, kws in _SEGMENT_NAMES.items():
        hits, contributors = count_keyword_hits(evidence, kws)
        if hits > 0:
            segment_hits[seg] = (hits, contributors)

    if not segment_hits:
        return []

    ranked = sorted(segment_hits.items(), key=lambda x: x[1][0], reverse=True)
    results: list[SegmentPriority] = []
    for rank, (seg, (hits, contributors)) in enumerate(ranked, 1):
        kws = _SEGMENT_NAMES[seg]
        scored = score_chunks(evidence, kws, top_k=2)
        conf, refs = build_finding_from_scored("", scored, evidence, kws)
        growth_hits, _ = count_keyword_hits(contributors, ["grew", "record", "growth", "strong", "accelerat"])
        framing = "growth" if growth_hits > 0 else "stable"
        sent = first_match(evidence, kws) or f"{seg.title()} segment mentioned in evidence."
        results.append(SegmentPriority(
            segment_name=seg.title(),
            priority_rank=rank,
            growth_framing=framing,
            finding=Finding(text=sent, confidence=conf, evidence_refs=refs),
        ))
    return results[:6]


def _extract_strategic_positioning(
    evidence: list[IngestedEvidence],
) -> StrategicPositioning:
    # Target market
    market_scores: dict[str, int] = {}
    for market, kws in _STRATEGIC_MARKET.items():
        h, _ = count_keyword_hits(evidence, kws)
        market_scores[market] = h
    target = max(market_scores, key=lambda k: market_scores[k]) if market_scores else "unknown"

    # Differentiation
    diff_axes: list[str] = []
    for axis, kws in _DIFFERENTIATION.items():
        h, _ = count_keyword_hits(evidence, kws)
        if h >= 1:
            diff_axes.append(axis)

    # Moat
    MOAT_KWS = {
        "switching_costs": ["switching cost", "ecosystem lock-in", "switching"],
        "brand":           ["brand", "brand loyalty"],
        "network_effects": ["network effect", "platform"],
        "scale":           ["economies of scale", "scale"],
        "ip":              ["patent", "intellectual property"],
    }
    moat_list: list[str] = []
    for moat, kws in MOAT_KWS.items():
        h, _ = count_keyword_hits(evidence, kws)
        if h >= 1:
            moat_list.append(moat)

    all_kws = (
        list(_STRATEGIC_MARKET.values())[0]
        + list(_DIFFERENTIATION.values())[0]
    )
    scored = score_chunks(evidence, all_kws, top_k=3)
    conf, refs = build_finding_from_scored("", scored, evidence, all_kws)
    sent = first_match(evidence, list(_DIFFERENTIATION.values())[0]) or "Strategic positioning inferred from evidence."
    return StrategicPositioning(
        target_market=target,
        differentiation_axes=diff_axes or ["unknown"],
        moat_assessment=moat_list or ["unknown"],
        finding=Finding(text=sent, confidence=conf, evidence_refs=refs),
    )


def _extract_credibility_signals(evidence: list[IngestedEvidence]) -> list[CredibilitySignal]:
    signals: list[CredibilitySignal] = []
    for sig_type, kws in _CREDIBILITY_SIGNALS.items():
        scored = score_chunks(
            evidence, kws, top_k=2,
            logical_types=["earnings_transcript", "management_commentary"],
        )
        if not scored:
            continue
        conf, refs = build_finding_from_scored("", scored, evidence, kws)
        sent = first_match(evidence, kws, logical_types=["earnings_transcript", "management_commentary"])
        if not sent:
            continue
        signals.append(CredibilitySignal(
            signal_type=sig_type,
            description=sent[:200],
            finding=Finding(text=sent, confidence=conf, evidence_refs=refs),
        ))
    return signals[:5]


# ---------------------------------------------------------------------------
# CompanyStrategyAgent
# ---------------------------------------------------------------------------


class CompanyStrategyAgent(BaseAgent):
    """Analyses company strategy from management disclosures.

    No operating forecasts. No valuation. Credibility signals must be
    grounded in disclosed material only.
    """

    @property
    def agent_id(self) -> str:
        return "strategy_v1"

    @property
    def agent_version(self) -> str:
        return "1.0"

    def required_inputs(self) -> list[str]:
        return ["filing", "earnings_transcript"]

    def run(self, ticker: str, evidence: list[IngestedEvidence]) -> AgentRunResult:
        analysis = self._analyse(ticker, evidence)
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

    def _analyse(self, ticker: str, evidence: list[IngestedEvidence]) -> CompanyStrategyAnalysis:
        priorities = _extract_mgmt_priorities(evidence)
        cap_alloc = _extract_capital_allocation(evidence)
        shifts = _extract_narrative_shifts(evidence)
        risks = _extract_disclosed_risks(evidence)
        segments = _extract_segment_priorities(evidence)
        positioning = _extract_strategic_positioning(evidence)
        credibility = _extract_credibility_signals(evidence)
        unresolved = self._unresolved_questions(evidence, priorities, risks)

        all_confs = (
            [f.confidence for f in priorities]
            + [a.finding.confidence for a in cap_alloc]
            + [r.finding.confidence for r in risks]
            + [s.finding.confidence for s in segments]
            + [positioning.finding.confidence]
        )
        overall = round(sum(all_confs) / max(len(all_confs), 1), 3)

        return CompanyStrategyAnalysis(
            ticker=ticker,
            management_priorities=priorities,
            capital_allocation=cap_alloc,
            narrative_shifts=shifts,
            risk_disclosures=risks,
            segment_priorities=segments,
            strategic_positioning=positioning,
            mgmt_credibility_signals=credibility,
            unresolved_questions=unresolved,
            overall_confidence=overall,
            evidence_ids=[str(ev.evidence_id) for ev in evidence],
        )

    def _unresolved_questions(
        self,
        evidence: list[IngestedEvidence],
        priorities: list[Finding],
        risks: list[DisclosedRisk],
    ) -> list[str]:
        questions: list[str] = []
        missing = self.missing_input_types(evidence)
        if "earnings_transcript" in missing:
            questions.append(
                "No earnings transcript available; management priorities inferred from "
                "filing disclosures only, which may be more conservative / lagged."
            )
        if "management_commentary" not in {ev.logical_type for ev in evidence}:
            questions.append(
                "No standalone management commentary available; "
                "strategic framing relies on structured disclosures."
            )
        if len(priorities) < 2:
            questions.append(
                "Fewer than 2 explicit management priorities identified; "
                "evidence may be sparse or priorities not clearly stated."
            )
        cap_cats = {"buybacks", "dividends", "capex"}
        # Check capital allocation coverage
        hits, _ = count_keyword_hits(evidence, _CAPEX_KW)
        if hits < 2:
            questions.append(
                "Capex guidance not clearly disclosed; capital intensity assessment limited."
            )
        return questions

    def validate_output(self, result: AgentRunResult) -> list[str]:
        errors: list[str] = []
        p = result.payload
        # management_priorities may be empty for sparse evidence — that's OK if noted
        if not p.get("management_priorities") and not p.get("unresolved_questions"):
            errors.append("management_priorities is empty and no unresolved_questions noted.")
        if not p.get("risk_disclosures"):
            errors.append("risk_disclosures is empty.")
        if not p.get("segment_priorities"):
            errors.append("segment_priorities is empty.")
        if not (0.0 <= p.get("overall_confidence", -1) <= 1.0):
            errors.append("overall_confidence out of range.")
        if "unresolved_questions" not in p:
            errors.append("unresolved_questions field missing.")
        positioning = p.get("strategic_positioning", {})
        if not positioning.get("target_market"):
            errors.append("strategic_positioning.target_market is empty.")
        return errors

    def render_markdown(self, result: AgentRunResult) -> str:
        p = result.payload
        lines: list[str] = []
        conf_label = self._conf_label(p.get("overall_confidence", 0))

        lines += [
            f"# Company Strategy Analysis — {p.get('ticker', result.ticker)}",
            f"",
            f"**Agent:** `{self.agent_id}` v{self.agent_version}  "
            f"**Confidence:** {self._pct(p.get('overall_confidence', 0))} ({conf_label})  "
            f"**Generated:** {self._now()}",
            f"",
            f"> **Scope:** Management priorities, capital allocation, narrative shifts, "
            f"risk disclosures, segment priorities, strategic positioning.  "
            f"No operating forecast. No valuation.",
            f"",
        ]

        # Management priorities
        prios = p.get("management_priorities", [])
        lines += [f"## Management Priorities ({len(prios)} identified)", ""]
        if prios:
            for i, f in enumerate(prios, 1):
                conf = f.get("confidence", 0)
                lines.append(
                    f"{i}. {f.get('text', '')}  \n   "
                    f"_Confidence: {self._pct(conf)} ({self._conf_label(conf)})_"
                )
        else:
            lines.append("_No explicit management priorities extracted from available evidence._")
        lines.append("")

        # Capital allocation
        cap = p.get("capital_allocation", [])
        if cap:
            lines += ["## Capital Allocation", "", "| Category | Magnitude | Confidence | Finding |",
                      "| --- | --- | --- | --- |"]
            for item in cap:
                conf = item.get("finding", {}).get("confidence", 0)
                text = item.get("finding", {}).get("text", "")[:80]
                lines.append(
                    f"| {item['category']} | {item.get('magnitude_hint', '—')} | "
                    f"{self._pct(conf)} | {text}… |"
                    if len(item.get("finding", {}).get("text", "")) > 80
                    else f"| {item['category']} | {item.get('magnitude_hint', '—')} | "
                    f"{self._pct(conf)} | {text} |"
                )
            lines.append("")

        # Segment priorities
        segs = p.get("segment_priorities", [])
        if segs:
            lines += ["## Segment Priorities", "", "| Rank | Segment | Growth Framing | Confidence |",
                      "| --- | --- | --- | --- |"]
            for seg in segs:
                conf = seg.get("finding", {}).get("confidence", 0)
                lines.append(
                    f"| #{seg['priority_rank']} | **{seg['segment_name']}** | "
                    f"{seg.get('growth_framing', 'N/A')} | {self._pct(conf)} |"
                )
            lines.append("")

        # Strategic positioning
        pos = p.get("strategic_positioning", {})
        if pos:
            lines += [
                "## Strategic Positioning",
                "",
                f"**Target market:** {pos.get('target_market', 'N/A')}",
                f"**Differentiation:** {', '.join(pos.get('differentiation_axes', []))}",
                f"**Moat assessment:** {', '.join(pos.get('moat_assessment', []))}",
                f"**Confidence:** {self._pct(pos.get('finding', {}).get('confidence', 0))}",
                "",
                f"> {pos.get('finding', {}).get('text', '')}",
                "",
            ]

        # Narrative shifts
        shifts = p.get("narrative_shifts", [])
        if shifts:
            lines += [f"## Narrative Shifts ({len(shifts)} detected)", ""]
            for shift in shifts:
                arrow = "↑" if shift["shift_type"] == "emphasis_increase" else "↓"
                lines += [
                    f"### {shift['topic']} {arrow}",
                    f"**Type:** {shift['shift_type']}  "
                    f"**Confidence:** {self._pct(shift.get('confidence', 0))}",
                    f"- _Earlier framing:_ {shift.get('old_framing', '')[:150]}",
                    f"- _Recent framing:_ {shift.get('new_framing', '')[:150]}",
                    "",
                ]

        # Risk disclosures
        risks = p.get("risk_disclosures", [])
        if risks:
            lines += [f"## Disclosed Risks ({len(risks)})", ""]
            for risk in risks:
                conf = risk.get("finding", {}).get("confidence", 0)
                lines.append(
                    f"- **{risk['name']}** [{risk['category'].upper()}] "
                    f"— {risk.get('severity_from_disclosure', '').upper()}  \n  "
                    f"_{risk.get('finding', {}).get('text', '')[:150]}_  \n  "
                    f"Confidence: {self._pct(conf)}"
                )
            lines.append("")

        # Credibility signals
        sigs = p.get("mgmt_credibility_signals", [])
        if sigs:
            lines += [f"## Management Credibility Signals ({len(sigs)})", ""]
            for sig in sigs:
                conf = sig.get("finding", {}).get("confidence", 0)
                lines.append(
                    f"- **{sig['signal_type']}**: {sig.get('description', '')[:150]}  \n  "
                    f"_Confidence: {self._pct(conf)}_"
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
