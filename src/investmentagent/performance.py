from __future__ import annotations

import json
import re
from copy import deepcopy
from datetime import date, timedelta
from pathlib import Path
from typing import Any


LEDGER_SCHEMA_VERSION = 1
HORIZONS = ("1d", "5d", "20d", "60d")
HORIZON_DAYS = {"1d": 1, "5d": 5, "20d": 20, "60d": 60}
DISCLAIMER = "Research triage only. Not financial advice."
STRATEGIES = ("trading", "long-term")
STRATEGY_TITLES = {
    "trading": "Trading Ideas",
    "long-term": "Long-Term Investment Ideas",
}
STRATEGY_LABELS = {
    "trading": "Trading",
    "long-term": "Long-Term",
}


def empty_ledger() -> dict[str, Any]:
    return {"schema_version": LEDGER_SCHEMA_VERSION, "picks": [], "market_snapshots": {}}


def load_ledger(path: Path) -> dict[str, Any]:
    if not path.exists():
        return empty_ledger()
    ledger = json.loads(path.read_text(encoding="utf-8"))
    if ledger.get("schema_version") != LEDGER_SCHEMA_VERSION:
        raise ValueError(
            f"unsupported performance ledger schema: {ledger.get('schema_version')}"
        )
    if not isinstance(ledger.get("picks"), list):
        raise ValueError("performance ledger is missing picks list")
    ledger.setdefault("market_snapshots", {})
    return ledger


def save_ledger(path: Path, ledger: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(ledger, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def add_report_picks(
    ledger: dict[str, Any],
    report_payload: dict[str, Any],
    *,
    report_date: date,
    report_url: str,
) -> dict[str, Any]:
    updated = deepcopy(ledger)
    existing_by_id = {pick["pick_id"]: pick for pick in updated["picks"]}
    strategy = str(report_payload.get("metadata", {}).get("strategy") or "").strip()
    generated_at = report_payload.get("metadata", {}).get("generated_at")
    for item in report_payload.get("items", []):
        pick = _pick_from_report_item(
            item,
            strategy=strategy,
            report_date=report_date,
            report_url=report_url,
            generated_at=generated_at,
        )
        existing = existing_by_id.get(pick["pick_id"])
        if existing is None:
            updated["picks"].append(pick)
            existing_by_id[pick["pick_id"]] = pick
        else:
            _merge_existing_pick(existing, pick)
    updated["picks"].sort(key=lambda pick: pick["pick_id"])
    return updated


def _pick_from_report_item(
    item: dict[str, Any],
    *,
    strategy: str,
    report_date: date,
    report_url: str,
    generated_at: str | None,
) -> dict[str, Any]:
    company = item.get("company", {})
    financials = item.get("financials", {})
    score = item.get("score", {})
    rank = int(item["rank"])
    ticker = str(company["ticker"]).upper()
    country = str(company.get("country") or "").upper()
    pick = {
        "pick_id": f"{report_date.isoformat()}|{strategy}|{country}|{ticker}",
        "report_date": report_date.isoformat(),
        "strategy": strategy,
        "rank": rank,
        "ticker": ticker,
        "name": company.get("name"),
        "country": country,
        "exchange": company.get("exchange"),
        "segment": company.get("segment"),
        "sector": company.get("sector"),
        "report_url": report_url,
        "entry_price": financials.get("price"),
        "entry_currency": financials.get("currency"),
        "entry_timestamp": generated_at,
        "score_total": score.get("total"),
        "reasons": list(score.get("reasons") or ()),
        "risks": list(item.get("risks") or ()),
        "data_quality": item.get("data_quality"),
        "outcomes": _empty_outcomes(),
    }
    conviction = item.get("long_term_conviction")
    if conviction:
        pick["long_term_conviction"] = conviction
    return pick


def _merge_existing_pick(existing: dict[str, Any], incoming: dict[str, Any]) -> None:
    outcomes = existing["outcomes"]
    entry_values = {
        key: existing.get(key)
        for key in ("entry_price", "entry_currency", "entry_timestamp")
    }
    has_priced_outcome = any(
        outcome.get("status") == "priced" for outcome in outcomes.values()
    )
    existing.clear()
    existing.update(incoming)
    existing["outcomes"] = outcomes
    if has_priced_outcome:
        existing.update(entry_values)


def _empty_outcomes() -> dict[str, dict[str, Any]]:
    return {
        horizon: {
            "as_of_date": None,
            "price": None,
            "currency": None,
            "return_pct": None,
            "status": "not_due",
        }
        for horizon in HORIZONS
    }


def parse_report_date(value: str) -> date:
    return date.fromisoformat(value)


def price_lookup_from_provider(
    provider, *, countries: tuple[str, ...] = ("SE", "FI")
) -> dict[tuple[str, str], dict[str, Any]]:
    lookup: dict[tuple[str, str], dict[str, Any]] = {}
    for company in provider.list_companies(countries=countries, include_first_north=True):
        get_company_research = getattr(provider, "get_company_research", None)
        if callable(get_company_research):
            research = get_company_research(company)
        else:
            research = provider.get_research(company.ticker)
        lookup[(company.ticker, company.country)] = {
            "price": research.financials.price,
            "currency": research.financials.currency,
            "name": company.name,
            "segment": str(
                company.segment.value
                if hasattr(company.segment, "value")
                else company.segment
            ),
            "sector": company.sector,
            "catalysts": list(research.catalysts),
            "risks": list(research.risks),
        }
    return lookup


def record_market_snapshot(
    ledger: dict[str, Any],
    *,
    as_of_date: date,
    price_lookup: dict[tuple[str, str], dict[str, Any]],
) -> dict[str, Any]:
    updated = deepcopy(ledger)
    snapshots = updated.setdefault("market_snapshots", {})
    snapshot: dict[str, dict[str, Any]] = {}
    for (ticker, country), quote in price_lookup.items():
        price = quote.get("price")
        currency = quote.get("currency")
        if price is None or currency is None:
            continue
        normalized_ticker = str(ticker).upper()
        normalized_country = str(country).upper()
        snapshot[f"{normalized_country}|{normalized_ticker}"] = {
            "ticker": normalized_ticker,
            "country": normalized_country,
            "price": price,
            "currency": currency,
            "name": quote.get("name"),
            "segment": quote.get("segment"),
            "sector": quote.get("sector"),
            "catalysts": list(quote.get("catalysts") or ()),
            "risks": list(quote.get("risks") or ()),
        }
    snapshots[as_of_date.isoformat()] = snapshot
    return updated


def update_due_outcomes(
    ledger: dict[str, Any],
    *,
    as_of_date: date,
    price_lookup: dict[tuple[str, str], dict[str, Any]],
) -> dict[str, Any]:
    updated = deepcopy(ledger)
    for pick in updated["picks"]:
        report_date = date.fromisoformat(pick["report_date"])
        entry_price = pick.get("entry_price")
        entry_currency = pick.get("entry_currency")
        for horizon, days in HORIZON_DAYS.items():
            outcome = pick["outcomes"][horizon]
            if outcome["status"] != "not_due":
                continue
            due_date = _add_trading_days(report_date, days)
            if as_of_date < due_date:
                continue
            if as_of_date > due_date:
                outcome.update(
                    {
                        "as_of_date": as_of_date.isoformat(),
                        "price": None,
                        "currency": None,
                        "return_pct": None,
                        "status": "missed_window",
                    }
                )
                continue
            quote = price_lookup.get((pick["ticker"], pick["country"]))
            if not quote or quote.get("price") is None:
                outcome.update(
                    {
                        "as_of_date": as_of_date.isoformat(),
                        "price": None,
                        "currency": None,
                        "return_pct": None,
                        "status": "missing_price",
                    }
                )
                continue
            quote_currency = quote.get("currency")
            if (
                entry_price is None
                or entry_price == 0
                or entry_currency is None
                or quote_currency != entry_currency
            ):
                outcome.update(
                    {
                        "as_of_date": as_of_date.isoformat(),
                        "price": quote.get("price"),
                        "currency": quote_currency,
                        "return_pct": None,
                        "status": "missing_price",
                    }
                )
                continue
            return_pct = ((quote["price"] - entry_price) / entry_price) * 100
            benchmark_return_pct = _country_benchmark_return_pct(
                updated,
                country=pick["country"],
                entry_date=report_date,
                as_of_date=as_of_date,
            )
            outcome.update(
                {
                    "as_of_date": as_of_date.isoformat(),
                    "price": quote["price"],
                    "currency": quote_currency,
                    "return_pct": round(return_pct, 2),
                    "status": "priced",
                }
            )
            if benchmark_return_pct is not None:
                outcome.update(
                    {
                        "benchmark_label": f"Equal-weight {pick['country']} market",
                        "benchmark_return_pct": benchmark_return_pct,
                        "excess_return_pct": round(
                            round(return_pct, 2) - benchmark_return_pct, 2
                        ),
                    }
                )
    return updated


def _country_benchmark_return_pct(
    ledger: dict[str, Any],
    *,
    country: str,
    entry_date: date,
    as_of_date: date,
) -> float | None:
    snapshots = ledger.get("market_snapshots") or {}
    entry_snapshot = snapshots.get(entry_date.isoformat()) or {}
    exit_snapshot = snapshots.get(as_of_date.isoformat()) or {}
    returns: list[float] = []
    normalized_country = country.upper()
    for key, entry in entry_snapshot.items():
        if entry.get("country") != normalized_country:
            continue
        exit_quote = exit_snapshot.get(key)
        if not exit_quote:
            continue
        entry_price = entry.get("price")
        exit_price = exit_quote.get("price")
        if (
            entry_price in (None, 0)
            or exit_price is None
            or entry.get("currency") != exit_quote.get("currency")
        ):
            continue
        returns.append(((exit_price - entry_price) / entry_price) * 100)
    if not returns:
        return None
    return round(sum(returns) / len(returns), 2)


def _add_trading_days(start_date: date, days: int) -> date:
    current = start_date
    remaining = days
    while remaining > 0:
        current += timedelta(days=1)
        if _is_weekday_trading_day(current):
            remaining -= 1
    return current


def _is_weekday_trading_day(value: date) -> bool:
    return value.weekday() < 5


def summarize_ledger(ledger: dict[str, Any]) -> dict[str, Any]:
    return {
        "strategies": {
            strategy: {
                horizon: _strategy_horizon_summary(ledger, strategy, horizon)
                for horizon in HORIZONS
            }
            for strategy in STRATEGIES
        },
        "best_picks": _ranked_completed_picks(ledger, reverse=True),
        "worst_picks": _ranked_completed_picks(ledger, reverse=False),
        "best_picks_by_strategy": {
            strategy: _ranked_completed_picks(
                ledger, reverse=True, strategy=strategy
            )
            for strategy in STRATEGIES
        },
        "worst_picks_by_strategy": {
            strategy: _ranked_completed_picks(
                ledger, reverse=False, strategy=strategy
            )
            for strategy in STRATEGIES
        },
        "signals": _signal_summaries(ledger),
        "signals_by_strategy": {
            strategy: _signal_summaries(ledger, strategy=strategy)
            for strategy in STRATEGIES
        },
    }


def render_scorecard_markdown(ledger: dict[str, Any], *, generated_at: str) -> str:
    summary = summarize_ledger(ledger)
    lines = [
        "# InvestmentAgent Performance",
        "",
        f"> {DISCLAIMER}",
        "",
        f"Generated: {generated_at}",
        "",
    ]
    market_context = _latest_market_context(ledger)
    if market_context is not None:
        lines.extend(
            [
                "## Market Context",
                "",
                f"- Latest snapshot: {market_context['snapshot_date']}",
                f"- Market tone: {market_context['tone']}",
                f"- Companies tracked: {market_context['companies']}",
                f"- Large positive movers: {market_context['positive_movers']}",
                f"- Sharp selloffs: {market_context['selloffs']}",
                f"- Active turnover signals: {market_context['active_turnover']}",
                "",
            ]
        )
    for strategy in STRATEGIES:
        lines.extend(_strategy_performance_section(summary, ledger, strategy))
    while lines and lines[-1] == "":
        lines.pop()
    return "\n".join(lines)


def learning_suggestions(
    ledger: dict[str, Any], *, strategy: str | None = None
) -> list[str]:
    eligible = [
        signal
        for signal in _signal_summaries(ledger, strategy=strategy)
        if signal["observations"] >= 10
    ]
    if not eligible:
        return [
            "No learning suggestions yet. At least 10 completed observations are needed for a signal."
        ]
    suggestions = []
    for signal in eligible[:5]:
        direction = "positive" if signal["average_return_pct"] > 0 else "negative"
        suggestions.append(
            f"{_humanize_signal(signal['signal'])} has produced a {direction} "
            f"average return of {_format_percent(signal['average_return_pct'], signed=True)} "
            f"across {signal['observations']} "
            "completed observations. Review whether its scoring weight should change."
        )
    return suggestions


def _latest_market_context(ledger: dict[str, Any]) -> dict[str, Any] | None:
    snapshots = ledger.get("market_snapshots") or {}
    if not snapshots:
        return None
    snapshot_date = sorted(snapshots)[-1]
    snapshot = snapshots.get(snapshot_date) or {}
    companies = len(snapshot)
    if companies == 0:
        return None
    positive_movers = 0
    selloffs = 0
    active_turnover = 0
    for entry in snapshot.values():
        catalysts = tuple(str(item).lower() for item in entry.get("catalysts") or ())
        risks = tuple(str(item).lower() for item in entry.get("risks") or ())
        if any("intraday momentum" in catalyst for catalyst in catalysts):
            positive_movers += 1
        if any("sharp intraday selloff" in risk for risk in risks):
            selloffs += 1
        if any(
            "high live turnover" in catalyst or "moderate live turnover" in catalyst
            for catalyst in catalysts
        ):
            active_turnover += 1
    return {
        "snapshot_date": snapshot_date,
        "tone": _market_tone(positive_movers, selloffs),
        "companies": companies,
        "positive_movers": positive_movers,
        "selloffs": selloffs,
        "active_turnover": active_turnover,
    }


def _market_tone(positive_movers: int, selloffs: int) -> str:
    if positive_movers >= 2 and positive_movers >= selloffs * 2:
        return "Risk-on / broad momentum"
    if selloffs >= 2 and selloffs >= positive_movers * 2:
        return "Risk-off / broad selloff"
    return "Mixed / quiet"


def _strategy_horizon_summary(
    ledger: dict[str, Any], strategy: str, horizon: str
) -> dict[str, Any]:
    returns = [
        pick["outcomes"][horizon]["return_pct"]
        for pick in ledger["picks"]
        if pick["strategy"] == strategy
        and pick["outcomes"][horizon]["status"] == "priced"
        and pick["outcomes"][horizon]["return_pct"] is not None
    ]
    if not returns:
        return {
            "completed": 0,
            "hit_rate_pct": None,
            "average_return_pct": None,
            "median_return_pct": None,
            "worst_return_pct": None,
            "loss_rate_pct": None,
            "large_loser_count": 0,
            "volatility_pct": None,
            "average_benchmark_return_pct": None,
            "average_excess_return_pct": None,
            "excess_hit_rate_pct": None,
        }
    sorted_returns = sorted(returns)
    midpoint = len(sorted_returns) // 2
    if len(sorted_returns) % 2:
        median = sorted_returns[midpoint]
    else:
        median = (sorted_returns[midpoint - 1] + sorted_returns[midpoint]) / 2
    hits = sum(value > 0 for value in returns)
    benchmark_returns = [
        pick["outcomes"][horizon].get("benchmark_return_pct")
        for pick in ledger["picks"]
        if pick["strategy"] == strategy
        and pick["outcomes"][horizon]["status"] == "priced"
        and pick["outcomes"][horizon].get("benchmark_return_pct") is not None
    ]
    excess_returns = [
        pick["outcomes"][horizon].get("excess_return_pct")
        for pick in ledger["picks"]
        if pick["strategy"] == strategy
        and pick["outcomes"][horizon]["status"] == "priced"
        and pick["outcomes"][horizon].get("excess_return_pct") is not None
    ]
    return {
        "completed": len(returns),
        "hit_rate_pct": round((hits / len(returns)) * 100, 1),
        "average_return_pct": round(sum(returns) / len(returns), 2),
        "median_return_pct": round(median, 2),
        "worst_return_pct": round(min(returns), 2),
        "loss_rate_pct": round(
            (sum(value < 0 for value in returns) / len(returns)) * 100, 1
        ),
        "large_loser_count": sum(value <= -10 for value in returns),
        "volatility_pct": _volatility_pct(returns),
        "average_benchmark_return_pct": _average_or_none(benchmark_returns),
        "average_excess_return_pct": _average_or_none(excess_returns),
        "excess_hit_rate_pct": (
            round(
                (sum(value > 0 for value in excess_returns) / len(excess_returns))
                * 100,
                1,
            )
            if excess_returns
            else None
        ),
    }


def _average_or_none(values: list[float]) -> float | None:
    if not values:
        return None
    return round(sum(values) / len(values), 2)


def _volatility_pct(values: list[float]) -> float:
    if len(values) <= 1:
        return 0.0
    average = sum(values) / len(values)
    variance = sum((value - average) ** 2 for value in values) / len(values)
    return round(variance**0.5, 2)


def _ranked_completed_picks(
    ledger: dict[str, Any], *, reverse: bool, strategy: str | None = None
) -> list[dict[str, Any]]:
    completed = []
    for pick in ledger["picks"]:
        if strategy is not None and pick["strategy"] != strategy:
            continue
        for horizon, outcome in pick["outcomes"].items():
            if outcome["status"] == "priced" and outcome["return_pct"] is not None:
                completed.append(
                    {
                        "name": pick["name"],
                        "ticker": pick["ticker"],
                        "strategy": pick["strategy"],
                        "horizon": horizon,
                        "return_pct": outcome["return_pct"],
                        "report_url": pick["report_url"],
                    }
                )
    ranked = sorted(completed, key=lambda item: item["return_pct"], reverse=reverse)
    return _deduplicate_completed_pick_rows(ranked)[:5]


def _signal_summaries(
    ledger: dict[str, Any], *, strategy: str | None = None
) -> list[dict[str, Any]]:
    buckets: dict[str, list[float]] = {}
    for pick in ledger["picks"]:
        if strategy is not None and pick["strategy"] != strategy:
            continue
        return_pct = _latest_completed_return_pct(pick)
        if return_pct is None:
            continue
        signals = [
            f"country:{pick.get('country')}",
            f"segment:{pick.get('segment')}",
        ]
        if strategy is None:
            signals.append(f"strategy:{pick.get('strategy')}")
        signals.extend(f"reason:{reason}" for reason in pick.get("reasons", []))
        conviction = pick.get("long_term_conviction")
        if conviction:
            signals.append(f"bucket:{conviction.get('bucket')}")
        for signal in signals:
            buckets.setdefault(signal, []).append(return_pct)
    summaries = []
    for signal, returns in buckets.items():
        summaries.append(
            {
                "signal": signal,
                "observations": len(returns),
                "average_return_pct": round(sum(returns) / len(returns), 2),
                "hit_rate_pct": round(
                    (sum(value > 0 for value in returns) / len(returns)) * 100, 1
                ),
            }
        )
    return sorted(summaries, key=lambda item: (-item["observations"], item["signal"]))


def _latest_completed_return_pct(pick: dict[str, Any]) -> float | None:
    for horizon in reversed(HORIZONS):
        outcome = pick["outcomes"][horizon]
        if outcome["status"] == "priced" and outcome["return_pct"] is not None:
            return outcome["return_pct"]
    return None


def _strategy_performance_section(
    summary: dict[str, Any], ledger: dict[str, Any], strategy: str
) -> list[str]:
    label = STRATEGY_LABELS[strategy]
    best_picks = summary["best_picks_by_strategy"][strategy]
    worst_picks = _exclude_pick_rows(
        summary["worst_picks_by_strategy"][strategy], best_picks
    )
    return [
        f"## {STRATEGY_TITLES[strategy]}",
        "",
        "### Horizon Scorecard",
        "",
        *_strategy_table(summary, strategy),
        "",
        "### Risk And Benchmark",
        "",
        *_risk_benchmark_table(summary, strategy),
        "",
        f"### Best {label} Picks",
        "",
        *_pick_lines(
            best_picks,
            empty_label=f"No completed {label.lower()} picks yet.",
        ),
        "",
        f"### Worst {label} Picks",
        "",
        *_pick_lines(
            worst_picks,
            empty_label=f"No completed {label.lower()} picks yet.",
        ),
        "",
        f"### {label} Signal Review",
        "",
        *_signal_table(summary["signals_by_strategy"][strategy]),
        "",
        f"### {label} Learning Suggestions",
        "",
        *[
            f"- {suggestion}"
            for suggestion in learning_suggestions(ledger, strategy=strategy)
        ],
        "",
    ]


def _strategy_table(summary: dict[str, Any], strategy: str) -> list[str]:
    lines = [
        "| Horizon | Completed | Hit Rate | Average Return | Median Return |",
        "| --- | ---: | ---: | ---: | ---: |",
    ]
    for horizon in HORIZONS:
        row = summary["strategies"][strategy][horizon]
        lines.append(
            "| "
            f"{horizon} | "
            f"{row['completed']} | "
            f"{_percent_cell(row['hit_rate_pct'])} | "
            f"{_percent_cell(row['average_return_pct'], signed=True)} | "
            f"{_percent_cell(row['median_return_pct'], signed=True)} |"
        )
    return lines


def _risk_benchmark_table(summary: dict[str, Any], strategy: str) -> list[str]:
    lines = [
        (
            "| Horizon | Worst Return | Loss Rate | Large Losers | Volatility | "
            "Benchmark | Excess Return | Excess Hit Rate |"
        ),
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for horizon in HORIZONS:
        row = summary["strategies"][strategy][horizon]
        lines.append(
            "| "
            f"{horizon} | "
            f"{_percent_cell(row['worst_return_pct'], signed=True)} | "
            f"{_percent_cell(row['loss_rate_pct'])} | "
            f"{row['large_loser_count']} | "
            f"{_percent_cell(row['volatility_pct'])} | "
            f"{_percent_cell(row['average_benchmark_return_pct'], signed=True)} | "
            f"{_percent_cell(row['average_excess_return_pct'], signed=True)} | "
            f"{_percent_cell(row['excess_hit_rate_pct'])} |"
        )
    return lines


def _pick_lines(picks: list[dict[str, Any]], *, empty_label: str) -> list[str]:
    if not picks:
        return [f"- {empty_label}"]
    return [
        f"- **{pick['name']} ({pick['ticker']})** - {pick['horizon']} return "
        f"**{_format_percent(pick['return_pct'], signed=True)}** "
        f"([report]({pick['report_url']}))"
        for pick in picks
    ]


def _signal_table(signals: list[dict[str, Any]]) -> list[str]:
    if not signals:
        return ["_No completed signal observations yet._"]
    lines = [
        "| Signal | Observations | Average Return | Hit Rate |",
        "| --- | ---: | ---: | ---: |",
    ]
    for signal in signals[:12]:
        lines.append(
            "| "
            f"{_humanize_signal(signal['signal'])} | "
            f"{signal['observations']} | "
            f"{_format_percent(signal['average_return_pct'], signed=True)} | "
            f"{_format_percent(signal['hit_rate_pct'])} |"
        )
    return lines


def _percent_cell(value: float | None, *, signed: bool = False) -> str:
    if value is None:
        return "-"
    return _format_percent(value, signed=signed)


def _format_percent(value: float, *, signed: bool = False) -> str:
    text = f"{abs(value):.2f}".rstrip("0").rstrip(".")
    if signed and value > 0:
        return f"+{text}%"
    if value < 0:
        return f"-{text}%"
    return f"{text}%"


def _deduplicate_completed_pick_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    deduplicated = []
    seen = set()
    for row in rows:
        key = _completed_pick_company_key(row)
        if key in seen:
            continue
        seen.add(key)
        deduplicated.append(row)
    return deduplicated


def _exclude_pick_rows(
    rows: list[dict[str, Any]], excluded_rows: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    excluded_keys = {_completed_pick_company_key(row) for row in excluded_rows}
    return [
        row for row in rows if _completed_pick_company_key(row) not in excluded_keys
    ]


def _completed_pick_company_key(row: dict[str, Any]) -> str:
    name = str(row.get("name") or "").strip()
    if name:
        return _normalize_company_name(name)
    return str(row.get("ticker") or "").strip().upper()


def _normalize_company_name(name: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", " ", name.lower()).strip()
    suffixes = {
        "ab",
        "ag",
        "corp",
        "corporation",
        "inc",
        "limited",
        "ltd",
        "oy",
        "oyj",
        "plc",
        "publ",
        "a",
        "b",
    }
    words = normalized.split()
    while words and words[-1] in suffixes:
        words.pop()
    return " ".join(words)


def _humanize_signal(signal: str) -> str:
    prefix, _, value = signal.partition(":")
    labels = {
        "bucket": "Bucket",
        "country": "Country",
        "reason": "Reason",
        "segment": "Segment",
        "strategy": "Strategy",
    }
    readable_value = value.replace("_", " ")
    if readable_value:
        readable_value = readable_value[0].upper() + readable_value[1:]
    return f"{labels.get(prefix, prefix.title())}: {readable_value}"
