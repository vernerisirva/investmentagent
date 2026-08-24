from __future__ import annotations

import json
import math
import re
import ssl
from collections.abc import Callable
from dataclasses import replace
from datetime import date, datetime, timezone
from typing import Any
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

import certifi

from investmentagent.fundamentals_cache import (
    CacheCoverage,
    CacheFreshness,
    CachedFundamentalsRecord,
    FundamentalsCache,
    FundamentalsFreshnessPolicy,
    company_cache_identity,
)
from investmentagent.models import (
    Company,
    CompanyResearch,
    DataQuality,
    Evidence,
    FinancialObservation,
    FinancialSnapshot,
    FundamentalsSnapshot,
    ObservationConfidence,
    ReportingPeriodType,
    SourceCheck,
)


YAHOO_QUOTE_SUMMARY_URL = (
    "https://query1.finance.yahoo.com/v10/finance/quoteSummary/{symbol}"
    "?modules=price,summaryDetail,financialData"
)
YAHOO_FETCH_TIMEOUT_SECONDS = 3
FINNHUB_PROFILE_URL = (
    "https://finnhub.io/api/v1/stock/profile2?symbol={symbol}&token={token}"
)
FINNHUB_METRIC_URL = (
    "https://finnhub.io/api/v1/stock/metric?symbol={symbol}&metric=all&token={token}"
)
FINNHUB_PROFILE_DOC_URL = "https://finnhub.io/docs/api/company-profile2"
FINNHUB_FETCH_TIMEOUT_SECONDS = 3
FINIMPULSE_STATISTICS_URL = "https://api.finimpulse.com/v1/statistics/general"
FINIMPULSE_STATISTICS_DOC_URL = (
    "https://developers.finimpulse.com/v1/statistics/general/"
)
FINIMPULSE_PROFILE_URL = "https://api.finimpulse.com/v1/profile"
FINIMPULSE_PROFILE_DOC_URL = "https://developers.finimpulse.com/v1/profile/"
FINIMPULSE_FETCH_TIMEOUT_SECONDS = 3
EODHD_FUNDAMENTALS_URL = "https://eodhd.com/api/v1.1/fundamentals/{symbol}"
EODHD_FUNDAMENTALS_DOC_URL = (
    "https://eodhd.com/financial-apis/stock-etfs-fundamental-data-feeds"
)
EODHD_FETCH_TIMEOUT_SECONDS = 3
_STATIC_EUR_RATES = {"EUR": 1.0, "SEK": 0.1, "USD": 0.92}
FINIMPULSE_PE_KEYS = ("trailing_pe", "forward_pe")
FINIMPULSE_PRICE_TO_BOOK_KEYS = ("price_to_book",)
DIRECT_VALUATION_FIELDS = ("pe_ratio", "price_to_book", "ev_to_ebit")
PROXY_VALUATION_FIELDS = ("revenue_eur_m", "book_value_eur_m", "net_income_eur_m")

# The public top-10 reports evaluate a 3x preliminary pool. Thirty companies is
# materially broader than the output while keeping daily provider work bounded.
DEFAULT_WATCHLIST_ENRICHMENT_LIMIT = 30

# Fundamentals can legitimately be annual and reported with delay. This broad
# bound only prevents clearly old observations from upgrading aggregate quality;
# it does not reject or hide the value.
MAX_QUALITY_AS_OF_AGE_DAYS = 730


class YahooFundamentalsProvider:
    def __init__(self, fetcher: Callable[[str], str] | None = None) -> None:
        self._fetcher = fetcher or _fetch_url
        self.attempted_lookups = 0
        self.successful_lookups = 0
        self.valuation_support_lookups = 0
        self.direct_valuation_lookups = 0
        self.proxy_input_lookups = 0
        self.last_error: str | None = None

    def get_fundamentals(self, company: Company) -> FundamentalsSnapshot | None:
        for symbol in yahoo_symbol_candidates(company):
            snapshot = self._get_fundamentals_for_symbol(
                symbol, fallback_currency=company.currency
            )
            if snapshot is not None:
                return snapshot
        return None

    def get_fundamentals_for_symbol(
        self, symbol: str, fallback_currency: str | None = None
    ) -> FundamentalsSnapshot | None:
        normalized_symbol = symbol.strip().upper()
        if not normalized_symbol:
            raise ValueError("symbol is required")
        return self._get_fundamentals_for_symbol(
            normalized_symbol, fallback_currency=fallback_currency
        )

    def _get_fundamentals_for_symbol(
        self, symbol: str, fallback_currency: str | None
    ) -> FundamentalsSnapshot | None:
        self.attempted_lookups += 1
        url = _yahoo_quote_summary_url(symbol)
        try:
            snapshot = _parse_fundamentals_payload(
                payload=self._fetcher(url),
                symbol=symbol,
                url=url,
                fallback_currency=fallback_currency,
            )
        except Exception as exc:
            self.last_error = str(exc)
            return None
        if snapshot is None:
            return None
        self._record_valuation_coverage(snapshot)
        self.successful_lookups += 1
        self.last_error = None
        return snapshot

    def source_check(self) -> SourceCheck:
        if self.attempted_lookups == 0:
            return SourceCheck(
                name="free fundamentals",
                status="warning",
                detail="No lookups attempted for Yahoo-style fundamentals",
            )

        ratio = (
            f"{self.successful_lookups}/{self.attempted_lookups} "
            "Yahoo-style lookups parsed"
        )
        if self.successful_lookups == self.attempted_lookups:
            return SourceCheck(
                name="free fundamentals",
                status="ok",
                detail=self._source_detail(ratio),
            )

        if self.successful_lookups == 0:
            detail = f"No successful Yahoo-style fundamentals lookups ({ratio})"
            if self.last_error:
                detail = f"{detail}: {self.last_error}"
            return SourceCheck(
                name="free fundamentals",
                status="warning",
                detail=detail,
            )

        return SourceCheck(
            name="free fundamentals",
            status="warning",
            detail=self._source_detail(ratio),
        )

    def _record_valuation_coverage(self, snapshot: FundamentalsSnapshot) -> None:
        financials = snapshot.financials
        if has_valuation_support(financials):
            self.valuation_support_lookups += 1
        if has_any_financial_field(financials, DIRECT_VALUATION_FIELDS):
            self.direct_valuation_lookups += 1
        if has_any_financial_field(financials, PROXY_VALUATION_FIELDS):
            self.proxy_input_lookups += 1

    def _source_detail(self, ratio: str) -> str:
        return (
            f"{ratio}; valuation support {self.valuation_support_lookups}/"
            f"{self.successful_lookups}; direct valuation "
            f"{self.direct_valuation_lookups}/{self.successful_lookups}; "
            f"proxy inputs {self.proxy_input_lookups}/{self.successful_lookups}; "
            f"missing valuation support "
            f"{self.successful_lookups - self.valuation_support_lookups}/"
            f"{self.successful_lookups}"
        )


class FinnhubFundamentalsProvider:
    def __init__(
        self, api_key: str, fetcher: Callable[[str], str] | None = None
    ) -> None:
        self.api_key = api_key
        self._fetcher = fetcher or _fetch_finnhub_url
        self.attempted_lookups = 0
        self.successful_lookups = 0
        self.last_error: str | None = None

    def get_fundamentals(self, company: Company) -> FundamentalsSnapshot | None:
        for symbol in finnhub_symbol_candidates(company):
            self.attempted_lookups += 1
            try:
                profile = json.loads(
                    self._fetcher(_finnhub_profile_url(symbol, self.api_key))
                )
                metrics = json.loads(
                    self._fetcher(_finnhub_metric_url(symbol, self.api_key))
                )
                snapshot = _parse_finnhub_payload(
                    payload={"profile": profile, "metrics": metrics},
                    symbol=symbol,
                    fallback_currency=company.currency,
                )
            except Exception as exc:
                self.last_error = _token_safe_error(exc, self.api_key)
                continue
            if snapshot is not None:
                self.successful_lookups += 1
                self.last_error = None
                return snapshot
        return None

    def source_check(self) -> SourceCheck:
        if self.attempted_lookups == 0:
            return SourceCheck(
                name="finnhub fundamentals",
                status="warning",
                detail="No lookups attempted for Finnhub fundamentals",
            )

        ratio = (
            f"{self.successful_lookups}/{self.attempted_lookups} "
            "Finnhub lookups parsed"
        )
        if self.successful_lookups == self.attempted_lookups:
            return SourceCheck(name="finnhub fundamentals", status="ok", detail=ratio)

        if self.successful_lookups == 0:
            detail = f"No successful Finnhub fundamentals lookups ({ratio})"
            if self.last_error:
                detail = f"{detail}: {self.last_error}"
            return SourceCheck(
                name="finnhub fundamentals",
                status="warning",
                detail=detail,
            )

        return SourceCheck(name="finnhub fundamentals", status="warning", detail=ratio)


class EodhdFundamentalsProvider:
    def __init__(
        self, api_key: str | None, fetcher: Callable[[str], str] | None = None
    ) -> None:
        self.api_key = api_key.strip() if api_key is not None else None
        self._fetcher = fetcher or _fetch_eodhd_url
        self.attempted_lookups = 0
        self.successful_lookups = 0
        self.valuation_support_lookups = 0
        self.direct_valuation_lookups = 0
        self.proxy_input_lookups = 0
        self.last_error: str | None = None

    def get_fundamentals(self, company: Company) -> FundamentalsSnapshot | None:
        for symbol in eodhd_symbol_candidates(company):
            snapshot = self._get_fundamentals_for_symbol(
                symbol, fallback_currency=company.currency
            )
            if snapshot is not None:
                return snapshot
        return None

    def get_fundamentals_for_symbol(
        self, symbol: str, fallback_currency: str | None = None
    ) -> FundamentalsSnapshot | None:
        normalized_symbol = symbol.strip().upper()
        if not normalized_symbol:
            raise ValueError("symbol is required")
        return self._get_fundamentals_for_symbol(
            normalized_symbol, fallback_currency=fallback_currency
        )

    def _get_fundamentals_for_symbol(
        self, symbol: str, fallback_currency: str | None
    ) -> FundamentalsSnapshot | None:
        if not self.api_key:
            self.last_error = "EODHD_API_KEY is not configured"
            return None
        self.attempted_lookups += 1
        url = _eodhd_fundamentals_url(symbol, self.api_key)
        try:
            snapshot = _parse_eodhd_fundamentals_payload(
                payload=self._fetcher(url),
                symbol=symbol,
                fallback_currency=fallback_currency,
            )
        except Exception as exc:
            self.last_error = _token_safe_error(exc, self.api_key)
            return None
        if snapshot is None:
            return None
        self._record_valuation_coverage(snapshot)
        self.successful_lookups += 1
        self.last_error = None
        return snapshot

    def source_check(self) -> SourceCheck:
        if not self.api_key:
            return SourceCheck(
                name="eodhd fundamentals",
                status="warning",
                detail="EODHD_API_KEY is not configured",
            )
        if self.attempted_lookups == 0:
            return SourceCheck(
                name="eodhd fundamentals",
                status="warning",
                detail="No lookups attempted for EODHD fundamentals",
            )

        ratio = (
            f"{self.successful_lookups}/{self.attempted_lookups} "
            "EODHD lookups parsed"
        )
        if self.successful_lookups == self.attempted_lookups:
            return SourceCheck(
                name="eodhd fundamentals",
                status="ok",
                detail=self._source_detail(ratio),
            )
        if self.successful_lookups == 0:
            detail = f"No successful EODHD fundamentals lookups ({ratio})"
            if self.last_error:
                detail = f"{detail}: {self.last_error}"
            return SourceCheck(
                name="eodhd fundamentals",
                status="warning",
                detail=detail,
            )
        return SourceCheck(
            name="eodhd fundamentals",
            status="warning",
            detail=self._source_detail(ratio),
        )

    def _record_valuation_coverage(self, snapshot: FundamentalsSnapshot) -> None:
        financials = snapshot.financials
        if has_valuation_support(financials):
            self.valuation_support_lookups += 1
        if has_any_financial_field(financials, DIRECT_VALUATION_FIELDS):
            self.direct_valuation_lookups += 1
        if has_any_financial_field(financials, PROXY_VALUATION_FIELDS):
            self.proxy_input_lookups += 1

    def _source_detail(self, ratio: str) -> str:
        return (
            f"{ratio}; valuation support {self.valuation_support_lookups}/"
            f"{self.successful_lookups}; direct valuation "
            f"{self.direct_valuation_lookups}/{self.successful_lookups}; "
            f"proxy inputs {self.proxy_input_lookups}/{self.successful_lookups}; "
            f"missing valuation support "
            f"{self.successful_lookups - self.valuation_support_lookups}/"
            f"{self.successful_lookups}"
        )


class FinimpulseFundamentalsProvider:
    def __init__(
        self,
        api_key: str,
        fetcher: Callable[[str, str, dict[str, str]], str] | None = None,
    ) -> None:
        self.api_key = api_key
        self._fetcher = fetcher or _post_json
        self.attempted_lookups = 0
        self.successful_lookups = 0
        self.valuation_support_lookups = 0
        self.direct_valuation_lookups = 0
        self.proxy_input_lookups = 0
        self.last_error: str | None = None

    def get_fundamentals(self, company: Company) -> FundamentalsSnapshot | None:
        for symbol in finimpulse_symbol_candidates(company):
            snapshot = self._get_fundamentals_for_symbol(
                symbol, fallback_currency=company.currency
            )
            if snapshot is not None:
                return snapshot
        return None

    def get_fundamentals_for_symbol(
        self, symbol: str, fallback_currency: str | None = None
    ) -> FundamentalsSnapshot | None:
        normalized_symbol = symbol.strip().upper()
        if not normalized_symbol:
            raise ValueError("symbol is required")
        return self._get_fundamentals_for_symbol(
            normalized_symbol, fallback_currency=fallback_currency
        )

    def _get_fundamentals_for_symbol(
        self, symbol: str, fallback_currency: str | None
    ) -> FundamentalsSnapshot | None:
        self.attempted_lookups += 1
        payload = json.dumps({"symbol": symbol})
        headers = {
            "Accept": "application/json,text/plain,*/*",
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "User-Agent": "Mozilla/5.0",
        }
        try:
            snapshot = _parse_finimpulse_statistics_payload(
                payload=self._fetcher(FINIMPULSE_STATISTICS_URL, payload, headers),
                symbol=symbol,
                fallback_currency=fallback_currency,
            )
        except Exception as exc:
            self.last_error = _token_safe_error(exc, self.api_key)
            return None
        if snapshot is None:
            return None
        snapshot = self._with_profile(snapshot, headers)
        self._record_valuation_coverage(snapshot)
        self.successful_lookups += 1
        self.last_error = None
        return snapshot

    def _with_profile(
        self, snapshot: FundamentalsSnapshot, headers: dict[str, str]
    ) -> FundamentalsSnapshot:
        payload = json.dumps({"symbol": snapshot.symbol})
        try:
            profile = _parse_finimpulse_profile_payload(
                self._fetcher(FINIMPULSE_PROFILE_URL, payload, headers),
                symbol=snapshot.symbol,
            )
        except Exception as exc:
            self.last_error = _token_safe_error(exc, self.api_key)
            return snapshot
        if profile is None:
            return snapshot
        return replace(
            snapshot,
            business_description=profile.get("business_description"),
            ir_url=profile.get("ir_url"),
        )

    def source_check(self) -> SourceCheck:
        if self.attempted_lookups == 0:
            return SourceCheck(
                name="finimpulse fundamentals",
                status="warning",
                detail="No lookups attempted for Finimpulse fundamentals",
            )

        ratio = (
            f"{self.successful_lookups}/{self.attempted_lookups} "
            "Finimpulse lookups parsed"
        )
        if self.successful_lookups == self.attempted_lookups:
            return SourceCheck(
                name="finimpulse fundamentals",
                status="ok",
                detail=self._source_detail(ratio),
            )

        if self.successful_lookups == 0:
            detail = f"No successful Finimpulse fundamentals lookups ({ratio})"
            if self.last_error:
                detail = f"{detail}: {self.last_error}"
            return SourceCheck(
                name="finimpulse fundamentals",
                status="warning",
                detail=detail,
            )

        return SourceCheck(
            name="finimpulse fundamentals",
            status="warning",
            detail=self._source_detail(ratio),
        )

    def _record_valuation_coverage(self, snapshot: FundamentalsSnapshot) -> None:
        financials = snapshot.financials
        if has_valuation_support(financials):
            self.valuation_support_lookups += 1
        if has_any_financial_field(financials, DIRECT_VALUATION_FIELDS):
            self.direct_valuation_lookups += 1
        if has_any_financial_field(financials, PROXY_VALUATION_FIELDS):
            self.proxy_input_lookups += 1

    def _source_detail(self, ratio: str) -> str:
        return (
            f"{ratio}; valuation support {self.valuation_support_lookups}/"
            f"{self.successful_lookups}; direct valuation "
            f"{self.direct_valuation_lookups}/{self.successful_lookups}; "
            f"proxy inputs {self.proxy_input_lookups}/{self.successful_lookups}; "
            f"missing valuation support "
            f"{self.successful_lookups - self.valuation_support_lookups}/"
            f"{self.successful_lookups}"
        )


class FallbackFundamentalsProvider:
    def __init__(self, primary_provider, fallback_provider) -> None:
        self.primary_provider = primary_provider
        self.fallback_provider = fallback_provider
        self.fallback_attempts = 0
        self.fallback_successes = 0
        self.fallback_valuation_successes = 0

    def get_fundamentals(self, company: Company) -> FundamentalsSnapshot | None:
        primary = self.primary_provider.get_fundamentals(company)
        if primary is not None and has_valuation_support(primary.financials):
            return primary
        self.fallback_attempts += 1
        fallback = self.fallback_provider.get_fundamentals(company)
        return self._merge(primary, fallback)

    def get_fundamentals_for_symbol(
        self, symbol: str, fallback_currency: str | None = None
    ) -> FundamentalsSnapshot | None:
        primary_lookup = getattr(self.primary_provider, "get_fundamentals_for_symbol")
        primary = primary_lookup(symbol, fallback_currency=fallback_currency)
        if primary is not None and has_valuation_support(primary.financials):
            return primary
        self.fallback_attempts += 1
        fallback_lookup = getattr(self.fallback_provider, "get_fundamentals_for_symbol")
        fallback = fallback_lookup(symbol, fallback_currency=fallback_currency)
        return self._merge(primary, fallback)

    def source_check(self) -> SourceCheck:
        if self.fallback_attempts == 0:
            return SourceCheck(
                "valuation fallback",
                "warning",
                "0 fallback valuation enrichments; no fallback lookups attempted",
            )
        status = "ok" if self.fallback_valuation_successes else "warning"
        detail = (
            f"{self.fallback_successes}/{self.fallback_attempts} fallback "
            f"lookups parsed; {self.fallback_valuation_successes} fallback "
            "valuation enrichments"
        )
        fallback_check = self._provider_source_check(self.fallback_provider)
        if (
            fallback_check is not None
            and fallback_check.status != "ok"
            and fallback_check.detail
        ):
            detail = f"{detail}; fallback source: {fallback_check.detail}"
        return SourceCheck(
            "valuation fallback",
            status,
            detail,
        )

    def source_checks(self):
        checks = []
        for provider in (self.primary_provider, self.fallback_provider):
            source_checks = getattr(provider, "source_checks", None)
            if callable(source_checks):
                checks.extend(source_checks())
                continue
            source_check = getattr(provider, "source_check", None)
            if callable(source_check):
                checks.append(source_check())
        checks.append(self.source_check())
        return checks

    def _provider_source_check(self, provider) -> SourceCheck | None:
        source_check = getattr(provider, "source_check", None)
        if callable(source_check):
            return source_check()
        return None

    def _merge(
        self,
        primary: FundamentalsSnapshot | None,
        fallback: FundamentalsSnapshot | None,
    ) -> FundamentalsSnapshot | None:
        if fallback is None:
            return primary
        self.fallback_successes += 1
        if has_valuation_support(fallback.financials):
            self.fallback_valuation_successes += 1
        if primary is None:
            return fallback
        return replace(
            primary,
            financials=_merge_financials(primary.financials, fallback.financials),
        )


def compose_valuation_fallback_provider(
    primary_provider,
    eodhd_provider,
    yahoo_provider,
):
    provider = primary_provider
    if eodhd_provider is not None:
        provider = FallbackFundamentalsProvider(provider, eodhd_provider)
    return FallbackFundamentalsProvider(provider, yahoo_provider)


class EnrichedResearchProvider:
    def __init__(
        self,
        base_provider,
        fundamentals_provider,
        enrichment_limit: int = DEFAULT_WATCHLIST_ENRICHMENT_LIMIT,
        cache: FundamentalsCache | None = None,
        freshness_policy: FundamentalsFreshnessPolicy | None = None,
        known_at: datetime | None = None,
        retrieval_clock: Callable[[], datetime] | None = None,
    ) -> None:
        if enrichment_limit < 0:
            raise ValueError("enrichment_limit must be at least 0")
        self.base_provider = base_provider
        self.fundamentals_provider = fundamentals_provider
        self.enrichment_limit = enrichment_limit
        self.cache = cache
        self.freshness_policy = freshness_policy or FundamentalsFreshnessPolicy()
        self.known_at = (known_at or datetime.now(timezone.utc)).astimezone(timezone.utc)
        self._retrieval_clock = retrieval_clock or (
            lambda: datetime.now(timezone.utc)
        )
        self._enrichment_attempts = 0
        self._successful_enrichments = 0
        self._eligible_enrichment_keys: set[tuple[str, str]] | None = None
        self._selected_enrichment_keys: tuple[tuple[str, str], ...] = ()
        self._eligible_universe_size = 0
        self._cutoff_tie_count = 0
        self._cutoff_tie_excluded = 0
        self._watchlist_enrichment_prepared = False
        self._cache_records: dict[str, CachedFundamentalsRecord | None] = {}
        self._cache_hits = 0
        self._cache_misses = 0
        self._cache_coverage: CacheCoverage | None = None
        self._cache_eligible_companies: tuple[Company, ...] = ()
        self._refreshed_company_ids: set[str] = set()

    def list_companies(self, countries, include_first_north):
        return self.base_provider.list_companies(countries, include_first_north)

    def get_research(self, ticker: str) -> CompanyResearch:
        base = self.base_provider.get_research(ticker)
        cached = self._with_cached_snapshot(base)
        return self._refresh(base, cached)

    def get_company_research(self, company: Company) -> CompanyResearch:
        base = self._get_unenriched_company_research(company)
        cached = self._with_cached_snapshot(base)
        return self._refresh(base, cached)

    def get_base_company_research(self, company: Company) -> CompanyResearch:
        return self._with_cached_snapshot(
            self._get_unenriched_company_research(company)
        )

    def _get_unenriched_company_research(self, company: Company) -> CompanyResearch:
        get_company_research = getattr(
            self.base_provider, "get_company_research", None
        )
        if callable(get_company_research):
            return get_company_research(company)
        return self.base_provider.get_research(company.ticker)

    def prepare_watchlist_enrichment(
        self,
        companies: tuple[Company, ...],
        *,
        eligible_universe_size: int | None = None,
        cutoff_tie_count: int = 0,
        cutoff_tie_excluded: int = 0,
    ) -> None:
        companies = companies[: self.enrichment_limit]
        self._enrichment_attempts = 0
        self._successful_enrichments = 0
        self._selected_enrichment_keys = tuple(
            (company.ticker, company.country) for company in companies
        )
        self._eligible_enrichment_keys = set(self._selected_enrichment_keys)
        self._eligible_universe_size = (
            len(companies)
            if eligible_universe_size is None
            else eligible_universe_size
        )
        self._cutoff_tie_count = cutoff_tie_count
        self._cutoff_tie_excluded = cutoff_tie_excluded
        self._watchlist_enrichment_prepared = True

    def prepare_cached_watchlist_enrichment(
        self,
        eligible_companies: tuple[Company, ...],
        important_companies: tuple[Company, ...],
        *,
        cutoff_tie_count: int = 0,
        cutoff_tie_excluded: int = 0,
    ) -> tuple[Company, ...]:
        if self.cache is None:
            self.prepare_watchlist_enrichment(
                important_companies,
                eligible_universe_size=len(eligible_companies),
                cutoff_tie_count=cutoff_tie_count,
                cutoff_tie_excluded=cutoff_tie_excluded,
            )
            return important_companies[: self.enrichment_limit]

        self._enrichment_attempts = 0
        self._successful_enrichments = 0
        unique_companies = {
            company_cache_identity(company): company for company in eligible_companies
        }
        self._cache_eligible_companies = tuple(unique_companies.values())
        important_rank = {
            company_cache_identity(company): index
            for index, company in enumerate(important_companies)
        }
        refresh_candidates: list[tuple[tuple, Company]] = []
        for company_id, company in unique_companies.items():
            record = self._cached_record(company)
            if record is None:
                priority = (
                    0,
                    important_rank.get(company_id, len(important_rank)),
                    company_id,
                )
            elif (
                self.freshness_policy.classify(record, known_at=self.known_at)
                == CacheFreshness.STALE
            ):
                priority = (
                    1,
                    record.retrieved_at,
                    important_rank.get(company_id, len(important_rank)),
                    company_id,
                )
            else:
                continue
            refresh_candidates.append((priority, company))

        selected = tuple(
            company
            for _, company in sorted(refresh_candidates, key=lambda item: item[0])[
                : self.enrichment_limit
            ]
        )
        self._selected_enrichment_keys = tuple(
            (company.ticker, company.country) for company in selected
        )
        self._eligible_enrichment_keys = set(self._selected_enrichment_keys)
        self._eligible_universe_size = len(unique_companies)
        self._cutoff_tie_count = cutoff_tie_count
        self._cutoff_tie_excluded = cutoff_tie_excluded
        self._watchlist_enrichment_prepared = True
        self._cache_coverage = self.cache.coverage(
            self._cache_eligible_companies,
            known_at=self.known_at,
            freshness_policy=self.freshness_policy,
        )
        return selected

    def enrichment_stats(self) -> dict:
        if self.cache is not None and self._cache_eligible_companies:
            self._cache_coverage = self.cache.coverage(
                self._cache_eligible_companies,
                known_at=self.known_at,
                freshness_policy=self.freshness_policy,
            )
        stats = {
            "eligible_universe_size": self._eligible_universe_size,
            "enrichment_budget": self.enrichment_limit,
            "refresh_budget": self.enrichment_limit,
            "selected_candidates": len(self._selected_enrichment_keys),
            "candidate_keys": tuple(
                f"{country}|{ticker}"
                for ticker, country in self._selected_enrichment_keys
            ),
            "attempts": self._enrichment_attempts,
            "successful_enrichments": self._successful_enrichments,
            "cutoff_tie_count": self._cutoff_tie_count,
            "cutoff_tie_excluded": self._cutoff_tie_excluded,
            "cache_enabled": self.cache is not None,
            "cache_hits": self._cache_hits,
            "cache_misses": self._cache_misses,
            "cache_max_age_days": self.freshness_policy.max_age_days,
        }
        if self._cache_coverage is not None:
            stats.update(self._cache_coverage.as_dict())
        return stats

    def enrichment_source_check(self) -> SourceCheck:
        if not self._watchlist_enrichment_prepared:
            return SourceCheck(
                "fundamentals enrichment",
                "warning",
                f"watchlist enrichment not prepared; budget={self.enrichment_limit}",
            )
        stats = self.enrichment_stats()
        cache_detail = ""
        if stats["cache_enabled"]:
            cache_detail = (
                f"cache coverage={stats.get('cached_companies', 0)}/"
                f"{stats['eligible_universe_size']} "
                f"(fresh={stats.get('fresh_companies', 0)}, "
                f"stale={stats.get('stale_companies', 0)}, "
                f"missing={stats.get('missing_companies', 0)}); "
            )
        return SourceCheck(
            "fundamentals enrichment",
            "ok",
            (
                f"eligible={stats['eligible_universe_size']}; "
                f"budget={stats['enrichment_budget']}; "
                f"selected={stats['selected_candidates']}; "
                f"attempts={stats['attempts']}; "
                f"successful={stats['successful_enrichments']}; "
                f"{cache_detail}"
                f"cache hits={stats['cache_hits']}; "
                f"cache misses={stats['cache_misses']}; "
                f"cutoff ties={stats['cutoff_tie_count']} "
                f"({stats['cutoff_tie_excluded']} excluded)"
            ),
        )

    def evaluation_cache_status(self, company: Company) -> dict[str, Any]:
        if self.cache is None:
            return {
                "enabled": False,
                "participated": False,
                "state": "disabled",
                "refreshed_this_run": False,
                "retrieved_at": None,
                "providers": [],
            }
        company_id = company_cache_identity(company)
        record = self._cached_record(company)
        if record is None:
            return {
                "enabled": True,
                "participated": False,
                "state": "missing",
                "refreshed_this_run": False,
                "retrieved_at": None,
                "providers": [],
            }
        refreshed_this_run = company_id in self._refreshed_company_ids
        freshness = self.freshness_policy.classify(record, known_at=self.known_at)
        return {
            "enabled": True,
            "participated": not refreshed_this_run,
            "state": (
                CacheFreshness.FRESH.value
                if refreshed_this_run
                else freshness.value
            ),
            "refreshed_this_run": refreshed_this_run,
            "retrieved_at": record.retrieved_at.isoformat().replace("+00:00", "Z"),
            "providers": list(record.providers),
        }

    def source_checks(self):
        checks = list(self.base_provider.source_checks())
        checks.append(self.enrichment_source_check())
        source_checks = getattr(self.fundamentals_provider, "source_checks", None)
        if callable(source_checks):
            checks.extend(source_checks())
            return checks
        source_check = getattr(self.fundamentals_provider, "source_check", None)
        if callable(source_check):
            checks.append(source_check())
        return checks

    def _refresh(
        self,
        base_research: CompanyResearch,
        cached_research: CompanyResearch,
    ) -> CompanyResearch:
        key = (base_research.company.ticker, base_research.company.country)
        if (
            self._eligible_enrichment_keys is not None
            and key not in self._eligible_enrichment_keys
        ):
            return cached_research
        if self._enrichment_attempts >= self.enrichment_limit:
            return cached_research
        self._enrichment_attempts += 1
        snapshot = self.fundamentals_provider.get_fundamentals(base_research.company)
        if snapshot is None:
            return cached_research
        if self.cache is not None:
            retrieved_at = self._retrieval_clock()
            if not isinstance(retrieved_at, datetime) or retrieved_at.tzinfo is None:
                raise ValueError("retrieval clock must return a timezone-aware datetime")
            retrieved_at = retrieved_at.astimezone(timezone.utc)
            record = self.cache.store(
                base_research.company,
                snapshot,
                retrieved_at=retrieved_at,
            )
            company_id = company_cache_identity(base_research.company)
            self._cache_records[company_id] = record
            self._refreshed_company_ids.add(company_id)
            self.known_at = max(self.known_at, retrieved_at)
        self._successful_enrichments += 1
        return self._apply_snapshot(base_research, snapshot)

    def _with_cached_snapshot(self, research: CompanyResearch) -> CompanyResearch:
        record = self._cached_record(research.company)
        if record is None:
            return research
        return self._apply_snapshot(research, record.snapshot)

    def _cached_record(
        self, company: Company
    ) -> CachedFundamentalsRecord | None:
        if self.cache is None:
            return None
        company_id = company_cache_identity(company)
        if company_id in self._cache_records:
            return self._cache_records[company_id]
        record = self.cache.get_latest(company, known_at=self.known_at)
        self._cache_records[company_id] = record
        if record is None:
            self._cache_misses += 1
        else:
            self._cache_hits += 1
        return record

    def _apply_snapshot(
        self,
        research: CompanyResearch,
        snapshot: FundamentalsSnapshot,
    ) -> CompanyResearch:
        company = research.company
        if company.market_cap_eur_m is None and snapshot.market_cap_eur_m is not None:
            company = replace(company, market_cap_eur_m=snapshot.market_cap_eur_m)
        if (
            company.business_description is None
            and snapshot.business_description is not None
        ):
            company = replace(
                company, business_description=snapshot.business_description
            )
        if company.ir_url is None and snapshot.ir_url is not None:
            company = replace(company, ir_url=snapshot.ir_url)

        financials = _merge_financials(
            research.financials,
            snapshot.financials,
        )
        evidence = research.evidence
        if snapshot.evidence is not None:
            evidence = (*evidence, snapshot.evidence)

        return replace(
            research,
            company=company,
            financials=financials,
            evidence=evidence,
            data_quality=financials.data_quality,
        )


def _merge_financials(
    base: FinancialSnapshot,
    enrichment: FinancialSnapshot,
) -> FinancialSnapshot:
    preserved_fields = {
        "price",
        "currency",
        "one_year_return_pct",
        "distance_from_52w_high_pct",
        "observations",
    }
    merged_values = {}
    accepted_observations: list[FinancialObservation] = []

    for field_name in FinancialSnapshot.__dataclass_fields__:
        if field_name in preserved_fields or field_name == "data_quality":
            continue

        if getattr(base, field_name) is not None:
            continue

        enrichment_value = getattr(enrichment, field_name)
        if enrichment_value is not None:
            merged_values[field_name] = enrichment_value
            observation = enrichment.observation_for(field_name)
            if observation is not None:
                accepted_observations.append(observation)

    if accepted_observations:
        merged_values["observations"] = (
            *base.observations,
            *accepted_observations,
        )

    if (
        _observations_support_quality_upgrade(accepted_observations)
        and base.data_quality == DataQuality.THIN
    ):
        merged_values["data_quality"] = DataQuality.PARTIAL

    return replace(base, **merged_values)


def _observations_support_quality_upgrade(
    observations: list[FinancialObservation],
) -> bool:
    period_types = {
        observation.period_type
        for observation in observations
        if observation.period_type is not None
    }
    if ReportingPeriodType.FORWARD in period_types and len(period_types) > 1:
        return False
    return any(
        observation.confidence
        in {ObservationConfidence.HIGH, ObservationConfidence.MEDIUM}
        and not _is_explicitly_stale(observation.as_of)
        for observation in observations
    )


def _is_explicitly_stale(as_of: str | None) -> bool:
    if as_of is None:
        return False
    try:
        as_of_date = date.fromisoformat(as_of[:10])
    except ValueError:
        return False
    return (date.today() - as_of_date).days > MAX_QUALITY_AS_OF_AGE_DAYS


def yahoo_symbol_candidates(company: Company) -> tuple[str, ...]:
    return _symbol_candidates(company)


def finnhub_symbol_candidates(company: Company) -> tuple[str, ...]:
    return _symbol_candidates(company)


def finimpulse_symbol_candidates(company: Company) -> tuple[str, ...]:
    return _symbol_candidates(company)


def eodhd_symbol_candidates(company: Company) -> tuple[str, ...]:
    return _symbol_candidates(company)


def _symbol_candidates(company: Company) -> tuple[str, ...]:
    suffix_by_country = {"SE": ".ST", "FI": ".HE"}
    suffix = suffix_by_country.get(company.country.upper())
    if suffix is None:
        return ()

    ticker = company.ticker.strip().upper()
    normalized = "-".join(ticker.split())
    compact = normalized.replace("-", "")

    candidates = [f"{normalized}{suffix}"]
    if compact != normalized:
        candidates.append(f"{compact}{suffix}")
    return tuple(dict.fromkeys(candidates))


def _parse_finnhub_payload(
    payload: dict[str, Any], symbol: str, fallback_currency: str | None
) -> FundamentalsSnapshot | None:
    profile = _dict_value(payload, "profile")
    metrics = _dict_value(payload, "metrics")
    metric = _dict_value(metrics, "metric")
    currency = str(profile.get("currency") or fallback_currency or "").upper()
    fx_rate = _STATIC_EUR_RATES.get(currency)

    market_cap_eur_m = _currency_m_to_eur_m(
        _number(profile, "marketCapitalization"), fx_rate
    )
    pe_ratio, pe_key = _first_number_with_key(
        metric, ("peBasicExclExtraTTM", "peNormalizedAnnual")
    )
    price_to_book, pb_key = _first_number_with_key(
        metric, ("pbQuarterly", "pbAnnual")
    )
    revenue_growth_pct, growth_key = _first_number_with_key(
        metric, ("revenueGrowthTTMYoy", "revenueGrowthQuarterlyYoy")
    )
    operating_margin_pct, margin_key = _first_number_with_key(
        metric, ("operatingMarginTTM", "operatingMarginAnnual")
    )
    debt_to_equity_source, debt_key = _first_number_with_key(
        metric,
        (
            "totalDebt/totalEquityQuarterly",
            "totalDebt/totalEquityAnnual",
        ),
    )
    debt_to_equity = _debt_to_equity_ratio(debt_to_equity_source)
    observations: list[FinancialObservation] = []
    _add_observation(
        observations,
        "pe_ratio",
        pe_ratio,
        "finnhub",
        pe_key,
        period_type=_period_type_for_key(
            pe_key,
            {
                "peBasicExclExtraTTM": ReportingPeriodType.TTM,
                "peNormalizedAnnual": ReportingPeriodType.ANNUAL,
            },
        ),
    )
    _add_observation(
        observations,
        "price_to_book",
        price_to_book,
        "finnhub",
        pb_key,
        period_type=_period_type_for_key(
            pb_key,
            {
                "pbQuarterly": ReportingPeriodType.QUARTERLY,
                "pbAnnual": ReportingPeriodType.ANNUAL,
            },
        ),
    )
    _add_observation(
        observations,
        "revenue_growth_pct",
        revenue_growth_pct,
        "finnhub",
        growth_key,
        period_type=_period_type_for_key(
            growth_key,
            {
                "revenueGrowthTTMYoy": ReportingPeriodType.TTM,
                "revenueGrowthQuarterlyYoy": ReportingPeriodType.QUARTERLY,
            },
        ),
    )
    _add_observation(
        observations,
        "operating_margin_pct",
        operating_margin_pct,
        "finnhub",
        margin_key,
        period_type=_period_type_for_key(
            margin_key,
            {
                "operatingMarginTTM": ReportingPeriodType.TTM,
                "operatingMarginAnnual": ReportingPeriodType.ANNUAL,
            },
        ),
    )
    _add_observation(
        observations,
        "debt_to_equity",
        debt_to_equity,
        "finnhub",
        debt_key,
        period_type=_period_type_for_key(
            debt_key,
            {
                "totalDebt/totalEquityQuarterly": ReportingPeriodType.QUARTERLY,
                "totalDebt/totalEquityAnnual": ReportingPeriodType.ANNUAL,
            },
        ),
        is_derived=True,
        derivation="provider percentage divided by 100 to normalize as a ratio",
    )
    financials = FinancialSnapshot(
        pe_ratio=pe_ratio,
        price_to_book=price_to_book,
        revenue_growth_pct=revenue_growth_pct,
        operating_margin_pct=operating_margin_pct,
        debt_to_equity=debt_to_equity,
        data_quality=DataQuality.PARTIAL,
        observations=tuple(observations),
    )
    if not _has_meaningful_fields(market_cap_eur_m, financials):
        return None

    return FundamentalsSnapshot(
        symbol=symbol,
        market_cap_eur_m=market_cap_eur_m,
        financials=financials,
        evidence=Evidence(
            label=f"Finnhub fundamentals lookup ({symbol})",
            url=FINNHUB_PROFILE_DOC_URL,
            source="finnhub",
        ),
    )


def _parse_finimpulse_statistics_payload(
    payload: str, symbol: str, fallback_currency: str | None
) -> FundamentalsSnapshot | None:
    result = json.loads(payload).get("result")
    if not isinstance(result, list) or not result:
        return None

    item = next(
        (
            candidate
            for candidate in result
            if isinstance(candidate, dict)
            and str(candidate.get("symbol") or "").upper() == symbol.upper()
        ),
        None,
    )
    if item is None:
        return None

    currency = str(item.get("currency") or fallback_currency or "").upper()
    fx_rate = _STATIC_EUR_RATES.get(currency)
    as_of = _clean_text(item.get("update_time"))
    market_cap_eur_m = _eur_m(_number(item, "market_cap"), fx_rate)

    average_daily_value_eur = None
    price = _number(item, "current_price")
    average_daily_volume = _number(item, "average_volume_10days")
    if fx_rate is not None and price is not None and average_daily_volume is not None:
        average_daily_value_eur = _finite_number(
            round(price * average_daily_volume * fx_rate, 2)
        )

    pe_ratio, pe_key = _first_number_with_key(item, FINIMPULSE_PE_KEYS)
    price_to_book, pb_key = _first_number_with_key(
        item, FINIMPULSE_PRICE_TO_BOOK_KEYS
    )
    revenue_source = _number(item, "total_revenue")
    revenue_key = "total_revenue" if revenue_source is not None else None
    revenue_eur_m = _eur_m(revenue_source, fx_rate)
    net_income_source = _number(item, "net_income_to_common")
    net_income_key = (
        "net_income_to_common" if net_income_source is not None else None
    )
    net_income_eur_m = _eur_m(net_income_source, fx_rate)
    total_cash = _number(item, "total_cash")
    total_debt = _number(item, "total_debt")
    net_cash_eur_m = None
    if total_cash is not None and total_debt is not None:
        net_cash_eur_m = _eur_m(total_cash - total_debt, fx_rate)
    revenue_growth_source = _number(item, "revenue_growth")
    revenue_growth_pct = _ratio_to_percent(revenue_growth_source)
    operating_margin_source = _number(item, "operating_margins")
    operating_margin_key = (
        "operating_margins" if operating_margin_source is not None else None
    )
    operating_margin_pct = _ratio_to_percent(operating_margin_source)
    debt_to_equity_source = _number(item, "debt_to_equity")
    debt_to_equity = _debt_to_equity_ratio(debt_to_equity_source)
    fifty_two_week_high = _number(item, "fifty_two_week_high")
    distance_from_52w_high_pct = (
        _finite_number(round((price / fifty_two_week_high - 1) * 100, 2))
        if price is not None
        and fifty_two_week_high is not None
        and fifty_two_week_high > 0
        else None
    )

    observations: list[FinancialObservation] = []
    _add_observation(
        observations,
        "pe_ratio",
        pe_ratio,
        "finimpulse",
        pe_key,
        as_of=as_of,
        period_type=_period_type_for_key(
            pe_key,
            {
                "trailing_pe": ReportingPeriodType.TTM,
                "forward_pe": ReportingPeriodType.FORWARD,
            },
        ),
        confidence=(
            ObservationConfidence.LOW
            if pe_key == "forward_pe"
            else ObservationConfidence.MEDIUM
        ),
    )
    _add_observation(
        observations,
        "price_to_book",
        price_to_book,
        "finimpulse",
        pb_key,
        as_of=as_of,
    )
    _add_fx_observation(
        observations,
        "revenue_eur_m",
        revenue_eur_m,
        "finimpulse",
        revenue_key,
        currency,
        fx_rate,
        as_of=as_of,
        period_type=_period_type_for_key(
            revenue_key,
            {
                "annual_revenue": ReportingPeriodType.ANNUAL,
                "revenue_ttm": ReportingPeriodType.TTM,
            },
        ),
    )
    _add_fx_observation(
        observations,
        "net_income_eur_m",
        net_income_eur_m,
        "finimpulse",
        net_income_key,
        currency,
        fx_rate,
        as_of=as_of,
    )
    _add_fx_observation(
        observations,
        "net_cash_eur_m",
        net_cash_eur_m,
        "finimpulse",
        "total_cash - total_debt" if net_cash_eur_m is not None else None,
        currency,
        fx_rate,
        as_of=as_of,
        extra_derivation="total cash minus total debt",
    )
    _add_observation(
        observations,
        "revenue_growth_pct",
        revenue_growth_pct,
        "finimpulse",
        "revenue_growth" if revenue_growth_source is not None else None,
        as_of=as_of,
        is_derived=True,
        derivation="ratio converted to percentage points",
    )
    _add_observation(
        observations,
        "operating_margin_pct",
        operating_margin_pct,
        "finimpulse",
        operating_margin_key,
        as_of=as_of,
        is_derived=True,
        derivation="ratio converted to percentage points",
    )
    _add_observation(
        observations,
        "debt_to_equity",
        debt_to_equity,
        "finimpulse",
        "debt_to_equity" if debt_to_equity_source is not None else None,
        as_of=as_of,
        is_derived=True,
        derivation="provider percentage divided by 100 to normalize as a ratio",
    )
    _add_observation(
        observations,
        "distance_from_52w_high_pct",
        distance_from_52w_high_pct,
        "finimpulse",
        (
            "current_price / fifty_two_week_high"
            if distance_from_52w_high_pct is not None
            else None
        ),
        as_of=as_of,
        reporting_period="trailing_52_weeks",
        is_derived=True,
        derivation=(
            "current price divided by 52-week high, minus one, as percentage points"
        ),
    )
    _add_fx_observation(
        observations,
        "average_daily_value_eur",
        average_daily_value_eur,
        "finimpulse",
        (
            "current_price * average_volume_10days"
            if average_daily_value_eur is not None
            else None
        ),
        currency,
        fx_rate,
        as_of=as_of,
        reporting_period="10_trading_days",
        normalize_to_millions=False,
        extra_derivation="price multiplied by 10-day average volume",
    )

    financials = FinancialSnapshot(
        pe_ratio=pe_ratio,
        price_to_book=price_to_book,
        revenue_eur_m=revenue_eur_m,
        net_income_eur_m=net_income_eur_m,
        net_cash_eur_m=net_cash_eur_m,
        revenue_growth_pct=revenue_growth_pct,
        operating_margin_pct=operating_margin_pct,
        debt_to_equity=debt_to_equity,
        distance_from_52w_high_pct=distance_from_52w_high_pct,
        average_daily_value_eur=average_daily_value_eur,
        data_quality=DataQuality.PARTIAL,
        observations=tuple(observations),
    )
    if not _has_meaningful_fields(market_cap_eur_m, financials):
        return None

    parsed_symbol = str(item.get("symbol") or symbol)
    return FundamentalsSnapshot(
        symbol=parsed_symbol,
        market_cap_eur_m=market_cap_eur_m,
        financials=financials,
        evidence=Evidence(
            label=f"Finimpulse fundamentals lookup ({parsed_symbol})",
            url=FINIMPULSE_STATISTICS_DOC_URL,
            source="finimpulse",
        ),
    )


def _parse_finimpulse_profile_payload(
    payload: str, symbol: str
) -> dict[str, str | None] | None:
    result = _dict_value(json.loads(payload), "result")
    items = result.get("items")
    if not isinstance(items, list) or not items:
        return None

    item = next(
        (
            candidate
            for candidate in items
            if isinstance(candidate, dict)
            and str(candidate.get("symbol") or "").upper() == symbol.upper()
        ),
        None,
    )
    if item is None:
        return None

    business_description = _clean_text(item.get("long_business_summary"))
    ir_url = _clean_text(item.get("ir_website"))
    if business_description is None and ir_url is None:
        return None
    return {"business_description": business_description, "ir_url": ir_url}


def _parse_eodhd_fundamentals_payload(
    payload: str, symbol: str, fallback_currency: str | None
) -> FundamentalsSnapshot | None:
    data = json.loads(payload)
    general = _dict_value(data, "General")
    highlights = _dict_value(data, "Highlights")
    valuation = _dict_value(data, "Valuation")
    currency = str(general.get("CurrencyCode") or fallback_currency or "").upper()
    fx_rate = _STATIC_EUR_RATES.get(currency)
    as_of = _clean_text(general.get("UpdatedAt"))

    market_cap_eur_m = _eur_m(_number(highlights, "MarketCapitalization"), fx_rate)
    pe_ratio, pe_key = _first_number_with_key(valuation, ("TrailingPE",))
    pe_source_section = "Valuation"
    if pe_ratio is None:
        pe_ratio, pe_key = _first_number_with_key(highlights, ("PERatio",))
        pe_source_section = "Highlights"
    if pe_ratio is None:
        pe_ratio, pe_key = _first_number_with_key(valuation, ("ForwardPE",))
        pe_source_section = "Valuation"
    price_to_book = _number(valuation, "PriceBookMRQ")
    revenue_eur_m = _eur_m(_number(highlights, "RevenueTTM"), fx_rate)
    revenue_growth_source = _number(highlights, "QuarterlyRevenueGrowthYOY")
    revenue_growth_pct = _ratio_to_percent(revenue_growth_source)
    operating_margin_source = _number(highlights, "OperatingMarginTTM")
    operating_margin_pct = _ratio_to_percent(operating_margin_source)
    observations: list[FinancialObservation] = []
    _add_observation(
        observations,
        "pe_ratio",
        pe_ratio,
        "eodhd",
        f"{pe_source_section}.{pe_key}" if pe_key is not None else None,
        as_of=as_of,
        period_type={
            "TrailingPE": ReportingPeriodType.TTM,
            "ForwardPE": ReportingPeriodType.FORWARD,
        }.get(pe_key),
        confidence=(
            ObservationConfidence.LOW
            if pe_key == "ForwardPE"
            else ObservationConfidence.MEDIUM
        ),
    )
    _add_observation(
        observations,
        "price_to_book",
        price_to_book,
        "eodhd",
        "Valuation.PriceBookMRQ" if price_to_book is not None else None,
        as_of=as_of,
        period_type=ReportingPeriodType.MRQ,
    )
    _add_fx_observation(
        observations,
        "revenue_eur_m",
        revenue_eur_m,
        "eodhd",
        "Highlights.RevenueTTM" if revenue_eur_m is not None else None,
        currency,
        fx_rate,
        as_of=as_of,
        period_type=ReportingPeriodType.TTM,
    )
    _add_observation(
        observations,
        "revenue_growth_pct",
        revenue_growth_pct,
        "eodhd",
        (
            "Highlights.QuarterlyRevenueGrowthYOY"
            if revenue_growth_pct is not None
            else None
        ),
        as_of=as_of,
        period_type=ReportingPeriodType.QUARTERLY,
        is_derived=True,
        derivation="ratio converted to percentage points",
    )
    _add_observation(
        observations,
        "operating_margin_pct",
        operating_margin_pct,
        "eodhd",
        (
            "Highlights.OperatingMarginTTM"
            if operating_margin_pct is not None
            else None
        ),
        as_of=as_of,
        period_type=ReportingPeriodType.TTM,
        is_derived=True,
        derivation="ratio converted to percentage points",
    )
    financials = FinancialSnapshot(
        pe_ratio=pe_ratio,
        price_to_book=price_to_book,
        revenue_eur_m=revenue_eur_m,
        revenue_growth_pct=revenue_growth_pct,
        operating_margin_pct=operating_margin_pct,
        data_quality=DataQuality.PARTIAL,
        observations=tuple(observations),
    )
    if not _has_meaningful_fields(market_cap_eur_m, financials):
        return None

    parsed_symbol = str(general.get("Code") or symbol).upper()
    return FundamentalsSnapshot(
        symbol=parsed_symbol,
        market_cap_eur_m=market_cap_eur_m,
        business_description=_clean_text(general.get("Description")),
        ir_url=_clean_text(general.get("WebURL")),
        financials=financials,
        evidence=Evidence(
            label=f"EODHD fundamentals lookup ({parsed_symbol})",
            url=EODHD_FUNDAMENTALS_DOC_URL,
            source="eodhd",
        ),
    )


def _parse_fundamentals_payload(
    payload: str, symbol: str, url: str, fallback_currency: str | None
) -> FundamentalsSnapshot | None:
    result = _first_quote_summary_result(json.loads(payload))
    if not result:
        return None

    price = _dict_value(result, "price")
    summary = _dict_value(result, "summaryDetail")
    financial_data = _dict_value(result, "financialData")
    currency = str(price.get("currency") or fallback_currency or "").upper()
    fx_rate = _STATIC_EUR_RATES.get(currency)

    market_cap = _raw(price, "marketCap")
    trailing_pe = _raw(summary, "trailingPE")
    price_to_book = _raw(summary, "priceToBook")
    revenue_growth = _raw(financial_data, "revenueGrowth")
    operating_margin = _raw(financial_data, "operatingMargins")
    debt_to_equity = _raw(financial_data, "debtToEquity")
    total_cash = _raw(financial_data, "totalCash")
    total_debt = _raw(financial_data, "totalDebt")
    average_daily_volume = _raw(summary, "averageDailyVolume10Day")
    previous_close = _raw(summary, "previousClose")

    market_cap_eur_m = _eur_m(market_cap, fx_rate)
    net_cash_eur_m = None
    if fx_rate is not None and total_cash is not None and total_debt is not None:
        net_cash_eur_m = _eur_m(total_cash - total_debt, fx_rate)

    average_daily_value_eur = None
    if (
        fx_rate is not None
        and average_daily_volume is not None
        and previous_close is not None
    ):
        average_daily_value_eur = _finite_number(
            average_daily_volume * previous_close * fx_rate
        )

    revenue_growth_pct = _percent(revenue_growth)
    operating_margin_pct = _percent(operating_margin)
    normalized_debt_to_equity = (
        _finite_number(round(debt_to_equity / 100, 4))
        if debt_to_equity is not None
        else None
    )
    observations: list[FinancialObservation] = []
    _add_observation(
        observations,
        "pe_ratio",
        trailing_pe,
        "yahoo",
        "summaryDetail.trailingPE" if trailing_pe is not None else None,
        period_type=ReportingPeriodType.TTM,
    )
    _add_observation(
        observations,
        "price_to_book",
        price_to_book,
        "yahoo",
        "summaryDetail.priceToBook" if price_to_book is not None else None,
    )
    _add_observation(
        observations,
        "revenue_growth_pct",
        revenue_growth_pct,
        "yahoo",
        "financialData.revenueGrowth" if revenue_growth_pct is not None else None,
        is_derived=True,
        derivation="ratio converted to percentage points",
    )
    _add_observation(
        observations,
        "operating_margin_pct",
        operating_margin_pct,
        "yahoo",
        "financialData.operatingMargins"
        if operating_margin_pct is not None
        else None,
        is_derived=True,
        derivation="ratio converted to percentage points",
    )
    _add_observation(
        observations,
        "debt_to_equity",
        normalized_debt_to_equity,
        "yahoo",
        "financialData.debtToEquity"
        if normalized_debt_to_equity is not None
        else None,
        is_derived=True,
        derivation="provider percentage divided by 100 to normalize as a ratio",
    )
    _add_fx_observation(
        observations,
        "net_cash_eur_m",
        net_cash_eur_m,
        "yahoo",
        (
            "financialData.totalCash - financialData.totalDebt"
            if net_cash_eur_m is not None
            else None
        ),
        currency,
        fx_rate,
        extra_derivation="cash less debt",
    )
    _add_fx_observation(
        observations,
        "average_daily_value_eur",
        average_daily_value_eur,
        "yahoo",
        (
            "summaryDetail.previousClose * summaryDetail.averageDailyVolume10Day"
            if average_daily_value_eur is not None
            else None
        ),
        currency,
        fx_rate,
        reporting_period="10_trading_days",
        normalize_to_millions=False,
        extra_derivation="previous close multiplied by 10-day average volume",
    )

    financials = FinancialSnapshot(
        pe_ratio=trailing_pe,
        price_to_book=price_to_book,
        revenue_growth_pct=revenue_growth_pct,
        operating_margin_pct=operating_margin_pct,
        debt_to_equity=normalized_debt_to_equity,
        net_cash_eur_m=net_cash_eur_m,
        average_daily_value_eur=average_daily_value_eur,
        data_quality=DataQuality.PARTIAL,
        observations=tuple(observations),
    )
    if not _has_meaningful_fields(market_cap_eur_m, financials):
        return None

    return FundamentalsSnapshot(
        symbol=symbol,
        market_cap_eur_m=market_cap_eur_m,
        financials=financials,
        evidence=Evidence(
            label=f"Yahoo-style fundamentals lookup ({symbol})",
            url=url,
            source="yahoo",
        ),
    )


def _first_quote_summary_result(payload: dict[str, Any]) -> dict[str, Any] | None:
    quote_summary = _dict_value(payload, "quoteSummary")
    results = quote_summary.get("result")
    if isinstance(results, list) and results and isinstance(results[0], dict):
        return results[0]
    return None


def _dict_value(source: dict[str, Any], key: str) -> dict[str, Any]:
    value = source.get(key)
    return value if isinstance(value, dict) else {}


def _finite_number(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def _raw(source: dict[str, Any], key: str) -> float | None:
    value = source.get(key)
    if isinstance(value, dict):
        value = value.get("raw")
    return _finite_number(value)


def _number(source: dict[str, Any], key: str) -> float | None:
    return _finite_number(source.get(key))


def _clean_text(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    stripped = " ".join(value.split())
    return stripped or None


def _first_number(source: dict[str, Any], keys: tuple[str, ...]) -> float | None:
    value, _ = _first_number_with_key(source, keys)
    return value


def _first_number_with_key(
    source: dict[str, Any], keys: tuple[str, ...]
) -> tuple[float | None, str | None]:
    for key in keys:
        value = _number(source, key)
        if value is not None:
            return value, key
    return None, None


def _period_type_for_key(
    key: str | None,
    period_types: dict[str, ReportingPeriodType],
) -> ReportingPeriodType | None:
    return period_types.get(key) if key is not None else None


def _add_observation(
    observations: list[FinancialObservation],
    canonical_field: str,
    value: float | None,
    provider: str,
    source_metric: str | None,
    *,
    as_of: str | None = None,
    reporting_period: str | None = None,
    period_type: ReportingPeriodType | None = None,
    original_currency: str | None = None,
    normalized_currency: str | None = None,
    is_derived: bool = False,
    derivation: str | None = None,
    confidence: ObservationConfidence | None = ObservationConfidence.MEDIUM,
) -> None:
    if value is None or source_metric is None:
        return
    observations.append(
        FinancialObservation(
            canonical_field=canonical_field,
            normalized_value=value,
            provider=provider,
            source_metric=source_metric,
            as_of=as_of,
            reporting_period=reporting_period,
            period_type=period_type,
            original_currency=original_currency,
            normalized_currency=normalized_currency,
            is_derived=is_derived,
            derivation=derivation,
            confidence=confidence,
        )
    )


def _add_fx_observation(
    observations: list[FinancialObservation],
    canonical_field: str,
    value: float | None,
    provider: str,
    source_metric: str | None,
    currency: str,
    fx_rate: float | None,
    *,
    as_of: str | None = None,
    reporting_period: str | None = None,
    period_type: ReportingPeriodType | None = None,
    normalize_to_millions: bool = True,
    extra_derivation: str | None = None,
) -> None:
    if value is None or source_metric is None or fx_rate is None:
        return
    derivation_parts = [extra_derivation] if extra_derivation else []
    if currency == "EUR":
        if normalize_to_millions:
            derivation_parts.append("divided by 1,000,000 to normalize to EUR millions")
    else:
        derivation_parts.append(
            f"static FX assumption: 1 {currency} = {fx_rate:g} EUR"
        )
        if normalize_to_millions:
            derivation_parts.append("divided by 1,000,000 to normalize to EUR millions")
    _add_observation(
        observations,
        canonical_field,
        value,
        provider,
        source_metric,
        as_of=as_of,
        reporting_period=reporting_period,
        period_type=period_type,
        original_currency=currency,
        normalized_currency="EUR",
        is_derived=True,
        derivation="; ".join(derivation_parts) or "normalized to EUR",
        confidence=(
            ObservationConfidence.MEDIUM
            if currency == "EUR"
            else ObservationConfidence.LOW
        ),
    )


def _percent(value: float | None) -> float | None:
    if value is None:
        return None
    return _finite_number(round(value * 100, 2))


def _ratio_to_percent(value: float | None) -> float | None:
    if value is None:
        return None
    if -1 <= value <= 1:
        value *= 100
    return _finite_number(round(value, 2))


def _eur_m(value: float | None, fx_rate: float | None) -> float | None:
    if value is None or fx_rate is None:
        return None
    return _finite_number(round(value * fx_rate / 1_000_000, 2))


def _currency_m_to_eur_m(value: float | None, fx_rate: float | None) -> float | None:
    if value is None or fx_rate is None:
        return None
    return _finite_number(round(value * fx_rate, 2))


def _debt_to_equity_ratio(value: float | None) -> float | None:
    if value is None:
        return None
    return _finite_number(round(value / 100, 4))


def _token_safe_error(exc: Exception, token: str) -> str:
    message = str(exc)
    message = re.sub(r"token=[^&\s]+", "token <redacted>", message)
    if token:
        message = message.replace(token, "<redacted>")
    return message


def _has_meaningful_fields(
    market_cap_eur_m: float | None, financials: FinancialSnapshot
) -> bool:
    return any(
        value is not None
        for value in (
            market_cap_eur_m,
            financials.pe_ratio,
            financials.price_to_book,
            financials.ev_to_ebit,
            financials.revenue_eur_m,
            financials.book_value_eur_m,
            financials.net_income_eur_m,
            financials.revenue_growth_pct,
            financials.operating_margin_pct,
            financials.debt_to_equity,
            financials.net_cash_eur_m,
            financials.average_daily_value_eur,
            financials.one_year_return_pct,
            financials.distance_from_52w_high_pct,
        )
    )


def has_any_financial_field(
    financials: FinancialSnapshot, field_names: tuple[str, ...]
) -> bool:
    return any(getattr(financials, field_name) is not None for field_name in field_names)


def has_valuation_support(financials: FinancialSnapshot) -> bool:
    return has_any_financial_field(
        financials, DIRECT_VALUATION_FIELDS + PROXY_VALUATION_FIELDS
    )


def _yahoo_quote_summary_url(symbol: str) -> str:
    return YAHOO_QUOTE_SUMMARY_URL.format(symbol=quote(symbol, safe=""))


def _finnhub_profile_url(symbol: str, token: str) -> str:
    return FINNHUB_PROFILE_URL.format(
        symbol=quote(symbol, safe=""),
        token=quote(token, safe=""),
    )


def _finnhub_metric_url(symbol: str, token: str) -> str:
    return FINNHUB_METRIC_URL.format(
        symbol=quote(symbol, safe=""),
        token=quote(token, safe=""),
    )


def _eodhd_fundamentals_url(symbol: str, token: str) -> str:
    query = urlencode({"api_token": token, "fmt": "json"})
    return f"{EODHD_FUNDAMENTALS_URL.format(symbol=quote(symbol, safe=''))}?{query}"


def _fetch_url(url: str) -> str:
    request = Request(
        url,
        headers={
            "Accept": "application/json,text/plain,*/*",
            "User-Agent": "Mozilla/5.0",
        },
    )
    context = ssl.create_default_context(cafile=certifi.where())
    with urlopen(
        request, timeout=YAHOO_FETCH_TIMEOUT_SECONDS, context=context
    ) as response:
        return response.read().decode("utf-8")


def _fetch_finnhub_url(url: str) -> str:
    request = Request(
        url,
        headers={
            "Accept": "application/json,text/plain,*/*",
            "User-Agent": "Mozilla/5.0",
        },
    )
    with urlopen(request, timeout=FINNHUB_FETCH_TIMEOUT_SECONDS) as response:
        return response.read().decode("utf-8")


def _fetch_eodhd_url(url: str) -> str:
    request = Request(
        url,
        headers={
            "Accept": "application/json,text/plain,*/*",
            "User-Agent": "Mozilla/5.0",
        },
    )
    with urlopen(request, timeout=EODHD_FETCH_TIMEOUT_SECONDS) as response:
        return response.read().decode("utf-8")


def _post_json(url: str, payload: str, headers: dict[str, str]) -> str:
    request = Request(
        url,
        data=payload.encode("utf-8"),
        headers=headers,
        method="POST",
    )
    with urlopen(request, timeout=FINIMPULSE_FETCH_TIMEOUT_SECONDS) as response:
        return response.read().decode("utf-8")
