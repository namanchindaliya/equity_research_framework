"""Rich terminal rendering and markdown report generation."""

from __future__ import annotations

from datetime import datetime

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from .schemas import (
    Assumption,
    AssumptionStatus,
    Company,
    Episode,
    EpisodeStatus,
    Prediction,
    PredictionOutcome,
    Rating,
)

console = Console()

_RATING_COLOR: dict[Rating, str] = {
    Rating.BUY: "bold green",
    Rating.HOLD: "bold yellow",
    Rating.SELL: "bold red",
    Rating.NOT_RATED: "dim",
}

_OUTCOME_COLOR: dict[PredictionOutcome, str] = {
    PredictionOutcome.PENDING: "yellow",
    PredictionOutcome.CORRECT: "green",
    PredictionOutcome.INCORRECT: "red",
    PredictionOutcome.INCONCLUSIVE: "dim",
}


# ---------------------------------------------------------------------------
# Company summary panel
# ---------------------------------------------------------------------------


def show_company(company: Company) -> None:
    rating_text = Text(company.current_rating.value, style=_RATING_COLOR[company.current_rating])
    pt = (
        f"{company.current_price_target:.2f} {company.currency}"
        if company.current_price_target is not None
        else "—"
    )
    lines = [
        f"[bold]{company.name}[/bold]  ({company.ticker})",
        f"Sector: {company.sector or '—'}  |  Industry: {company.industry or '—'}",
        f"Rating: {company.current_rating.value}  |  Price Target: {pt}",
        f"Episodes: {len(company.episodes)}  |  Updated: {company.updated_at.strftime('%Y-%m-%d')}",
    ]
    if company.description:
        lines.append(f"\n{company.description}")
    console.print(Panel("\n".join(lines), title="Company Overview", border_style="blue"))


# ---------------------------------------------------------------------------
# Episode list table
# ---------------------------------------------------------------------------


def show_episodes(company: Company) -> None:
    table = Table(title=f"Episodes — {company.ticker}", show_lines=True)
    table.add_column("ID (short)", style="dim", width=10)
    table.add_column("Title")
    table.add_column("Rating")
    table.add_column("PT")
    table.add_column("Status")
    table.add_column("Opened")
    table.add_column("Closed")

    for ep in company.episodes:
        table.add_row(
            str(ep.id)[:8],
            ep.title,
            Text(ep.rating.value, style=_RATING_COLOR[ep.rating]),
            f"{ep.price_target:.2f} {ep.currency}" if ep.price_target else "—",
            Text(ep.status.value, style="green" if ep.status == EpisodeStatus.OPEN else "dim"),
            ep.created_at.strftime("%Y-%m-%d"),
            ep.closed_at.strftime("%Y-%m-%d") if ep.closed_at else "—",
        )
    console.print(table)


# ---------------------------------------------------------------------------
# Episode detail
# ---------------------------------------------------------------------------


def show_episode(ep: Episode) -> None:
    console.print(
        Panel(
            f"[bold]{ep.title}[/bold]\n\n{ep.thesis}",
            title=f"Episode {str(ep.id)[:8]}  [{ep.status.value}]",
            border_style="cyan",
        )
    )
    _show_assumptions(ep.assumptions)
    _show_predictions(ep.predictions)


def _show_assumptions(assumptions: list[Assumption]) -> None:
    if not assumptions:
        return
    table = Table(title="Assumptions", show_lines=True)
    table.add_column("Key")
    table.add_column("Value")
    table.add_column("Unit")
    table.add_column("Status")
    table.add_column("Rationale")
    for a in assumptions:
        style = "dim" if a.status != AssumptionStatus.ACTIVE else ""
        table.add_row(
            Text(a.key, style=style),
            Text(str(a.value), style=style),
            a.unit or "—",
            a.status.value,
            a.rationale,
        )
    console.print(table)


def _show_predictions(predictions: list[Prediction]) -> None:
    if not predictions:
        return
    table = Table(title="Predictions", show_lines=True)
    table.add_column("Description")
    table.add_column("Target")
    table.add_column("Horizon")
    table.add_column("Outcome")
    table.add_column("Actual")
    for p in predictions:
        table.add_row(
            p.description,
            f"{p.target_value} {p.unit or ''}".strip(),
            p.horizon,
            Text(p.outcome.value, style=_OUTCOME_COLOR[p.outcome]),
            str(p.actual_value) if p.actual_value is not None else "—",
        )
    console.print(table)


# ---------------------------------------------------------------------------
# Markdown report
# ---------------------------------------------------------------------------


def markdown_report(company: Company) -> str:
    lines: list[str] = []
    pt = (
        f"{company.current_price_target:.2f} {company.currency}"
        if company.current_price_target is not None
        else "N/A"
    )
    lines += [
        f"# {company.name} ({company.ticker}) — Coverage Report",
        f"",
        f"**Rating:** {company.current_rating.value}  |  **Price Target:** {pt}",
        f"**Sector:** {company.sector or 'N/A'}  |  **Industry:** {company.industry or 'N/A'}",
        f"**Generated:** {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}",
        f"",
    ]
    if company.description:
        lines += [company.description, ""]

    for ep in company.episodes:
        lines += [
            f"---",
            f"",
            f"## Episode: {ep.title}",
            f"**ID:** `{ep.id}`  |  **Status:** {ep.status.value}  |  **Rating:** {ep.rating.value}",
            f"**Opened:** {ep.created_at.strftime('%Y-%m-%d')}",
        ]
        if ep.closed_at:
            lines.append(f"**Closed:** {ep.closed_at.strftime('%Y-%m-%d')}")
        lines += ["", f"### Thesis", ep.thesis, ""]

        if ep.assumptions:
            lines += ["### Assumptions", ""]
            lines += ["| Key | Value | Unit | Status | Rationale |", "| --- | --- | --- | --- | --- |"]
            for a in ep.assumptions:
                lines.append(
                    f"| {a.key} | {a.value} | {a.unit or ''} | {a.status.value} | {a.rationale} |"
                )
            lines.append("")

        if ep.predictions:
            lines += ["### Predictions", ""]
            lines += ["| Description | Target | Horizon | Outcome | Actual |", "| --- | --- | --- | --- | --- |"]
            for p in ep.predictions:
                actual = str(p.actual_value) if p.actual_value is not None else "—"
                lines.append(
                    f"| {p.description} | {p.target_value} {p.unit or ''} | {p.horizon} | {p.outcome.value} | {actual} |"
                )
            lines.append("")

        if ep.close_note:
            lines += [f"### Close Note", ep.close_note, ""]

    return "\n".join(lines)
