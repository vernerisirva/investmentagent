"""ISIN-verified EODHD symbols for securities whose ticker-derived symbols never priced.

EODHD codes usually equal the ticker in the evaluation universe, but not always (share-class
suffixes, renamed instruments), and such a security never prices. When a security has failed
and has no established symbol, its ISIN is looked up in EODHD's exchange symbol list. A mapping
is accepted only for exactly one row with the same ISIN, the security's currency and a shared
name word; anything else fails closed. Nothing is calculated differently: the mapped symbol only
replaces the ticker guesses for that security, and it becomes established only when a response
for it prices. Decisions and list provenance are kept under the outcome root.
"""
from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Iterable

from investmentagent.market_prices import EODHD_EXCHANGE_BY_COUNTRY, SecurityReference
from investmentagent.price_histories import atomic_json


SYMBOL_MAPPING_METHODOLOGY = "eodhd-exchange-symbol-list-isin-v1"
SYMBOL_MAPPING_FILE = Path("symbol-mappings") / "eodhd-isin-v1.json"
# An exchange list is requested at most once per exchange in this many days, ok or not.
SYMBOL_LIST_REFRESH_DAYS = 28
_CODE = re.compile(r"^[A-Z0-9][A-Z0-9._-]*$")
_GENERIC_NAME_WORDS = frozenset({
    "abp", "and", "class", "company", "corp", "corporation", "group", "holding", "holdings", "inc",
    "limited", "ltd", "osk", "oyj", "plc", "publ", "series", "share", "shares", "the",
})


@dataclass
class SymbolMappings:
    exchange_lists: dict[str, dict[str, Any]] = field(default_factory=dict)
    decisions: dict[str, dict[str, Any]] = field(default_factory=dict)

    @classmethod
    def load(cls, path: Path) -> SymbolMappings:
        if not path.exists():
            return cls()
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict) or payload.get("mapping_methodology") != SYMBOL_MAPPING_METHODOLOGY:
            raise ValueError("unsupported symbol mapping methodology")
        return cls(dict(payload["exchange_lists"]), dict(payload["decisions"]))

    def save(self, path: Path) -> None:
        atomic_json(path, {"mapping_methodology": SYMBOL_MAPPING_METHODOLOGY,
                           "exchange_lists": self.exchange_lists, "decisions": self.decisions})

    def mapped_symbols(self) -> dict[str, str]:
        return {isin: decision["symbol"] for isin, decision in self.decisions.items()
                if decision["decision"] == "mapped"}

    def list_due(self, exchange: str, now: datetime) -> bool:
        attempt = self.exchange_lists.get(exchange)
        return attempt is None or now - datetime.fromisoformat(attempt["attempted_at"]) >= timedelta(
            days=SYMBOL_LIST_REFRESH_DAYS)

    def record_list(self, exchange: str, attempted_at: datetime, rows: tuple[dict[str, Any], ...] | None,
                    error: str | None) -> None:
        entry: dict[str, Any] = {"attempted_at": attempted_at.isoformat(), "status": "error" if rows is None else "ok"}
        if rows is None:
            entry["detail"] = error
        else:
            entry.update(rows=len(rows), rows_with_isin=sum(bool(_normalized(row.get("Isin"))) for row in rows),
                         response_sha256=hashlib.sha256(json.dumps(
                             rows, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")).hexdigest())
        self.exchange_lists[exchange] = entry

    def decide(self, security: SecurityReference, name: str | None, rows: Iterable[dict[str, Any]],
               exchange: str, decided_at: datetime) -> dict[str, Any]:
        isin = _normalized(security.isin)
        matches = [row for row in rows if isin and _normalized(row.get("Isin")) == isin]
        record: dict[str, Any] = {
            "company_id": security.company_id, "ticker": security.ticker, "name": name,
            "exchange": exchange, "decided_at": decided_at.isoformat(),
            "listed": [{key.lower(): row.get(key) for key in ("Code", "Name", "Exchange", "Currency", "Type")}
                       for row in matches],
        }
        code = _normalized(matches[0].get("Code")) if len(matches) == 1 else ""
        if not isin:
            record["decision"] = "no_isin"
        elif not matches:
            record["decision"] = "not_listed"
        elif len(matches) > 1:
            record["decision"] = "ambiguous"
        elif not _CODE.fullmatch(code):
            record["decision"] = "invalid_code"
        elif security.currency and _normalized(matches[0].get("Currency")) != security.currency.upper():
            record["decision"] = "currency_mismatch"
        elif not _name_words(name) & _name_words(matches[0].get("Name")):
            record["decision"] = "name_mismatch"
        else:
            record.update(decision="mapped", symbol=f"{code}.{exchange}")
        if isin:
            self.decisions[isin] = record
        return record


class IsinSymbolResolver:
    """Looks up symbol-seeking securities, spending at most one call per exchange and refresh period."""

    def __init__(self, provider: Any, outcome_root: Path, *, dry_run: bool) -> None:
        self.provider, self.path, self.dry_run = provider, outcome_root / SYMBOL_MAPPING_FILE, dry_run
        self.mappings = SymbolMappings.load(self.path)
        self.list_calls, self._changed = 0, False
        provider.isin_symbols.update(self.mappings.mapped_symbols())

    @staticmethod
    def supported(provider: Any) -> bool:
        return isinstance(getattr(provider, "isin_symbols", None), dict) and callable(
            getattr(provider, "exchange_symbol_list", None))

    def mapped_symbol(self, security: SecurityReference) -> str | None:
        return self.provider.isin_symbols.get(_normalized(security.isin))

    def refresh_lists(self, seekers: Iterable[tuple[SecurityReference, str | None]], *, now: datetime,
                      calls_left: int) -> int:
        """Request each due exchange list that a symbol-seeking security needs, within the calls left.

        Returns the calls used; a dry run reserves one per list without requesting anything. Every
        symbol-seeking security on an exchange is decided from the same list, whether it is due
        today or in backoff, so its mapping is ready whenever its turn comes.
        """
        seekers = list(seekers)
        exchanges = sorted({EODHD_EXCHANGE_BY_COUNTRY.get(s.country.strip().upper()) for s, _ in seekers} - {None})
        spent = 0
        for exchange in exchanges:
            if calls_left - spent < 1 or not self.mappings.list_due(exchange, now):
                continue
            if self.dry_run:
                spent += 1
                continue
            before = self.provider.api_call_count
            try:
                rows, error = self.provider.exchange_symbol_list(exchange), None
            except RuntimeError as exc:
                rows, error = None, str(exc)
            used = self.provider.api_call_count - before
            # A request the provider refused to send (no key, open circuit) is not an attempt.
            if used:
                self.mappings.record_list(exchange, now, rows, error)
                for seeker, name in seekers if rows is not None else ():
                    if EODHD_EXCHANGE_BY_COUNTRY.get(seeker.country.strip().upper()) == exchange:
                        self.mappings.decide(seeker, name, rows, exchange, now)
                self._changed = True
            spent += used
        if self._changed:
            # The newest list decides: a mapping the list no longer supports is dropped.
            self.provider.isin_symbols.clear()
            self.provider.isin_symbols.update(self.mappings.mapped_symbols())
        self.list_calls += spent
        return spent

    def save(self) -> None:
        if self._changed and not self.dry_run:
            self.mappings.save(self.path)


def _normalized(value: Any) -> str:
    return str(value or "").strip().upper()


def _name_words(name: Any) -> set[str]:
    plain = unicodedata.normalize("NFKD", str(name or "")).encode("ascii", "ignore").decode("ascii").lower()
    return {word for word in re.findall(r"[a-z0-9]+", plain) if len(word) >= 3 and word not in _GENERIC_NAME_WORDS}
