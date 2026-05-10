from __future__ import annotations

import json
from importlib.resources import files
from typing import Protocol

from investmentagent.models import (
    Company,
    CompanyResearch,
    DataQuality,
    Evidence,
    FinancialSnapshot,
    ListingSegment,
    SourceCheck,
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
    def list_companies(
        self, countries: tuple[str, ...] = ("SE", "FI"), include_first_north: bool = True
    ) -> list[Company]:
        return []

    def get_research(self, ticker: str) -> CompanyResearch:
        raise LookupError(f"No live research found for ticker: {ticker}")

    def source_checks(self) -> list[SourceCheck]:
        return [
            SourceCheck(
                name="nasdaq nordic live data",
                status="unavailable",
                detail="Live provider is not implemented yet",
            )
        ]


def create_provider(name: str) -> ResearchProvider:
    normalized = name.strip().lower()
    if normalized == "fixture":
        return FixtureResearchProvider()
    if normalized == "live":
        return LiveNasdaqNordicProvider()
    raise ValueError("provider must be 'fixture' or 'live'")
