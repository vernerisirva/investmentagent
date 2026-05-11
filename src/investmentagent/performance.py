from __future__ import annotations

import json
from copy import deepcopy
from datetime import date, timedelta
from pathlib import Path
from typing import Any


LEDGER_SCHEMA_VERSION = 1
HORIZONS = ("1d", "5d", "20d", "60d")
HORIZON_DAYS = {"1d": 1, "5d": 5, "20d": 20, "60d": 60}
DISCLAIMER = "Research triage only. Not financial advice."


def empty_ledger() -> dict[str, Any]:
    return {"schema_version": LEDGER_SCHEMA_VERSION, "picks": []}


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
        }
    return lookup


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
            outcome.update(
                {
                    "as_of_date": as_of_date.isoformat(),
                    "price": quote["price"],
                    "currency": quote_currency,
                    "return_pct": round(return_pct, 2),
                    "status": "priced",
                }
            )
    return updated


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
            for strategy in ("trading", "long-term")
        },
        "best_picks": _ranked_completed_picks(ledger, reverse=True),
        "worst_picks": _ranked_completed_picks(ledger, reverse=False),
        "signals": _signal_summaries(ledger),
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
        "## Trading Ideas",
        *_strategy_table(summary, "trading"),
        "",
        "## Long-Term Ideas",
        *_strategy_table(summary, "long-term"),
        "",
        "## Best Completed Picks",
        *_pick_lines(summary["best_picks"]),
        "",
        "## Worst Completed Picks",
        *_pick_lines(summary["worst_picks"]),
        "",
        "## Signal Review",
        *_signal_lines(summary["signals"]),
        "",
        "## Learning Suggestions",
        *[f"- {suggestion}" for suggestion in learning_suggestions(ledger)],
    ]
    return "\n".join(lines)


def learning_suggestions(ledger: dict[str, Any]) -> list[str]:
    eligible = [
        signal
        for signal in _signal_summaries(ledger)
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
            f"{signal['signal']} has produced a {direction} average return "
            f"of {signal['average_return_pct']}% across {signal['observations']} "
            "completed observations. Review whether its scoring weight should change."
        )
    return suggestions


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
        }
    sorted_returns = sorted(returns)
    midpoint = len(sorted_returns) // 2
    if len(sorted_returns) % 2:
        median = sorted_returns[midpoint]
    else:
        median = (sorted_returns[midpoint - 1] + sorted_returns[midpoint]) / 2
    hits = sum(value > 0 for value in returns)
    return {
        "completed": len(returns),
        "hit_rate_pct": round((hits / len(returns)) * 100, 1),
        "average_return_pct": round(sum(returns) / len(returns), 2),
        "median_return_pct": round(median, 2),
    }


def _ranked_completed_picks(ledger: dict[str, Any], *, reverse: bool) -> list[dict[str, Any]]:
    completed = []
    for pick in ledger["picks"]:
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
    return sorted(completed, key=lambda item: item["return_pct"], reverse=reverse)[:5]


def _signal_summaries(ledger: dict[str, Any]) -> list[dict[str, Any]]:
    buckets: dict[str, list[float]] = {}
    for pick in ledger["picks"]:
        return_pct = _latest_completed_return_pct(pick)
        if return_pct is None:
            continue
        signals = [
            f"country:{pick.get('country')}",
            f"segment:{pick.get('segment')}",
            f"strategy:{pick.get('strategy')}",
        ]
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
            f"{_percent_cell(row['average_return_pct'])} | "
            f"{_percent_cell(row['median_return_pct'])} |"
        )
    return lines


def _pick_lines(picks: list[dict[str, Any]]) -> list[str]:
    if not picks:
        return ["- No completed picks yet."]
    return [
        f"- {pick['name']} ({pick['ticker']}), {pick['strategy']} {pick['horizon']}: "
        f"{pick['return_pct']}% - [{pick['report_url']}]({pick['report_url']})"
        for pick in picks
    ]


def _signal_lines(signals: list[dict[str, Any]]) -> list[str]:
    if not signals:
        return ["- No completed signal observations yet."]
    return [
        f"- {signal['signal']}: {signal['observations']} observations, "
        f"{signal['average_return_pct']}% average return, "
        f"{signal['hit_rate_pct']}% hit rate"
        for signal in signals[:12]
    ]


def _percent_cell(value: float | None) -> str:
    if value is None:
        return "-"
    return f"{value}%"
