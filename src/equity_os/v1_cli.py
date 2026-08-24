"""equity-os v1 CLI — evidence research coverage system.

Entry point: eqos
Data root: ./companies/  (or $EQUITY_OS_COMPANIES or --companies-dir)
Input root: ./inputs/    (or $EQUITY_OS_INPUTS   or --inputs-dir)

Commands
--------
  init-company          Create folder tree + starter CompanyDossier
  new-episode           Create a dated ThesisEpisode skeleton
  add-assumption        Add an AssumptionRecord to an episode
  update-assumption     Revise an assumption (always creates AssumptionChange)
  list-assumptions      Show all assumptions for an episode
  log-prediction        Add a PredictionRecord to an episode
  resolve-prediction    Attach a ResolutionRecord to a prediction
  render-company-summary Rebuild dossier.md from all episodes
  ingest                Ingest local documents from inputs/{ticker}/
  list-evidence         List ingested evidence for a ticker
"""

from __future__ import annotations

import sys
from datetime import date, datetime
from dateutil.parser import parse as _parse_date
from pathlib import Path
from typing import Annotated, Any
from uuid import UUID

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from .fs.io import append_jsonl, read_jsonl, write_json, write_md
from .fs.layout import CompanyLayout
from .fs.naming import unique_episode_dir_name
from .fs.readers import (
    find_active_assumption,
    find_prediction_by_metric,
    load_dossier,
    load_episode,
    load_full_dossier,
    resolve_episode_slug,
)
from .md_render import dossier_md, episode_md
from .schemas import (
    AssumptionChange,
    AssumptionRecord,
    AssumptionStatus,
    CompanyDossier,
    MaterialityLevel,
    PredictionRecord,
    Rating,
    ResolutionStatus,
    ThesisEpisode,
)

app = typer.Typer(
    name="eqos",
    help="equity-os v1 — public-equity company coverage system.",
    no_args_is_help=True,
)
console = Console()

_DEFAULT_COMPANIES = Path("companies")
_CompaniesDir = Annotated[
    Path,
    typer.Option("--companies-dir", envvar="EQUITY_OS_COMPANIES", help="Root data directory"),
]


def _layout(companies_dir: Path, ticker: str) -> CompanyLayout:
    return CompanyLayout(companies_dir, ticker)


def _abort(msg: str) -> None:
    console.print(f"[red]Error:[/red] {msg}")
    raise typer.Exit(1)


def _coerce_value(raw: str) -> float | int | str:
    """Try float → int → str for CLI-supplied values."""
    try:
        f = float(raw)
        return int(f) if f == int(f) else f
    except ValueError:
        return raw


# ===========================================================================
# init-company
# ===========================================================================


@app.command("init-company")
def init_company(
    ticker: Annotated[str, typer.Argument(help="Ticker symbol, e.g. AAPL")],
    name: Annotated[str, typer.Option("--name", "-n")],
    sector: Annotated[str | None, typer.Option("--sector")] = None,
    industry: Annotated[str | None, typer.Option("--industry")] = None,
    exchange: Annotated[str | None, typer.Option("--exchange")] = None,
    country: Annotated[str, typer.Option("--country")] = "US",
    description: Annotated[str | None, typer.Option("--description", "-d")] = None,
    tags: Annotated[str | None, typer.Option("--tags", help="Comma-separated tags")] = None,
    companies_dir: _CompaniesDir = _DEFAULT_COMPANIES,
) -> None:
    """Initialise coverage for a new company — creates folder tree + dossier.json."""
    layout = _layout(companies_dir, ticker)
    if layout.exists():
        _abort(f"{ticker.upper()} already initialised at {layout.root}")

    layout.init_dirs()

    tag_list = [t.strip() for t in tags.split(",")] if tags else []
    dossier = CompanyDossier(
        ticker=ticker.upper(),
        name=name,
        sector=sector,
        industry=industry,
        exchange=exchange,
        country=country,
        description=description,
        tags=tag_list,
    )

    write_json(layout.dossier_json, dossier)
    write_md(layout.dossier_md, dossier_md(dossier))

    console.print(
        Panel(
            f"[bold]{ticker.upper()}[/bold] — {name}\n"
            f"Root: [dim]{layout.root}[/dim]",
            title="[green]Company initialised[/green]",
            border_style="green",
        )
    )


# ===========================================================================
# new-episode
# ===========================================================================


@app.command("new-episode")
def new_episode(
    ticker: Annotated[str, typer.Argument()],
    title: Annotated[str, typer.Option("--title", "-t")],
    thesis: Annotated[str, typer.Option("--thesis")],
    rating: Annotated[Rating, typer.Option("--rating", "-r")],
    price_target: Annotated[float | None, typer.Option("--price-target", "--pt")] = None,
    currency: Annotated[str, typer.Option("--currency")] = "USD",
    companies_dir: _CompaniesDir = _DEFAULT_COMPANIES,
) -> None:
    """Create a new thesis episode for a company."""
    layout = _layout(companies_dir, ticker)
    if not layout.exists():
        _abort(f"{ticker.upper()} not initialised. Run init-company first.")

    slug = unique_episode_dir_name(title, layout.episodes_dir)
    episode = ThesisEpisode(
        ticker=ticker.upper(),
        title=title,
        thesis_statement=thesis,
        rating=rating,
        price_target=price_target,
        currency=currency,
    )

    layout.episode_dir(slug).mkdir(parents=True, exist_ok=True)
    write_json(layout.episode_json(slug), episode)
    write_md(layout.episode_md(slug), episode_md(episode))

    console.print(
        Panel(
            f"Episode:  [bold]{title}[/bold]\n"
            f"Slug:     [cyan]{slug}[/cyan]\n"
            f"Rating:   {rating.value}   PT: {price_target or 'N/A'} {currency}\n"
            f"ID:       [dim]{episode.id}[/dim]",
            title="[green]Episode created[/green]",
            border_style="green",
        )
    )


# ===========================================================================
# add-assumption
# ===========================================================================


@app.command("add-assumption")
def add_assumption(
    ticker: Annotated[str, typer.Argument()],
    episode: Annotated[str, typer.Argument(help="Episode slug or prefix")],
    key: Annotated[str, typer.Option("--key", "-k")],
    label: Annotated[str, typer.Option("--label", "-l")],
    value: Annotated[str, typer.Option("--value", "-v")],
    rationale: Annotated[str, typer.Option("--rationale", "-r")],
    unit: Annotated[str | None, typer.Option("--unit")] = None,
    owner_agent: Annotated[str, typer.Option("--owner-agent")] = "analyst",
    confidence: Annotated[float, typer.Option("--confidence", min=0.0, max=1.0)] = 0.7,
    materiality: Annotated[MaterialityLevel, typer.Option("--materiality")] = MaterialityLevel.MEDIUM,
    companies_dir: _CompaniesDir = _DEFAULT_COMPANIES,
) -> None:
    """Add an assumption to a thesis episode."""
    layout = _layout(companies_dir, ticker)
    if not layout.exists():
        _abort(f"{ticker.upper()} not initialised.")

    try:
        slug = resolve_episode_slug(layout, episode)
        ep = load_episode(layout, slug)
    except (FileNotFoundError, ValueError) as exc:
        _abort(str(exc))
        return  # unreachable; satisfies type checker

    # Prevent duplicate active keys
    existing_keys = [a.key for a in ep.assumptions if a.status == AssumptionStatus.ACTIVE]
    if key in existing_keys:
        _abort(
            f"Active assumption {key!r} already exists in this episode. "
            f"Use update-assumption to revise it."
        )

    assumption = AssumptionRecord(
        key=key,
        label=label,
        value=_coerce_value(value),
        unit=unit,
        owner_agent=owner_agent,
        rationale=rationale,
        confidence=confidence,
        materiality=materiality,
    )
    ep.assumptions.append(assumption)
    ep = ep.model_copy(update={"updated_at": datetime.utcnow()})

    write_json(layout.episode_json(slug), ep)
    write_md(layout.episode_md(slug), episode_md(ep))
    write_json(layout.assumption_json(slug, key, assumption.version), assumption)

    console.print(
        f"[green]Assumption added.[/green] "
        f"Key: [cyan]{key}[/cyan]  v{assumption.version}  "
        f"ID: [dim]{str(assumption.id)[:8]}…[/dim]"
    )


# ===========================================================================
# update-assumption
# ===========================================================================


@app.command("update-assumption")
def update_assumption(
    ticker: Annotated[str, typer.Argument()],
    episode: Annotated[str, typer.Argument(help="Episode slug or prefix")],
    key: Annotated[str, typer.Argument(help="Assumption key to revise")],
    new_value: Annotated[str, typer.Option("--new-value", "-v")],
    reason: Annotated[str, typer.Option("--reason", "-r")],
    confidence: Annotated[float | None, typer.Option("--confidence", min=0.0, max=1.0)] = None,
    changed_by: Annotated[str, typer.Option("--changed-by")] = "analyst",
    unit: Annotated[str | None, typer.Option("--unit")] = None,
    companies_dir: _CompaniesDir = _DEFAULT_COMPANIES,
) -> None:
    """Revise an assumption. Always records an AssumptionChange — never silently mutates."""
    layout = _layout(companies_dir, ticker)
    if not layout.exists():
        _abort(f"{ticker.upper()} not initialised.")

    try:
        slug = resolve_episode_slug(layout, episode)
        ep = load_episode(layout, slug)
        old = find_active_assumption(ep, key)
    except (FileNotFoundError, ValueError) as exc:
        _abort(str(exc))
        return

    new_conf = confidence if confidence is not None else old.confidence
    revised = old.revise(
        new_value=_coerce_value(new_value),
        new_confidence=new_conf,
        reason=reason,
        changed_by=changed_by,
        unit=unit,
    )

    # Replace old record with revised in episode (mark old as REVISED)
    ep.assumptions = [
        revised if a.id == old.id else a for a in ep.assumptions
    ]
    ep = ep.model_copy(update={"updated_at": datetime.utcnow()})

    # The change record that .revise() appended as the last history entry
    change_record: AssumptionChange = revised.history[-1]

    write_json(layout.episode_json(slug), ep)
    write_md(layout.episode_md(slug), episode_md(ep))
    write_json(layout.assumption_json(slug, key, revised.version), revised)
    append_jsonl(layout.assumption_changes(slug, key), change_record)

    console.print(
        f"[green]Assumption revised.[/green] "
        f"Key: [cyan]{key}[/cyan]  "
        f"v{old.version} → v{revised.version}  "
        f"[dim]{old.value} → {revised.value}[/dim]"
    )


# ===========================================================================
# list-assumptions
# ===========================================================================


@app.command("list-assumptions")
def list_assumptions(
    ticker: Annotated[str, typer.Argument()],
    episode: Annotated[str, typer.Argument(help="Episode slug or prefix")],
    all_versions: Annotated[bool, typer.Option("--all", help="Show retired/revised too")] = False,
    companies_dir: _CompaniesDir = _DEFAULT_COMPANIES,
) -> None:
    """List all assumptions for a thesis episode."""
    layout = _layout(companies_dir, ticker)
    if not layout.exists():
        _abort(f"{ticker.upper()} not initialised.")

    try:
        slug = resolve_episode_slug(layout, episode)
        ep = load_episode(layout, slug)
    except (FileNotFoundError, ValueError) as exc:
        _abort(str(exc))
        return

    assumptions = ep.assumptions if all_versions else ep.open_assumption_records()
    if not assumptions:
        console.print("[dim]No assumptions found.[/dim]")
        return

    table = Table(title=f"{ticker.upper()} — {slug} — Assumptions", show_lines=True)
    table.add_column("Key", style="cyan")
    table.add_column("Label")
    table.add_column("Value")
    table.add_column("Unit")
    table.add_column("Confidence")
    table.add_column("Materiality")
    table.add_column("Status")
    table.add_column("v#")
    table.add_column("Changes")

    for a in assumptions:
        n_changes = len(a.history)
        conf_color = "green" if a.confidence >= 0.75 else "yellow" if a.confidence >= 0.5 else "red"
        table.add_row(
            a.key,
            a.label,
            str(a.value),
            a.unit or "—",
            Text(f"{a.confidence * 100:.0f}%", style=conf_color),
            a.materiality.value,
            a.status.value,
            str(a.version),
            str(n_changes),
        )

    console.print(table)


# ===========================================================================
# log-prediction
# ===========================================================================


@app.command("log-prediction")
def log_prediction(
    ticker: Annotated[str, typer.Argument()],
    episode: Annotated[str, typer.Argument(help="Episode slug or prefix")],
    metric: Annotated[str, typer.Option("--metric", "-m")],
    description: Annotated[str, typer.Option("--description", "-d")],
    threshold: Annotated[str, typer.Option("--threshold", "-t")],
    horizon: Annotated[str, typer.Option("--horizon", "-h")],
    due_date: Annotated[str, typer.Option("--due-date", help="YYYY-MM-DD")],
    resolution_rule: Annotated[str, typer.Option("--resolution-rule")] = "To be determined at resolution time.",
    unit: Annotated[str | None, typer.Option("--unit")] = None,
    probability: Annotated[float, typer.Option("--probability", min=0.0, max=1.0)] = 0.6,
    materiality: Annotated[MaterialityLevel, typer.Option("--materiality")] = MaterialityLevel.MEDIUM,
    companies_dir: _CompaniesDir = _DEFAULT_COMPANIES,
) -> None:
    """Add an explicit, falsifiable prediction to an episode."""
    layout = _layout(companies_dir, ticker)
    if not layout.exists():
        _abort(f"{ticker.upper()} not initialised.")

    try:
        slug = resolve_episode_slug(layout, episode)
        ep = load_episode(layout, slug)
    except (FileNotFoundError, ValueError) as exc:
        _abort(str(exc))
        return

    try:
        parsed_due_date = _parse_date(due_date).date()
    except ValueError:
        _abort(f"Invalid due-date {due_date!r}. Expected YYYY-MM-DD.")
        return

    # Prevent duplicate metrics in same episode
    existing_metrics = [p.metric for p in ep.predictions]
    if metric in existing_metrics:
        _abort(f"Prediction with metric {metric!r} already exists. Metrics must be unique per episode.")

    prediction = PredictionRecord(
        description=description,
        metric=metric,
        threshold=_coerce_value(threshold),
        unit=unit,
        horizon=horizon,
        due_date=parsed_due_date,
        probability=probability,
        materiality=materiality,
        resolution_rule=resolution_rule,
    )
    ep.predictions.append(prediction)
    ep = ep.model_copy(update={"updated_at": datetime.utcnow()})

    write_json(layout.episode_json(slug), ep)
    write_md(layout.episode_md(slug), episode_md(ep))
    write_json(layout.prediction_json(slug, metric, prediction.id), prediction)

    console.print(
        f"[green]Prediction logged.[/green] "
        f"Metric: [cyan]{metric}[/cyan]  "
        f"Threshold: {prediction.threshold} {unit or ''}  "
        f"Due: {due_date}  "
        f"ID: [dim]{str(prediction.id)[:8]}…[/dim]"
    )


# ===========================================================================
# resolve-prediction
# ===========================================================================


@app.command("resolve-prediction")
def resolve_prediction(
    ticker: Annotated[str, typer.Argument()],
    episode: Annotated[str, typer.Argument(help="Episode slug or prefix")],
    metric: Annotated[str, typer.Argument(help="Prediction metric to resolve")],
    status: Annotated[ResolutionStatus, typer.Option("--status", "-s")],
    actual: Annotated[str, typer.Option("--actual", "-a")],
    notes: Annotated[str, typer.Option("--notes", "-n")],
    resolved_by: Annotated[str, typer.Option("--resolved-by")] = "analyst",
    companies_dir: _CompaniesDir = _DEFAULT_COMPANIES,
) -> None:
    """Record the actual outcome of a prediction."""
    layout = _layout(companies_dir, ticker)
    if not layout.exists():
        _abort(f"{ticker.upper()} not initialised.")

    try:
        slug = resolve_episode_slug(layout, episode)
        ep = load_episode(layout, slug)
        pred = find_prediction_by_metric(ep, metric)
    except (FileNotFoundError, ValueError) as exc:
        _abort(str(exc))
        return

    if pred.is_resolved:
        _abort(f"Prediction {metric!r} is already resolved as {pred.resolution.resolved_status.value}.")

    resolved_pred = pred.resolve(
        resolved_status=status,
        actual_outcome=_coerce_value(actual),
        notes=notes,
        resolved_by=resolved_by,
    )

    ep.predictions = [
        resolved_pred if p.metric == metric else p for p in ep.predictions
    ]
    ep = ep.model_copy(update={"updated_at": datetime.utcnow()})

    write_json(layout.episode_json(slug), ep)
    write_md(layout.episode_md(slug), episode_md(ep))
    write_json(
        layout.resolution_json(slug, metric, pred.id),
        resolved_pred.resolution,
    )

    err = (
        f"  Error: {resolved_pred.resolution.error_magnitude * 100:+.1f}%"
        if resolved_pred.resolution.error_magnitude is not None
        else ""
    )
    console.print(
        f"[green]Prediction resolved.[/green] "
        f"Metric: [cyan]{metric}[/cyan]  "
        f"Status: [bold]{status.value}[/bold]  "
        f"Actual: {resolved_pred.resolution.actual_outcome}{err}"
    )


# ===========================================================================
# render-company-summary
# ===========================================================================


@app.command("render-company-summary")
def render_company_summary(
    ticker: Annotated[str, typer.Argument()],
    companies_dir: _CompaniesDir = _DEFAULT_COMPANIES,
) -> None:
    """Rebuild dossier.md from all episodes and print a rich summary."""
    layout = _layout(companies_dir, ticker)
    if not layout.exists():
        _abort(f"{ticker.upper()} not initialised.")

    try:
        full = load_full_dossier(layout)
    except FileNotFoundError as exc:
        _abort(str(exc))
        return

    # Write refreshed markdown
    md = dossier_md(full)
    write_md(layout.dossier_md, md)

    # Rich terminal output
    pt = (
        f"{full.current_price_target:,.2f} {full.currency}"
        if full.current_price_target
        else "N/A"
    )
    console.print(
        Panel(
            f"[bold]{full.name}[/bold]  ({full.ticker})\n"
            f"Rating: [bold]{full.current_rating.value}[/bold]   PT: {pt}\n"
            f"Sector: {full.sector or '—'}   Industry: {full.industry or '—'}\n"
            f"Episodes: {len(full.episodes)}   Tags: {', '.join(full.tags) or '—'}",
            title="Company Summary",
            border_style="blue",
        )
    )

    if full.episodes:
        table = Table(title="Episodes", show_lines=True)
        table.add_column("Title")
        table.add_column("Rating")
        table.add_column("PT")
        table.add_column("Status")
        table.add_column("Assumptions")
        table.add_column("Predictions")
        table.add_column("Opened")

        for ep in full.episodes:
            n_active = sum(1 for a in ep.assumptions if a.status.value == "ACTIVE")
            n_pending = sum(1 for p in ep.predictions if not p.is_resolved)
            pt_ep = f"{ep.price_target:,.2f}" if ep.price_target else "—"
            table.add_row(
                ep.title,
                ep.rating.value,
                pt_ep,
                ep.status.value,
                str(n_active),
                f"{n_pending} pending",
                ep.created_at.strftime("%Y-%m-%d"),
            )
        console.print(table)

    console.print(f"[dim]Markdown written to {layout.dossier_md}[/dim]")


# ===========================================================================
# ingest
# ===========================================================================

_DEFAULT_INPUTS = Path("inputs")
_InputsDir = Annotated[
    Path,
    typer.Option("--inputs-dir", envvar="EQUITY_OS_INPUTS", help="Root inputs directory"),
]


@app.command("ingest")
def ingest(
    ticker: Annotated[str, typer.Argument()],
    file: Annotated[Path | None, typer.Option("--file", "-f", help="Ingest a single file")] = None,
    logical_type: Annotated[str | None, typer.Option("--logical-type", "-t")] = None,
    force: Annotated[bool, typer.Option("--force", help="Re-ingest even if duplicate")] = False,
    inputs_dir: _InputsDir = _DEFAULT_INPUTS,
    companies_dir: _CompaniesDir = _DEFAULT_COMPANIES,
) -> None:
    """Ingest local documents from inputs/{ticker}/ into companies/{ticker}/evidence/."""
    from .ingest.pipeline import ingest_dir, ingest_file

    ticker = ticker.upper()
    layout = _layout(companies_dir, ticker)
    if not layout.exists():
        _abort(f"{ticker} not initialised. Run init-company first.")

    if file is not None:
        if not file.exists():
            _abort(f"File not found: {file}")
        try:
            result = ingest_file(file, ticker, companies_dir, logical_type=logical_type, force=force)
        except Exception as exc:
            _abort(str(exc))
            return
        if result is None:
            console.print(f"[yellow]Skipped[/yellow] (duplicate): {file.name}")
        else:
            console.print(
                f"[green]Ingested[/green] {file.name}\n"
                f"  ID:     {result.evidence_id}\n"
                f"  Type:   {result.logical_type}\n"
                f"  Chunks: {len(result.chunks)}\n"
                f"  Words:  {result.extracted_metadata.get('word_count', '?')}"
            )
        return

    # Batch: ingest entire inputs/{ticker}/ directory
    ticker_inputs = inputs_dir / ticker
    if not ticker_inputs.exists():
        _abort(f"Inputs directory not found: {ticker_inputs}")

    ingested, skipped, failed = ingest_dir(
        ticker_inputs, ticker, companies_dir, logical_type=logical_type, force=force
    )

    table = Table(title=f"Ingest results — {ticker}", show_lines=True)
    table.add_column("File")
    table.add_column("Type")
    table.add_column("Chunks")
    table.add_column("Words")
    table.add_column("Status")

    for ev in ingested:
        table.add_row(
            Path(ev.file_path).name,
            ev.logical_type,
            str(len(ev.chunks)),
            str(ev.extracted_metadata.get("word_count", "?")),
            Text("ingested", style="green"),
        )
    for s in skipped:
        table.add_row(Path(s).name, "—", "—", "—", Text("duplicate", style="yellow"))
    for f_msg in failed:
        short = f_msg.split(":")[0]
        table.add_row(Path(short).name, "—", "—", "—", Text("failed", style="red"))

    console.print(table)
    if failed:
        for f_msg in failed:
            console.print(f"[red]  Error:[/red] {f_msg}")


# ===========================================================================
# list-evidence
# ===========================================================================


@app.command("list-evidence")
def list_evidence(
    ticker: Annotated[str, typer.Argument()],
    companies_dir: _CompaniesDir = _DEFAULT_COMPANIES,
) -> None:
    """List all ingested evidence for a company."""
    from .ingest.pipeline import list_catalog

    layout = _layout(companies_dir, ticker)
    if not layout.exists():
        _abort(f"{ticker.upper()} not initialised.")

    try:
        entries = list_catalog(companies_dir, ticker)
    except Exception as exc:
        _abort(str(exc))
        return

    if not entries:
        console.print("[dim]No evidence ingested yet.[/dim]")
        return

    table = Table(title=f"{ticker.upper()} — Evidence Catalog", show_lines=True)
    table.add_column("ID (short)")
    table.add_column("Type")
    table.add_column("Title")
    table.add_column("Source Date")
    table.add_column("Chunks")
    table.add_column("Reliability")

    for e in entries:
        table.add_row(
            str(e.evidence_id)[:8],
            e.logical_type,
            e.title[:50],
            str(e.source_date) if e.source_date else "—",
            str(e.chunk_count),
            f"{e.chunk_count}",  # placeholder for reliability (not in manifest)
        )
    console.print(table)


# ===========================================================================
# score-company
# ===========================================================================


@app.command("score-company")
def score_company(
    ticker: Annotated[str, typer.Argument()],
    episode: Annotated[str | None, typer.Option("--episode", "-e", help="Episode slug or prefix")] = None,
    companies_dir: _CompaniesDir = _DEFAULT_COMPANIES,
) -> None:
    """Score resolved predictions for a company (or one specific episode)."""
    from .fs.io import write_json, write_md
    from .fs.readers import load_episode, resolve_episode_slug
    from .learning.renderer import render_episode_score
    from .learning.scoring import score_episode

    layout = _layout(companies_dir, ticker)
    if not layout.exists():
        _abort(f"{ticker.upper()} not initialised.")

    slugs = [resolve_episode_slug(layout, episode)] if episode else layout.episode_slugs()
    if not slugs:
        console.print("[dim]No episodes found.[/dim]")
        return

    for slug in slugs:
        try:
            ep = load_episode(layout, slug)
        except FileNotFoundError:
            continue

        # Collect prediction dicts from episode
        predictions = [p.model_dump(mode="json") for p in ep.predictions]
        if not predictions:
            console.print(f"[dim]{slug}: no predictions.[/dim]")
            continue

        # Resolutions are embedded in prediction.resolution
        score = score_episode(ticker.upper(), slug, predictions, {})

        layout.scores_dir.mkdir(parents=True, exist_ok=True)
        layout.score_json(slug).write_text(score.model_dump_json(indent=2), encoding="utf-8")
        write_md(layout.score_md(slug), render_episode_score(score))

        b_str = f"{score.brier_score:.4f}" if score.brier_score is not None else "—"
        hr_str = f"{(score.hit_rate or 0) * 100:.0f}%" if score.hit_rate is not None else "—"
        console.print(
            f"[green]{slug}[/green]  "
            f"Brier: [bold]{b_str}[/bold]  Hit rate: [bold]{hr_str}[/bold]  "
            f"Scored: {score.scored_count}/{score.total_predictions}"
        )


# ===========================================================================
# resolve-episode
# ===========================================================================


@app.command("resolve-episode")
def resolve_episode_cmd(
    ticker: Annotated[str, typer.Argument()],
    episode: Annotated[str, typer.Argument(help="Episode slug or prefix")],
    resolution_file: Annotated[Path | None, typer.Option("--resolution-file", "-f",
        help="JSON array of {metric, status, actual, notes} objects")] = None,
    metric: Annotated[str | None, typer.Option("--metric", "-m")] = None,
    status: Annotated[str | None, typer.Option("--status", "-s")] = None,
    actual: Annotated[str | None, typer.Option("--actual", "-a")] = None,
    notes: Annotated[str, typer.Option("--notes", "-n")] = "",
    resolved_by: Annotated[str, typer.Option("--resolved-by")] = "analyst",
    companies_dir: _CompaniesDir = _DEFAULT_COMPANIES,
) -> None:
    """Resolve predictions in an episode from a JSON file or individual flags."""
    import json
    from .fs.io import write_json, write_md
    from .fs.readers import load_episode, resolve_episode_slug
    from .md_render import episode_md as ep_md
    from .schemas.enums import ResolutionStatus

    layout = _layout(companies_dir, ticker)
    if not layout.exists():
        _abort(f"{ticker.upper()} not initialised.")

    try:
        slug = resolve_episode_slug(layout, episode)
        ep = load_episode(layout, slug)
    except (FileNotFoundError, ValueError) as exc:
        _abort(str(exc))
        return

    # Build resolution specs
    if resolution_file is not None:
        if not resolution_file.exists():
            _abort(f"Resolution file not found: {resolution_file}")
        specs = json.loads(resolution_file.read_text(encoding="utf-8"))
    elif metric and status and actual is not None:
        specs = [{"metric": metric, "status": status, "actual": actual, "notes": notes}]
    else:
        _abort("Provide --resolution-file or all of --metric, --status, --actual.")
        return

    applied = 0
    for spec in specs:
        m = spec.get("metric", "")
        s = spec.get("status", "")
        a = spec.get("actual")
        n = spec.get("notes", "")

        try:
            rs = ResolutionStatus(s.upper())
        except ValueError:
            console.print(f"[red]Unknown status {s!r} for metric {m!r} — skipped.[/red]")
            continue

        pred = next((p for p in ep.predictions if p.metric == m), None)
        if pred is None:
            console.print(f"[yellow]Metric {m!r} not found in episode — skipped.[/yellow]")
            continue
        if pred.is_resolved:
            console.print(f"[yellow]{m!r} already resolved — skipped.[/yellow]")
            continue

        resolved = pred.resolve(
            resolved_status=rs,
            actual_outcome=_coerce_value(str(a)),
            notes=n,
            resolved_by=resolved_by,
        )
        ep.predictions = [resolved if p.metric == m else p for p in ep.predictions]
        applied += 1
        console.print(f"[green]Resolved[/green] `{m}` → {s.upper()}")

    if applied:
        ep = ep.model_copy(update={"updated_at": datetime.utcnow()})
        write_json(layout.episode_json(slug), ep)
        write_md(layout.episode_md(slug), ep_md(ep))
        console.print(f"[green]{applied} prediction(s) resolved and episode updated.[/green]")
    else:
        console.print("[yellow]No predictions were resolved.[/yellow]")


# ===========================================================================
# postmortem-episode
# ===========================================================================


@app.command("postmortem-episode")
def postmortem_episode(
    ticker: Annotated[str, typer.Argument()],
    episode: Annotated[str, typer.Argument(help="Episode slug or prefix")],
    thesis: Annotated[str | None, typer.Option("--thesis", "-t",
        help="Thesis statement (uses episode thesis if omitted)")] = None,
    companies_dir: _CompaniesDir = _DEFAULT_COMPANIES,
) -> None:
    """Generate a postmortem for a completed episode."""
    from .fs.io import write_md
    from .fs.readers import load_episode, resolve_episode_slug
    from .learning.postmortem import generate_postmortem
    from .learning.renderer import render_episode_score, render_postmortem
    from .learning.scoring import score_episode

    layout = _layout(companies_dir, ticker)
    if not layout.exists():
        _abort(f"{ticker.upper()} not initialised.")

    try:
        slug = resolve_episode_slug(layout, episode)
        ep = load_episode(layout, slug)
    except (FileNotFoundError, ValueError) as exc:
        _abort(str(exc))
        return

    predictions = [p.model_dump(mode="json") for p in ep.predictions]
    if not predictions:
        _abort(f"No predictions in episode {slug!r}. Log predictions first.")

    resolved_count = sum(1 for p in ep.predictions if p.is_resolved)
    if resolved_count == 0:
        _abort(f"No resolved predictions in {slug!r}. Use resolve-episode first.")

    assumptions = [a.model_dump(mode="json") for a in ep.assumptions]
    thesis_stmt = thesis or ep.thesis_statement

    score = score_episode(ticker.upper(), slug, predictions, {})
    report = generate_postmortem(score, thesis_stmt, assumptions)

    layout.postmortems_dir.mkdir(parents=True, exist_ok=True)
    layout.scores_dir.mkdir(parents=True, exist_ok=True)
    layout.score_json(slug).write_text(score.model_dump_json(indent=2), encoding="utf-8")
    layout.postmortem_json(slug).write_text(report.model_dump_json(indent=2), encoding="utf-8")
    write_md(layout.score_md(slug), render_episode_score(score))
    write_md(layout.postmortem_md(slug), render_postmortem(report))

    console.print(
        Panel(
            f"Verdict: [bold]{report.verdict}[/bold]\n"
            f"Hit rate: {(score.hit_rate or 0) * 100:.0f}%  "
            f"Brier: {f'{score.brier_score:.4f}' if score.brier_score is not None else '—'}\n"
            f"Scored: {score.scored_count}/{score.total_predictions} predictions\n"
            f"Postmortem: [dim]{layout.postmortem_md(slug)}[/dim]",
            title=f"[green]Postmortem — {ticker.upper()} / {slug}[/green]",
            border_style="green",
        )
    )
