"""Learning loop output models.

These aggregate and score the domain models (PredictionRecord, ResolutionRecord)
from schemas/prediction.py.  They do not replace them.

Hierarchy
---------
ScoredPrediction        — one prediction + its resolution + its score contribution
CalibrationBin          — one probability bucket in the calibration table
ErrorAttributionSummary — counts by error bucket across all failed predictions
EpisodeScore            — full scoring summary for one episode
PostmortemReport        — 6-section narrative answering what/why/what-happened/broke/failed/next
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Error attribution buckets
# ---------------------------------------------------------------------------


class ErrorBucket(str, Enum):
    MACRO = "macro"           # economy/market moved against the prediction
    INDUSTRY = "industry"     # industry cycle or structure changed unexpectedly
    STRATEGY = "strategy"     # management changed direction or execution failed
    VALUATION = "valuation"   # multiple / price assumption was wrong (future use)
    TIMING = "timing"         # direction was right but deadline was too tight
    DATA_QUALITY = "data_quality"  # metric definition mismatch or bad data


# ---------------------------------------------------------------------------
# ScoredPrediction
# ---------------------------------------------------------------------------


class ScoredPrediction(BaseModel):
    """One prediction with its resolution and its contribution to episode scoring."""

    prediction_id: UUID
    metric: str
    description: str
    horizon: str
    due_date: Any                       # date as stored in prediction
    probability: float                  # p_i
    threshold: Any
    operator: str
    linked_assumption_keys: list[str] = Field(default_factory=list)
    materiality: str = "MEDIUM"
    score_weight: float = Field(default=1.0, gt=0.0)

    # Resolution fields (None = unresolved)
    resolved_status: str | None = None  # ResolutionStatus value
    actual_outcome: Any | None = None
    error_magnitude: float | None = None   # signed: (actual - threshold) / |threshold|
    resolution_notes: str = ""
    source_of_truth: str | None = None     # URL or document reference

    # Scoring
    outcome_score: float | None = None    # o_i: 1.0 / 0.5 / 0.0
    brier_contribution: float | None = None  # (p_i - o_i)^2
    error_bucket: ErrorBucket | None = None
    is_excluded: bool = False             # True if EXPIRED/WITHDRAWN/INCONCLUSIVE
    exclusion_reason: str = ""
    direction_correct: bool | None = None


# ---------------------------------------------------------------------------
# Calibration
# ---------------------------------------------------------------------------


class CalibrationBin(BaseModel):
    """One probability bucket in the calibration table."""

    label: str              # e.g. "0.0–0.2"
    low: float
    high: float
    count: int
    predicted_avg: float    # mean assigned probability in this bucket
    actual_freq: float      # actual fraction that came true
    calibration_error: float  # |predicted_avg - actual_freq|


# ---------------------------------------------------------------------------
# Error attribution
# ---------------------------------------------------------------------------


class ErrorAttributionSummary(BaseModel):
    """Counts and fractions by error bucket across all failed predictions."""

    macro: int = 0
    industry: int = 0
    strategy: int = 0
    valuation: int = 0
    timing: int = 0
    data_quality: int = 0
    total_failed: int = 0

    def dominant_bucket(self) -> ErrorBucket | None:
        """Return the most frequent error bucket, or None if no failures."""
        if self.total_failed == 0:
            return None
        buckets = {
            ErrorBucket.MACRO: self.macro,
            ErrorBucket.INDUSTRY: self.industry,
            ErrorBucket.STRATEGY: self.strategy,
            ErrorBucket.VALUATION: self.valuation,
            ErrorBucket.TIMING: self.timing,
            ErrorBucket.DATA_QUALITY: self.data_quality,
        }
        return max(buckets, key=lambda b: buckets[b])


# ---------------------------------------------------------------------------
# EpisodeScore
# ---------------------------------------------------------------------------


class EpisodeScore(BaseModel):
    """Calibration summary, Brier score, hit rate, and error attribution for one episode."""

    score_id: UUID = Field(default_factory=uuid4)
    ticker: str
    episode_slug: str
    scored_at: datetime = Field(default_factory=datetime.utcnow)

    # Raw counts
    total_predictions: int
    resolved_count: int
    excluded_count: int    # EXPIRED / WITHDRAWN / INCONCLUSIVE
    scored_count: int      # predictions included in Brier/hit-rate
    unresolved_count: int = 0
    resolution_coverage: float = Field(default=0.0, ge=0.0, le=1.0)
    scoreable_coverage: float = Field(default=0.0, ge=0.0, le=1.0)

    # A thesis verdict requires enough resolved, scoreable evidence.
    minimum_verdict_coverage: float = Field(default=2 / 3, ge=0.0, le=1.0)
    minimum_verdict_sample: int = Field(default=3, ge=1)
    verdict_eligible: bool = False
    verdict_ineligibility_reasons: list[str] = Field(default_factory=list)

    # Brier score (lower = better; 0.25 = uninformative baseline)
    brier_score: float | None = None    # None if no scored predictions
    brier_vs_baseline: float | None = None  # brier_score - 0.25

    # Hit rate (fraction correct + 0.5 * partial)
    hit_rate: float | None = None
    directional_accuracy: float | None = None
    mean_absolute_magnitude_error: float | None = None
    timing_error_count: int = 0

    # Calibration
    calibration_bins: list[CalibrationBin] = Field(default_factory=list)
    mean_calibration_error: float | None = None
    minimum_calibration_sample: int = Field(default=5, ge=1)
    calibration_is_reliable: bool = False

    # Error attribution
    error_attribution: ErrorAttributionSummary = Field(
        default_factory=ErrorAttributionSummary
    )

    # Scored predictions (for drill-down)
    scored_predictions: list[ScoredPrediction] = Field(default_factory=list)

    @property
    def is_well_calibrated(self) -> bool:
        return self.calibration_is_reliable and (self.mean_calibration_error or 1.0) < 0.10

    @property
    def beat_baseline(self) -> bool:
        return (self.brier_vs_baseline or 0.0) < 0.0


# ---------------------------------------------------------------------------
# PostmortemReport — 6-section narrative
# ---------------------------------------------------------------------------


class PostmortemReport(BaseModel):
    """Structured retrospective for one completed episode.

    Answers:
        1. What we believed          (thesis_at_time)
        2. Why we believed it        (belief_rationale)
        3. What actually happened    (actual_outcomes)
        4. What broke                (what_broke)
        5. Which assumptions failed  (failed_assumptions)
        6. What the orchestrator should do differently  (orchestrator_recommendations)
    """

    report_id: UUID = Field(default_factory=uuid4)
    ticker: str
    episode_slug: str
    generated_at: datetime = Field(default_factory=datetime.utcnow)

    # Embedded score
    episode_score: EpisodeScore

    # 1. What we believed
    thesis_at_time: str

    # 2. Why we believed it
    belief_rationale: list[str] = Field(default_factory=list)

    # 3. What actually happened
    actual_outcomes: list[str] = Field(default_factory=list)

    # 4. What broke
    what_broke: list[str] = Field(default_factory=list)

    # 5. Which assumptions failed
    failed_assumptions: list[str] = Field(default_factory=list)

    # 6. What the orchestrator should do differently
    orchestrator_recommendations: list[str] = Field(default_factory=list)

    # Overall verdict (derived from score)
    verdict: str = ""      # includes PENDING / INSUFFICIENT_EVIDENCE when coverage is inadequate
