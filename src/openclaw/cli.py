import typer

from openclaw.providers import FixtureResearchProvider
from openclaw.renderers import (
    render_deep_dive_text,
    render_watchlist_json,
    render_watchlist_text,
)
from openclaw.reports import build_deep_dive, build_watchlist


app = typer.Typer(help="OpenClaw Nordic investing research CLI.")
sources_app = typer.Typer(help="Inspect and validate research sources.")
app.add_typer(sources_app, name="sources")


@app.callback()
def main() -> None:
    """OpenClaw Nordic investing research CLI."""


def _parse_countries(raw: str) -> tuple[str, ...]:
    return tuple(country.strip().upper() for country in raw.split(",") if country.strip())


@app.command()
def watchlist(
    country: str = typer.Option(
        "se,fi",
        "--country",
        help="Comma-separated country codes, such as se,fi.",
    ),
    limit: int = typer.Option(20, "--limit", min=1, max=100),
    include_first_north: bool = typer.Option(True, "--include-first-north/--exclude-first-north"),
    output: str = typer.Option("text", "--output", help="Output format: text or json."),
) -> None:
    provider = FixtureResearchProvider()
    items = build_watchlist(
        provider,
        countries=_parse_countries(country),
        limit=limit,
        include_first_north=include_first_north,
    )

    normalized_output = output.strip().lower()
    if normalized_output == "text":
        typer.echo(render_watchlist_text(items))
        return
    if normalized_output == "json":
        typer.echo(render_watchlist_json(items))
        return
    raise typer.BadParameter("output must be 'text' or 'json'")


@app.command("deep-dive")
def deep_dive(ticker: str) -> None:
    provider = FixtureResearchProvider()
    try:
        report = build_deep_dive(provider, ticker)
    except LookupError as exc:
        raise typer.BadParameter(str(exc)) from exc
    typer.echo(render_deep_dive_text(report))


@sources_app.command("test")
def test_sources() -> None:
    provider = FixtureResearchProvider()
    for check in provider.source_checks():
        typer.echo(f"{check.name}: {check.status} - {check.detail}")
