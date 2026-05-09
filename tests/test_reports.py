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
