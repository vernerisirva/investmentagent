from __future__ import annotations

import json
import math
import ssl
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Callable, Iterable, Protocol
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

import certifi


EODHD_EOD_URL = "https://eodhd.com/api/eod/{symbol}"
EODHD_EOD_DOCUMENTATION_URL = (
    "https://eodhd.com/financial-apis/api-for-historical-data-and-volumes/"
)
ADJUSTED_PRICE_TYPE = "adjusted_close_total_return"
PRICE_HISTORY_STATUSES = {
    "ok",
    "symbol_unresolved",
    "provider_error",
    "corporate_action_unsupported",
}


@dataclass(frozen=True)
class SecurityReference:
    company_id: str
    isin: str | None
    ticker: str
    country: str
    exchange: str
    currency: str | None = None


@dataclass(frozen=True)
class HistoricalPriceObservation:
    provider: str
    symbol: str
    market: str
    session_date: date
    close: float | None
    adjusted_close: float
    currency: str | None
    retrieved_at: datetime
    price_type: str = ADJUSTED_PRICE_TYPE
    is_adjusted: bool = True

    def __post_init__(self) -> None:
        if not self.provider.strip() or not self.symbol.strip() or not self.market.strip():
            raise ValueError("price observation provider, symbol, and market are required")
        if self.price_type != ADJUSTED_PRICE_TYPE or self.is_adjusted is not True:
            raise ValueError("primary price observations must be adjusted closes")
        if not _positive_finite(self.adjusted_close):
            raise ValueError("adjusted close must be a positive finite number")
        if self.close is not None and not _positive_finite(self.close):
            raise ValueError("raw close must be a positive finite number when present")
        if self.retrieved_at.tzinfo is None:
            raise ValueError("price retrieval timestamp must be timezone-aware")
        object.__setattr__(self, "provider", self.provider.strip().lower())
        object.__setattr__(self, "symbol", self.symbol.strip().upper())
        object.__setattr__(self, "market", self.market.strip().lower())
        object.__setattr__(
            self, "retrieved_at", self.retrieved_at.astimezone(timezone.utc)
        )
        if self.currency is not None:
            object.__setattr__(self, "currency", self.currency.strip().upper() or None)


@dataclass(frozen=True)
class HistoricalPriceHistory:
    status: str
    provider: str
    symbol: str | None
    market: str
    observations: tuple[HistoricalPriceObservation, ...] = ()
    detail: str | None = None

    def __post_init__(self) -> None:
        if self.status not in PRICE_HISTORY_STATUSES:
            raise ValueError(f"unsupported price-history status: {self.status}")
        dates = [observation.session_date for observation in self.observations]
        if dates != sorted(dates) or len(dates) != len(set(dates)):
            raise ValueError("price observations must have unique ascending sessions")
        if self.status == "ok" and not self.observations:
            raise ValueError("an ok price history must contain observations")

    def observation_on(self, session_date: date) -> HistoricalPriceObservation | None:
        return next(
            (
                observation
                for observation in self.observations
                if observation.session_date == session_date
            ),
            None,
        )


class HistoricalPriceProvider(Protocol):
    name: str

    def get_history(
        self,
        security: SecurityReference,
        *,
        start_date: date,
        end_date: date,
        market: str,
        retrieved_at: datetime,
        symbol: str | None = None,
    ) -> HistoricalPriceHistory: ...


class FixtureHistoricalPriceProvider:
    name = "fixture"

    def __init__(
        self,
        histories: dict[str, Iterable[HistoricalPriceObservation]],
        *,
        unresolved: Iterable[str] = (),
        provider_errors: dict[str, str] | None = None,
        unsupported_adjustments: Iterable[str] = (),
    ) -> None:
        self._histories = {
            company_id: tuple(sorted(rows, key=lambda row: row.session_date))
            for company_id, rows in histories.items()
        }
        self._unresolved = set(unresolved)
        self._provider_errors = dict(provider_errors or {})
        self._unsupported_adjustments = set(unsupported_adjustments)

    @classmethod
    def from_path(cls, path: Path) -> FixtureHistoricalPriceProvider:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError(f"unable to load price fixture: {path}") from exc
        if not isinstance(payload, dict) or not isinstance(payload.get("histories"), dict):
            raise ValueError("price fixture must contain a histories object")
        histories: dict[str, tuple[HistoricalPriceObservation, ...]] = {}
        unsupported = set(_string_list(payload.get("unsupported_adjustments", [])))
        for company_id, raw_rows in payload["histories"].items():
            if not isinstance(company_id, str) or not isinstance(raw_rows, list):
                raise ValueError("malformed price fixture history")
            rows: list[HistoricalPriceObservation] = []
            for raw_row in raw_rows:
                if not isinstance(raw_row, dict):
                    raise ValueError("malformed price fixture observation")
                adjusted_close = raw_row.get("adjusted_close")
                if adjusted_close is None and raw_row.get("close") is not None:
                    unsupported.add(company_id)
                    continue
                rows.append(
                    HistoricalPriceObservation(
                        provider="fixture",
                        symbol=str(raw_row.get("symbol") or "FIXTURE").upper(),
                        market=str(raw_row.get("market") or "stockholm"),
                        session_date=date.fromisoformat(str(raw_row["session_date"])),
                        close=_optional_number(raw_row.get("close")),
                        adjusted_close=_required_number(adjusted_close),
                        currency=_optional_string(raw_row.get("currency")),
                        retrieved_at=_parse_timestamp(raw_row.get("retrieved_at")),
                    )
                )
            histories[company_id] = tuple(rows)
        provider_errors = payload.get("provider_errors", {})
        if not isinstance(provider_errors, dict):
            raise ValueError("price fixture provider_errors must be an object")
        return cls(
            histories,
            unresolved=_string_list(payload.get("unresolved", [])),
            provider_errors={str(key): str(value) for key, value in provider_errors.items()},
            unsupported_adjustments=unsupported,
        )

    def get_history(
        self,
        security: SecurityReference,
        *,
        start_date: date,
        end_date: date,
        market: str,
        retrieved_at: datetime,
        symbol: str | None = None,
    ) -> HistoricalPriceHistory:
        del retrieved_at
        if security.company_id in self._provider_errors:
            return HistoricalPriceHistory(
                "provider_error",
                self.name,
                symbol,
                market,
                detail=self._provider_errors[security.company_id],
            )
        if security.company_id in self._unsupported_adjustments:
            return HistoricalPriceHistory(
                "corporate_action_unsupported",
                self.name,
                symbol,
                market,
                detail="fixture contains raw closes without adjusted closes",
            )
        if security.company_id in self._unresolved or security.company_id not in self._histories:
            return HistoricalPriceHistory(
                "symbol_unresolved",
                self.name,
                symbol,
                market,
                detail="fixture has no symbol mapping",
            )
        rows = tuple(
            row
            for row in self._histories[security.company_id]
            if start_date <= row.session_date <= end_date
        )
        if not rows:
            return HistoricalPriceHistory(
                "symbol_unresolved",
                self.name,
                symbol,
                market,
                detail="fixture has no observations in the requested range",
            )
        resolved_symbol = symbol or rows[0].symbol
        return HistoricalPriceHistory("ok", self.name, resolved_symbol, market, rows)


class EodhdHistoricalPriceProvider:
    name = "eodhd"

    def __init__(
        self,
        api_key: str | None,
        fetcher: Callable[[str], str] | None = None,
    ) -> None:
        self.api_key = api_key.strip() if api_key is not None else None
        self._fetcher = fetcher or _fetch_eodhd_url
        self._consecutive_provider_errors = 0
        self._circuit_error: str | None = None

    def get_history(
        self,
        security: SecurityReference,
        *,
        start_date: date,
        end_date: date,
        market: str,
        retrieved_at: datetime,
        symbol: str | None = None,
    ) -> HistoricalPriceHistory:
        if start_date > end_date:
            raise ValueError("price-history start date cannot be after end date")
        if retrieved_at.tzinfo is None:
            raise ValueError("price retrieval timestamp must be timezone-aware")
        if not self.api_key:
            return HistoricalPriceHistory(
                "provider_error",
                self.name,
                symbol,
                market,
                detail="EODHD_API_KEY is not configured",
            )
        if self._circuit_error is not None:
            return HistoricalPriceHistory(
                "provider_error",
                self.name,
                symbol,
                market,
                detail=self._circuit_error,
            )
        candidates = (symbol,) if symbol else eodhd_symbol_candidates(security)
        if not candidates:
            return HistoricalPriceHistory(
                "symbol_unresolved",
                self.name,
                None,
                market,
                detail="no EODHD symbol candidate for this country",
            )
        errors: list[str] = []
        unsupported_symbols: list[str] = []
        received_valid_response = False
        for candidate in candidates:
            try:
                payload = self._fetcher(
                    _eodhd_history_url(
                        candidate,
                        self.api_key,
                        start_date=start_date,
                        end_date=end_date,
                    )
                )
                parsed = _parse_eodhd_history(
                    payload,
                    symbol=candidate,
                    market=market,
                    currency=security.currency,
                    retrieved_at=retrieved_at,
                )
            except Exception as exc:
                errors.append(_token_safe_error(exc, self.api_key))
                continue
            received_valid_response = True
            if parsed is None:
                unsupported_symbols.append(candidate)
                continue
            if parsed:
                self._clear_error_circuit()
                return HistoricalPriceHistory(
                    "ok", self.name, candidate, market, parsed
                )
        if unsupported_symbols:
            self._clear_error_circuit()
            return HistoricalPriceHistory(
                "corporate_action_unsupported",
                self.name,
                unsupported_symbols[0],
                market,
                detail="EODHD rows omitted adjusted_close; raw close was not substituted",
            )
        if errors and len(errors) == len(candidates):
            detail = errors[-1]
            self._consecutive_provider_errors += 1
            if self._consecutive_provider_errors >= 3:
                self._circuit_error = (
                    "EODHD request circuit opened after three consecutive provider "
                    f"errors; last error: {detail}"
                )
                detail = self._circuit_error
            return HistoricalPriceHistory(
                "provider_error",
                self.name,
                symbol,
                market,
                detail=detail,
            )
        if received_valid_response:
            self._clear_error_circuit()
        return HistoricalPriceHistory(
            "symbol_unresolved",
            self.name,
            symbol,
            market,
            detail="EODHD returned no observations for any symbol candidate",
        )

    def _clear_error_circuit(self) -> None:
        self._consecutive_provider_errors = 0
        self._circuit_error = None


def eodhd_symbol_candidates(security: SecurityReference) -> tuple[str, ...]:
    suffix = {"SE": ".ST", "FI": ".HE"}.get(security.country.strip().upper())
    if suffix is None:
        return ()
    normalized = "-".join(security.ticker.strip().upper().split())
    compact = normalized.replace("-", "")
    candidates = [f"{normalized}{suffix}"]
    if compact != normalized:
        candidates.append(f"{compact}{suffix}")
    return tuple(dict.fromkeys(candidates))


def _parse_eodhd_history(
    payload: str,
    *,
    symbol: str,
    market: str,
    currency: str | None,
    retrieved_at: datetime,
) -> tuple[HistoricalPriceObservation, ...] | None:
    data = json.loads(payload)
    if isinstance(data, dict):
        message = data.get("message") or data.get("error")
        raise ValueError(str(message or "unexpected EODHD response object"))
    if not isinstance(data, list):
        raise ValueError("unexpected EODHD response type")
    rows: list[HistoricalPriceObservation] = []
    saw_unadjusted_only = False
    for raw_row in data:
        if not isinstance(raw_row, dict):
            raise ValueError("malformed EODHD price row")
        adjusted_close = _optional_number(raw_row.get("adjusted_close"))
        close = _optional_number(raw_row.get("close"))
        if adjusted_close is None:
            if close is not None:
                saw_unadjusted_only = True
            continue
        rows.append(
            HistoricalPriceObservation(
                provider="eodhd",
                symbol=symbol,
                market=market,
                session_date=date.fromisoformat(str(raw_row["date"])),
                close=close,
                adjusted_close=adjusted_close,
                currency=currency,
                retrieved_at=retrieved_at,
            )
        )
    if saw_unadjusted_only:
        return None
    return tuple(sorted(rows, key=lambda row: row.session_date))


def _eodhd_history_url(
    symbol: str,
    token: str,
    *,
    start_date: date,
    end_date: date,
) -> str:
    query = urlencode(
        {
            "api_token": token,
            "fmt": "json",
            "period": "d",
            "order": "a",
            "from": start_date.isoformat(),
            "to": end_date.isoformat(),
        }
    )
    return f"{EODHD_EOD_URL.format(symbol=quote(symbol, safe=''))}?{query}"


def _fetch_eodhd_url(url: str) -> str:
    request = Request(
        url,
        headers={
            "Accept": "application/json,text/plain,*/*",
            "User-Agent": "InvestmentAgent/0.1",
        },
    )
    context = ssl.create_default_context(cafile=certifi.where())
    with urlopen(request, timeout=10, context=context) as response:
        return response.read().decode("utf-8")


def _parse_timestamp(value: object) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("fixture retrieved_at must be a timezone-aware ISO timestamp")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("fixture retrieved_at must be timezone-aware")
    return parsed.astimezone(timezone.utc)


def _required_number(value: object) -> float:
    parsed = _optional_number(value)
    if parsed is None:
        raise ValueError("fixture adjusted_close must be numeric")
    return parsed


def _optional_number(value: object) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)) and math.isfinite(value):
        return float(value)
    raise ValueError("price value must be a finite number")


def _optional_string(value: object) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError("price currency must be a string")
    return value.strip() or None


def _string_list(value: object) -> list[str]:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ValueError("price fixture status lists must contain strings")
    return value


def _positive_finite(value: float) -> bool:
    return (
        not isinstance(value, bool)
        and isinstance(value, (int, float))
        and math.isfinite(value)
        and value > 0
    )


def _token_safe_error(exc: Exception, token: str) -> str:
    return str(exc).replace(token, "[redacted]") or exc.__class__.__name__
