import json

import pytest

from investmentagent.fundamentals import FundamentalsSnapshot
from investmentagent.global_ai import (
    GlobalAIReport,
    GlobalAIReportItem,
    GlobalAIScoreBreakdown,
    GlobalAIUniverseEntry,
    build_global_ai_top5,
    load_global_ai_universe,
    score_global_ai_candidate,
)
from investmentagent.models import (
    Company,
    CompanyResearch,
    DataQuality,
    Evidence,
    FinancialSnapshot,
    ListingSegment,
    SourceCheck,
)
from investmentagent.renderers import (
    render_global_ai_report_json,
    render_global_ai_report_markdown,
)


def valid_universe_dict(**overrides):
    values = {
        "name": "NVIDIA",
        "ticker": "NVDA",
        "provider_symbol": "NVDA",
        "country": "US",
        "exchange": "NASDAQ",
        "currency": "USD",
        "sector": "Semiconductors",
        "ai_category": "AI compute semiconductors",
        "ai_thesis": (
            "Dominant accelerator platform for model training, inference, "
            "networking, and AI software ecosystems."
        ),
    }
    values.update(overrides)
    return values


def valid_universe_entry(**overrides) -> GlobalAIUniverseEntry:
    return GlobalAIUniverseEntry(**valid_universe_dict(**overrides))


def make_research(
    entry: GlobalAIUniverseEntry,
    *,
    pe_ratio: float | None = None,
    price_to_book: float | None = None,
    ev_to_ebit: float | None = None,
    revenue_growth_pct: float | None = None,
    operating_margin_pct: float | None = None,
    debt_to_equity: float | None = None,
    data_quality: DataQuality = DataQuality.PARTIAL,
) -> CompanyResearch:
    company = Company(
        name=entry.name,
        ticker=entry.ticker,
        country=entry.country,
        exchange=entry.exchange,
        segment=ListingSegment.OTHER_PUBLIC,
        sector=entry.sector,
        currency=entry.currency,
        business_description=entry.ai_thesis,
    )
    financials = FinancialSnapshot(
        pe_ratio=pe_ratio,
        price_to_book=price_to_book,
        ev_to_ebit=ev_to_ebit,
        revenue_growth_pct=revenue_growth_pct,
        operating_margin_pct=operating_margin_pct,
        debt_to_equity=debt_to_equity,
        data_quality=data_quality,
    )
    return CompanyResearch(
        company=company,
        financials=financials,
        evidence=(
            Evidence(
                label=f"Finimpulse fundamentals lookup ({entry.provider_symbol})",
                url="https://developers.finimpulse.com/v1/search/",
                source="finimpulse",
            ),
        ),
        data_quality=data_quality,
    )


def snapshot_for(
    *,
    symbol: str,
    pe_ratio: float | None = None,
    price_to_book: float | None = None,
    ev_to_ebit: float | None = None,
    revenue_growth_pct: float | None = None,
    operating_margin_pct: float | None = None,
    debt_to_equity: float | None = None,
    data_quality: DataQuality = DataQuality.PARTIAL,
) -> FundamentalsSnapshot:
    return FundamentalsSnapshot(
        symbol=symbol,
        market_cap_eur_m=10_000,
        business_description=f"{symbol} is an AI-exposed public company.",
        financials=FinancialSnapshot(
            pe_ratio=pe_ratio,
            price_to_book=price_to_book,
            ev_to_ebit=ev_to_ebit,
            revenue_growth_pct=revenue_growth_pct,
            operating_margin_pct=operating_margin_pct,
            debt_to_equity=debt_to_equity,
            data_quality=data_quality,
        ),
        evidence=Evidence(
            label=f"Finimpulse fundamentals lookup ({symbol})",
            url="https://developers.finimpulse.com/v1/search/",
            source="finimpulse",
        ),
    )


class StaticFundamentalsProvider:
    def __init__(self, snapshots: dict[str, FundamentalsSnapshot | None]):
        self.snapshots = snapshots
        self.requests: list[tuple[str, str | None]] = []

    def get_fundamentals_for_symbol(
        self, symbol: str, fallback_currency: str | None = None
    ):
        self.requests.append((symbol, fallback_currency))
        return self.snapshots.get(symbol)

    def source_check(self):
        return SourceCheck("finimpulse fundamentals", "ok", "fixture lookups parsed")


def test_load_global_ai_universe_reads_packaged_entries():
    entries = load_global_ai_universe()

    assert len(entries) >= 10
    assert entries[0].ticker == "NVDA"
    assert entries[0].provider_symbol == "NVDA"
    assert entries[0].ai_category
    assert entries[0].ai_thesis


def test_load_global_ai_universe_rejects_missing_required_field(tmp_path):
    path = tmp_path / "bad.json"
    path.write_text(json.dumps([{"name": "Broken"}]), encoding="utf-8")

    with pytest.raises(ValueError, match="provider_symbol"):
        load_global_ai_universe(path)


def test_load_global_ai_universe_rejects_duplicate_symbols(tmp_path):
    base = valid_universe_dict()
    path = tmp_path / "bad.json"
    path.write_text(json.dumps([base, {**base, "name": "Copy"}]), encoding="utf-8")

    with pytest.raises(ValueError, match="duplicate ticker"):
        load_global_ai_universe(path)


def test_score_global_ai_candidate_rewards_quality_growth_and_reasonable_valuation():
    entry = valid_universe_entry(ai_category="Cloud AI platform")
    research = make_research(
        entry,
        pe_ratio=22,
        price_to_book=4.0,
        ev_to_ebit=18,
        revenue_growth_pct=18,
        operating_margin_pct=32,
        debt_to_equity=0.4,
        data_quality=DataQuality.PARTIAL,
    )

    score = score_global_ai_candidate(research, entry)

    assert score.total > 60
    assert score.valuation > 0
    assert score.quality >= 20
    assert score.growth >= 12
    assert "profitable AI-exposed business" in score.reasons


def test_score_global_ai_candidate_penalizes_missing_valuation():
    entry = valid_universe_entry()
    research = make_research(
        entry,
        revenue_growth_pct=18,
        operating_margin_pct=24,
        data_quality=DataQuality.THIN,
    )

    score = score_global_ai_candidate(research, entry)

    assert score.data_quality_penalty >= 14
    assert any("missing valuation" in warning for warning in score.warnings)


def test_build_global_ai_top5_orders_candidates_by_total_score():
    provider = StaticFundamentalsProvider(
        {
            "CHEAP": snapshot_for(
                symbol="CHEAP",
                pe_ratio=18,
                operating_margin_pct=30,
                revenue_growth_pct=15,
            ),
            "EXPENSIVE": snapshot_for(
                symbol="EXPENSIVE",
                pe_ratio=95,
                operating_margin_pct=20,
                revenue_growth_pct=35,
            ),
            "THIN": snapshot_for(symbol="THIN", data_quality=DataQuality.THIN),
        }
    )
    entries = (
        valid_universe_entry(
            name="Cheap Quality", ticker="CHEAP", provider_symbol="CHEAP"
        ),
        valid_universe_entry(
            name="Expensive Growth", ticker="EXPENSIVE", provider_symbol="EXPENSIVE"
        ),
        valid_universe_entry(name="Thin Data", ticker="THIN", provider_symbol="THIN"),
    )

    report = build_global_ai_top5(
        provider,
        entries=entries,
        limit=2,
        generated_at="2026-06-08 08:00 EEST",
    )

    assert [item.entry.ticker for item in report.items] == ["CHEAP", "EXPENSIVE"]
    assert report.metadata["report_type"] == "global-ai"
    assert report.metadata["limit"] == 2
    assert report.source_checks[0].name == "global ai universe"


def test_build_global_ai_top5_includes_fallback_valuation():
    entry = valid_universe_entry(
        name="Fallback AI",
        ticker="FALL",
        provider_symbol="FALL",
    )
    provider = StaticFundamentalsProvider(
        {
            "FALL": snapshot_for(
                symbol="FALL",
                pe_ratio=24,
                price_to_book=5,
                operating_margin_pct=30,
                revenue_growth_pct=18,
            )
        }
    )

    report = build_global_ai_top5(
        provider,
        entries=(entry,),
        limit=1,
        generated_at="2026-06-19 08:00 EEST",
    )

    assert report.metadata["fundamentals"] == "finimpulse+yahoo-fallback"
    assert report.items[0].valuation_summary == "P/E 24; P/B 5"
    assert "missing valuation support" not in report.items[0].risk_flags


def sample_global_ai_report() -> GlobalAIReport:
    entry = valid_universe_entry()
    research = make_research(
        entry,
        pe_ratio=31.2,
        price_to_book=9.5,
        ev_to_ebit=28,
        revenue_growth_pct=65,
        operating_margin_pct=54,
        debt_to_equity=0.2,
    )
    score = GlobalAIScoreBreakdown(
        valuation=17,
        quality=30,
        growth=20,
        ai_relevance=10,
        risk_penalty=0,
        data_quality_penalty=4,
        total=73,
        reasons=("profitable AI-exposed business",),
        warnings=("valuation risk: high P/B",),
    )
    item = GlobalAIReportItem(
        rank=1,
        entry=entry,
        research=research,
        score=score,
        valuation_summary="P/E 31.2; P/B 9.5; EV/EBIT 28.0",
        quality_summary="Operating margin 54.0%; debt/equity 0.2",
        growth_summary="Revenue growth 65.0%",
        risk_flags=("valuation risk: high P/B",),
    )
    return GlobalAIReport(
        items=(item,),
        metadata={
            "generated_at": "2026-06-08 08:00 EEST",
            "report_type": "global-ai",
            "limit": 5,
            "universe_size": 1,
        },
        source_checks=(
            SourceCheck("global ai universe", "ok", "1 curated global AI companies loaded"),
        ),
    )


def test_render_global_ai_report_markdown_includes_expected_sections():
    report = sample_global_ai_report()

    markdown = render_global_ai_report_markdown(report)

    assert "# InvestmentAgent Global AI Top 5" in markdown
    assert "Research triage only. Not financial advice." in markdown
    assert "## Source Checks" in markdown
    assert "## Top 5 Global AI Candidates" in markdown
    assert "AI compute semiconductors" in markdown
    assert "Valuation:" in markdown
    assert "Quality:" in markdown
    assert "Growth:" in markdown


def test_render_global_ai_report_json_contains_ai_fields():
    report = sample_global_ai_report()

    payload = json.loads(render_global_ai_report_json(report))

    assert payload["metadata"]["report_type"] == "global-ai"
    assert payload["items"][0]["ai_category"]
    assert payload["items"][0]["ai_thesis"]
    assert payload["items"][0]["score"]["total"] == report.items[0].score.total
