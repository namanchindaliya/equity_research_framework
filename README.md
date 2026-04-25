# equity_os — Public-Equity Company Coverage System

A structured, filesystem-backed system for tracking equity research: thesis episodes, assumptions, and predictions — with full version history.

## Design Principles

1. **Source of truth is structured state, not prose.** Everything lives in versioned JSON.
2. **Every company has its own folder.** `~/.equity_os/data/<TICKER>/`
3. **Every update preserves the previous state.** A snapshot is taken before every write.
4. **Each coverage cycle is a thesis episode.** Open → Close, with full audit trail.
5. **Assumptions are first-class objects with version history.** Revising an assumption retires the old one and creates a new one linked by `revised_from`.
6. **Predictions must be explicit and later resolvable.** Every prediction has an outcome status that can be resolved with an actual value.
7. **JSON first, markdown second.** Raw state is always JSON; reports are generated markdown.

## Quickstart

```bash
# Install
uv sync

# Init coverage
uv run equity-os init AAPL --name "Apple Inc." --sector Technology --industry "Consumer Electronics"

# Open a thesis episode
uv run equity-os episode new AAPL \
  --title "FY2026 Initiation" \
  --thesis "Services flywheel drives durable margin expansion." \
  --rating BUY --pt 230.0

# Add assumptions
uv run equity-os assumption add AAPL <episode-id> \
  --key services_rev_growth --value 0.18 --unit "%" \
  --rationale "Management guide + recent quarter trend"

# Add predictions
uv run equity-os prediction add AAPL <episode-id> \
  --description "Services revenue exceeds $120B in FY2026" \
  --metric services_revenue --target 120 --horizon FY2026 --unit "B USD"

# View coverage
uv run equity-os show AAPL

# Generate report
uv run equity-os report AAPL --output AAPL_coverage.md

# Resolve a prediction
uv run equity-os prediction resolve AAPL <episode-id> <prediction-id> \
  --outcome CORRECT --actual 124.3 --note "Beat guide by 4B"

# Close episode
uv run equity-os episode close AAPL <episode-id> --note "Thesis fully played out."
```

## Data Layout

```
~/.equity_os/data/
  AAPL/
    company.json            ← current state (never read-only)
    snapshots/
      20260101T120000Z.json ← immutable point-in-time snapshots
      20260424T090000Z.json
  MSFT/
    company.json
    snapshots/
```

## Tech Stack

| Concern | Library |
|---|---|
| Schemas | pydantic v2 |
| CLI | typer + rich |
| Persistence | plain JSON via pathlib |
| Tabular (future) | pandas + pyarrow |
| Tests | pytest |
| Package mgmt | uv |

## End-to-End Demo

A complete coverage cycle for **Microsoft (MSFT)** using four synthetic local
documents (no external APIs). Run it with:

```bash
make demo
# or
uv run python scripts/run_demo.py
```

The demo runs 10 sequential steps and writes all artifacts to `demo/`:

| Step | What happens | Key output |
|---|---|---|
| 1 | Company initialised | `demo/companies/MSFT/core/dossier.json` |
| 2 | 4 documents ingested and chunked | `demo/companies/MSFT/evidence/` |
| 3 | IndustryAgent run | `demo/agents/industry_analysis.md` |
| 4 | CompanyStrategyAgent run | `demo/agents/strategy_analysis.md` |
| 5 | Orchestrator synthesises Ep1 | `demo/orchestrator/ep1/decision.md` |
| 6 | Episode 1 created (3 predictions) | `demo/companies/MSFT/episodes/…/episode.json` |
| 7 | Prediction 1 resolved (CORRECT) | `demo/companies/MSFT/resolutions/…` |
| 8 | Episode 2 with revised assumption + diff | `demo/diff/industry_diff_ep1_ep2.md` |
| 9 | Score + postmortem generated | `demo/postmortem/ep1_postmortem.md` |
| 10 | Demo README written | `demo/README.md` |

### What it proves

**Prior state is preserved.** Episode 1 JSON is never overwritten by Episode 2.
Each episode lives in its own `episodes/{slug}/` directory.  Snapshots are not
needed at the episode level because episodes are immutable once created.

**Updates create auditable diffs.** `demo/diff/industry_diff_ep1_ep2.md`
shows every field that changed between Episode 1 and Episode 2 industry runs,
with materiality labels and assumption-update proposals.

**The orchestrator can be judged later.** `demo/orchestrator/ep1/decision.json`
records the exact thesis, assumptions, falsification conditions, and monitoring
triggers at Episode 1 time.  When the postmortem runs, the verdict (THESIS_CORRECT /
INCORRECT / PARTIAL) is computed against those predictions.

**No external APIs.** All four input documents are in `demo/inputs/MSFT/`.
Ingestion, chunking, agent analysis, orchestration, diff, scoring, and postmortem
generation are all local, deterministic, and reproducible.

### Clean demo artifacts

```bash
make clean-demo   # removes generated artifacts, keeps demo/inputs/
make demo         # re-run from scratch
```

## Running Tests

```bash
uv run pytest -v
```

## CLI Reference

```
equity-os --help

Commands:
  init             Initialize coverage for a new company
  show             Show company overview and episodes
  list-companies   List all covered companies
  report           Generate a markdown report
  episode new      Open a new thesis episode
  episode close    Close a thesis episode
  episode show     Show episode detail
  assumption add   Add an assumption to an episode
  assumption revise  Revise an assumption (preserves history)
  prediction add   Add a prediction to an episode
  prediction resolve  Record the actual outcome of a prediction
```
