from datetime import date

from investmentagent.performance import (
    HORIZONS,
    add_report_picks,
    empty_ledger,
    learning_suggestions,
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
        as_of_date=date(2026, 5, 16),
        price_lookup={("STABL", "SE"): {"price": 1.10, "currency": "SEK"}},
    )

    outcomes = updated["picks"][0]["outcomes"]
    assert outcomes["1d"]["status"] == "priced"
    assert outcomes["1d"]["return_pct"] == 20.0
    assert outcomes["5d"]["status"] == "priced"
    assert outcomes["5d"]["return_pct"] == 29.41
    assert outcomes["20d"]["status"] == "not_due"


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
        as_of_date=date(2026, 5, 16),
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


def test_render_scorecard_markdown_includes_strategy_sections_and_disclaimer():
    ledger = add_report_picks(
        empty_ledger(),
        report_payload(),
        report_date=date(2026, 5, 11),
        report_url="reports/trading/2026-05-11.html",
    )
    ledger = update_due_outcomes(
        ledger,
        as_of_date=date(2026, 5, 16),
        price_lookup={("STABL", "SE"): {"price": 1.02, "currency": "SEK"}},
    )

    output = render_scorecard_markdown(
        ledger,
        generated_at="2026-05-16 08:48 EEST",
    )

    assert "# InvestmentAgent Performance" in output
    assert "Research triage only. Not financial advice." in output
    assert "## Trading Ideas" in output
    assert "| 5d | 1 | 100.0% | 20.0% | 20.0% |" in output
    assert "## Long-Term Ideas" in output
    assert "## Learning Suggestions" in output


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
