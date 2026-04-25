"""Typer CLI — entry point: equity-os."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Annotated
from uuid import UUID

import typer
from rich.console import Console

from .episode import (
    add_assumption,
    add_prediction,
    close_episode,
    open_episode,
    resolve_prediction,
    revise_assumption,
)
from .render import console, markdown_report, show_company, show_episode, show_episodes
from .schemas import Company, PredictionOutcome, Rating
from .store import CompanyStore

app = typer.Typer(name="equity-os", help="Public-equity company coverage system.", no_args_is_help=True)
episode_app = typer.Typer(help="Manage thesis episodes.", no_args_is_help=True)
assumption_app = typer.Typer(help="Manage assumptions.", no_args_is_help=True)
prediction_app = typer.Typer(help="Manage predictions.", no_args_is_help=True)

app.add_typer(episode_app, name="episode")
app.add_typer(assumption_app, name="assumption")
app.add_typer(prediction_app, name="prediction")

_DATA_DIR_DEFAULT = Path.home() / ".equity_os" / "data"


def _store(data_dir: Path) -> CompanyStore:
    return CompanyStore(data_dir)


# ---------------------------------------------------------------------------
# Company commands
# ---------------------------------------------------------------------------


@app.command()
def init(
    ticker: Annotated[str, typer.Argument(help="Ticker symbol, e.g. AAPL")],
    name: Annotated[str, typer.Option("--name", "-n", help="Full company name")],
    sector: Annotated[str | None, typer.Option("--sector")] = None,
    industry: Annotated[str | None, typer.Option("--industry")] = None,
    description: Annotated[str | None, typer.Option("--description", "-d")] = None,
    data_dir: Annotated[Path, typer.Option("--data-dir", envvar="EQUITY_OS_DATA")] = _DATA_DIR_DEFAULT,
) -> None:
    """Initialize coverage for a new company."""
    store = _store(data_dir)
    company = Company(
        ticker=ticker.upper(),
        name=name,
        sector=sector,
        industry=industry,
        description=description,
    )
    try:
        path = store.create(company)
        console.print(f"[green]Created[/green] coverage for {ticker.upper()} at {path}")
    except ValueError as e:
        console.print(f"[red]Error:[/red] {e}")
        raise typer.Exit(1)


@app.command()
def show(
    ticker: Annotated[str, typer.Argument(help="Ticker symbol")],
    data_dir: Annotated[Path, typer.Option("--data-dir", envvar="EQUITY_OS_DATA")] = _DATA_DIR_DEFAULT,
) -> None:
    """Show company overview and all episodes."""
    store = _store(data_dir)
    try:
        company = store.load(ticker)
    except FileNotFoundError as e:
        console.print(f"[red]Error:[/red] {e}")
        raise typer.Exit(1)
    show_company(company)
    show_episodes(company)


@app.command()
def list_companies(
    data_dir: Annotated[Path, typer.Option("--data-dir", envvar="EQUITY_OS_DATA")] = _DATA_DIR_DEFAULT,
) -> None:
    """List all covered companies."""
    store = _store(data_dir)
    tickers = store.all_tickers()
    if not tickers:
        console.print("[dim]No companies in coverage.[/dim]")
        return
    for t in tickers:
        company = store.load(t)
        console.print(f"[bold]{t}[/bold]  {company.name}  [{company.current_rating.value}]")


@app.command()
def report(
    ticker: Annotated[str, typer.Argument(help="Ticker symbol")],
    output: Annotated[Path | None, typer.Option("--output", "-o", help="Write markdown to file")] = None,
    data_dir: Annotated[Path, typer.Option("--data-dir", envvar="EQUITY_OS_DATA")] = _DATA_DIR_DEFAULT,
) -> None:
    """Generate a markdown report for a company."""
    store = _store(data_dir)
    try:
        company = store.load(ticker)
    except FileNotFoundError as e:
        console.print(f"[red]Error:[/red] {e}")
        raise typer.Exit(1)
    md = markdown_report(company)
    if output:
        output.write_text(md)
        console.print(f"[green]Report written to {output}[/green]")
    else:
        console.print(md)


# ---------------------------------------------------------------------------
# Episode commands
# ---------------------------------------------------------------------------


@episode_app.command("new")
def episode_new(
    ticker: Annotated[str, typer.Argument(help="Ticker symbol")],
    title: Annotated[str, typer.Option("--title", "-t")],
    thesis: Annotated[str, typer.Option("--thesis")],
    rating: Annotated[Rating, typer.Option("--rating", "-r")],
    price_target: Annotated[float | None, typer.Option("--pt")] = None,
    currency: Annotated[str, typer.Option("--currency")] = "USD",
    data_dir: Annotated[Path, typer.Option("--data-dir", envvar="EQUITY_OS_DATA")] = _DATA_DIR_DEFAULT,
) -> None:
    """Open a new thesis episode."""
    store = _store(data_dir)
    try:
        ep = open_episode(store, ticker, title, thesis, rating, price_target, currency)
        console.print(f"[green]Episode opened.[/green] ID: {ep.id}")
    except FileNotFoundError as e:
        console.print(f"[red]Error:[/red] {e}")
        raise typer.Exit(1)


@episode_app.command("close")
def episode_close(
    ticker: Annotated[str, typer.Argument(help="Ticker symbol")],
    episode_id: Annotated[str, typer.Argument(help="Episode UUID (or prefix)")],
    note: Annotated[str, typer.Option("--note", "-n")],
    data_dir: Annotated[Path, typer.Option("--data-dir", envvar="EQUITY_OS_DATA")] = _DATA_DIR_DEFAULT,
) -> None:
    """Close a thesis episode."""
    store = _store(data_dir)
    try:
        company = store.load(ticker)
        ep_id = _resolve_episode_id(company, episode_id)
        ep = close_episode(store, ticker, ep_id, note)
        console.print(f"[green]Episode closed.[/green] ID: {ep.id}")
    except (FileNotFoundError, ValueError) as e:
        console.print(f"[red]Error:[/red] {e}")
        raise typer.Exit(1)


@episode_app.command("show")
def episode_show(
    ticker: Annotated[str, typer.Argument(help="Ticker symbol")],
    episode_id: Annotated[str, typer.Argument(help="Episode UUID (or prefix)")],
    data_dir: Annotated[Path, typer.Option("--data-dir", envvar="EQUITY_OS_DATA")] = _DATA_DIR_DEFAULT,
) -> None:
    """Show a single episode in detail."""
    store = _store(data_dir)
    try:
        company = store.load(ticker)
        ep_id = _resolve_episode_id(company, episode_id)
        ep = next(e for e in company.episodes if e.id == ep_id)
        show_episode(ep)
    except (FileNotFoundError, ValueError) as e:
        console.print(f"[red]Error:[/red] {e}")
        raise typer.Exit(1)


# ---------------------------------------------------------------------------
# Assumption commands
# ---------------------------------------------------------------------------


@assumption_app.command("add")
def assumption_add(
    ticker: Annotated[str, typer.Argument()],
    episode_id: Annotated[str, typer.Argument()],
    key: Annotated[str, typer.Option("--key", "-k")],
    value: Annotated[str, typer.Option("--value", "-v")],
    rationale: Annotated[str, typer.Option("--rationale", "-r")],
    unit: Annotated[str | None, typer.Option("--unit")] = None,
    data_dir: Annotated[Path, typer.Option("--data-dir", envvar="EQUITY_OS_DATA")] = _DATA_DIR_DEFAULT,
) -> None:
    """Add an assumption to an episode."""
    store = _store(data_dir)
    try:
        company = store.load(ticker)
        ep_id = _resolve_episode_id(company, episode_id)
        a = add_assumption(store, ticker, ep_id, key, _coerce(value), rationale, unit)
        console.print(f"[green]Assumption added.[/green] ID: {a.id}")
    except (FileNotFoundError, ValueError) as e:
        console.print(f"[red]Error:[/red] {e}")
        raise typer.Exit(1)


@assumption_app.command("revise")
def assumption_revise(
    ticker: Annotated[str, typer.Argument()],
    episode_id: Annotated[str, typer.Argument()],
    assumption_id: Annotated[str, typer.Argument()],
    value: Annotated[str, typer.Option("--value", "-v")],
    rationale: Annotated[str, typer.Option("--rationale", "-r")],
    unit: Annotated[str | None, typer.Option("--unit")] = None,
    data_dir: Annotated[Path, typer.Option("--data-dir", envvar="EQUITY_OS_DATA")] = _DATA_DIR_DEFAULT,
) -> None:
    """Revise an existing assumption (preserves history)."""
    store = _store(data_dir)
    try:
        company = store.load(ticker)
        ep_id = _resolve_episode_id(company, episode_id)
        ep = next(e for e in company.episodes if e.id == ep_id)
        a_id = _resolve_assumption_id(ep, assumption_id)
        new_a = revise_assumption(store, ticker, ep_id, a_id, _coerce(value), rationale, unit)
        console.print(f"[green]Assumption revised.[/green] New ID: {new_a.id}")
    except (FileNotFoundError, ValueError) as e:
        console.print(f"[red]Error:[/red] {e}")
        raise typer.Exit(1)


# ---------------------------------------------------------------------------
# Prediction commands
# ---------------------------------------------------------------------------


@prediction_app.command("add")
def prediction_add(
    ticker: Annotated[str, typer.Argument()],
    episode_id: Annotated[str, typer.Argument()],
    description: Annotated[str, typer.Option("--description", "-d")],
    metric: Annotated[str, typer.Option("--metric", "-m")],
    target: Annotated[str, typer.Option("--target", "-t")],
    horizon: Annotated[str, typer.Option("--horizon", "-h")],
    unit: Annotated[str | None, typer.Option("--unit")] = None,
    data_dir: Annotated[Path, typer.Option("--data-dir", envvar="EQUITY_OS_DATA")] = _DATA_DIR_DEFAULT,
) -> None:
    """Add a prediction to an episode."""
    store = _store(data_dir)
    try:
        company = store.load(ticker)
        ep_id = _resolve_episode_id(company, episode_id)
        p = add_prediction(store, ticker, ep_id, description, metric, _coerce(target), horizon, unit)
        console.print(f"[green]Prediction added.[/green] ID: {p.id}")
    except (FileNotFoundError, ValueError) as e:
        console.print(f"[red]Error:[/red] {e}")
        raise typer.Exit(1)


@prediction_app.command("resolve")
def prediction_resolve(
    ticker: Annotated[str, typer.Argument()],
    episode_id: Annotated[str, typer.Argument()],
    prediction_id: Annotated[str, typer.Argument()],
    outcome: Annotated[PredictionOutcome, typer.Option("--outcome", "-o")],
    actual: Annotated[str, typer.Option("--actual", "-a")],
    note: Annotated[str, typer.Option("--note", "-n")],
    data_dir: Annotated[Path, typer.Option("--data-dir", envvar="EQUITY_OS_DATA")] = _DATA_DIR_DEFAULT,
) -> None:
    """Resolve a prediction with its actual outcome."""
    store = _store(data_dir)
    try:
        company = store.load(ticker)
        ep_id = _resolve_episode_id(company, episode_id)
        ep = next(e for e in company.episodes if e.id == ep_id)
        p_id = _resolve_prediction_id(ep, prediction_id)
        p = resolve_prediction(store, ticker, ep_id, p_id, outcome, _coerce(actual), note)
        console.print(f"[green]Prediction resolved.[/green] Outcome: {p.outcome.value}")
    except (FileNotFoundError, ValueError) as e:
        console.print(f"[red]Error:[/red] {e}")
        raise typer.Exit(1)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _resolve_episode_id(company: Company, prefix: str) -> UUID:
    matches = [ep.id for ep in company.episodes if str(ep.id).startswith(prefix)]
    if not matches:
        raise ValueError(f"No episode matching prefix {prefix!r} for {company.ticker}.")
    if len(matches) > 1:
        raise ValueError(f"Ambiguous prefix {prefix!r} — matched {len(matches)} episodes.")
    return matches[0]


def _resolve_assumption_id(episode, prefix: str) -> UUID:
    from .schemas import Episode as Ep
    matches = [a.id for a in episode.assumptions if str(a.id).startswith(prefix)]
    if not matches:
        raise ValueError(f"No assumption matching prefix {prefix!r}.")
    if len(matches) > 1:
        raise ValueError(f"Ambiguous assumption prefix {prefix!r}.")
    return matches[0]


def _resolve_prediction_id(episode, prefix: str) -> UUID:
    matches = [p.id for p in episode.predictions if str(p.id).startswith(prefix)]
    if not matches:
        raise ValueError(f"No prediction matching prefix {prefix!r}.")
    if len(matches) > 1:
        raise ValueError(f"Ambiguous prediction prefix {prefix!r}.")
    return matches[0]


def _coerce(value: str) -> float | int | str:
    """Try to parse a CLI string value as a number, else keep as string."""
    try:
        as_int = int(value)
        return as_int
    except ValueError:
        pass
    try:
        return float(value)
    except ValueError:
        return value
