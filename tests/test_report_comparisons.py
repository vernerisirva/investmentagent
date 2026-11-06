"""Decision-time stock comparisons are descriptive, direction-correct and never change X."""
import math

import pytest
from typer.testing import CliRunner

from investmentagent.cli import app
from investmentagent.models import (
    Company, CompanyResearch, DataQuality, FinancialSnapshot, ListingSegment, ScoreBreakdown,
    WatchlistItem,
)
from investmentagent.report_comparisons import (
    ALL_ELIGIBLE, LISTING_PEERS, METRICS_BY_KEY, PEER_MINIMUM_OBSERVATIONS, ComparisonRow,
    classify_value, compare_ideas, comparison_rows, favourable_percentile, median_or_none,
    mid_rank_percentile, peer_stat, relative_summary,
)


DECISION = "2026-11-06T06:21:00Z"


def row(index, *, country="SE", venue="main_market", score=50.0, rank=None, gate=None,
        components=None, cache_state="fresh", retrieved_at="2026-10-30T05:00:00Z", **metrics):
    values = {key: None for key in METRICS_BY_KEY}
    values.update(metrics)
    return ComparisonRow(
        company_id=f"isin:{country}{index:010d}", ticker=f"T{index:03d}", name=f"Company {index}",
        country=country, venue=venue, rank=rank or index + 1, score_total=score,
        components=components or {"value": score, "risk_penalty": 0.0}, gate_tier=gate,
        metrics=values, data_quality="partial", cache_state=cache_state, retrieved_at=retrieved_at,
    )


def test_mid_rank_percentile_counts_ties_as_half():
    assert mid_rank_percentile(5, [1, 5, 5, 9]) == 50.0
    assert mid_rank_percentile(9, [1, 5, 5]) == 100.0
    assert mid_rank_percentile(1, [1, 1]) == 50.0
    assert mid_rank_percentile(3, []) is None


def test_lower_is_better_metrics_are_not_reversed():
    # P/E 8: three peers are more expensive (10, 12, 20), one ties, one is cheaper.
    assert favourable_percentile(8, [10, 12, 20, 8, 5], "lower") == 70.0
    assert favourable_percentile(10, [5, 10, 20], "higher") == 50.0
    assert favourable_percentile(10, [5, 10, 20], "neutral") == 50.0
    with pytest.raises(ValueError):
        favourable_percentile(1, [1], "sideways")


def test_median_arithmetic():
    assert median_or_none([3, 1, 2]) == 2
    assert median_or_none([4, 1, 2, 3]) == 2.5
    assert median_or_none([]) is None


@pytest.mark.parametrize("value, expected", [
    (12.5, "valid"), (-5.0, "invalid"), (0.0, "invalid"), (None, "missing"),
    (math.nan, "missing"), (math.inf, "missing"), (True, "missing"), ("12", "missing"),
])
def test_pe_classification_handles_negative_zero_and_invalid_values(value, expected):
    assert classify_value(METRICS_BY_KEY["pe_ratio"], value) == expected


def test_debt_to_equity_negative_equity_is_not_meaningful():
    spec = METRICS_BY_KEY["debt_to_equity"]
    assert classify_value(spec, -0.2) == "invalid"
    assert classify_value(spec, 0.0) == "valid"


def test_invalid_multiples_are_excluded_and_counted():
    spec = METRICS_BY_KEY["pe_ratio"]
    peers = [row(i, pe_ratio=value) for i, value in enumerate([-3.0, 0.0, 10.0, 12.0, 15.0, 20.0, 25.0, None])]
    stat = peer_stat(spec, 11.0, "valid", peers, level=LISTING_PEERS, group="SE main market")
    assert (stat.population, stat.usable, stat.invalid, stat.missing) == (8, 5, 2, 1)
    assert stat.median == 15.0
    # Cheaper than 12, 15, 20, 25 (4 of 5 usable); the loss-makers are not ranked.
    assert stat.percentile == 80.0 and stat.status == "ok"


def test_incomplete_peer_data_is_unavailable_not_a_percentile():
    spec = METRICS_BY_KEY["operating_margin_pct"]
    peers = [row(i, operating_margin_pct=value) for i, value in enumerate([5.0, 6.0, 7.0, 8.0, None, None])]
    assert PEER_MINIMUM_OBSERVATIONS == 5
    stat = peer_stat(spec, 9.0, "valid", peers, level=LISTING_PEERS, group="SE main market")
    assert stat.status == "unavailable" and stat.percentile is None and stat.median is None
    assert (stat.usable, stat.missing) == (4, 2)


def test_own_invalid_or_missing_value_never_gets_a_percentile():
    spec = METRICS_BY_KEY["pe_ratio"]
    peers = [row(i, pe_ratio=10.0 + i) for i in range(6)]
    invalid = peer_stat(spec, -4.0, "invalid", peers, level=LISTING_PEERS, group="g")
    missing = peer_stat(spec, None, "missing", peers, level=LISTING_PEERS, group="g")
    assert invalid.status == "not_meaningful" and invalid.percentile is None and invalid.median == 12.5
    assert missing.status == "missing" and missing.percentile is None


def _universe():
    rows = [row(i, score=100.0 - i, pe_ratio=8.0 + i, operating_margin_pct=float(i)) for i in range(8)]
    rows.append(row(20, country="FI", score=40.0, pe_ratio=-2.0, operating_margin_pct=-5.0))
    rows.append(row(21, country="SE", venue="first_north", score=100.0 - 3, pe_ratio=30.0))
    return rows


def test_score_percentile_ties_and_median():
    rows = _universe()
    comparison = compare_ideas(rows, [rows[3].company_id], strategy="trading", public_limit=3,
                               decision_at=DECISION, cache_recorded=True)
    idea = comparison.ideas[0]
    # Score 97: 96, 95, 94, 93 and 40 are lower, the First North 97 ties, 3 are higher.
    assert idea.score_percentile == pytest.approx(100 * 5.5 / 9)
    assert idea.universe_median_score == median_or_none([r.score_total for r in rows])
    assert idea.score_minus_median == pytest.approx(97.0 - idea.universe_median_score)
    assert comparison.universe_size == 10 and comparison.country_counts == {"FI": 1, "SE": 9}


def test_listing_peers_use_only_country_and_venue_and_exclude_the_company():
    rows = _universe()
    comparison = compare_ideas(rows, [rows[0].company_id], strategy="trading", public_limit=3,
                               decision_at=DECISION, cache_recorded=True)
    idea = comparison.ideas[0]
    pe = idea.metric("pe_ratio")
    listing, everyone = pe.level(LISTING_PEERS), pe.level(ALL_ELIGIBLE)
    assert idea.listing_group == "SE main market" and idea.listing_group_size == 7
    assert listing.population == 7 and everyone.population == 9
    assert everyone.invalid == 1  # the loss-making FI company
    assert listing.percentile == 100.0  # lowest positive P/E among its listing peers


def test_country_minimum_inclusion_is_explained_from_the_base_order():
    rows = _universe()
    promoted = rows[8]  # FI, score 40, base position 10 of 10
    comparison = compare_ideas(rows, [rows[0].company_id, rows[1].company_id, promoted.company_id],
                               strategy="trading", public_limit=3, decision_at=DECISION,
                               cache_recorded=True)
    by_id = {idea.row.company_id: idea for idea in comparison.ideas}
    assert by_id[promoted.company_id].base_rank == 10
    assert by_id[promoted.company_id].included_by_country_minimum
    assert not by_id[rows[0].company_id].included_by_country_minimum


def test_long_term_base_order_uses_gate_tier_before_score():
    high = row(1, score=10.0, gate="High-conviction candidate")
    watch = row(2, score=90.0, gate="Fundamental watchlist")
    comparison = compare_ideas([high, watch], [high.company_id, watch.company_id], strategy="long-term",
                               public_limit=1, decision_at=DECISION, cache_recorded=True)
    assert [idea.base_rank for idea in comparison.ideas] == [1, 2]
    assert comparison.ideas[1].included_by_country_minimum  # base rank 2 exceeds limit 1


def test_penalty_percentiles_reward_smaller_penalties():
    rows = [row(i, components={"value": 10.0, "risk_penalty": float(i)}) for i in range(5)]
    comparison = compare_ideas(rows, [rows[0].company_id], strategy="trading", public_limit=1,
                               decision_at=DECISION, cache_recorded=True)
    assert comparison.ideas[0].component_percentiles["risk_penalty"] == 100.0


def test_stale_and_missing_fundamentals_are_reported_with_decision_time_age():
    rows = [row(0, cache_state="stale", retrieved_at="2026-09-01T05:00:00Z"),
            *[row(i, cache_state="fresh") for i in range(1, 4)],
            row(4, cache_state="missing", retrieved_at=None)]
    comparison = compare_ideas(rows, [rows[0].company_id, rows[4].company_id], strategy="trading",
                               public_limit=2, decision_at=DECISION, cache_recorded=True)
    stale, missing = comparison.ideas
    assert stale.fundamentals_age_days == 66
    assert missing.fundamentals_age_days is None
    assert stale.listing_group_fresh_share == 75.0


def test_fundamentals_retrieved_after_the_decision_are_rejected():
    rows = [row(0, retrieved_at="2026-11-07T00:00:00Z")]
    with pytest.raises(ValueError, match="after the decision"):
        compare_ideas(rows, [rows[0].company_id], strategy="trading", public_limit=1,
                      decision_at=DECISION, cache_recorded=True)


def test_selected_companies_must_belong_to_the_same_universe():
    rows = _universe()
    with pytest.raises(ValueError, match="missing from comparison universe"):
        compare_ideas(rows, ["isin:XX"], strategy="trading", public_limit=1, decision_at=DECISION,
                      cache_recorded=True)
    with pytest.raises(ValueError, match="duplicate"):
        compare_ideas([rows[0], rows[0]], [rows[0].company_id], strategy="trading", public_limit=1,
                      decision_at=DECISION, cache_recorded=True)


def test_relative_summary_wording_follows_metric_direction():
    peers = [row(i, pe_ratio=20.0 + i, operating_margin_pct=30.0 + i, market_cap_eur_m=100.0 + i)
             for i in range(1, 7)]
    stock = row(0, pe_ratio=5.0, operating_margin_pct=1.0, market_cap_eur_m=10.0)
    comparison = compare_ideas([stock, *peers], [stock.company_id], strategy="trading", public_limit=1,
                               decision_at=DECISION, cache_recorded=True)
    text = relative_summary(comparison.ideas[0])
    assert "stronger than most listing peers on P/E (cheaper than 100% of peers)" in text.lower().replace(
        "p/e", "P/E")
    assert "weaker than most listing peers on operating margin (lower than 100% of peers)" in text
    assert "smaller than 100% of peers on market cap" in text


def test_relative_summary_without_comparable_data_says_so():
    rows = [row(0, pe_ratio=5.0), row(1, pe_ratio=6.0)]
    comparison = compare_ideas(rows, [rows[0].company_id], strategy="trading", public_limit=1,
                               decision_at=DECISION, cache_recorded=True)
    assert relative_summary(comparison.ideas[0]).startswith("No clear relative strength")


def _item(index, *, rank, catalyst=20.0, segment=ListingSegment.MAIN_MARKET):
    company = Company(name=f"Company {index}", ticker=f"C{index:02d}", country="SE",
                      exchange="Nasdaq Stockholm", segment=segment, isin=f"SE{index:010d}",
                      market_cap_eur_m=200.0)
    research = CompanyResearch(company=company, financials=FinancialSnapshot(pe_ratio=9.0, data_quality=DataQuality.PARTIAL),
                               data_quality=DataQuality.PARTIAL)
    score = ScoreBreakdown(value=20.0, discovery=5.0, catalyst=catalyst, risk_penalty=3.0,
                           data_quality_penalty=7.0, total=35.0 + catalyst)
    return WatchlistItem(rank=rank, research=research, score=score)


def test_comparison_rows_join_x_by_identity_and_reject_disagreement():
    items = [_item(1, rank=1), _item(2, rank=2)]

    class Row:
        def __init__(self, company_id, rank, state="fresh"):
            self.company_id, self.rank, self.long_term = company_id, rank, None
            self.cache = {"state": state, "retrieved_at": "2026-10-01T00:00:00Z"}

    rows = comparison_rows(items, strategy="trading",
                           evaluation_rows=[Row("isin:SE0000000001", 1), Row("isin:SE0000000002", 2, "stale")])
    assert [r.cache_state for r in rows] == ["fresh", "stale"]
    assert rows[0].metrics["market_cap_eur_m"] == 200.0 and rows[0].metrics["pe_ratio"] == 9.0
    assert "ev_to_ebit" in rows[0].missing_inputs
    with pytest.raises(ValueError, match="disagrees"):
        comparison_rows(items, strategy="trading", evaluation_rows=[Row("isin:SE0000000001", 2),
                                                                   Row("isin:SE0000000002", 2)])
    with pytest.raises(ValueError, match="missing from the evaluation snapshot"):
        comparison_rows(items, strategy="trading", evaluation_rows=[Row("isin:SE0000000001", 1)])
    without_x = comparison_rows(items, strategy="trading")
    assert without_x[0].cache_state is None and without_x[0].retrieved_at is None


def test_long_term_rows_split_quality_adjustment_from_catalyst():
    item = _item(1, rank=1, catalyst=53.0)

    class Row:
        company_id, rank, cache = "isin:SE0000000001", 1, {}
        long_term = {"gate_tier": "High-conviction candidate", "quality_adjustment": 45.0}

    [result] = comparison_rows([item], strategy="long-term", evaluation_rows=[Row()])
    assert result.components["quality_adjustment"] == 45.0
    assert result.components["catalyst"] == 8.0
    assert result.gate_tier == "High-conviction candidate"


RUNNER = CliRunner()


def _watchlist(tmp_path, name, *saves, strategy="long-term"):
    root = tmp_path / name
    args = ["watchlist", "--provider", "fixture", "--strategy", strategy, "--limit", "3",
            "--min-country", "FI:1", "--evaluation-dir", str(root / "ev"),
            "--evaluation-decision-at", "2026-08-10T08:30:00+00:00"]
    if strategy == "long-term":
        args += ["--experiment-dir", str(root / "exp")]
    for save in saves:
        args += ["--save", str(root / save)]
    result = RUNNER.invoke(app, args)
    assert result.exit_code == 0, result.output
    return root


def _tree(root):
    return {path.relative_to(root).as_posix(): path.read_bytes()
            for path in sorted(root.rglob("*")) if path.is_file()}


@pytest.mark.parametrize("strategy", ["long-term", "trading"])
def test_markdown_comparisons_do_not_change_x_plans_sidecars_or_json(tmp_path, strategy):
    plain = _watchlist(tmp_path, "plain", "report.json", strategy=strategy)
    compared = _watchlist(tmp_path, "compared", "report.json", "report.md", strategy=strategy)
    for directory in ("ev", "exp"):
        assert _tree(plain / directory) == _tree(compared / directory)
    assert (plain / "report.json").read_bytes() == (compared / "report.json").read_bytes()
    markdown = (compared / "report.md").read_text()
    assert "## Run Diagnostics" in markdown and "<details" in markdown


def test_comparison_failure_never_blocks_the_report_or_x(tmp_path, monkeypatch):
    def broken(*args, **kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr("investmentagent.cli.compare_ideas", broken)
    root = _watchlist(tmp_path, "broken", "report.json", "report.md")
    markdown = (root / "report.md").read_text()
    assert "peer comparisons are unavailable for this run (RuntimeError)" in markdown
    assert "## Metadata" in markdown
    assert list((root / "ev").rglob("*.jsonl"))
