# eqos — Public-Equity Company Coverage System

A structured, filesystem-backed system for tracking equity research: thesis episodes, assumptions, and predictions — with full version history.

## Design Principles

1. **Source of truth is structured state, not prose.** Everything lives in versioned JSON.
2. **Every company has its own normalized folder tree.** `companies/<TICKER>/`
3. **Analytical history is append-only.** Episodes, assumption versions, predictions, and resolutions are stored separately.
4. **Each coverage cycle is a thesis episode.** Open → Close, with full audit trail.
5. **Assumptions are first-class objects with version history.** Revising an assumption retires the old one and creates a new one linked by `revised_from`.
6. **Predictions must be explicit and later resolvable.** Every prediction has an outcome status that can be resolved with an actual value.
7. **JSON first, markdown second.** Raw state is always JSON; reports are generated markdown.
8. **Weak evidence produces abstention, not forced conclusions.** Agent and orchestrator status is explicit.
9. **Verdicts require adequate coverage.** A thesis verdict needs at least three scoreable predictions and two-thirds scoreable coverage.

`eqos` is the canonical CLI and storage model. The older `equity-os` command remains available only for legacy compatibility.

## Quickstart

```bash
# Install
uv sync

# Init coverage
uv run eqos init-company AAPL --name "Apple Inc." --sector Technology --industry "Consumer Electronics"

# Open a thesis episode
uv run eqos new-episode AAPL \
  --title "FY2026 Initiation" \
  --thesis "Services flywheel drives durable margin expansion." \
  --rating BUY --pt 230.0

# Add assumptions
uv run eqos add-assumption AAPL <episode-slug> \
  --key services_rev_growth --label "Services revenue growth" \
  --value 0.18 --unit "%" --materiality CRITICAL \
  --rationale "Management guide + recent quarter trend"

# Add predictions
uv run eqos log-prediction AAPL <episode-slug> \
  --description "Services revenue exceeds $120B in FY2026" \
  --metric services_revenue --threshold 120 --horizon FY2026 \
  --due-date 2026-11-01 --unit "B USD" --materiality CRITICAL

# Resolve a prediction
uv run eqos resolve-prediction AAPL <episode-slug> services_revenue \
  --status CORRECT --actual 124.3 --notes "Beat guide by 4B"

# Score and generate a postmortem
uv run eqos score-company AAPL --episode <episode-slug>
uv run eqos postmortem-episode AAPL <episode-slug>
```

## Data Layout

```
companies/
  AAPL/
    core/dossier.json
    episodes/{date}_{slug}/episode.json
    assumptions/{date}_{slug}/{key}_v001.json
    predictions/{date}_{slug}/{metric}_{id8}.json
    resolutions/{date}_{slug}/{metric}_{id8}_resolution.json
    evidence/{uuid}.json
    scores/{date}_{slug}.json
    postmortems/{date}_{slug}.json
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

**Prior cycles are preserved.** Episode 2 never overwrites Episode 1. Each
coverage cycle has its own `episodes/{slug}/` directory, while assumption
versions and resolution records preserve changes within a cycle.

**Updates create auditable diffs.** `demo/diff/industry_diff_ep1_ep2.md`
shows every field that changed between Episode 1 and Episode 2 industry runs,
with materiality labels and assumption-update proposals.

**The orchestrator can be judged later.** `demo/orchestrator/ep1/decision.json`
records the exact thesis, assumptions, falsification conditions, and monitoring
triggers at Episode 1 time. A definitive postmortem verdict requires at least
three scoreable predictions and scoreable coverage of at least two-thirds.
Otherwise the result is `PENDING` or `INSUFFICIENT_EVIDENCE`.

**Weak evidence is explicit.** Specialist outputs are marked `COMPLETE`,
`LIMITED`, or `ABSTAINED`. Industry analysis requires at least two relevant
source categories, and the orchestrator will not synthesize a thesis when a
specialist abstains, core fields are unresolved, or confidence is below 25%.

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
eqos --help

Commands:
  init-company           Initialize coverage for a company
  new-episode            Open a thesis episode
  add-assumption         Add a versioned assumption
  update-assumption      Revise an assumption and append its change log
  list-assumptions       Show an episode's assumptions
  log-prediction         Add a materiality-weighted prediction
  resolve-prediction     Record an individual outcome
  resolve-episode        Resolve predictions individually or from JSON
  ingest                 Ingest local evidence files
  list-evidence          Show the evidence catalog
  render-company-summary Rebuild the dossier markdown
  score-company          Score prediction outcomes
  postmortem-episode     Generate a coverage-gated postmortem
```
