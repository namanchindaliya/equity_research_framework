"""All enumerations for equity_os schemas."""

from __future__ import annotations

from enum import Enum


# ---------------------------------------------------------------------------
# Legacy enums (v0 — kept for backward compat)
# ---------------------------------------------------------------------------


class Rating(str, Enum):
    BUY = "BUY"
    HOLD = "HOLD"
    SELL = "SELL"
    NOT_RATED = "NOT_RATED"


class EpisodeStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class AssumptionStatus(str, Enum):
    ACTIVE = "ACTIVE"
    REVISED = "REVISED"
    RETIRED = "RETIRED"


class PredictionOutcome(str, Enum):
    PENDING = "PENDING"
    CORRECT = "CORRECT"
    INCORRECT = "INCORRECT"
    INCONCLUSIVE = "INCONCLUSIVE"


# ---------------------------------------------------------------------------
# Source / evidence
# ---------------------------------------------------------------------------


class SourceType(str, Enum):
    FILING = "FILING"                  # SEC / regulatory filing
    EARNINGS_CALL = "EARNINGS_CALL"
    PRESS_RELEASE = "PRESS_RELEASE"
    NEWS_ARTICLE = "NEWS_ARTICLE"
    RESEARCH_REPORT = "RESEARCH_REPORT"
    CHANNEL_CHECK = "CHANNEL_CHECK"
    EXPERT_CALL = "EXPERT_CALL"
    PROPRIETARY = "PROPRIETARY"
    MARKET_DATA = "MARKET_DATA"
    OTHER = "OTHER"


class EvidenceType(str, Enum):
    FACT = "FACT"                  # verifiable, sourced
    INFERENCE = "INFERENCE"        # derived / interpreted
    DATA_POINT = "DATA_POINT"      # numeric observation
    ANECDOTE = "ANECDOTE"          # unverified / qualitative


class EvidenceDirection(str, Enum):
    SUPPORTING = "SUPPORTING"
    CONTRADICTING = "CONTRADICTING"
    NEUTRAL = "NEUTRAL"


# ---------------------------------------------------------------------------
# Assumption
# ---------------------------------------------------------------------------


class MaterialityLevel(str, Enum):
    CRITICAL = "CRITICAL"   # thesis breaks if this assumption is wrong
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


# ---------------------------------------------------------------------------
# Prediction / resolution
# ---------------------------------------------------------------------------


class ComparisonOperator(str, Enum):
    GT = ">"
    GTE = ">="
    LT = "<"
    LTE = "<="
    EQ = "=="
    IN_RANGE = "in_range"
    CHANGES = "changes"


class ResolutionStatus(str, Enum):
    CORRECT = "CORRECT"
    INCORRECT = "INCORRECT"
    PARTIALLY_CORRECT = "PARTIALLY_CORRECT"
    INCONCLUSIVE = "INCONCLUSIVE"
    EXPIRED = "EXPIRED"
    WITHDRAWN = "WITHDRAWN"


# ---------------------------------------------------------------------------
# Agent
# ---------------------------------------------------------------------------


class AgentType(str, Enum):
    FINANCIAL_ANALYST = "FINANCIAL_ANALYST"
    THESIS_BUILDER = "THESIS_BUILDER"
    RISK_ASSESSOR = "RISK_ASSESSOR"
    MONITORING = "MONITORING"
    ORCHESTRATOR = "ORCHESTRATOR"
    POSTMORTEM = "POSTMORTEM"
    GENERAL = "GENERAL"


# ---------------------------------------------------------------------------
# Monitoring
# ---------------------------------------------------------------------------


class TriggerFrequency(str, Enum):
    EVENT_DRIVEN = "EVENT_DRIVEN"
    DAILY = "DAILY"
    WEEKLY = "WEEKLY"
    MONTHLY = "MONTHLY"
    QUARTERLY = "QUARTERLY"


class TriggerAction(str, Enum):
    ALERT = "ALERT"
    REVISE_ASSUMPTION = "REVISE_ASSUMPTION"
    RERUN_THESIS = "RERUN_THESIS"
    CLOSE_EPISODE = "CLOSE_EPISODE"


# ---------------------------------------------------------------------------
# Postmortem
# ---------------------------------------------------------------------------


class PostmortemVerdict(str, Enum):
    THESIS_CORRECT = "THESIS_CORRECT"
    THESIS_INCORRECT = "THESIS_INCORRECT"
    PARTIALLY_CORRECT = "PARTIALLY_CORRECT"
    INCONCLUSIVE = "INCONCLUSIVE"
