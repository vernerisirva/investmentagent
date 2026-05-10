from datetime import datetime, timezone
from pathlib import Path

import typer

from investmentagent.providers import create_provider
from investmentagent.renderers import (
    render_deep_dive_json,
    render_deep_dive_text,
    render_watchlist_json,
    render_watchlist_report_json,
    render_watchlist_report_markdown,
    render_watchlist_text,
)
from investmentagent.reports import build_deep_dive, build_watchlist, normalize_watchlist_strategy


app = typer.Typer(help="InvestmentAgent Nordic investing research CLI.", no_args_is_help=False)
sources_app = typer.Typer(help="Inspect and validate research sources.")
app.add_typer(sources_app, name="sources")


@app.callback(invoke_without_command=True)
def main(ctx: typer.Context) -> None:
    """InvestmentAgent Nordic investing research CLI."""
    if ctx.invoked_subcommand is None:
        typer.echo(ctx.get_help())
        raise typer.Exit()


def _parse_countries(raw: str) -> tuple[str, ...]:
    countries = tuple(country.strip().upper() for country in raw.split(",") if country.strip())
    if not countries:
        raise typer.BadParameter("at least one country code is required")
    return countries


def _provider_from_option(name: str):
    try:
        return create_provider(name)
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from exc


def _normalize_output_option(output: str) -> str:
    normalized = output.strip().lower()
    if normalized not in {"text", "json"}:
        raise typer.BadParameter("output must be 'text' or 'json'")
    return normalized


def _raise_for_source_errors(provider) -> None:
    for check in provider.source_checks():
        if check.status == "error":
            raise typer.BadParameter(f"{check.name}: {check.status} - {check.detail}")


def _save_watchlist_report(path: str, items, metadata: dict, source_checks) -> None:
    report_path = Path(path)
    suffix = report_path.suffix.lower()
    if suffix == ".json":
        content = render_watchlist_report_json(items, metadata, source_checks)
    elif suffix in {".md", ".markdown"}:
        content = render_watchlist_report_markdown(items, metadata, source_checks)
    else:
        raise typer.BadParameter("save path must end in .json, .md, or .markdown")
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(content + "\n", encoding="utf-8")


@app.command()
def watchlist(
    country: str = typer.Option(
        "se,fi",
        "--country",
        help="Comma-separated country codes, such as se,fi.",
    ),
    limit: int = typer.Option(20, "--limit", min=1, max=100),
    include_first_north: bool = typer.Option(True, "--include-first-north/--exclude-first-north"),
    min_market_cap: float | None = typer.Option(None, "--min-market-cap"),
    max_market_cap: float | None = typer.Option(None, "--max-market-cap"),
    sector: str | None = typer.Option(None, "--sector"),
    strategy: str = typer.Option(
        "balanced",
        "--strategy",
        help="Watchlist strategy: balanced, long-term, trading, momentum, or discovery.",
    ),
    output: str = typer.Option("text", "--output", help="Output format: text or json."),
    verbose: bool = typer.Option(False, "--verbose"),
    provider_name: str = typer.Option("fixture", "--provider", help="Data provider: fixture or live."),
    save_path: str | None = typer.Option(
        None, "--save", help="Save report to .json, .md, or .markdown."
    ),
) -> None:
    normalized_output = _normalize_output_option(output)
    try:
        normalized_strategy = normalize_watchlist_strategy(strategy)
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from exc
    countries = _parse_countries(country)
    provider = _provider_from_option(provider_name)
    if provider_name.strip().lower() == "live":
        _raise_for_source_errors(provider)
    items = build_watchlist(
        provider,
        countries=countries,
        limit=limit,
        include_first_north=include_first_north,
        min_market_cap=min_market_cap,
        max_market_cap=max_market_cap,
        sector=sector,
        strategy=normalized_strategy,
    )
    source_checks = provider.source_checks()
    if save_path is not None:
        _save_watchlist_report(
            save_path,
            items,
            {
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "provider": provider_name.strip().lower(),
                "countries": list(countries),
                "limit": limit,
                "include_first_north": include_first_north,
                "min_market_cap": min_market_cap,
                "max_market_cap": max_market_cap,
                "sector": sector,
                "strategy": normalized_strategy,
            },
            source_checks,
        )

    if normalized_output == "text":
        if verbose:
            for check in source_checks:
                typer.echo(f"{check.name}: {check.status} - {check.detail}", err=True)
        typer.echo(render_watchlist_text(items))
        return
    if normalized_output == "json":
        typer.echo(render_watchlist_json(items))
        return


@app.command("deep-dive")
def deep_dive(
    ticker: str,
    output: str = typer.Option("text", "--output", help="Output format: text or json."),
    provider_name: str = typer.Option("fixture", "--provider", help="Data provider: fixture or live."),
) -> None:
    normalized_output = _normalize_output_option(output)
    provider = _provider_from_option(provider_name)
    if provider_name.strip().lower() == "live":
        _raise_for_source_errors(provider)
    try:
        report = build_deep_dive(provider, ticker)
    except LookupError as exc:
        raise typer.BadParameter(str(exc)) from exc

    if normalized_output == "text":
        typer.echo(render_deep_dive_text(report))
        return
    if normalized_output == "json":
        typer.echo(render_deep_dive_json(report))
        return


@sources_app.command("test")
def test_sources(
    provider_name: str = typer.Option("fixture", "--provider", help="Data provider: fixture or live."),
) -> None:
    provider = _provider_from_option(provider_name)
    for check in provider.source_checks():
        typer.echo(f"{check.name}: {check.status} - {check.detail}")


if __name__ == "__main__":
    app()
