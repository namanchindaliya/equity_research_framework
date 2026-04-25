"""Export JSON Schema (draft 2020-12) for all v1 domain models to generated/."""

from __future__ import annotations

import json
import sys
from pathlib import Path

# Allow running as a script without installing
repo_root = Path(__file__).parent.parent
sys.path.insert(0, str(repo_root / "src"))

from equity_os.schemas import (
    AgentOutput,
    AssumptionChange,
    AssumptionRecord,
    CompanyDossier,
    EvidenceItem,
    MonitoringTrigger,
    OrchestratorDecision,
    Postmortem,
    PredictionRecord,
    ResolutionRecord,
    SourceMetadata,
    ThesisEpisode,
)

MODELS = [
    SourceMetadata,
    EvidenceItem,
    AssumptionChange,
    AssumptionRecord,
    ResolutionRecord,
    PredictionRecord,
    ThesisEpisode,
    AgentOutput,
    OrchestratorDecision,
    MonitoringTrigger,
    CompanyDossier,
    Postmortem,
]


def main() -> None:
    out = Path(__file__).parent.parent / "generated"
    out.mkdir(exist_ok=True)

    for model in MODELS:
        schema = model.model_json_schema()
        dest = out / f"{model.__name__}.schema.json"
        dest.write_text(json.dumps(schema, indent=2))
        print(f"  wrote {dest.relative_to(repo_root)}")

    print(f"\n{len(MODELS)} schemas exported to generated/")


if __name__ == "__main__":
    main()
