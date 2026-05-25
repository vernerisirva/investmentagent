from copy import deepcopy
from datetime import date

from investmentagent.performance import (
    HORIZONS,
    add_report_picks,
    empty_ledger,
    learning_suggestions,
    record_market_snapshot,
    render_scorecard_markdown,
    summarize_ledger,
    update_due_outcomes,
)


def report_payload(strategy="trading"):
    return {
        "metadata": {
            "generated_at": "2026-05-11T07:36:10+00:00",
            "strategy": strategy,
        },
        "items": [
            {
                "rank": 1,
                "company": {
                    "ticker": "STABL",
                    "name": "Stayble Therapeutics",
                    "country": "SE",
                    "exchange": "Nasdaq First North Growth Market Sweden",
                    "segment": "first_north",
                    "sector": "Health Care",
                },
                "financials": {"price": 0.85, "currency": "SEK"},
                "score": {"total": 37, "reasons": ["High live turnover"], "warnings": []},
                "risks": ["Speculative low-price share"],
                "data_quality": "partial",
            }
        ],
    }


def test_add_report_picks_creates_ledger_record_with_outcome_horizons():
    ledger = add_report_picks(
        empty_ledger(),
        report_payload(),
        report_date=date(2026, 5, 11),
        report_url="reports/trading/2026-05-11.html",
    )

    pick = ledger["picks"][0]
    assert pick["pick_id"] == "2026-05-11|trading|SE|STABL"
    assert pick["entry_price"] == 0.85
    assert pick["entry_currency"] == "SEK"
    assert pick["outcomes"] == {
        horizon: {
            "as_of_date": None,
            "price": None,
            "currency": None,
            "return_pct": None,
            "status": "not_due",
        }
        for horizon in HORIZONS
    }


def test_add_report_picks_is_idempotent_for_same_report():
    ledger = empty_ledger()
    ledger = add_report_picks(
        ledger,
        report_payload(),
        report_date=date(2026, 5, 11),
        report_url="reports/trading/2026-05-11.html",
    )
    ledger = add_report_picks(
        ledger,
        report_payload(),
        report_date=date(2026, 5, 11),
        report_url="reports/trading/2026-05-11.html",
    )

    assert len(ledger["picks"]) == 1


def test_add_report_picks_keeps_company_identity_stable_when_rank_changes():
    ledger = add_report_picks(
        empty_ledger(),
        report_payload(),
        report_date=date(2026, 5, 11),
        report_url="reports/trading/2026-05-11.html",
    )
    updated_payload = report_payload()
    updated_payload["items"][0]["rank"] = 4
    updated_payload["items"][0]["score"]["total"] = 42

    ledger = add_report_picks(
        ledger,
        updated_payload,
        report_date=date(2026, 5, 11),
        report_url="reports/trading/2026-05-11.html",
    )

    assert len(ledger["picks"]) == 1
    assert ledger["picks"][0]["pick_id"] == "2026-05-11|trading|SE|STABL"
    assert ledger["picks"][0]["rank"] == 4
    assert ledger["picks"][0]["score_total"] == 42


def test_add_report_picks_keeps_duplicate_tickers_in_different_countries_separate():
    payload = report_payload()
    second_item = report_payload()["items"][0]
    second_item["rank"] = 2
    second_item["company"]["country"] = "FI"
    payload["items"].append(second_item)

    ledger = add_report_picks(
        empty_ledger(),
        payload,
        report_date=date(2026, 5, 11),
        report_url="reports/trading/2026-05-11.html",
    )

    assert [pick["pick_id"] for pick in ledger["picks"]] == [
        "2026-05-11|trading|FI|STABL",
        "2026-05-11|trading|SE|STABL",
    ]


def test_update_due_outcomes_prices_due_horizons_and_leaves_future_horizons_open():
    ledger = add_report_picks(
        empty_ledger(),
        report_payload(),
        report_date=date(2026, 5, 11),
        report_url="reports/trading/2026-05-11.html",
    )

    updated = update_due_outcomes(
        ledger,
        as_of_date=date(2026, 5, 12),
        price_lookup={("STABL", "SE"): {"price": 1.02, "currency": "SEK"}},
    )
    updated = update_due_outcomes(
        updated,
        as_of_date=date(2026, 5, 18),
        price_lookup={("STABL", "SE"): {"price": 1.10, "currency": "SEK"}},
    )

    outcomes = updated["picks"][0]["outcomes"]
    assert outcomes["1d"]["status"] == "priced"
    assert outcomes["1d"]["return_pct"] == 20.0
    assert outcomes["5d"]["status"] == "priced"
    assert outcomes["5d"]["return_pct"] == 29.41
    assert outcomes["20d"]["status"] == "not_due"


def test_update_due_outcomes_uses_weekday_trading_days_for_due_dates():
    ledger = add_report_picks(
        empty_ledger(),
        report_payload(),
        report_date=date(2026, 5, 15),
        report_url="reports/trading/2026-05-15.html",
    )

    weekend = update_due_outcomes(
        ledger,
        as_of_date=date(2026, 5, 16),
        price_lookup={("STABL", "SE"): {"price": 1.02, "currency": "SEK"}},
    )
    monday = update_due_outcomes(
        weekend,
        as_of_date=date(2026, 5, 18),
        price_lookup={("STABL", "SE"): {"price": 1.02, "currency": "SEK"}},
    )

    assert weekend["picks"][0]["outcomes"]["1d"]["status"] == "not_due"
    assert monday["picks"][0]["outcomes"]["1d"]["status"] == "priced"
    assert monday["picks"][0]["outcomes"]["1d"]["return_pct"] == 20.0


def test_update_due_outcomes_marks_missed_window_instead_of_using_late_quote():
    ledger = add_report_picks(
        empty_ledger(),
        report_payload(),
        report_date=date(2026, 5, 11),
        report_url="reports/trading/2026-05-11.html",
    )

    updated = update_due_outcomes(
        ledger,
        as_of_date=date(2026, 5, 13),
        price_lookup={("STABL", "SE"): {"price": 1.02, "currency": "SEK"}},
    )

    assert updated["picks"][0]["outcomes"]["1d"]["status"] == "missed_window"
    assert updated["picks"][0]["outcomes"]["1d"]["return_pct"] is None


def test_update_due_outcomes_normalizes_report_country_for_price_lookup():
    payload = report_payload()
    payload["items"][0]["company"]["country"] = "se"
    ledger = add_report_picks(
        empty_ledger(),
        payload,
        report_date=date(2026, 5, 11),
        report_url="reports/trading/2026-05-11.html",
    )

    updated = update_due_outcomes(
        ledger,
        as_of_date=date(2026, 5, 12),
        price_lookup={("STABL", "SE"): {"price": 1.02, "currency": "SEK"}},
    )

    assert updated["picks"][0]["country"] == "SE"
    assert updated["picks"][0]["outcomes"]["1d"]["status"] == "priced"


def test_update_due_outcomes_marks_missing_price_without_overwriting_later():
    ledger = add_report_picks(
        empty_ledger(),
        report_payload(),
        report_date=date(2026, 5, 11),
        report_url="reports/trading/2026-05-11.html",
    )

    updated = update_due_outcomes(
        ledger,
        as_of_date=date(2026, 5, 12),
        price_lookup={},
    )

    assert updated["picks"][0]["outcomes"]["1d"]["status"] == "missing_price"
    assert updated["picks"][0]["outcomes"]["1d"]["return_pct"] is None


def test_update_due_outcomes_does_not_rewrite_terminal_missing_price_status():
    ledger = add_report_picks(
        empty_ledger(),
        report_payload(),
        report_date=date(2026, 5, 11),
        report_url="reports/trading/2026-05-11.html",
    )
    updated = update_due_outcomes(
        ledger,
        as_of_date=date(2026, 5, 12),
        price_lookup={},
    )

    updated = update_due_outcomes(
        updated,
        as_of_date=date(2026, 5, 13),
        price_lookup={("STABL", "SE"): {"price": 1.02, "currency": "SEK"}},
    )

    assert updated["picks"][0]["outcomes"]["1d"]["status"] == "missing_price"
    assert updated["picks"][0]["outcomes"]["1d"]["return_pct"] is None


def test_update_due_outcomes_adds_country_benchmark_and_excess_return():
    payload = report_payload()
    payload["items"][0]["financials"]["price"] = 10.0
    ledger = add_report_picks(
        empty_ledger(),
        payload,
        report_date=date(2026, 5, 11),
        report_url="reports/trading/2026-05-11.html",
    )
    ledger = record_market_snapshot(
        ledger,
        as_of_date=date(2026, 5, 11),
        price_lookup={
            ("STABL", "SE"): {"price": 10.0, "currency": "SEK"},
            ("PEER", "SE"): {"price": 10.0, "currency": "SEK"},
            ("LOSS", "SE"): {"price": 10.0, "currency": "SEK"},
        },
    )
    ledger = record_market_snapshot(
        ledger,
        as_of_date=date(2026, 5, 12),
        price_lookup={
            ("STABL", "SE"): {"price": 12.0, "currency": "SEK"},
            ("PEER", "SE"): {"price": 11.0, "currency": "SEK"},
            ("LOSS", "SE"): {"price": 9.0, "currency": "SEK"},
        },
    )

    updated = update_due_outcomes(
        ledger,
        as_of_date=date(2026, 5, 12),
        price_lookup={("STABL", "SE"): {"price": 12.0, "currency": "SEK"}},
    )

    outcome = updated["picks"][0]["outcomes"]["1d"]
    assert outcome["return_pct"] == 20.0
    assert outcome["benchmark_label"] == "Equal-weight SE market"
    assert outcome["benchmark_return_pct"] == 6.67
    assert outcome["excess_return_pct"] == 13.33


def test_summarize_ledger_separates_trading_and_long_term_results():
    trading = report_payload(strategy="trading")
    long_term = report_payload(strategy="long-term")
    long_term["items"][0]["company"]["ticker"] = "ADMCM"
    long_term["items"][0]["company"]["country"] = "FI"
    long_term["items"][0]["financials"]["price"] = 10.0
    long_term["items"][0]["financials"]["currency"] = "EUR"
    ledger = empty_ledger()
    ledger = add_report_picks(
        ledger,
        trading,
        report_date=date(2026, 5, 11),
        report_url="reports/trading/2026-05-11.html",
    )
    ledger = add_report_picks(
        ledger,
        long_term,
        report_date=date(2026, 5, 11),
        report_url="reports/long-term/2026-05-11.html",
    )
    ledger = update_due_outcomes(
        ledger,
        as_of_date=date(2026, 5, 18),
        price_lookup={
            ("STABL", "SE"): {"price": 1.02, "currency": "SEK"},
            ("ADMCM", "FI"): {"price": 11.0, "currency": "EUR"},
        },
    )

    summary = summarize_ledger(ledger)

    assert summary["strategies"]["trading"]["5d"]["completed"] == 1
    assert summary["strategies"]["trading"]["5d"]["average_return_pct"] == 20.0
    assert summary["strategies"]["long-term"]["5d"]["completed"] == 1
    assert summary["strategies"]["long-term"]["5d"]["average_return_pct"] == 10.0


def test_summarize_ledger_includes_risk_and_benchmark_metrics():
    payload = report_payload(strategy="trading")
    payload["items"].append(deepcopy(payload["items"][0]))
    payload["items"][0]["company"]["ticker"] = "WIN"
    payload["items"][0]["financials"]["price"] = 10.0
    payload["items"][1]["rank"] = 2
    payload["items"][1]["company"]["ticker"] = "LOSS"
    payload["items"][1]["financials"]["price"] = 10.0
    ledger = add_report_picks(
        empty_ledger(),
        payload,
        report_date=date(2026, 5, 11),
        report_url="reports/trading/2026-05-11.html",
    )
    ledger = update_due_outcomes(
        ledger,
        as_of_date=date(2026, 5, 12),
        price_lookup={
            ("WIN", "SE"): {"price": 12.0, "currency": "SEK"},
            ("LOSS", "SE"): {"price": 8.8, "currency": "SEK"},
        },
    )
    ledger["picks"][0]["outcomes"]["1d"]["benchmark_return_pct"] = 5.0
    ledger["picks"][0]["outcomes"]["1d"]["excess_return_pct"] = 15.0
    ledger["picks"][1]["outcomes"]["1d"]["benchmark_return_pct"] = 0.0
    ledger["picks"][1]["outcomes"]["1d"]["excess_return_pct"] = -12.0

    summary = summarize_ledger(ledger)
    row = summary["strategies"]["trading"]["1d"]

    assert row["worst_return_pct"] == -12.0
    assert row["loss_rate_pct"] == 50.0
    assert row["large_loser_count"] == 1
    assert row["volatility_pct"] == 16.0
    assert row["average_benchmark_return_pct"] == 2.5
    assert row["average_excess_return_pct"] == 1.5
    assert row["excess_hit_rate_pct"] == 50.0


def test_render_scorecard_markdown_includes_strategy_sections_and_disclaimer():
    ledger = add_report_picks(
        empty_ledger(),
        report_payload(),
        report_date=date(2026, 5, 11),
        report_url="reports/trading/2026-05-11.html",
    )
    ledger = update_due_outcomes(
        ledger,
        as_of_date=date(2026, 5, 18),
        price_lookup={("STABL", "SE"): {"price": 1.02, "currency": "SEK"}},
    )

    output = render_scorecard_markdown(
        ledger,
        generated_at="2026-05-16 08:48 EEST",
    )

    assert "# InvestmentAgent Performance" in output
    assert "Research triage only. Not financial advice." in output
    assert "## Trading Ideas" in output
    assert "| 5d | 1 | 100% | +20% | +20% |" in output
    assert "## Long-Term Investment Ideas" in output
    assert "### Trading Learning Suggestions" in output


def test_render_scorecard_markdown_includes_risk_and_benchmark_table():
    ledger = add_report_picks(
        empty_ledger(),
        report_payload(),
        report_date=date(2026, 5, 11),
        report_url="reports/trading/2026-05-11.html",
    )
    ledger = update_due_outcomes(
        ledger,
        as_of_date=date(2026, 5, 12),
        price_lookup={("STABL", "SE"): {"price": 1.02, "currency": "SEK"}},
    )
    ledger["picks"][0]["outcomes"]["1d"]["benchmark_return_pct"] = 5.0
    ledger["picks"][0]["outcomes"]["1d"]["excess_return_pct"] = 15.0

    output = render_scorecard_markdown(
        ledger,
        generated_at="2026-05-16 08:48 EEST",
    )

    assert "### Risk And Benchmark" in output
    assert "| Horizon | Worst Return | Loss Rate | Large Losers | Volatility | Benchmark | Excess Return | Excess Hit Rate |" in output
    assert "| 1d | +20% | 0% | 0 | 0% | +5% | +15% | 100% |" in output


def test_render_scorecard_markdown_includes_latest_market_context():
    ledger = record_market_snapshot(
        empty_ledger(),
        as_of_date=date(2026, 5, 12),
        price_lookup={
            ("AAA", "SE"): {
                "price": 10.0,
                "currency": "SEK",
                "catalysts": ["Strong intraday momentum (+12.0%)", "High live turnover"],
            },
            ("BBB", "SE"): {
                "price": 20.0,
                "currency": "SEK",
                "catalysts": ["Positive intraday momentum (+6.0%)"],
            },
            ("CCC", "FI"): {
                "price": 5.0,
                "currency": "EUR",
                "risks": ["Sharp intraday selloff"],
            },
        },
    )

    output = render_scorecard_markdown(
        ledger,
        generated_at="2026-05-12 09:03 EEST",
    )

    assert "## Market Context" in output
    assert "- Latest snapshot: 2026-05-12" in output
    assert "- Market tone: Risk-on / broad momentum" in output
    assert "- Large positive movers: 2" in output
    assert "- Sharp selloffs: 1" in output
    assert "- Active turnover signals: 1" in output


def test_render_scorecard_markdown_keeps_strategy_details_separate():
    ledger = empty_ledger()
    trading_payload = report_payload(strategy="trading")
    trading_payload["items"].append(deepcopy(trading_payload["items"][0]))
    trading_payload["items"][0]["company"]["ticker"] = "TRADEWIN"
    trading_payload["items"][0]["company"]["name"] = "Trading Winner"
    trading_payload["items"][1]["rank"] = 2
    trading_payload["items"][1]["company"]["ticker"] = "TRADELOSS"
    trading_payload["items"][1]["company"]["name"] = "Trading Loser"

    long_term_payload = report_payload(strategy="long-term")
    long_term_payload["items"].append(deepcopy(long_term_payload["items"][0]))
    long_term_payload["items"][0]["company"]["ticker"] = "LONGWIN"
    long_term_payload["items"][0]["company"]["name"] = "Long-Term Winner"
    long_term_payload["items"][1]["rank"] = 2
    long_term_payload["items"][1]["company"]["ticker"] = "LONGLOSS"
    long_term_payload["items"][1]["company"]["name"] = "Long-Term Loser"

    ledger = add_report_picks(
        ledger,
        trading_payload,
        report_date=date(2026, 5, 11),
        report_url="reports/trading/2026-05-11.html",
    )
    ledger = add_report_picks(
        ledger,
        long_term_payload,
        report_date=date(2026, 5, 11),
        report_url="reports/long-term/2026-05-11.html",
    )
    ledger = update_due_outcomes(
        ledger,
        as_of_date=date(2026, 5, 12),
        price_lookup={
            ("TRADEWIN", "SE"): {"price": 1.02, "currency": "SEK"},
            ("TRADELOSS", "SE"): {"price": 0.75, "currency": "SEK"},
            ("LONGWIN", "SE"): {"price": 0.94, "currency": "SEK"},
            ("LONGLOSS", "SE"): {"price": 0.68, "currency": "SEK"},
        },
    )

    output = render_scorecard_markdown(ledger, generated_at="2026-05-12 09:03 EEST")
    trading_section = output.split("## Long-Term Investment Ideas")[0]
    long_term_section = output.split("## Long-Term Investment Ideas")[1]

    assert "### Horizon Scorecard\n\n| Horizon | Completed" in output
    assert "### Best Trading Picks" in trading_section
    assert "Trading Winner" in trading_section
    assert "Long-Term Winner" not in trading_section
    assert "### Best Long-Term Picks" in long_term_section
    assert "Long-Term Winner" in long_term_section
    assert "Trading Winner" not in long_term_section
    assert "| Signal | Observations | Average Return | Hit Rate |" in output
    assert "Reason: High live turnover" in output


def test_long_term_performance_review_includes_quality_bucket_signals():
    ledger = {
        "schema_version": 1,
        "picks": [
            {
                "pick_id": "long-term:2026-05-01:QUAL:SE",
                "strategy": "long-term",
                "report_date": "2026-05-01",
                "ticker": "QUAL",
                "name": "Quality AB",
                "country": "SE",
                "segment": "first_north",
                "score": 25.0,
                "entry": {"price": 10.0, "currency": "SEK"},
                "reasons": [
                    "Quality small-cap candidate",
                    "Positive operating margin (16.0%)",
                ],
                "risks": [],
                "data_quality": "partial",
                "long_term_conviction": {"bucket": "Quality small-cap candidate"},
                "report_url": "../reports/long-term/2026-05-01.html",
                "outcomes": {
                    "1d": {"status": "priced", "return_pct": 4.0},
                    "5d": {"status": "not_due", "return_pct": None},
                    "20d": {"status": "not_due", "return_pct": None},
                    "60d": {"status": "not_due", "return_pct": None},
                },
            },
            {
                "pick_id": "long-term:2026-05-01:SPEC:SE",
                "strategy": "long-term",
                "report_date": "2026-05-01",
                "ticker": "SPEC",
                "name": "Speculative AB",
                "country": "SE",
                "segment": "first_north",
                "score": -5.0,
                "entry": {"price": 5.0, "currency": "SEK"},
                "reasons": ["Speculative small-cap monitor"],
                "risks": ["Missing valuation data", "No profitability signal"],
                "data_quality": "thin",
                "long_term_conviction": {"bucket": "Speculative small-cap monitor"},
                "report_url": "../reports/long-term/2026-05-01.html",
                "outcomes": {
                    "1d": {"status": "priced", "return_pct": -3.0},
                    "5d": {"status": "not_due", "return_pct": None},
                    "20d": {"status": "not_due", "return_pct": None},
                    "60d": {"status": "not_due", "return_pct": None},
                },
            },
        ],
        "market_snapshots": {},
    }

    rendered = render_scorecard_markdown(ledger, generated_at="2026-05-02 08:00 EEST")

    assert "Bucket: Quality small-cap candidate" in rendered
    assert "Bucket: Speculative small-cap monitor" in rendered
    assert "Quality: Positive operating margin" in rendered
    assert "Proof gap: Missing valuation data" in rendered
    assert "Proof gap: No profitability signal" in rendered


def test_long_term_performance_review_uses_report_warnings_without_duplicate_signals():
    payload = report_payload(strategy="long-term")
    payload["items"][0]["company"]["ticker"] = "QUAL"
    payload["items"][0]["company"]["name"] = "Quality AB"
    payload["items"][0]["financials"]["price"] = 10.0
    payload["items"][0]["score"]["reasons"] = [
        "Net cash balance sheet",
        "Conservative balance sheet",
    ]
    payload["items"][0]["score"]["warnings"] = [
        "Missing valuation data",
        "No profitability signal",
    ]
    payload["items"][0]["long_term_conviction"] = {
        "bucket": "Quality small-cap candidate"
    }
    ledger = add_report_picks(
        empty_ledger(),
        payload,
        report_date=date(2026, 5, 11),
        report_url="reports/long-term/2026-05-11.html",
    )

    assert ledger["picks"][0]["risks"] == ["Speculative low-price share"]
    assert ledger["picks"][0]["warnings"] == [
        "Missing valuation data",
        "No profitability signal",
    ]

    ledger = update_due_outcomes(
        ledger,
        as_of_date=date(2026, 5, 12),
        price_lookup={("QUAL", "SE"): {"price": 11.0, "currency": "SEK"}},
    )

    rendered = render_scorecard_markdown(ledger, generated_at="2026-05-12 09:03 EEST")

    assert rendered.count("| Bucket: Quality small-cap candidate |") == 1
    assert "Proof gap: Missing valuation data" in rendered
    assert "Proof gap: No profitability signal" in rendered
    assert "| Quality: Conservative balance sheet | 1 | +10% | 100% |" in rendered


def test_render_scorecard_deduplicates_company_names_in_pick_highlights():
    payload = report_payload(strategy="trading")
    payload["items"].append(deepcopy(payload["items"][0]))
    payload["items"][0]["company"]["ticker"] = "NANOFS"
    payload["items"][0]["company"]["name"] = "Nanoform Finland Oyj"
    payload["items"][1]["rank"] = 2
    payload["items"][1]["company"]["ticker"] = "NANOFH"
    payload["items"][1]["company"]["name"] = "Nanoform Finland Oyj"
    ledger = add_report_picks(
        empty_ledger(),
        payload,
        report_date=date(2026, 5, 11),
        report_url="reports/trading/2026-05-11.html",
    )
    ledger = update_due_outcomes(
        ledger,
        as_of_date=date(2026, 5, 12),
        price_lookup={
            ("NANOFS", "SE"): {"price": 1.10, "currency": "SEK"},
            ("NANOFH", "SE"): {"price": 1.05, "currency": "SEK"},
        },
    )

    output = render_scorecard_markdown(ledger, generated_at="2026-05-12 09:03 EEST")

    assert output.count("Nanoform Finland Oyj") == 1


def test_learning_suggestions_require_minimum_sample_size():
    ledger = empty_ledger()
    for index in range(9):
        payload = report_payload()
        payload["items"][0]["rank"] = index + 1
        payload["items"][0]["company"]["ticker"] = f"AAA{index}"
        payload["items"][0]["score"]["reasons"] = ["High live turnover"]
        payload["items"][0]["financials"]["price"] = 10.0
        ledger = add_report_picks(
            ledger,
            payload,
            report_date=date(2026, 5, 11),
            report_url="reports/trading/2026-05-11.html",
        )
    lookup = {
        (f"AAA{index}", "SE"): {"price": 11.0, "currency": "SEK"}
        for index in range(9)
    }
    ledger = update_due_outcomes(ledger, as_of_date=date(2026, 5, 16), price_lookup=lookup)

    assert learning_suggestions(ledger) == [
        "No learning suggestions yet. At least 10 completed observations are needed for a signal."
    ]
