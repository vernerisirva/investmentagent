from __future__ import annotations

import json
import re
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from typing import Any
from urllib.parse import quote
from urllib.request import Request, urlopen

from investmentagent.models import (
    Company,
    CompanyResearch,
    DataQuality,
    Evidence,
    FinancialSnapshot,
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
FINIMPULSE_SEARCH_URL = "https://api.finimpulse.com/v1/search"
FINIMPULSE_SEARCH_DOC_URL = "https://developers.finimpulse.com/v1/search/"
FINIMPULSE_FETCH_TIMEOUT_SECONDS = 3
_EUR_RATES = {"EUR": 1.0, "SEK": 0.1}


@dataclass(frozen=True)
class FundamentalsSnapshot:
    symbol: str
    market_cap_eur_m: float | None = None
    financials: FinancialSnapshot = field(
        default_factory=lambda: FinancialSnapshot(data_quality=DataQuality.PARTIAL)
    )
    evidence: Evidence | None = None


class YahooFundamentalsProvider:
    def __init__(self, fetcher: Callable[[str], str] | None = None) -> None:
        self._fetcher = fetcher or _fetch_url
        self.attempted_lookups = 0
        self.successful_lookups = 0
        self.last_error: str | None = None

    def get_fundamentals(self, company: Company) -> FundamentalsSnapshot | None:
        for symbol in yahoo_symbol_candidates(company):
            self.attempted_lookups += 1
            url = _yahoo_quote_summary_url(symbol)
            try:
                snapshot = _parse_fundamentals_payload(
                    payload=self._fetcher(url),
                    symbol=symbol,
                    url=url,
                    fallback_currency=company.currency,
                )
            except Exception as exc:
                self.last_error = str(exc)
                continue
            if snapshot is not None:
                self.successful_lookups += 1
                self.last_error = None
                return snapshot
        return None

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
            return SourceCheck(name="free fundamentals", status="ok", detail=ratio)

        if self.successful_lookups == 0:
            detail = f"No successful Yahoo-style fundamentals lookups ({ratio})"
            if self.last_error:
                detail = f"{detail}: {self.last_error}"
            return SourceCheck(
                name="free fundamentals",
                status="warning",
                detail=detail,
            )

        return SourceCheck(name="free fundamentals", status="warning", detail=ratio)


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
        self.last_error: str | None = None

    def get_fundamentals(self, company: Company) -> FundamentalsSnapshot | None:
        for symbol in finimpulse_symbol_candidates(company):
            self.attempted_lookups += 1
            payload = json.dumps(
                {"symbols": [symbol], "quote_types": ["stock"], "limit": 1}
            )
            headers = {
                "Accept": "application/json,text/plain,*/*",
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
                "User-Agent": "Mozilla/5.0",
            }
            try:
                snapshot = _parse_finimpulse_search_payload(
                    payload=self._fetcher(FINIMPULSE_SEARCH_URL, payload, headers),
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
                name="finimpulse fundamentals", status="ok", detail=ratio
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
            name="finimpulse fundamentals", status="warning", detail=ratio
        )


class EnrichedResearchProvider:
    def __init__(
        self, base_provider, fundamentals_provider, max_enrichments: int | None = None
    ) -> None:
        self.base_provider = base_provider
        self.fundamentals_provider = fundamentals_provider
        self.max_enrichments = max_enrichments
        self._enrichment_attempts = 0
        self._eligible_enrichment_keys: set[tuple[str, str]] | None = None

    def list_companies(self, countries, include_first_north):
        return self.base_provider.list_companies(countries, include_first_north)

    def get_research(self, ticker: str) -> CompanyResearch:
        return self._enrich(self.base_provider.get_research(ticker))

    def get_company_research(self, company: Company) -> CompanyResearch:
        return self._enrich(self.get_base_company_research(company))

    def get_base_company_research(self, company: Company) -> CompanyResearch:
        get_company_research = getattr(
            self.base_provider, "get_company_research", None
        )
        if callable(get_company_research):
            return get_company_research(company)
        return self.base_provider.get_research(company.ticker)

    def prepare_watchlist_enrichment(self, companies: tuple[Company, ...]) -> None:
        self._enrichment_attempts = 0
        self._eligible_enrichment_keys = {
            (company.ticker, company.country) for company in companies
        }

    def source_checks(self):
        checks = list(self.base_provider.source_checks())
        source_check = getattr(self.fundamentals_provider, "source_check", None)
        if callable(source_check):
            checks.append(source_check())
        return checks

    def _enrich(self, research: CompanyResearch) -> CompanyResearch:
        key = (research.company.ticker, research.company.country)
        if (
            self._eligible_enrichment_keys is not None
            and key not in self._eligible_enrichment_keys
        ):
            return research
        if (
            self.max_enrichments is not None
            and self._enrichment_attempts >= self.max_enrichments
        ):
            return research
        self._enrichment_attempts += 1
        snapshot = self.fundamentals_provider.get_fundamentals(research.company)
        if snapshot is None:
            return research

        company = research.company
        market_cap_enriched = False
        if company.market_cap_eur_m is None and snapshot.market_cap_eur_m is not None:
            company = replace(company, market_cap_eur_m=snapshot.market_cap_eur_m)
            market_cap_enriched = True

        financials = _merge_financials(
            research.financials,
            snapshot.financials,
            market_cap_enriched=market_cap_enriched,
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
    market_cap_enriched: bool = False,
) -> FinancialSnapshot:
    preserved_fields = {
        "price",
        "currency",
        "one_year_return_pct",
        "distance_from_52w_high_pct",
    }
    merged_values = {}
    enrichment_applied = False

    for field_name in FinancialSnapshot.__dataclass_fields__:
        if field_name in preserved_fields or field_name == "data_quality":
            continue

        if getattr(base, field_name) is not None:
            continue

        enrichment_value = getattr(enrichment, field_name)
        if enrichment_value is not None:
            merged_values[field_name] = enrichment_value
            enrichment_applied = True

    if (
        (enrichment_applied or market_cap_enriched)
        and base.data_quality == DataQuality.THIN
    ):
        merged_values["data_quality"] = DataQuality.PARTIAL

    return replace(base, **merged_values)


def yahoo_symbol_candidates(company: Company) -> tuple[str, ...]:
    return _symbol_candidates(company)


def finnhub_symbol_candidates(company: Company) -> tuple[str, ...]:
    return _symbol_candidates(company)


def finimpulse_symbol_candidates(company: Company) -> tuple[str, ...]:
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
    fx_rate = _EUR_RATES.get(currency)

    market_cap_eur_m = _currency_m_to_eur_m(
        _number(profile, "marketCapitalization"), fx_rate
    )
    financials = FinancialSnapshot(
        pe_ratio=_first_number(metric, ("peBasicExclExtraTTM", "peNormalizedAnnual")),
        price_to_book=_first_number(metric, ("pbQuarterly", "pbAnnual")),
        revenue_growth_pct=_first_number(
            metric, ("revenueGrowthTTMYoy", "revenueGrowthQuarterlyYoy")
        ),
        operating_margin_pct=_first_number(
            metric, ("operatingMarginTTM", "operatingMarginAnnual")
        ),
        debt_to_equity=_debt_to_equity_ratio(
            _first_number(
                metric,
                (
                    "totalDebt/totalEquityQuarterly",
                    "totalDebt/totalEquityAnnual",
                ),
            )
        ),
        data_quality=DataQuality.PARTIAL,
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


def _parse_finimpulse_search_payload(
    payload: str, symbol: str, fallback_currency: str | None
) -> FundamentalsSnapshot | None:
    result = _dict_value(json.loads(payload), "result")
    items = result.get("items")
    if not isinstance(items, list) or not items or not isinstance(items[0], dict):
        return None

    item = items[0]
    currency = str(item.get("currency") or fallback_currency or "").upper()
    fx_rate = _EUR_RATES.get(currency)
    market_cap_eur_m = _eur_m(_number(item, "amount"), fx_rate)

    average_daily_value_eur = None
    price = _number(item, "regular_market_price")
    average_daily_volume = _number(item, "average_daily_volume_10_day")
    if fx_rate is not None and price is not None and average_daily_volume is not None:
        average_daily_value_eur = round(price * average_daily_volume * fx_rate, 2)

    financials = FinancialSnapshot(
        revenue_growth_pct=_ratio_to_percent(_number(item, "revenue_growth")),
        operating_margin_pct=_ratio_to_percent(
            _first_number(item, ("net_margin", "free_cash_flow_margin"))
        ),
        debt_to_equity=_number(item, "debt_to_equity"),
        one_year_return_pct=_number(item, "one_year_return"),
        distance_from_52w_high_pct=_number(
            item, "fifty_two_week_high_change_percent"
        ),
        average_daily_value_eur=average_daily_value_eur,
        data_quality=DataQuality.PARTIAL,
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
            url=FINIMPULSE_SEARCH_DOC_URL,
            source="finimpulse",
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
    fx_rate = _EUR_RATES.get(currency)

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
        average_daily_value_eur = average_daily_volume * previous_close * fx_rate

    financials = FinancialSnapshot(
        pe_ratio=trailing_pe,
        price_to_book=price_to_book,
        revenue_growth_pct=_percent(revenue_growth),
        operating_margin_pct=_percent(operating_margin),
        debt_to_equity=round(debt_to_equity / 100, 4)
        if debt_to_equity is not None
        else None,
        net_cash_eur_m=net_cash_eur_m,
        average_daily_value_eur=average_daily_value_eur,
        data_quality=DataQuality.PARTIAL,
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


def _raw(source: dict[str, Any], key: str) -> float | None:
    value = source.get(key)
    if isinstance(value, dict):
        value = value.get("raw")
    if isinstance(value, bool) or value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _number(source: dict[str, Any], key: str) -> float | None:
    value = source.get(key)
    if isinstance(value, bool) or value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _first_number(source: dict[str, Any], keys: tuple[str, ...]) -> float | None:
    for key in keys:
        value = _number(source, key)
        if value is not None:
            return value
    return None


def _percent(value: float | None) -> float | None:
    if value is None:
        return None
    return round(value * 100, 2)


def _ratio_to_percent(value: float | None) -> float | None:
    if value is None:
        return None
    if -1 <= value <= 1:
        value *= 100
    return round(value, 2)


def _eur_m(value: float | None, fx_rate: float | None) -> float | None:
    if value is None or fx_rate is None:
        return None
    return round(value * fx_rate / 1_000_000, 2)


def _currency_m_to_eur_m(value: float | None, fx_rate: float | None) -> float | None:
    if value is None or fx_rate is None:
        return None
    return round(value * fx_rate, 2)


def _debt_to_equity_ratio(value: float | None) -> float | None:
    if value is None:
        return None
    return round(value / 100, 4)


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
            financials.revenue_growth_pct,
            financials.operating_margin_pct,
            financials.debt_to_equity,
            financials.net_cash_eur_m,
            financials.average_daily_value_eur,
            financials.one_year_return_pct,
            financials.distance_from_52w_high_pct,
        )
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


def _fetch_url(url: str) -> str:
    request = Request(
        url,
        headers={
            "Accept": "application/json,text/plain,*/*",
            "User-Agent": "Mozilla/5.0",
        },
    )
    with urlopen(request, timeout=YAHOO_FETCH_TIMEOUT_SECONDS) as response:
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


def _post_json(url: str, payload: str, headers: dict[str, str]) -> str:
    request = Request(
        url,
        data=payload.encode("utf-8"),
        headers=headers,
        method="POST",
    )
    with urlopen(request, timeout=FINIMPULSE_FETCH_TIMEOUT_SECONDS) as response:
        return response.read().decode("utf-8")
