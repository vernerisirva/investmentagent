import json
from datetime import datetime, timezone

import pytest

from investmentagent.fundamentals_cache import (
    CacheFreshness,
    FileFundamentalsCache,
    FundamentalsFreshnessPolicy,
    company_cache_identity,
)
from investmentagent.models import (
    Company,
    DataQuality,
    Evidence,
    FinancialObservation,
    FinancialSnapshot,
    FundamentalsSnapshot,
    ListingSegment,
    ObservationConfidence,
    ReportingPeriodType,
)


def timestamp(day: int, hour: int = 8) -> datetime:
    return datetime(2026, 8, day, hour, tzinfo=timezone.utc)


def company(ticker: str = "AAA", isin: str = "SE0000000001") -> Company:
    return Company(
        name=f"{ticker} AB",
        ticker=ticker,
        country="SE",
        exchange="Nasdaq Stockholm",
        segment=ListingSegment.MAIN_MARKET,
        isin=isin,
        currency="SEK",
    )


def snapshot(pe_ratio: float = 12.4) -> FundamentalsSnapshot:
    return FundamentalsSnapshot(
        symbol="AAA.ST",
        market_cap_eur_m=120.5,
        business_description="AAA makes industrial software.",
        ir_url="https://example.test/investors",
        financials=FinancialSnapshot(
            pe_ratio=pe_ratio,
            revenue_eur_m=80.0,
            data_quality=DataQuality.PARTIAL,
            observations=(
                FinancialObservation(
                    canonical_field="pe_ratio",
                    normalized_value=pe_ratio,
                    provider="eodhd",
                    source_metric="Valuation.TrailingPE",
                    as_of="2026-08-01",
                    reporting_period="trailing_12_months",
                    period_type=ReportingPeriodType.TTM,
                    original_currency=None,
                    normalized_currency=None,
                    is_derived=False,
                    derivation=None,
                    confidence=ObservationConfidence.MEDIUM,
                ),
                FinancialObservation(
                    canonical_field="revenue_eur_m",
                    normalized_value=80.0,
                    provider="finimpulse",
                    source_metric="total_revenue",
                    as_of="2026-08-02T06:00:00Z",
                    original_currency="SEK",
                    normalized_currency="EUR",
                    is_derived=True,
                    derivation="static FX assumption: 1 SEK = 0.1 EUR",
                    confidence=ObservationConfidence.LOW,
                ),
            ),
        ),
        evidence=Evidence(
            label="EODHD fundamentals lookup (AAA.ST)",
            url="https://example.test/fundamentals",
            source="eodhd",
            timestamp="2026-08-03T07:00:00Z",
        ),
    )


def test_missing_and_empty_cache_are_valid(tmp_path):
    path = tmp_path / "cache.json"

    assert FileFundamentalsCache(path).records == ()

    path.write_text("")
    assert FileFundamentalsCache(path).records == ()


def test_store_reload_preserves_snapshot_and_observation_metadata(tmp_path):
    path = tmp_path / "cache.json"
    cache = FileFundamentalsCache(path)

    stored = cache.store(company(), snapshot(), retrieved_at=timestamp(10))
    restored = FileFundamentalsCache(path).get_latest(
        company(), known_at=timestamp(11)
    )

    assert restored == stored
    assert restored.snapshot.financials.pe_ratio == 12.4
    observation = restored.snapshot.financials.observation_for("revenue_eur_m")
    assert observation is not None
    assert observation.provider == "finimpulse"
    assert observation.source_metric == "total_revenue"
    assert observation.as_of == "2026-08-02T06:00:00Z"
    assert observation.original_currency == "SEK"
    assert observation.normalized_currency == "EUR"
    assert observation.is_derived is True
    assert observation.confidence == ObservationConfidence.LOW
    assert restored.snapshot.evidence.timestamp == "2026-08-03T07:00:00Z"
    payload = json.loads(path.read_text())
    assert payload["schema_version"] == 1
    assert payload["records"][0]["schema_version"] == 1


def test_multiple_versions_are_immutable_and_cutoff_selects_latest_eligible(tmp_path):
    cache = FileFundamentalsCache(tmp_path / "cache.json")
    first = cache.store(company(), snapshot(12.0), retrieved_at=timestamp(10))
    second = cache.store(company(), snapshot(9.0), retrieved_at=timestamp(20))

    assert len(cache.records_for(company())) == 2
    assert cache.get_latest(company(), known_at=timestamp(15)) == first
    assert cache.get_latest(company(), known_at=timestamp(21)) == second
    assert first.snapshot.financials.pe_ratio == 12.0
    assert second.snapshot.financials.pe_ratio == 9.0


def test_future_version_is_never_returned_for_earlier_cutoff(tmp_path):
    cache = FileFundamentalsCache(tmp_path / "cache.json")
    cache.store(company(), snapshot(8.0), retrieved_at=timestamp(20))

    assert cache.get_latest(company(), known_at=timestamp(19)) is None


def test_same_day_identical_rerun_is_idempotent(tmp_path):
    cache = FileFundamentalsCache(tmp_path / "cache.json")
    first = cache.store(company(), snapshot(), retrieved_at=timestamp(10, 8))
    rerun = cache.store(company(), snapshot(), retrieved_at=timestamp(10, 12))

    assert rerun.record_id == first.record_id
    assert len(cache.records) == 1


def test_same_day_changed_content_creates_a_real_new_version(tmp_path):
    cache = FileFundamentalsCache(tmp_path / "cache.json")
    cache.store(company(), snapshot(12.0), retrieved_at=timestamp(10, 8))
    cache.store(company(), snapshot(11.0), retrieved_at=timestamp(10, 12))

    assert len(cache.records) == 2


def test_snapshot_without_provider_provenance_is_rejected(tmp_path):
    cache = FileFundamentalsCache(tmp_path / "cache.json")
    unprovenanced = FundamentalsSnapshot(
        symbol="AAA.ST",
        financials=FinancialSnapshot(
            pe_ratio=12.0,
            data_quality=DataQuality.PARTIAL,
        ),
    )

    with pytest.raises(ValueError, match="explicit provider provenance"):
        cache.store(company(), unprovenanced, retrieved_at=timestamp(10))

    assert cache.records == ()


def test_isin_identity_survives_ticker_change(tmp_path):
    old_listing = company("OLD")
    new_listing = company("NEW")
    cache = FileFundamentalsCache(tmp_path / "cache.json")
    stored = cache.store(old_listing, snapshot(), retrieved_at=timestamp(10))

    assert company_cache_identity(old_listing) == company_cache_identity(new_listing)
    assert cache.get_latest(new_listing, known_at=timestamp(11)) == stored


def test_freshness_uses_retrieval_time_not_source_as_of(tmp_path):
    cache = FileFundamentalsCache(tmp_path / "cache.json")
    record = cache.store(company(), snapshot(), retrieved_at=timestamp(10))
    policy = FundamentalsFreshnessPolicy(max_age_days=5)

    assert policy.classify(record, known_at=timestamp(15)) == CacheFreshness.FRESH
    assert policy.classify(record, known_at=timestamp(16)) == CacheFreshness.STALE


def test_coverage_reports_country_fresh_stale_and_missing_counts(tmp_path):
    cache = FileFundamentalsCache(tmp_path / "cache.json")
    cache.store(company("AAA", "SE0000000001"), snapshot(), retrieved_at=timestamp(10))
    cache.store(company("BBB", "SE0000000002"), snapshot(), retrieved_at=timestamp(1))
    companies = (
        company("AAA", "SE0000000001"),
        company("BBB", "SE0000000002"),
        company("CCC", "SE0000000003"),
    )

    coverage = cache.coverage(
        companies,
        known_at=timestamp(20),
        freshness_policy=FundamentalsFreshnessPolicy(max_age_days=10),
    )

    assert coverage.cached_companies == 2
    assert coverage.fresh_companies == 1
    assert coverage.stale_companies == 1
    assert coverage.missing_companies == 1
    assert coverage.country_coverage["SE"] == {
        "eligible": 3,
        "cached": 2,
        "fresh": 1,
        "stale": 1,
        "missing": 1,
    }


def test_unsupported_schema_fails_clearly(tmp_path):
    path = tmp_path / "cache.json"
    path.write_text(json.dumps({"schema_version": 99, "records": []}))

    with pytest.raises(ValueError, match="unsupported fundamentals cache schema: 99"):
        FileFundamentalsCache(path)


def test_malformed_cache_fails_and_is_not_overwritten(tmp_path):
    path = tmp_path / "cache.json"
    path.write_text('{"schema_version": 1, "records": [')

    with pytest.raises(ValueError, match="malformed fundamentals cache"):
        FileFundamentalsCache(path)

    assert path.read_text() == '{"schema_version": 1, "records": ['


@pytest.mark.parametrize("invalid", [float("nan"), float("inf"), float("-inf")])
def test_non_finite_values_cannot_enter_through_deserialization(tmp_path, invalid):
    path = tmp_path / "cache.json"
    cache = FileFundamentalsCache(path)
    cache.store(company(), snapshot(), retrieved_at=timestamp(10))
    payload = json.loads(path.read_text())
    payload["records"][0]["snapshot"]["financials"]["pe_ratio"] = invalid
    path.write_text(json.dumps(payload))

    with pytest.raises(ValueError, match="non-finite cached numeric value"):
        FileFundamentalsCache(path)
