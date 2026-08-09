import json
from datetime import date, datetime, timezone

import pytest

from investmentagent.evaluation import (
    EVALUATION_SCHEMA_VERSION,
    build_evaluation_snapshot,
    load_evaluation_snapshot,
    save_evaluation_snapshot,
    serialize_evaluation_snapshot,
)
from investmentagent.fundamentals import EnrichedResearchProvider
from investmentagent.fundamentals_cache import FileFundamentalsCache
from investmentagent.models import (
    Company,
    CompanyResearch,
    DataQuality,
    Evidence,
    FinancialObservation,
    FinancialSnapshot,
    FundamentalsSnapshot,
    ListingSegment,
    ObservationConfidence,
    ReportingPeriodType,
    SourceCheck,
)
from investmentagent.reports import build_watchlist_result
from investmentagent.scoring import SCORING_MODEL_VERSION


def timestamp(day: int, hour: int = 8) -> datetime:
    return datetime(2026, 8, day, hour, tzinfo=timezone.utc)


def make_research(index: int, *, country: str = "SE") -> CompanyResearch:
    ticker = f"C{index:02d}"
    company = Company(
        name=f"Company {index:02d} AB",
        ticker=ticker,
        country=country,
        exchange="Nasdaq Stockholm" if country == "SE" else "Nasdaq Helsinki",
        segment=(
            ListingSegment.FIRST_NORTH
            if index % 3 == 0
            else ListingSegment.MAIN_MARKET
        ),
        isin=f"{country}{index:010d}",
        sector="Software",
        market_cap_eur_m=100.0 + index,
        currency="SEK" if country == "SE" else "EUR",
        business_description=f"Company {index:02d} sells business software.",
    )
    financials = FinancialSnapshot(
        price=10.0 + index,
        currency=company.currency,
        pe_ratio=7.0 + index,
        price_to_book=0.8 + index / 20,
        net_cash_eur_m=20.0 - index / 2,
        debt_to_equity=0.2,
        revenue_growth_pct=5.0 + index,
        operating_margin_pct=8.0 + index,
        one_year_return_pct=-40.0 + index,
        distance_from_52w_high_pct=-50.0 + index,
        average_daily_value_eur=150_000.0 + index,
        data_quality=DataQuality.PARTIAL,
    )
    return CompanyResearch(
        company=company,
        financials=financials,
        catalysts=("Contract announced",),
        risks=(),
        evidence=(Evidence("Fixture evidence", "https://example.test", "fixture"),),
        data_quality=DataQuality.PARTIAL,
    )


class ResearchProvider:
    def __init__(self, research: tuple[CompanyResearch, ...]) -> None:
        self.research = research

    def list_companies(self, countries, include_first_north):
        wanted = {country.upper() for country in countries}
        return [
            item.company
            for item in self.research
            if item.company.country in wanted
            and (
                include_first_north
                or item.company.segment != ListingSegment.FIRST_NORTH
            )
        ]

    def get_company_research(self, company: Company) -> CompanyResearch:
        return next(
            item
            for item in self.research
            if item.company.ticker == company.ticker
            and item.company.country == company.country
        )

    def get_research(self, ticker: str) -> CompanyResearch:
        return next(item for item in self.research if item.company.ticker == ticker)

    def source_checks(self):
        return [SourceCheck("fixture universe", "ok", f"{len(self.research)} rows")]


class DiagnosticProvider(ResearchProvider):
    def enrichment_stats(self):
        return {
            "eligible_universe_size": len(self.research),
            "refresh_budget": 3,
            "attempts": 3,
            "successful_enrichments": 2,
            "cached_companies": len(self.research) - 1,
            "fresh_companies": len(self.research) - 2,
            "stale_companies": 1,
            "missing_companies": 1,
            "candidate_keys": ("SE|C00",),
        }

    def evaluation_cache_status(self, company: Company):
        return {
            "enabled": True,
            "participated": company.ticker != "C00",
            "state": "fresh" if company.ticker != "C00" else "missing",
            "refreshed_this_run": False,
            "retrieved_at": (
                "2026-08-09T08:00:00Z" if company.ticker != "C00" else None
            ),
            "providers": ["fixture"] if company.ticker != "C00" else [],
        }


def make_result(
    count: int = 20,
    *,
    limit: int = 3,
    strategy: str = "long-term",
    provider_class=ResearchProvider,
):
    research = tuple(
        make_research(index, country="FI" if index % 5 == 0 else "SE")
        for index in range(count)
    )
    provider = provider_class(research)
    result = build_watchlist_result(
        provider,
        countries=("SE", "FI"),
        limit=limit,
        include_first_north=True,
        strategy=strategy,
    )
    return provider, result


def make_snapshot(
    *,
    count: int = 20,
    limit: int = 3,
    strategy: str = "long-term",
    decision_at: datetime = timestamp(10),
    provider_class=ResearchProvider,
):
    provider, result = make_result(
        count,
        limit=limit,
        strategy=strategy,
        provider_class=provider_class,
    )
    snapshot = build_evaluation_snapshot(
        result,
        provider=provider,
        strategy=strategy,
        decision_at=decision_at,
        report_date=date(2026, 8, 10),
        countries=("SE", "FI"),
        configuration={
            "provider": "fixture",
            "public_limit": limit,
            "refresh_budget": 0,
            "cache": {"enabled": False, "max_age_days": 45},
        },
        source_checks=provider.source_checks(),
    )
    return result, snapshot


def test_full_universe_is_persisted_while_public_report_stays_top_three():
    result, snapshot = make_snapshot(count=20, limit=3)

    assert len(snapshot.rows) == 20
    assert len(result.selected_items) == 3
    assert [row.rank for row in snapshot.rows] == list(range(1, 21))
    assert [row.ticker for row in snapshot.rows[:3]] == [
        item.research.company.ticker for item in result.selected_items
    ]
    assert [row.score["total"] for row in snapshot.rows[:3]] == [
        item.score.total for item in result.selected_items
    ]


def test_snapshot_preserves_final_post_enrichment_scores():
    research_items = [make_research(index) for index in range(4)]
    unenriched = research_items[-1]
    research_items[-1] = CompanyResearch(
        company=unenriched.company,
        financials=FinancialSnapshot(
            price=unenriched.financials.price,
            currency=unenriched.financials.currency,
            data_quality=DataQuality.THIN,
        ),
        catalysts=unenriched.catalysts,
        evidence=unenriched.evidence,
        data_quality=DataQuality.THIN,
    )
    research = tuple(research_items)
    base = ResearchProvider(research)
    enriched_company = research[-1].company

    class FundamentalsProvider:
        def get_fundamentals(self, company):
            if company.ticker != enriched_company.ticker:
                return None
            return FundamentalsSnapshot(
                symbol=f"{company.ticker}.ST",
                financials=FinancialSnapshot(
                    pe_ratio=5.0,
                    price_to_book=0.5,
                    net_cash_eur_m=50.0,
                    operating_margin_pct=25.0,
                    revenue_growth_pct=30.0,
                    data_quality=DataQuality.PARTIAL,
                ),
            )

        def source_check(self):
            return SourceCheck("fundamentals", "ok", "fixture enrichment")

    provider = EnrichedResearchProvider(base, FundamentalsProvider(), enrichment_limit=4)
    result = build_watchlist_result(
        provider,
        countries=("SE",),
        limit=2,
        include_first_north=True,
        strategy="long-term",
    )
    snapshot = build_evaluation_snapshot(
        result,
        provider=provider,
        strategy="long-term",
        decision_at=timestamp(10),
        report_date=date(2026, 8, 10),
        countries=("SE",),
        configuration={"provider": "fixture", "public_limit": 2},
        source_checks=provider.source_checks(),
    )

    ranked_item = next(
        item for item in result.ranked_items if item.research.company == enriched_company
    )
    row = next(row for row in snapshot.rows if row.ticker == enriched_company.ticker)
    assert ranked_item.research.financials.pe_ratio == 5.0
    assert row.score["total"] == ranked_item.score.total
    assert "pe_ratio" in row.model_inputs["available_financial_fields"]


def test_long_term_gate_order_and_actual_ranks_are_preserved():
    result, snapshot = make_snapshot(count=20, limit=3, strategy="long-term")
    gate_order = {
        "High-conviction candidate": 0,
        "Fundamental watchlist": 1,
        "Speculative monitor": 2,
        "Insufficient evidence": 3,
    }

    assert [row.rank for row in snapshot.rows] == [
        item.rank for item in result.ranked_items
    ]
    tiers = [gate_order[row.long_term["gate_tier"]] for row in snapshot.rows]
    assert tiers == sorted(tiers)


def test_trading_and_long_term_runs_are_strategy_specific():
    _, long_term = make_snapshot(count=5, limit=2, strategy="long-term")
    _, trading = make_snapshot(count=5, limit=2, strategy="trading")

    assert long_term.run_id != trading.run_id
    assert all(row.long_term is not None for row in long_term.rows)
    assert all(row.long_term is None for row in trading.rows)


def test_durable_rows_omit_raw_financial_values_and_observations():
    _, snapshot = make_snapshot(count=2, limit=1)
    row = snapshot.rows[0].as_payload()

    assert "financials" not in row
    assert "observations" not in row
    assert "normalized_value" not in serialize_evaluation_snapshot(snapshot)
    assert "available_financial_fields" in row["model_inputs"]
    assert "threshold_flags" in row["model_inputs"]


def test_stable_identity_and_decision_timestamp_round_trip(tmp_path):
    _, snapshot = make_snapshot(count=4, limit=2)
    path = save_evaluation_snapshot(tmp_path / "evaluations", snapshot)
    restored = load_evaluation_snapshot(path)

    assert restored == snapshot
    assert restored.decision_at == timestamp(10)
    assert restored.decision_at.tzinfo is not None
    assert restored.rows[0].company_id.startswith("isin:")
    assert restored.rows[0].isin is not None
    assert restored.scoring_model_version == SCORING_MODEL_VERSION
    assert serialize_evaluation_snapshot(restored) == path.read_text()


def test_source_exclusion_and_cache_coverage_diagnostics_are_persisted():
    _, snapshot = make_snapshot(
        count=5,
        limit=2,
        provider_class=DiagnosticProvider,
    )

    assert snapshot.diagnostics["source_universe_size"] == 5
    assert snapshot.diagnostics["source_country_counts"] == {"FI": 1, "SE": 4}
    assert snapshot.diagnostics["source_segment_counts"]
    assert snapshot.diagnostics["exclusion_counts"] == {}
    assert snapshot.diagnostics["enrichment"]["cached_companies"] == 4
    assert "candidate_keys" not in snapshot.diagnostics["enrichment"]
    assert snapshot.diagnostics["source_checks"][0]["status"] == "ok"
    assert any(row.cache["participated"] for row in snapshot.rows)


def test_filter_research_and_strategy_exclusions_are_counted():
    valid = make_research(1)
    wrong_sector = make_research(2)
    wrong_sector = CompanyResearch(
        company=Company(
            name=wrong_sector.company.name,
            ticker=wrong_sector.company.ticker,
            country=wrong_sector.company.country,
            exchange=wrong_sector.company.exchange,
            segment=wrong_sector.company.segment,
            isin=wrong_sector.company.isin,
            sector="Industrials",
        ),
        financials=wrong_sector.financials,
        data_quality=wrong_sector.data_quality,
    )
    no_setup = make_research(3)
    no_setup = CompanyResearch(
        company=no_setup.company,
        financials=no_setup.financials,
        evidence=no_setup.evidence,
        data_quality=no_setup.data_quality,
    )

    class ExclusionProvider(ResearchProvider):
        def get_company_research(self, company):
            if company.ticker == valid.company.ticker:
                raise RuntimeError("fixture research failure")
            return super().get_company_research(company)

    provider = ExclusionProvider((valid, wrong_sector, no_setup))
    result = build_watchlist_result(
        provider,
        countries=("SE",),
        limit=1,
        include_first_north=True,
        sector="Software",
        strategy="trading",
    )

    assert result.diagnostics.source_universe_size == 3
    assert result.diagnostics.filtered_universe_size == 2
    assert result.diagnostics.successfully_scored_universe_size == 0
    assert result.diagnostics.exclusion_counts == {
        "research_error": 1,
        "sector_mismatch": 1,
        "trading_setup_missing": 1,
    }


def test_same_run_is_idempotent_but_distinct_decision_is_not_collapsed(tmp_path):
    _, first = make_snapshot(count=4, limit=2, decision_at=timestamp(10, 8))
    _, second = make_snapshot(count=4, limit=2, decision_at=timestamp(10, 9))
    root = tmp_path / "evaluations"

    first_path = save_evaluation_snapshot(root, first)
    rerun_path = save_evaluation_snapshot(root, first)
    second_path = save_evaluation_snapshot(root, second)

    assert rerun_path == first_path
    assert second_path != first_path
    assert first.run_id != second.run_id
    assert len(tuple(root.rglob("*.jsonl"))) == 2


def test_future_cache_observation_cannot_contaminate_earlier_evaluation(tmp_path):
    base_research = make_research(1)
    company = base_research.company
    cache = FileFundamentalsCache(tmp_path / "fundamentals.json")
    cache.store(
        company,
        FundamentalsSnapshot(
            symbol=f"{company.ticker}.ST",
            financials=FinancialSnapshot(
                pe_ratio=3.0,
                data_quality=DataQuality.PARTIAL,
                observations=(
                    FinancialObservation(
                        canonical_field="pe_ratio",
                        normalized_value=3.0,
                        provider="fixture-fundamentals",
                        source_metric="trailing_pe",
                        period_type=ReportingPeriodType.TTM,
                        confidence=ObservationConfidence.MEDIUM,
                    ),
                ),
            ),
            evidence=Evidence(
                "Fixture fundamentals", "https://example.test", "fixture-fundamentals"
            ),
        ),
        retrieved_at=timestamp(20),
    )
    provider = EnrichedResearchProvider(
        ResearchProvider((base_research,)),
        fundamentals_provider=object(),
        enrichment_limit=0,
        cache=cache,
        known_at=timestamp(10),
    )
    result = build_watchlist_result(
        provider,
        countries=("SE",),
        limit=1,
        include_first_north=True,
        strategy="long-term",
    )
    snapshot = build_evaluation_snapshot(
        result,
        provider=provider,
        strategy="long-term",
        decision_at=timestamp(10, 9),
        report_date=date(2026, 8, 10),
        countries=("SE",),
        configuration={"provider": "fixture", "public_limit": 1},
        source_checks=provider.source_checks(),
    )

    row = snapshot.rows[0]
    assert row.cache["state"] == "missing"
    assert row.cache["participated"] is False
    assert row.model_inputs["threshold_flags"]["pe_at_or_below_12"] is True
    assert result.ranked_items[0].research.financials.pe_ratio != 3.0


def test_snapshot_rejects_cache_status_from_after_decision_cutoff():
    class FutureStatusProvider(ResearchProvider):
        def evaluation_cache_status(self, company):
            return {
                "enabled": True,
                "participated": True,
                "state": "fresh",
                "refreshed_this_run": False,
                "retrieved_at": "2026-08-11T08:00:00Z",
                "providers": ["fixture"],
            }

    provider, result = make_result(
        count=2,
        limit=1,
        provider_class=FutureStatusProvider,
    )

    with pytest.raises(ValueError, match="contains future cache data"):
        build_evaluation_snapshot(
            result,
            provider=provider,
            strategy="long-term",
            decision_at=timestamp(10),
            report_date=date(2026, 8, 10),
            countries=("SE", "FI"),
            configuration={"provider": "fixture"},
            source_checks=provider.source_checks(),
        )


def test_naive_decision_timestamp_is_rejected():
    provider, result = make_result(count=2, limit=1)

    with pytest.raises(ValueError, match="timezone-aware"):
        build_evaluation_snapshot(
            result,
            provider=provider,
            strategy="long-term",
            decision_at=datetime(2026, 8, 10, 8),
            report_date=date(2026, 8, 10),
            countries=("SE", "FI"),
            configuration={"provider": "fixture"},
            source_checks=provider.source_checks(),
        )


def test_unsupported_and_corrupt_evaluation_schemas_fail_clearly(tmp_path):
    unsupported = tmp_path / "unsupported.jsonl"
    unsupported.write_text(
        json.dumps({"record_type": "run", "schema_version": 99}) + "\n"
    )
    corrupt = tmp_path / "corrupt.jsonl"
    corrupt.write_text('{"record_type":"run"\n')

    with pytest.raises(ValueError, match="unsupported evaluation schema: 99"):
        load_evaluation_snapshot(unsupported)
    with pytest.raises(ValueError, match="malformed evaluation snapshot"):
        load_evaluation_snapshot(corrupt)


def test_schema_version_is_explicit():
    _, snapshot = make_snapshot(count=2, limit=1)

    assert EVALUATION_SCHEMA_VERSION == 1
    assert snapshot.header_payload()["schema_version"] == 1
