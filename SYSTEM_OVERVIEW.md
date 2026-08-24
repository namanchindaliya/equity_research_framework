# equity-os — System Overview

Complete reference for functions, capabilities, inputs, and outputs.
Use this as the entry point when understanding or extending the codebase.

---

## Reading order

### 1. Understand the data model first

Read these four files in order — everything else is built on top of them.

| File | What it defines |
|---|---|
| `src/equity_os/schemas/enums.py` | All enumerations: `Rating`, `ResolutionStatus`, `MaterialityLevel`, `SourceType`, etc. Read this first — it is the vocabulary of the whole system. |
| `src/equity_os/schemas/common.py` | `SourceMetadata` and `EvidenceItem` — the two primitives that ground every claim in a source. |
| `src/equity_os/schemas/assumption.py` | `AssumptionRecord` and `AssumptionChange` — how assumptions are versioned and why `.revise()` returns a new record instead of mutating. |
| `src/equity_os/schemas/prediction.py` | `PredictionRecord` and `ResolutionRecord` — the falsifiable forecast model and how error magnitude is computed. |

---

### 2. Understand how documents enter the system

**Layer: `src/equity_os/ingest/`**

Read in this order:

```
normalize.py   →  extract(path) → (metadata_dict, plain_text)
chunk.py       →  chunk_text(text, ticker, id_prefix) → list[TextChunk]
dedup.py       →  is_duplicate(ev_dir, text) → (bool, sha256_hash)
adapters.py    →  source_type_for(logical_type), reliability_for(logical_type)
pipeline.py    →  ingest_file(path, ticker, companies_root) → IngestedEvidence | None
models.py      →  IngestedEvidence schema (the output of pipeline.py)
```

**Input:** any `.txt`, `.md`, `.html`, or `.csv` file under `inputs/{ticker}/`  
**Output:** `companies/{ticker}/evidence/{uuid}.json` — a fully chunked, deduplicated `IngestedEvidence` record  
**Key invariant:** same file → same hash → skip (dedup at document level)

#### Supported logical source types

| Logical type | `SourceType` | Default reliability |
|---|---|---|
| `filing` | `FILING` | 1.00 |
| `earnings_transcript` | `EARNINGS_CALL` | 0.95 |
| `management_commentary` | `EARNINGS_CALL` | 0.90 |
| `investor_presentation_notes` | `RESEARCH_REPORT` | 0.85 |
| `industry_note` | `RESEARCH_REPORT` | 0.75 |
| `channel_check_note` | `CHANNEL_CHECK` | 0.70 |
| `news_note` | `NEWS_ARTICLE` | 0.60 |

#### Chunking strategy

1. Split on `\n\n` (paragraph boundaries)
2. Paragraphs > 1 600 chars → split at sentence boundaries
3. Sentences > 1 600 chars → force-split at char boundary
4. Passages < 80 chars → merge with next passage
5. Citation anchor: `{ticker}-{evidence_id[:8]}-{index:04d}`

---

### 3. Understand how agents consume evidence

**Layer: `src/equity_os/agents/`**

```
base.py        →  BaseAgent ABC — required_inputs(), run(), validate_output(), render_markdown()
extraction.py  →  score_chunks(), build_ref(), compute_confidence() — pure functions, no I/O
industry.py    →  IndustryAgent — market structure, Porter forces, KPIs, regulatory, risks
strategy.py    →  CompanyStrategyAgent — priorities, capital allocation, narrative shifts, risks
models.py      →  all output Pydantic models (IndustryAnalysis, CompanyStrategyAnalysis, etc.)
```

**Input:** `list[IngestedEvidence]` (loaded from disk)  
**Output:** `AgentRunResult` containing `payload: dict` (model_dump of analysis) + `memo: str` (markdown)  
**Key invariant:** agents are pure functions — same evidence → same output structure. No I/O inside `run()`.

The confidence formula lives in `extraction.py:compute_confidence()`. Every finding traces back to a `TextChunk` via `EvidenceRef`.

#### Evidence quality and abstention

Each specialist output includes an `analysis_status` and `evidence_quality` record:

- `COMPLETE` — required source coverage and claim-level citation checks pass.
- `LIMITED` — conclusions are usable with explicit source-coverage limitations.
- `ABSTAINED` — the agent returns structurally valid `UNKNOWN` fields and no unsupported conclusions.

Industry analysis requires at least two distinct required source categories.
Strategy analysis requires at least one filing or earnings transcript. Every
positive-confidence material claim must have a citation, and confidence of 75%
or higher requires citations from at least two distinct documents. The
evidence-quality record separately marks sources `FRESH`, `STALE`, `MIXED`, or
`UNDATED` using a 180-day threshold, so rerunning an agent does not reset source
freshness. The
orchestrator also abstains when a specialist abstains, a core analytical field
is unresolved, or overall synthesis confidence is below 25%.

#### IndustryAgent scope

- Market structure (MONOPOLY / OLIGOPOLY / COMPETITIVE / FRAGMENTED)
- Cycle stage (EARLY_GROWTH / GROWTH / MATURE / DECLINE)
- Porter's five forces (scored HIGH / MEDIUM / LOW / UNKNOWN)
- Key industry KPIs (name, trend direction, evidence ref)
- Regulatory factors (name, jurisdiction, severity)
- Competitive dynamics (moat type, basis of competition)
- Top industry risks
- Unresolved questions

**Out of scope:** valuation, management quality judgments.

#### CompanyStrategyAgent scope

- Management stated priorities
- Capital allocation (buybacks, dividends, capex, M&A)
- Narrative shifts over time
- Disclosed risks (by category and severity)
- Segment priorities (ranked by management emphasis)
- Strategic positioning (target market, moat, differentiation)
- Management credibility signals (guidance beat/miss — evidence-based only)
- Unresolved questions

**Out of scope:** operating forecasts, valuation.

---

### 4. Understand the storage layer

**Layer: `src/equity_os/fs/`**

```
layout.py   →  CompanyLayout — every path the system can write to, in one place
naming.py   →  slugify(), episode_dir_name(), assumption_filename() — deterministic names
io.py       →  write_json() (atomic via .tmp rename), write_md(), append_jsonl()
readers.py  →  load_dossier(), load_episode(), resolve_episode_slug() (prefix matching)
```

**The folder tree:**

```
companies/{TICKER}/
  core/
    dossier.json                    ← slim CompanyDossier (episodes: [])
    dossier.md                      ← generated markdown summary
  episodes/{YYYY-MM-DD}_{slug}/
    episode.json                    ← full ThesisEpisode (authoritative per cycle)
    episode.md                      ← generated markdown sidecar
  assumptions/{slug}/
    {key}_v001.json                 ← AssumptionRecord snapshot per version
    {key}_changes.jsonl             ← append-only AssumptionChange log
  predictions/{slug}/
    {metric}_{id8}.json             ← PredictionRecord
  resolutions/{slug}/
    {metric}_{id8}_resolution.json  ← ResolutionRecord
  evidence/
    {uuid}.json                     ← IngestedEvidence
    _index.jsonl                    ← content_hash → evidence_id (dedup)
    _catalog.json                   ← lightweight manifest
  scores/{slug}.json                ← EpisodeScore
  postmortems/{slug}.json           ← PostmortemReport
```

**Naming conventions:**
- Episode dir: `{YYYY-MM-DD}_{slugified-title}` (deterministic, collision-safe with counter)
- Assumption snapshot: `{key}_v{version:03d}.json`
- Prediction: `{metric_slug}_{id[:8]}.json`

---

### 5. Understand the diff / assumptions engine

**Layer: `src/equity_os/diff/`**

```
models.py    →  FieldChange, AssumptionProposal, ConflictFlag, EpisodeDiff, ChangeLog
engine.py    →  diff_payloads(prior, current, ...) → EpisodeDiff
proposer.py  →  propose_updates(changes, ...) → (list[AssumptionProposal], list[ConflictFlag])
renderer.py  →  render_episode_diff(diff) → "What changed, why, and what it means" memo
```

**Input:** two `AgentRunResult.payload` dicts (prior run and current run)  
**Output:** `EpisodeDiff` with `field_changes`, `assumption_proposals`, `conflict_flags`

**FieldChange fields:** `field_path`, `change_type` (ADDED/REMOVED/MODIFIED/UNCHANGED), `prior_value`, `current_value`, `change_magnitude`, `materiality` (HIGH/MEDIUM/LOW), `owner_agent`, `evidence_ids`, `timestamp`

**AssumptionProposal fields:** `assumption_key`, `prior_value`, `proposed_value`, `rationale`, `evidence_ids`, `confidence`, `materiality`, `impacted_model_fields`, `implication_for_thesis`, `implication_for_valuation`, `triggered_by_field_paths`, `timestamp`

**Conflict types detected:**
- `confidence_inversion`: same field confidence dropped > 50%
- `evidence_disagreement`: HIGH-materiality field changed with new evidence set
- `oscillation`: field reversed a direction from a prior diff
- `unresolved_growth`: `unresolved_questions` list grew

**Key design:** lists are diffed by identity key (`name`, `category`, `segment_name`) not position — reordering doesn't produce false positives.

---

### 6. Understand the orchestrator

**Layer: `src/equity_os/orchestrator/`**

```
policy.py       →  OrchestratorPolicy (loads policy/orchestrator_policy.yaml)
conflict.py     →  detect_conflicts(industry, strategy, policy) → list[AgentConflict]
synthesis.py    →  build_observation_layer(), build_inference_layer(), build_decision_layer()
orchestrator.py →  Orchestrator.run(ticker, industry, strategy, assumptions, ...) → OrchestratorDecision
renderer.py     →  render_decision(decision) → 3-section markdown memo
models.py       →  ObservationLayer, InferenceLayer, DecisionLayer, OrchestratorDecision
```

**Input:**
- `industry: dict` — `IndustryAnalysis.model_dump(mode="json")`
- `strategy: dict` — `CompanyStrategyAnalysis.model_dump(mode="json")`
- `assumptions: list[dict]` — current `AssumptionRecord` ledger
- `prior_thesis: dict | None` — previous `ThesisEpisode` or orchestrator decision
- `change_log: dict | None` — `ChangeLog` from the diff engine

**Output:** `OrchestratorDecision` with three structurally-separated layers:

```
ObservationLayer   ← raw facts from agents (no interpretation added)
InferenceLayer     ← thesis, variant view, conflicts, adjusted assumptions, drivers
DecisionLayer      ← predictions, falsification conditions, monitoring triggers, next evidence
```

**Policy file** (`policy/orchestrator_policy.yaml`) governs:

| Section | Controls |
|---|---|
| `evidence_weighting` | Base weight per agent; `agreement_boost` when both agree |
| `confidence_adjustments` | Penalties for missing evidence, conflicts, sparse data |
| `freshness_penalties` | Confidence decay by evidence age (days_30 → days_9999) |
| `conflict_resolution` | Which agent wins per dimension (regulatory → industry_v1, segment → strategy_v1) |
| `source_reliability_weights` | Base reliability by logical_type |
| `synthesis_thresholds` | Min confidence to promote a finding to the decision layer |

**Five conflict dimensions checked:**
1. Competitive intensity (Porter rivalry vs. strategy risk disclosures)
2. Regulatory risk (industry regulatory factors vs. strategy explicit disclosure)
3. Growth / cycle alignment (cycle stage vs. narrative shifts)
4. Moat type (industry competitive_dynamics vs. strategy moat_assessment)
5. Overall confidence divergence (if gap ≥ `disagreement_threshold`)

---

### 7. Understand the learning loop

**Layer: `src/equity_os/learning/`**

```
models.py     →  ScoredPrediction, CalibrationBin, EpisodeScore, PostmortemReport
scoring.py    →  brier_score(), hit_rate(), calibration_bins(), classify_error_bucket(), score_episode()
postmortem.py →  generate_postmortem() → PostmortemReport (6 structured sections)
renderer.py   →  render_episode_score(), render_postmortem()
```

**Input:** `list[PredictionRecord.model_dump()]` (resolutions embedded or passed separately)  
**Output:** `EpisodeScore` (numeric) + `PostmortemReport` (narrative)

#### Scoring formulas

**Materiality-weighted Brier score:** `B = Σwᵢ(pᵢ − oᵢ)² / Σwᵢ`
- `oᵢ = 1.0` for CORRECT, `0.5` for PARTIALLY_CORRECT, `0.0` for INCORRECT
- Weights are CRITICAL `4.0`, HIGH `2.0`, MEDIUM `1.0`, LOW `0.5`.
- EXPIRED / WITHDRAWN / INCONCLUSIVE are excluded from Brier
- EXPIRED with correct direction → classified as TIMING (counted in error attribution)
- Lower = better; **0.25 = uninformative baseline** (always predict 50%)

**Weighted hit rate:** `Σwᵢoᵢ / Σwᵢ`

The score also reports directional accuracy, mean absolute magnitude error,
timing-error count, resolution coverage, and scoreable coverage.

#### Verdict and calibration gates

- A definitive thesis verdict requires at least 3 scoreable predictions.
- Scoreable predictions must represent at least two-thirds of all predictions.
- An incomplete episode returns `PENDING`; a completed but inadequate sample
  returns `INSUFFICIENT_EVIDENCE`.
- Calibration statistics remain visible for small samples, but are not labeled
  reliable and do not drive systematic calibration recommendations until at
  least 5 predictions are scoreable.

**Calibration bins:** 5 probability buckets (0–0.2, 0.2–0.4, …, 0.8–1.0). Each reports `predicted_avg`, `actual_freq`, `calibration_error = |predicted_avg − actual_freq|`.

#### Error attribution buckets

| Bucket | Trigger (assumption key keywords) |
|---|---|
| `macro` | `macro`, `recession`, `inflation`, `interest_rate`, `fx`, `gdp` |
| `industry` | `industry_cycle`, `market_structure`, `porter`, `regulatory`, `antitrust` |
| `strategy` | `management_priorities`, `capital_allocation`, `segment_priority`, `guidance` |
| `valuation` | `valuation`, `multiple`, `pe_ratio`, `wacc`, `terminal_value` |
| `timing` | EXPIRED prediction where direction was correct |
| `data_quality` | Default when no assumption key matches |

#### PostmortemReport — 6 sections

1. **What we believed** — thesis statement verbatim
2. **Why we believed it** — assumption values with materiality and confidence
3. **What actually happened** — resolution summaries per prediction
4. **What broke** — failed predictions with error attribution bucket
5. **Which assumptions failed** — assumption keys linked to failures
6. **What the orchestrator should do differently** — recommendations driven by dominant error bucket

---

### 8. Understand the CLI

**File: `src/equity_os/v1_cli.py`** — Entry point: `eqos`

Every command follows the same pattern:
1. Resolve `--companies-dir` → `CompanyLayout`
2. Load state (`load_episode`, `load_dossier`)
3. Mutate state (pure logic, no side effects until write)
4. Write back (`write_json` atomic + `write_md` sidecar)
5. Print rich terminal output

| Command | Core operation | Key output |
|---|---|---|
| `init-company TICKER` | Creates `CompanyDossier` + 10 subdirs | `core/dossier.json` |
| `new-episode TICKER` | Creates `ThesisEpisode` | `episodes/{slug}/episode.json` |
| `add-assumption TICKER EPISODE` | Appends `AssumptionRecord` to episode | `assumptions/{slug}/{key}_v001.json` |
| `update-assumption TICKER EPISODE KEY` | Calls `AssumptionRecord.revise()` | `{key}_v002.json` + `_changes.jsonl` |
| `list-assumptions TICKER EPISODE` | Reads episode, renders rich table | terminal only |
| `log-prediction TICKER EPISODE` | Appends materiality-weighted `PredictionRecord` | `predictions/{slug}/{metric}_{id}.json` |
| `resolve-prediction TICKER EPISODE METRIC` | Calls `PredictionRecord.resolve()` | `resolutions/{slug}/…_resolution.json` |
| `render-company-summary TICKER` | Rebuilds `dossier.md` from all episodes | `core/dossier.md` |
| `ingest TICKER [--file FILE]` | Calls `ingest_file()` or `ingest_dir()` | `evidence/{uuid}.json` |
| `list-evidence TICKER` | Reads `_catalog.json` | terminal only |
| `score-company TICKER [--episode SLUG]` | Calls `score_episode()` | `scores/{slug}.json` + `.md` |
| `resolve-episode TICKER EPISODE` | Bulk-resolves from `--resolution-file` or single flags | updates `episode.json` |
| `postmortem-episode TICKER EPISODE` | Calls `score_episode()` + `generate_postmortem()` | `postmortems/{slug}.json` + `.md` |

---

### 9. See it all wired together

**File: `scripts/run_demo.py`**

Canonical end-to-end trace for Microsoft (MSFT). Each `step_*` is one layer:

```
step_init()              fs/layout.py + schemas/company.py
step_ingest()            ingest/pipeline.py
step_run_agents()        agents/industry.py + agents/strategy.py
step_orchestrate_ep1()   orchestrator/orchestrator.py
step_episode1()          schemas/episode.py + fs/io.py
step_resolve()           schemas/prediction.py
step_episode2_and_diff() diff/engine.py + diff/renderer.py + orchestrator (ep2)
step_postmortem()        learning/scoring.py + learning/postmortem.py
```

Run with: `make demo` or `uv run python scripts/run_demo.py`  
All artifacts land in `demo/`. Re-runnable: `make clean-demo && make demo`

---

### 10. Policy and configuration

| File | What it controls |
|---|---|
| `policy/orchestrator_policy.yaml` | Evidence weighting, confidence decay, conflict resolution rules, source reliability |
| `pyproject.toml` | Dependencies, entry points (`eqos`), pytest config |
| `CLAUDE.md` | Operating rules for working in this repo (never overwrite state, explicit schemas, test every command) |
| `generated/*.schema.json` | JSON Schema files for all 12 domain models (regenerate: `make schemas`) |

---

## Data flow in one paragraph

A local document enters via **`ingest/pipeline.py`** → gets chunked into `TextChunk`s with citation anchors → specialist agents (**`IndustryAgent`**, **`CompanyStrategyAgent`**) score those chunks with keyword matching → each agent emits a typed payload + confidence + evidence refs → the **`Orchestrator`** reads the policy file, detects agent conflicts, adjusts confidence for staleness, synthesises a thesis and variant view, and emits an `OrchestratorDecision` with three structurally-separated layers (observations / inferences / decisions) → the analyst logs explicit predictions → the **`diff`** engine detects what changed between runs and proposes assumption updates → once predictions resolve, **`scoring.py`** computes Brier score and error attribution → **`postmortem.py`** generates a 6-section narrative answering what we believed, why, what happened, what broke, which assumptions failed, and what to do differently.

---

## Key invariants

| Invariant | Enforced by |
|---|---|
| Prior company state is never overwritten | `CompanyStore._snapshot()` (v0) / immutable episode dirs (v1) |
| Assumptions have complete version history | `AssumptionRecord.revise()` returns new record; `_changes.jsonl` is append-only |
| Every claim is grounded in evidence | `Finding.evidence_refs: list[EvidenceRef]` — required on all outputs |
| Agents are deterministic | No I/O or randomness inside `run()`; same evidence → same structure |
| Predictions are explicitly falsifiable | `resolution_rule` is required; `due_date` hard deadline |
| Orchestrator decisions cite policy | `AgentConflict.resolution_basis` includes the policy rule name |
| All JSON writes are atomic | `write_json()` writes to `.tmp` then renames |

---

## Module dependency graph

```
schemas/          ← no dependencies (pure Pydantic)
  enums.py
  common.py
  assumption.py   ← common.py
  prediction.py   ← common.py, enums.py
  episode.py      ← assumption.py, prediction.py, agent.py
  postmortem.py   ← common.py, enums.py

ingest/           ← schemas/ (for SourceType enum only)
  normalize.py    ← stdlib only
  chunk.py        ← stdlib only
  dedup.py        ← stdlib only
  adapters.py     ← stdlib only
  pipeline.py     ← normalize, chunk, dedup, adapters, models

agents/           ← ingest/models, schemas/
  extraction.py   ← ingest/models, agents/models
  base.py         ← ingest/models, agents/models
  industry.py     ← base.py, extraction.py
  strategy.py     ← base.py, extraction.py

fs/               ← schemas/ (for models)
  naming.py       ← stdlib only
  io.py           ← pydantic
  layout.py       ← naming.py
  readers.py      ← io.py, layout.py, schemas/

diff/             ← agents/models (payload dicts)
  models.py       ← pydantic
  engine.py       ← diff/models, diff/proposer
  proposer.py     ← diff/models
  renderer.py     ← diff/models

orchestrator/     ← agents/models, diff/models, schemas/
  policy.py       ← stdlib only
  conflict.py     ← orchestrator/models, orchestrator/policy
  synthesis.py    ← orchestrator/models, orchestrator/policy
  orchestrator.py ← all orchestrator/ submodules
  renderer.py     ← orchestrator/models

learning/         ← schemas/prediction, schemas/enums
  models.py       ← pydantic
  scoring.py      ← learning/models, schemas/enums
  postmortem.py   ← learning/models, learning/scoring
  renderer.py     ← learning/models

v1_cli.py         ← all of the above
```
