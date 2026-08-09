import json
import os
from datetime import date, datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import typer

from investmentagent.evaluation import (
    build_evaluation_snapshot,
    save_evaluation_snapshot,
)
from investmentagent.fundamentals import (
    DEFAULT_WATCHLIST_ENRICHMENT_LIMIT,
    EnrichedResearchProvider,
    EodhdFundamentalsProvider,
    FallbackFundamentalsProvider,
    FinimpulseFundamentalsProvider,
    FinnhubFundamentalsProvider,
    YahooFundamentalsProvider,
    compose_valuation_fallback_provider,
)
from investmentagent.fundamentals_cache import (
    DEFAULT_FUNDAMENTALS_MAX_AGE_DAYS,
    FileFundamentalsCache,
    FundamentalsFreshnessPolicy,
)
from investmentagent.global_ai import build_global_ai_top5
from investmentagent.market_calendar import market_day_status
from investmentagent.providers import create_provider
from investmentagent.performance import (
    add_report_picks,
    load_ledger,
    parse_report_date,
    price_lookup_from_provider,
    record_market_snapshot,
    render_scorecard_markdown,
    save_ledger,
    update_due_outcomes,
)
from investmentagent.renderers import (
    render_deep_dive_json,
    render_deep_dive_text,
    render_global_ai_report_json,
    render_global_ai_report_markdown,
    render_watchlist_json,
    render_watchlist_report_json,
    render_watchlist_report_markdown,
    render_watchlist_text,
)
from investmentagent.reports import (
    build_deep_dive,
    build_watchlist_result,
    normalize_watchlist_strategy,
)


app = typer.Typer(help="InvestmentAgent Nordic investing research CLI.", no_args_is_help=False)
sources_app = typer.Typer(help="Inspect and validate research sources.")
performance_app = typer.Typer(help="Track and publish watchlist performance.")
markets_app = typer.Typer(help="Inspect Nordic stock-market calendars.")
global_ai_app = typer.Typer(help="Generate global AI investment candidate reports.")
app.add_typer(sources_app, name="sources")
app.add_typer(performance_app, name="performance")
app.add_typer(markets_app, name="markets")
app.add_typer(global_ai_app, name="global-ai")


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


def _parse_iso_date(raw: str) -> date:
    try:
        return date.fromisoformat(raw)
    except ValueError as exc:
        raise typer.BadParameter("date must use YYYY-MM-DD") from exc


def _parse_aware_timestamp(raw: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError as exc:
        raise typer.BadParameter("decision timestamp must use ISO 8601") from exc
    if parsed.tzinfo is None:
        raise typer.BadParameter("decision timestamp must include a timezone")
    return parsed.astimezone(timezone.utc)


def _is_under_docs(path: Path) -> bool:
    resolved = path.resolve()
    docs_root = (Path.cwd() / "docs").resolve()
    return resolved == docs_root or docs_root in resolved.parents


def _parse_min_country_options(raw_values: tuple[str, ...]) -> dict[str, int]:
    parsed: dict[str, int] = {}
    for raw in raw_values:
        if ":" not in raw:
            raise typer.BadParameter("min-country must use COUNTRY:COUNT")
        country, raw_count = raw.split(":", 1)
        normalized_country = country.strip().upper()
        if not normalized_country:
            raise typer.BadParameter("min-country must use COUNTRY:COUNT")
        try:
            count = int(raw_count)
        except ValueError as exc:
            raise typer.BadParameter("min-country count must be an integer") from exc
        if count < 0:
            raise typer.BadParameter("min-country count must be at least 0")
        parsed[normalized_country] = count
    return parsed


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


def _normalize_global_ai_output_option(output: str) -> str:
    normalized = output.strip().lower()
    if normalized not in {"markdown", "json"}:
        raise typer.BadParameter("output must be 'markdown' or 'json'")
    return normalized


def _normalize_fundamentals_option(value: str) -> str:
    normalized = value.strip().lower()
    if normalized not in {"auto", "off", "free", "finnhub", "finimpulse"}:
        raise typer.BadParameter(
            "fundamentals must be 'auto', 'off', 'free', 'finnhub', or 'finimpulse'"
        )
    return normalized


def _effective_fundamentals_mode(
    normalized_mode: str,
    normalized_provider_name: str,
    finimpulse_api_key: str | None,
    finnhub_api_key: str | None,
) -> str:
    if normalized_provider_name != "live":
        return "off"
    if normalized_mode == "auto":
        if finimpulse_api_key:
            return "finimpulse"
        if finnhub_api_key:
            return "finnhub"
        return "free"
    return normalized_mode


def _api_key_from_environment(name: str) -> str | None:
    api_key = os.environ.get(name)
    if api_key is None:
        return None
    stripped = api_key.strip()
    return stripped or None


def _finimpulse_valuation_fallback_provider(
    finimpulse_api_key: str, eodhd_api_key: str | None
):
    return compose_valuation_fallback_provider(
        FinimpulseFundamentalsProvider(finimpulse_api_key),
        EodhdFundamentalsProvider(eodhd_api_key),
        YahooFundamentalsProvider(),
    )


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


def _save_global_ai_report(path: str, report) -> None:
    report_path = Path(path)
    suffix = report_path.suffix.lower()
    if suffix == ".json":
        content = render_global_ai_report_json(report)
    elif suffix in {".md", ".markdown"}:
        content = render_global_ai_report_markdown(report)
    else:
        raise typer.BadParameter("save path must end in .json, .md, or .markdown")
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(content + "\n", encoding="utf-8")


@markets_app.command("open")
def markets_open(
    target_date: str | None = typer.Option(
        None,
        "--date",
        help="Market date in YYYY-MM-DD format. Defaults to today in Europe/Helsinki.",
    ),
    markets: list[str] | None = typer.Option(
        None,
        "--market",
        help="Required market: stockholm or helsinki. Can be repeated.",
    ),
) -> None:
    day = (
        _parse_iso_date(target_date)
        if target_date is not None
        else datetime.now(ZoneInfo("Europe/Helsinki")).date()
    )
    requested_markets = tuple(markets or ("stockholm", "helsinki"))
    try:
        statuses = [market_day_status(day, market) for market in requested_markets]
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from exc

    closed_statuses = [status for status in statuses if not status.is_open]
    if closed_statuses:
        for status in closed_statuses:
            typer.echo(f"{status.market}: closed ({status.reason})")
        raise typer.Exit(1)

    typer.echo(f"All requested markets are open on {day.isoformat()}.")


@global_ai_app.command("top-5")
def global_ai_top5(
    limit: int = typer.Option(5, "--limit", min=1, max=20),
    output: str = typer.Option(
        "markdown", "--output", help="Output format: markdown or json."
    ),
    save_paths: list[str] | None = typer.Option(
        None,
        "--save",
        help="Save report to .json, .md, or .markdown. Can be repeated.",
    ),
    generated_at: str | None = typer.Option(
        None,
        "--generated-at",
        help="Display timestamp for the report.",
    ),
) -> None:
    normalized_output = _normalize_global_ai_output_option(output)
    finimpulse_api_key = _api_key_from_environment("FINIMPULSE_API_KEY")
    eodhd_api_key = _api_key_from_environment("EODHD_API_KEY")
    if finimpulse_api_key is None:
        raise typer.BadParameter("FINIMPULSE_API_KEY is required for global-ai top-5")

    provider = _finimpulse_valuation_fallback_provider(
        finimpulse_api_key,
        eodhd_api_key,
    )
    report = build_global_ai_top5(
        provider,
        limit=limit,
        generated_at=generated_at,
    )
    for save_path in save_paths or ():
        _save_global_ai_report(save_path, report)

    if normalized_output == "json":
        typer.echo(render_global_ai_report_json(report))
        return
    typer.echo(render_global_ai_report_markdown(report))


@app.command()
def watchlist(
    country: str = typer.Option(
        "se,fi",
        "--country",
        help="Comma-separated country codes, such as se,fi.",
    ),
    limit: int = typer.Option(20, "--limit", min=1, max=100),
    enrichment_limit: int = typer.Option(
        DEFAULT_WATCHLIST_ENRICHMENT_LIMIT,
        "--refresh-limit",
        "--enrichment-limit",
        min=0,
        max=100,
        help="Maximum external fundamentals refreshes for this run.",
    ),
    fundamentals_cache_path: str | None = typer.Option(
        None,
        "--fundamentals-cache",
        help="Path to the private point-in-time fundamentals cache.",
    ),
    cache_max_age_days: int = typer.Option(
        DEFAULT_FUNDAMENTALS_MAX_AGE_DAYS,
        "--cache-max-age-days",
        min=0,
        max=3650,
        help="Retrieval age after which cached fundamentals are refreshed.",
    ),
    evaluation_dir: str | None = typer.Option(
        None,
        "--evaluation-dir",
        help="Persist a durable Performance v2 snapshot under this directory.",
    ),
    evaluation_report_date: str | None = typer.Option(
        None,
        "--evaluation-report-date",
        help="Evaluation report date in YYYY-MM-DD format.",
    ),
    evaluation_decision_at: str | None = typer.Option(
        None,
        "--evaluation-decision-at",
        help="Fixture-only timezone-aware decision timestamp.",
    ),
    include_first_north: bool = typer.Option(True, "--include-first-north/--exclude-first-north"),
    min_market_cap: float | None = typer.Option(None, "--min-market-cap"),
    max_market_cap: float | None = typer.Option(None, "--max-market-cap"),
    sector: str | None = typer.Option(None, "--sector"),
    strategy: str = typer.Option(
        "balanced",
        "--strategy",
        help="Watchlist strategy: balanced, long-term, trading, momentum, or discovery.",
    ),
    fundamentals: str = typer.Option(
        "auto",
        "--fundamentals",
        help="Fundamentals enrichment mode: auto, off, free, finnhub, or finimpulse.",
    ),
    output: str = typer.Option("text", "--output", help="Output format: text or json."),
    verbose: bool = typer.Option(False, "--verbose"),
    provider_name: str = typer.Option("fixture", "--provider", help="Data provider: fixture or live."),
    min_country: list[str] | None = typer.Option(
        None,
        "--min-country",
        help="Minimum country representation, such as FI:3. Can be repeated.",
    ),
    save_paths: list[str] | None = typer.Option(
        None,
        "--save",
        help="Save report to .json, .md, or .markdown. Can be repeated.",
    ),
) -> None:
    run_timestamp = datetime.now(timezone.utc)
    normalized_output = _normalize_output_option(output)
    normalized_fundamentals = _normalize_fundamentals_option(fundamentals)
    try:
        normalized_strategy = normalize_watchlist_strategy(strategy)
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from exc
    countries = _parse_countries(country)
    min_country_counts = _parse_min_country_options(tuple(min_country or ()))
    normalized_provider_name = provider_name.strip().lower()
    explicit_decision_at = (
        _parse_aware_timestamp(evaluation_decision_at)
        if evaluation_decision_at is not None
        else None
    )
    explicit_evaluation_report_date = (
        _parse_iso_date(evaluation_report_date)
        if evaluation_report_date is not None
        else None
    )
    if evaluation_dir is None and (
        evaluation_report_date is not None or explicit_decision_at is not None
    ):
        raise typer.BadParameter(
            "evaluation report date/decision timestamp requires --evaluation-dir"
        )
    if evaluation_dir is not None:
        if normalized_strategy not in {"trading", "long-term"}:
            raise typer.BadParameter(
                "evaluation snapshots support trading and long-term strategies"
            )
        if _is_under_docs(Path(evaluation_dir)):
            raise typer.BadParameter("evaluation snapshots must not be stored under docs/")
    if normalized_provider_name == "live" and explicit_decision_at is not None:
        raise typer.BadParameter(
            "live evaluation cannot use an explicit decision timestamp"
        )
    if (
        normalized_provider_name == "live"
        and explicit_evaluation_report_date is not None
        and explicit_evaluation_report_date
        != datetime.now(ZoneInfo("Europe/Helsinki")).date()
    ):
        raise typer.BadParameter("live evaluation report date must be today")
    finimpulse_api_key = _api_key_from_environment("FINIMPULSE_API_KEY")
    eodhd_api_key = _api_key_from_environment("EODHD_API_KEY")
    finnhub_api_key = _api_key_from_environment("FINNHUB_API_KEY")
    effective_fundamentals = _effective_fundamentals_mode(
        normalized_fundamentals,
        normalized_provider_name,
        finimpulse_api_key,
        finnhub_api_key,
    )
    if normalized_provider_name == "live":
        if effective_fundamentals == "finimpulse" and finimpulse_api_key is None:
            raise typer.BadParameter(
                "FINIMPULSE_API_KEY is required for --fundamentals finimpulse"
            )
        if effective_fundamentals == "finnhub" and finnhub_api_key is None:
            raise typer.BadParameter("FINNHUB_API_KEY is required for --fundamentals finnhub")
    provider = _provider_from_option(provider_name)
    effective_enrichment_limit = 0
    if normalized_provider_name == "live":
        _raise_for_source_errors(provider)
        fundamentals_provider = None
        if effective_fundamentals == "free":
            fundamentals_provider = YahooFundamentalsProvider()
        elif effective_fundamentals == "finimpulse":
            fundamentals_provider = _finimpulse_valuation_fallback_provider(
                finimpulse_api_key,
                eodhd_api_key,
            )
        elif effective_fundamentals == "finnhub":
            fundamentals_provider = FinnhubFundamentalsProvider(finnhub_api_key)
        if fundamentals_provider is not None:
            effective_enrichment_limit = enrichment_limit
            fundamentals_cache = None
            if fundamentals_cache_path is not None:
                try:
                    fundamentals_cache = FileFundamentalsCache(
                        Path(fundamentals_cache_path)
                    )
                except ValueError as exc:
                    raise typer.BadParameter(str(exc)) from exc
            enrichment_options = {"enrichment_limit": enrichment_limit}
            if fundamentals_cache is not None:
                enrichment_options.update(
                    {
                        "cache": fundamentals_cache,
                        "freshness_policy": FundamentalsFreshnessPolicy(
                            cache_max_age_days
                        ),
                        "known_at": run_timestamp,
                    }
                )
            provider = EnrichedResearchProvider(
                provider,
                fundamentals_provider,
                **enrichment_options,
            )
    build_result = build_watchlist_result(
        provider,
        countries=countries,
        limit=limit,
        include_first_north=include_first_north,
        min_market_cap=min_market_cap,
        max_market_cap=max_market_cap,
        sector=sector,
        strategy=normalized_strategy,
        min_country_counts=min_country_counts,
    )
    items = list(build_result.selected_items)
    source_checks = provider.source_checks()
    enrichment_stats = getattr(provider, "enrichment_stats", None)
    enrichment_metadata = None
    if callable(enrichment_stats):
        enrichment_metadata = dict(enrichment_stats())
        enrichment_metadata.pop("candidate_keys", None)
    report_timestamp = explicit_decision_at or datetime.now(timezone.utc)
    metadata = {
        "generated_at": report_timestamp.isoformat(),
        "provider": normalized_provider_name,
        "fundamentals": effective_fundamentals,
        "countries": list(countries),
        "limit": limit,
        "enrichment_limit": effective_enrichment_limit,
        "enrichment": enrichment_metadata,
        "fundamentals_cache": {
            "enabled": normalized_provider_name == "live"
            and fundamentals_cache_path is not None
            and effective_fundamentals != "off",
            "max_age_days": cache_max_age_days,
        },
        "include_first_north": include_first_north,
        "min_market_cap": min_market_cap,
        "max_market_cap": max_market_cap,
        "sector": sector,
        "strategy": normalized_strategy,
        "min_country_counts": min_country_counts,
    }
    if evaluation_dir is not None:
        report_day = (
            explicit_evaluation_report_date
            if explicit_evaluation_report_date is not None
            else report_timestamp.astimezone(ZoneInfo("Europe/Helsinki")).date()
        )
        evaluation_configuration = {
            "provider": normalized_provider_name,
            "fundamentals": effective_fundamentals,
            "include_first_north": include_first_north,
            "public_limit": limit,
            "refresh_budget": effective_enrichment_limit,
            "minimum_country_counts": min_country_counts,
            "filters": {
                "min_market_cap_eur_m": min_market_cap,
                "max_market_cap_eur_m": max_market_cap,
                "sector": sector,
            },
            "cache": {
                "enabled": metadata["fundamentals_cache"]["enabled"],
                "max_age_days": cache_max_age_days,
            },
        }
        evaluation_snapshot = build_evaluation_snapshot(
            build_result,
            provider=provider,
            strategy=normalized_strategy,
            decision_at=report_timestamp,
            report_date=report_day,
            countries=countries,
            configuration=evaluation_configuration,
            source_checks=source_checks,
        )
        evaluation_path = save_evaluation_snapshot(
            Path(evaluation_dir), evaluation_snapshot
        )
        metadata["evaluation"] = {
            "run_id": evaluation_snapshot.run_id,
            "scoring_model_version": evaluation_snapshot.scoring_model_version,
            "decision_at": evaluation_snapshot.header_payload()["decision_at"],
        }
        if verbose:
            typer.echo(f"evaluation snapshot: {evaluation_path}", err=True)
    for save_path in save_paths or ():
        _save_watchlist_report(save_path, items, metadata, source_checks)

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


@performance_app.command("update")
def performance_update(
    report_json_paths: list[str] = typer.Option(
        ..., "--report-json", help="Saved watchlist report JSON file. Can be repeated."
    ),
    report_date_raw: str = typer.Option(..., "--report-date", help="Report date YYYY-MM-DD."),
    ledger_path: str = typer.Option(
        "docs/data/performance/ledger.json", "--ledger", help="Performance ledger path."
    ),
    output_path: str = typer.Option(
        "docs/performance/index.md", "--output", help="Performance scorecard Markdown path."
    ),
    latest_path: str | None = typer.Option(
        None, "--latest", help="Optional latest scorecard copy path."
    ),
    price_provider_name: str = typer.Option(
        "live", "--price-provider", help="Price provider: live, fixture, or off."
    ),
    generated_at: str | None = typer.Option(
        None, "--generated-at", help="Display timestamp for the scorecard."
    ),
) -> None:
    report_date = parse_report_date(report_date_raw)
    ledger_file = Path(ledger_path)
    ledger = load_ledger(ledger_file)
    for report_json_path in report_json_paths:
        report_path = Path(report_json_path)
        report_payload = json.loads(report_path.read_text(encoding="utf-8"))
        strategy = report_payload.get("metadata", {}).get("strategy")
        if strategy not in {"trading", "long-term"}:
            raise typer.BadParameter("report-json metadata strategy must be trading or long-term")
        report_url = f"../reports/{strategy}/{report_date.isoformat()}.html"
        ledger = add_report_picks(
            ledger,
            report_payload,
            report_date=report_date,
            report_url=report_url,
        )

    normalized_price_provider = price_provider_name.strip().lower()
    if normalized_price_provider == "off":
        price_lookup = {}
    else:
        provider = _provider_from_option(normalized_price_provider)
        if normalized_price_provider == "live":
            _raise_for_source_errors(provider)
        price_lookup = price_lookup_from_provider(provider)
        ledger = record_market_snapshot(
            ledger,
            as_of_date=date.today(),
            price_lookup=price_lookup,
        )

    ledger = update_due_outcomes(
        ledger,
        as_of_date=date.today(),
        price_lookup=price_lookup,
    )
    save_ledger(ledger_file, ledger)
    display_timestamp = generated_at or datetime.now(timezone.utc).isoformat()
    scorecard = render_scorecard_markdown(ledger, generated_at=display_timestamp)
    output_file = Path(output_path)
    output_file.parent.mkdir(parents=True, exist_ok=True)
    output_file.write_text(scorecard + "\n", encoding="utf-8")
    if latest_path is not None:
        latest_file = Path(latest_path)
        latest_file.parent.mkdir(parents=True, exist_ok=True)
        latest_file.write_text(scorecard + "\n", encoding="utf-8")


if __name__ == "__main__":
    app()
