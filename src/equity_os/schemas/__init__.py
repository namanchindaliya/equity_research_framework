"""equity_os.schemas — all domain models.

Public surface
--------------
New (v1) models:
    SourceMetadata, EvidenceItem
    AssumptionRecord, AssumptionChange
    PredictionRecord, ResolutionRecord
    ObservationRecord, InferenceRecord, DecisionRecord, ThesisEpisode
    AgentOutput, OrchestratorDecision, MonitoringTrigger
    RiskItem, ConflictItem, FalsificationCondition
    CompanyDossier
    Postmortem, AssumptionError

Legacy (v0) models — re-exported for backward compat:
    Company, Episode, Assumption, Prediction

All enums:
    Rating, EpisodeStatus, AssumptionStatus, PredictionOutcome
    SourceType, EvidenceType, EvidenceDirection
    MaterialityLevel, ComparisonOperator, ResolutionStatus
    AgentType, TriggerFrequency, TriggerAction, PostmortemVerdict
"""

from .agent import (
    AgentOutput,
    ConflictItem,
    FalsificationCondition,
    MonitoringTrigger,
    OrchestratorDecision,
    RiskItem,
)
from .assumption import AssumptionChange, AssumptionRecord
from .common import Confidence, EvidenceItem, SourceMetadata
from .company import CompanyDossier
from .enums import (
    AgentType,
    AssumptionStatus,
    ComparisonOperator,
    EpisodeStatus,
    EvidenceDirection,
    EvidenceType,
    MaterialityLevel,
    PostmortemVerdict,
    PredictionOutcome,
    Rating,
    ResolutionStatus,
    SourceType,
    TriggerAction,
    TriggerFrequency,
)
from .episode import (
    DecisionRecord,
    InferenceRecord,
    ObservationRecord,
    ThesisEpisode,
)
from .legacy import Assumption, Company, Episode, Prediction
from .postmortem import AssumptionError, Postmortem
from .prediction import PredictionRecord, ResolutionRecord

__all__ = [
    # common
    "Confidence",
    "SourceMetadata",
    "EvidenceItem",
    # assumption
    "AssumptionRecord",
    "AssumptionChange",
    # prediction
    "PredictionRecord",
    "ResolutionRecord",
    # episode
    "ObservationRecord",
    "InferenceRecord",
    "DecisionRecord",
    "ThesisEpisode",
    # agent
    "AgentOutput",
    "OrchestratorDecision",
    "MonitoringTrigger",
    "RiskItem",
    "ConflictItem",
    "FalsificationCondition",
    # company
    "CompanyDossier",
    # postmortem
    "Postmortem",
    "AssumptionError",
    # legacy
    "Company",
    "Episode",
    "Assumption",
    "Prediction",
    # enums
    "Rating",
    "EpisodeStatus",
    "AssumptionStatus",
    "PredictionOutcome",
    "SourceType",
    "EvidenceType",
    "EvidenceDirection",
    "MaterialityLevel",
    "ComparisonOperator",
    "ResolutionStatus",
    "AgentType",
    "TriggerFrequency",
    "TriggerAction",
    "PostmortemVerdict",
]
