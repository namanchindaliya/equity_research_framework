# CLAUDE.md — equity_reserach_framework

Operating rules for all future Claude Code sessions in this repo.

## Core rules

1. **Never overwrite prior company state.** `CompanyStore.save()` always snapshots before writing. Never bypass it — no direct `path.write_text()` on `company.json` outside the store.

2. **Prefer explicit schemas over loose dicts.** All data must pass through a Pydantic model. Do not use raw `dict` or untyped `Any` at module boundaries.

3. **Every major command must have tests.** Each CLI command in `cli.py` needs at least one `test_cli.py` test. Each business-logic function in `episode.py` needs a `test_episode.py` test.

4. **Every episode must be reproducible from stored inputs.** Episodes are self-contained in the JSON state. Do not rely on external APIs, mutable globals, or runtime-only state.

5. **Output both structured JSON and readable markdown where useful.** Commands that produce analysis should support `--output` to write a markdown report alongside the raw JSON state.

6. **Keep modules small and typed.** Each module has one clear responsibility. All function signatures must have type annotations. No untyped `**kwargs` at internal boundaries.

7. **Avoid external APIs in v0.** No HTTP calls, no market data feeds, no LLM calls. All data is user-supplied.

8. **Do not force conclusions from weak evidence.** Preserve `AnalysisStatus`, claim-level citation checks, cross-source requirements for high confidence, and the orchestrator synthesis gate.

9. **Do not issue small-sample thesis verdicts.** Preserve the minimum scoreable coverage/sample gates and distinguish `PENDING` from `INSUFFICIENT_EVIDENCE`.

10. **Use `eqos` for new development.** The `equity-os` command and monolithic store are legacy compatibility surfaces.

## Layout

```
src/equity_os/
  __init__.py    package root
  schemas.py     Pydantic v2 models (Company, Episode, Assumption, Prediction)
  store.py       filesystem read/write — single source of truth
  episode.py     business logic (open/close episodes, assumptions, predictions)
  render.py      rich terminal display + markdown generation
  cli.py         typer CLI entry point

tests/
  conftest.py    shared fixtures (tmp store, apple company)
  test_schemas.py
  test_store.py
  test_episode.py
  test_cli.py
```

## State layout on disk

```
~/.equity_os/data/
  AAPL/
    company.json          ← current state
    snapshots/
      20260101T120000Z.json
      20260115T093012Z.json
```

## Common commands

```bash
# Setup
uv sync

# Run tests
uv run pytest -v

# Init a company
uv run equity-os init AAPL --name "Apple Inc." --sector Technology

# Open a thesis episode
uv run equity-os episode new AAPL \
  --title "FY2026 Initiation" \
  --thesis "Services flywheel drives durable margin expansion." \
  --rating BUY --pt 230.0

# Add an assumption (use episode ID prefix)
uv run equity-os assumption add AAPL <ep-id> \
  --key services_rev_growth --value 0.18 --unit "%" \
  --rationale "Management guide + recent quarter trend"

# Add a prediction
uv run equity-os prediction add AAPL <ep-id> \
  --description "Services revenue exceeds $120B in FY2026" \
  --metric services_revenue --target 120 --horizon FY2026 --unit "B USD"

# Generate markdown report
uv run equity-os report AAPL --output AAPL_report.md

# Show company
uv run equity-os show AAPL
```

## Adding features — checklist

- [ ] Add/extend Pydantic schema in `schemas.py`
- [ ] Add business logic in `episode.py` (or new module)
- [ ] Expose via CLI in `cli.py`
- [ ] Write tests before marking done
- [ ] Never delete old assumptions — use `AssumptionStatus.REVISED` / `RETIRED`
- [ ] Never delete old episodes — `EpisodeStatus.CLOSED` is the terminal state
