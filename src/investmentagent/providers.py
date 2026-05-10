from __future__ import annotations

import csv
import json
from collections.abc import Callable
from importlib.resources import files
from io import StringIO
from typing import Protocol
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from investmentagent.models import (
    Company,
    CompanyResearch,
    DataQuality,
    Evidence,
    FinancialSnapshot,
    ListingSegment,
    SourceCheck,
)


NASDAQ_NORDIC_LISTINGS_URL = "https://api.nasdaq.com/api/nordic/screener/shares"
NASDAQ_NORDIC_SCREENER_SOURCE = "nasdaq_nordic_screener"
NASDAQ_NORDIC_SCREENER_REQUESTS = (
    {
        "category": "MAIN_MARKET",
        "market": "STO",
        "country": "SE",
        "exchange": "Nasdaq Stockholm",
        "listing_segment": ListingSegment.MAIN_MARKET.value,
    },
    {
        "category": "MAIN_MARKET",
        "market": "HEL",
        "country": "FI",
        "exchange": "Nasdaq Helsinki",
        "listing_segment": ListingSegment.MAIN_MARKET.value,
    },
    {
        "category": "FIRST_NORTH",
        "market": "STO",
        "country": "SE",
        "exchange": "Nasdaq First North Growth Market Sweden",
        "listing_segment": ListingSegment.FIRST_NORTH.value,
    },
    {
        "category": "FIRST_NORTH",
        "market": "HEL",
        "country": "FI",
        "exchange": "Nasdaq First North Growth Market Finland",
        "listing_segment": ListingSegment.FIRST_NORTH.value,
    },
)


class ResearchProvider(Protocol):
    def list_companies(
        self, countries: tuple[str, ...], include_first_north: bool
    ) -> list[Company]:
        ...

    def get_research(self, ticker: str) -> CompanyResearch:
        ...

    def source_checks(self) -> list[SourceCheck]:
        ...


class FixtureResearchProvider:
    def __init__(self) -> None:
        data_path = files("investmentagent").joinpath("data/nordic_seed_companies.json")
        self._rows = json.loads(data_path.read_text(encoding="utf-8"))

    def list_companies(
        self, countries: tuple[str, ...] = ("SE", "FI"), include_first_north: bool = True
    ) -> list[Company]:
        wanted = {country.upper() for country in countries}
        companies = [self._company_from_row(row) for row in self._rows]
        return [
            company
            for company in companies
            if company.country in wanted
            and (include_first_north or company.segment != ListingSegment.FIRST_NORTH)
        ]

    def get_research(self, ticker: str) -> CompanyResearch:
        normalized = ticker.strip().upper()
        for row in self._rows:
            if row["ticker"].upper() == normalized:
                return self._research_from_row(row)
        raise LookupError(f"No bundled research found for ticker: {ticker}")

    def source_checks(self) -> list[SourceCheck]:
        return [
            SourceCheck(
                name="bundled seed data",
                status="ok",
                detail=f"{len(self._rows)} companies available from local fixture data",
            )
        ]

    def _company_from_row(self, row: dict) -> Company:
        return Company(
            name=row["name"],
            ticker=row["ticker"],
            country=row["country"],
            exchange=row["exchange"],
            segment=ListingSegment(row["segment"]),
            sector=row.get("sector"),
            market_cap_eur_m=row.get("market_cap_eur_m"),
            currency=row.get("currency"),
            ir_url=row.get("ir_url"),
        )

    def _research_from_row(self, row: dict) -> CompanyResearch:
        financial_data = dict(row["financials"])
        financial_data["data_quality"] = DataQuality(financial_data["data_quality"])
        evidence = tuple(Evidence(**item) for item in row.get("evidence", []))
        financials = FinancialSnapshot(**financial_data)
        return CompanyResearch(
            company=self._company_from_row(row),
            financials=financials,
            catalysts=tuple(row.get("catalysts", [])),
            risks=tuple(row.get("risks", [])),
            evidence=evidence,
            data_quality=financials.data_quality,
        )


class LiveNasdaqNordicProvider:
    def __init__(
        self,
        source_url: str = NASDAQ_NORDIC_LISTINGS_URL,
        fetcher: Callable[[str], str] | None = None,
    ) -> None:
        self.source_url = source_url
        self._fetcher = fetcher or _default_fetcher
        self._companies: list[Company] | None = None
        self._market_rows: dict[str, dict] = {}
        self._last_error: str | None = None

    def list_companies(
        self, countries: tuple[str, ...] = ("SE", "FI"), include_first_north: bool = True
    ) -> list[Company]:
        wanted = {country.upper() for country in countries}
        return [
            company
            for company in self._load_companies()
            if company.country in wanted
            and (include_first_north or company.segment != ListingSegment.FIRST_NORTH)
        ]

    def get_research(self, ticker: str) -> CompanyResearch:
        normalized = ticker.strip().upper()
        for company in self._load_companies():
            if company.ticker == normalized:
                market_row = self._market_rows.get(company.ticker, {})
                return CompanyResearch(
                    company=company,
                    financials=FinancialSnapshot(
                        price=market_row.get("price"),
                        currency=market_row.get("currency"),
                        data_quality=DataQuality.THIN,
                    ),
                    catalysts=_live_market_catalysts(market_row),
                    risks=_live_market_risks(market_row),
                    evidence=(
                        Evidence(
                            label="Nasdaq Nordic listing source",
                            url=self.source_url,
                            source="nasdaq",
                        ),
                    ),
                    data_quality=DataQuality.THIN,
                )
        raise LookupError(f"No live research found for ticker: {ticker}")

    def source_checks(self) -> list[SourceCheck]:
        companies = self._load_companies()
        if self._last_error is not None:
            return [
                SourceCheck(
                    name="nasdaq nordic live data",
                    status="error",
                    detail=self._last_error,
                )
            ]
        return [
            SourceCheck(
                name="nasdaq nordic live data",
                status="ok",
                detail=f"{len(companies)} companies parsed from {self.source_url}",
            )
        ]

    def _load_companies(self) -> list[Company]:
        if self._companies is not None:
            return self._companies
        try:
            self._companies, self._market_rows = _parse_live_company_payload(
                self._fetcher(self.source_url)
            )
            self._last_error = None
        except Exception as exc:
            self._companies = []
            self._market_rows = {}
            self._last_error = str(exc)
        return self._companies


def create_provider(name: str) -> ResearchProvider:
    normalized = name.strip().lower()
    if normalized == "fixture":
        return FixtureResearchProvider()
    if normalized == "live":
        return LiveNasdaqNordicProvider()
    raise ValueError("provider must be 'fixture' or 'live'")


def _default_fetcher(url: str) -> str:
    if url == NASDAQ_NORDIC_LISTINGS_URL:
        return _fetch_nasdaq_nordic_screener_payload(url, _fetch_url)
    return _fetch_url(url)


def _fetch_url(url: str) -> str:
    request = Request(
        url,
        headers={
            "Accept": "application/json,text/plain,*/*",
            "User-Agent": "Mozilla/5.0",
        },
    )
    with urlopen(request, timeout=20) as response:
        return response.read().decode("utf-8")


def _fetch_nasdaq_nordic_screener_payload(
    base_url: str, fetcher: Callable[[str], str]
) -> str:
    responses = []
    for request in NASDAQ_NORDIC_SCREENER_REQUESTS:
        source_url = _build_nasdaq_nordic_screener_url(base_url, request)
        responses.append(
            {
                "country": request["country"],
                "exchange": request["exchange"],
                "segment": request["listing_segment"],
                "source_url": source_url,
                "payload": json.loads(fetcher(source_url)),
            }
        )
    return json.dumps({"source": NASDAQ_NORDIC_SCREENER_SOURCE, "responses": responses})


def _build_nasdaq_nordic_screener_url(base_url: str, request: dict[str, str]) -> str:
    params = {
        "category": request["category"],
        "market": request["market"],
        "tableonly": "false",
    }
    if request.get("segment"):
        params["segment"] = request["segment"]
    return f"{base_url}?{urlencode(params)}"


def _parse_live_company_payload(payload: str) -> tuple[list[Company], dict[str, dict]]:
    stripped = payload.strip()
    if stripped.startswith("{"):
        return _parse_live_company_json(stripped)

    reader = csv.DictReader(StringIO(payload))
    fieldnames = {field.strip().lower() for field in (reader.fieldnames or ())}
    has_ticker = bool(fieldnames & {"ticker", "symbol"})
    has_name = bool(fieldnames & {"name", "company"})
    if not has_ticker or not has_name or "country" not in fieldnames:
        raise ValueError("live payload is missing required listing columns")

    companies: list[Company] = []
    for row in reader:
        normalized_row = {
            (key or "").strip().lower(): value for key, value in row.items()
        }
        ticker = (normalized_row.get("ticker") or normalized_row.get("symbol") or "").strip()
        name = (normalized_row.get("name") or normalized_row.get("company") or "").strip()
        country = (normalized_row.get("country") or "").strip().upper()
        if not ticker or not name or country not in {"SE", "FI"}:
            continue
        companies.append(
            Company(
                name=name,
                ticker=ticker,
                country=country,
                exchange=(normalized_row.get("exchange") or "Nasdaq Nordic").strip(),
                segment=_parse_listing_segment(
                    normalized_row.get("segment") or normalized_row.get("market") or ""
                ),
                sector=(normalized_row.get("sector") or None),
                currency=(normalized_row.get("currency") or None),
            )
        )
    if not companies:
        raise ValueError("live payload contained no SE/FI listings")
    return companies, {}


def _parse_live_company_json(payload: str) -> tuple[list[Company], dict[str, dict]]:
    data = json.loads(payload)
    if data.get("source") == NASDAQ_NORDIC_SCREENER_SOURCE:
        return _parse_nasdaq_nordic_screener_responses(data.get("responses", []))
    if "data" in data:
        return _parse_nasdaq_nordic_screener_responses(
            (
                {
                    "country": "",
                    "exchange": "Nasdaq Nordic",
                    "segment": ListingSegment.OTHER_PUBLIC.value,
                    "payload": data,
                },
            )
        )
    raise ValueError("live JSON payload is missing supported listing data")


def _parse_nasdaq_nordic_screener_responses(
    responses,
) -> tuple[list[Company], dict[str, dict]]:
    companies: list[Company] = []
    market_rows: dict[str, dict] = {}
    seen: set[tuple[str, str, str]] = set()
    for response in responses:
        country = str(response.get("country") or "").upper()
        exchange = str(response.get("exchange") or "Nasdaq Nordic")
        segment = _parse_listing_segment(str(response.get("segment") or ""))
        payload = response.get("payload") or {}
        rows = (
            payload.get("data", {})
            .get("instrumentListing", {})
            .get("rows", [])
        )
        for row in rows:
            company = _company_from_nasdaq_screener_row(row, country, exchange, segment)
            if company is None:
                continue
            key = (company.ticker, company.country, company.exchange)
            if key in seen:
                continue
            seen.add(key)
            companies.append(company)
            market_rows[company.ticker] = _market_row_from_nasdaq_screener_row(row)
    if not companies:
        raise ValueError("live payload contained no SE/FI listings")
    return companies, market_rows


def _company_from_nasdaq_screener_row(
    row: dict, country: str, exchange: str, segment: ListingSegment
) -> Company | None:
    ticker = str(row.get("symbol") or "").strip().upper()
    name = str(row.get("fullName") or "").strip()
    inferred_country = country or _country_from_isin(str(row.get("isin") or ""))
    if not ticker or not name or inferred_country not in {"SE", "FI"}:
        return None
    return Company(
        name=name,
        ticker=ticker,
        country=inferred_country,
        exchange=exchange,
        segment=segment,
        sector=str(row.get("sector") or "").strip() or None,
        currency=str(row.get("currency") or "").strip() or None,
    )


def _country_from_isin(isin: str) -> str:
    prefix = isin.strip().upper()[:2]
    if prefix in {"SE", "FI"}:
        return prefix
    return ""


def _market_row_from_nasdaq_screener_row(row: dict) -> dict:
    return {
        "price": _parse_live_float(row.get("lastSalePrice")),
        "currency": str(row.get("currency") or "").strip() or None,
        "percentage_change": _parse_live_float(row.get("percentageChange")),
        "turnover": _parse_live_float(row.get("turnover")),
        "volume": _parse_live_float(row.get("volume")),
    }


def _parse_live_float(raw) -> float | None:
    if raw is None:
        return None
    cleaned = str(raw).strip().replace(",", "").replace("%", "")
    if not cleaned:
        return None
    try:
        return float(cleaned)
    except ValueError:
        return None


def _live_market_catalysts(market_row: dict) -> tuple[str, ...]:
    catalysts: list[str] = []
    if market_row.get("price") is not None:
        catalysts.append("Live price available from Nasdaq Nordic")
    percentage_change = market_row.get("percentage_change")
    if percentage_change is not None and percentage_change >= 10.0:
        catalysts.append(f"Strong intraday momentum (+{percentage_change:g}%)")
    elif percentage_change is not None and percentage_change >= 5.0:
        catalysts.append(f"Positive intraday momentum (+{percentage_change:g}%)")
    turnover = market_row.get("turnover")
    if turnover is not None and turnover >= 1_000_000:
        catalysts.append("High live turnover")
    elif turnover is not None and turnover >= 250_000:
        catalysts.append("Moderate live turnover")
    return tuple(catalysts)


def _live_market_risks(market_row: dict) -> tuple[str, ...]:
    risks = ["Sparse live-source data"]
    if not market_row:
        return tuple(risks)
    percentage_change = market_row.get("percentage_change")
    if percentage_change is not None and percentage_change <= -5.0:
        risks.append("Sharp intraday selloff")
    turnover = market_row.get("turnover")
    if turnover is not None and turnover < 100_000:
        risks.append("Low live turnover")
    if turnover is None and market_row.get("volume") is None:
        risks.append("Missing live turnover")
    return tuple(risks)


def _parse_listing_segment(raw: str) -> ListingSegment:
    normalized = raw.strip().lower().replace("-", " ")
    if "first north" in normalized or normalized == "first_north":
        return ListingSegment.FIRST_NORTH
    if "spotlight" in normalized:
        return ListingSegment.SPOTLIGHT
    if "main" in normalized:
        return ListingSegment.MAIN_MARKET
    return ListingSegment.OTHER_PUBLIC
