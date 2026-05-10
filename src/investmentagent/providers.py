from __future__ import annotations

import csv
import json
from collections.abc import Callable
from importlib.resources import files
from io import StringIO
from typing import Protocol
from urllib.request import urlopen

from investmentagent.models import (
    Company,
    CompanyResearch,
    DataQuality,
    Evidence,
    FinancialSnapshot,
    ListingSegment,
    SourceCheck,
)


NASDAQ_NORDIC_LISTINGS_URL = "https://www.nasdaqomxnordic.com/shares/listed-companies"


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
                return CompanyResearch(
                    company=company,
                    financials=FinancialSnapshot(data_quality=DataQuality.THIN),
                    risks=("Sparse live-source data",),
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
            self._companies = _parse_live_company_payload(self._fetcher(self.source_url))
            self._last_error = None
        except Exception as exc:
            self._companies = []
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
    with urlopen(url, timeout=20) as response:
        return response.read().decode("utf-8")


def _parse_live_company_payload(payload: str) -> list[Company]:
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
    return companies


def _parse_listing_segment(raw: str) -> ListingSegment:
    normalized = raw.strip().lower().replace("-", " ")
    if "first north" in normalized or normalized == "first_north":
        return ListingSegment.FIRST_NORTH
    if "spotlight" in normalized:
        return ListingSegment.SPOTLIGHT
    if "main" in normalized:
        return ListingSegment.MAIN_MARKET
    return ListingSegment.OTHER_PUBLIC
