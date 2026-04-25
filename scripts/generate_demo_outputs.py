"""Generate demo agent outputs for AAPL under demo_outputs/AAPL/."""

from __future__ import annotations

import json
import sys
from pathlib import Path

repo = Path(__file__).parent.parent
sys.path.insert(0, str(repo / "src"))

from equity_os.agents.industry import IndustryAgent
from equity_os.agents.strategy import CompanyStrategyAgent
from equity_os.ingest.pipeline import ingest_dir
from equity_os.ingest.models import IngestedEvidence

INPUTS = repo / "tests" / "test_ingest" / "fixtures" / "inputs" / "AAPL"
OUT = repo / "demo_outputs" / "AAPL"
OUT.mkdir(parents=True, exist_ok=True)

COMPANIES = repo / "demo_outputs" / "_companies"
(COMPANIES / "AAPL" / "evidence").mkdir(parents=True, exist_ok=True)


def main() -> None:
    print("Ingesting AAPL fixture evidence...")
    ingested, skipped, failed = ingest_dir(INPUTS, "AAPL", COMPANIES, force=True)
    print(f"  {len(ingested)} ingested, {len(skipped)} skipped, {len(failed)} failed")
    if failed:
        for f in failed:
            print(f"  FAILED: {f}")
        sys.exit(1)

    evidence = ingested

    print("\nRunning IndustryAgent...")
    industry_result = IndustryAgent().run("AAPL", evidence)
    _write(OUT / "industry_analysis.json", industry_result.payload)
    _write_text(OUT / "industry_analysis.md", industry_result.memo)
    print(f"  Confidence: {industry_result.payload['overall_confidence']:.0%}")
    print(f"  Validation: {industry_result.validation_errors or 'OK'}")

    print("\nRunning CompanyStrategyAgent...")
    strategy_result = CompanyStrategyAgent().run("AAPL", evidence)
    _write(OUT / "strategy_analysis.json", strategy_result.payload)
    _write_text(OUT / "strategy_analysis.md", strategy_result.memo)
    print(f"  Confidence: {strategy_result.payload['overall_confidence']:.0%}")
    print(f"  Validation: {strategy_result.validation_errors or 'OK'}")

    print(f"\nOutputs written to {OUT}")


def _write(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    print(f"  Wrote {path.name}")


def _write_text(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8")
    print(f"  Wrote {path.name}")


if __name__ == "__main__":
    main()
