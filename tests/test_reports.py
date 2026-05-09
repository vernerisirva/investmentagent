from openclaw.providers import FixtureResearchProvider
from openclaw.reports import build_deep_dive, build_watchlist


def test_build_watchlist_returns_ranked_items_by_score():
    items = build_watchlist(
        FixtureResearchProvider(), countries=("SE", "FI"), limit=3, include_first_north=True
    )

    assert len(items) == 3
    assert [item.rank for item in items] == [1, 2, 3]
    assert items[0].score.total >= items[1].score.total


def test_build_deep_dive_includes_manual_checks_and_thesis():
    report = build_deep_dive(FixtureResearchProvider(), "FREEM")

    assert report.research.company.ticker == "FREEM"
    assert report.why_it_appeared
    assert report.valuation_view
    assert report.bull_case
    assert report.base_case
    assert report.bear_case
    assert report.next_manual_checks

    valuation_text = " ".join(report.valuation_view)
    assert "P/E" in valuation_text
    assert "Price/book" in valuation_text
    assert (
        "Net cash" in valuation_text
        or "Net debt" in valuation_text
        or "unavailable" in valuation_text
    )

    manual_checks_text = " ".join(report.next_manual_checks)
    for required_text in (
        "annual",
        "interim",
        "insider",
        "ownership",
        "liquidity",
        "bid/ask",
        "Nordic",
        "peer",
    ):
        assert required_text in manual_checks_text
