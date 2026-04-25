.PHONY: demo test lint clean

# ── Demo ─────────────────────────────────────────────────────────────────────
## Run the full end-to-end demo (MSFT, no external APIs, all artifacts → demo/)
demo:
	uv run python scripts/run_demo.py

# ── Tests ────────────────────────────────────────────────────────────────────
## Run the full test suite
test:
	uv run pytest -v

## Run tests and show coverage summary
test-cov:
	uv run pytest -v --tb=short -q

# ── Schemas ──────────────────────────────────────────────────────────────────
## Re-export all JSON Schema files to generated/
schemas:
	uv run python scripts/export_schemas.py

# ── Clean ────────────────────────────────────────────────────────────────────
## Remove demo artifacts (leaves inputs/ intact)
clean-demo:
	rm -rf demo/companies demo/agents demo/orchestrator demo/diff demo/postmortem demo/README.md

## Remove generated JSON schemas
clean-schemas:
	rm -f generated/*.schema.json

## Remove all generated artifacts
clean: clean-demo clean-schemas
