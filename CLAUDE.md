# CLAUDE.md — EQOS

Operating rules for work in this repository.

## Core rules

1. **Use `eqos` for every workflow.** The normalized company-folder architecture under `companies/<TICKER>/` is the only supported storage model.

2. **Never overwrite prior analytical state.** Episodes, assumption versions, predictions, resolutions, scores, and postmortems are append-only or versioned. Use the path and I/O helpers in `src/equity_os/fs/`.

3. **Prefer explicit schemas over loose dictionaries.** Data crossing module boundaries must use Pydantic models. Keep functions and module responsibilities small and typed.

4. **Keep the reasoning chain auditable.** Preserve the separation between evidence, observations, inferences, decisions, predictions, outcomes, scoring, and postmortems.

5. **Do not force conclusions from weak evidence.** Preserve `AnalysisStatus`, source-coverage requirements, claim-level citations, freshness diagnostics, and orchestrator abstention gates.

6. **Do not issue small-sample thesis verdicts.** Preserve minimum scoreable sample and coverage gates, and distinguish `PENDING` from `INSUFFICIENT_EVIDENCE`.

7. **Preserve source provenance.** Evidence must retain its source identity, retrieval metadata, content hash, and raw-document location when applicable. Do not silently impute or invent missing source fields.

8. **Treat external access as an explicit connector concern.** Connectors must use typed `RawDocument` boundaries, declared identities, host allowlists, conservative rate limits, retries, and deduplication before entering the shared ingestion pipeline.

9. **Generate readable sidecars from structured state.** JSON is authoritative; markdown is a generated view and should remain reproducible from stored inputs.

10. **Test every material change.** Add focused tests for new behavior, run the relevant targeted suite, then run the full suite before handoff.

## Architecture

```text
src/equity_os/
  schemas/       Pydantic domain models and enums
  fs/            normalized paths, atomic I/O, and readers
  ingest/        normalization, chunking, deduplication, and evidence storage
  connectors/    external document discovery and retrieval
  agents/        evidence-backed specialist analysis
  orchestrator/  policy, conflicts, synthesis, and decisions
  diff/          analytical change detection and assumption proposals
  learning/      prediction scoring and postmortems
  md_render.py   markdown sidecar generation
  v1_cli.py      `eqos` Typer entry point
```

## State layout

```text
companies/<TICKER>/
  core/dossier.json
  episodes/<episode-slug>/episode.json
  assumptions/<episode-slug>/<key>_vNNN.json
  predictions/<episode-slug>/<metric>_<id8>.json
  resolutions/<episode-slug>/<metric>_<id8>_resolution.json
  evidence/<evidence-id>.json
  scores/<episode-slug>.json
  postmortems/<episode-slug>.json
```

## Common commands

```bash
uv sync
uv run eqos --help
uv run eqos init-company AAPL --name "Apple Inc." --sector Technology
uv run eqos ingest AAPL
uv run eqos config-check
uv run eqos sync-sec AAPL
uv run pytest -v
```

Local `config/eqos.toml` may contain contact information and must remain ignored. Downloaded raw evidence under `companies/*/evidence/raw/` is also ignored; do not delete local company data during cleanup or testing.
