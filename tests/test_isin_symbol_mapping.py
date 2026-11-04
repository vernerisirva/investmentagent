"""ISIN-verified EODHD symbols: only never-priced failing securities, exact matches, inside the budget."""
from dataclasses import replace
from datetime import datetime, timedelta, timezone
import json
import socket
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlsplit

import pytest

from investmentagent.evaluation import save_evaluation_snapshot
from investmentagent.evaluation_outcomes import DEFAULT_STRATEGY_HORIZONS, load_outcome_set, outcome_store_path, refresh_outcome_store
from investmentagent.market_calendar import advance_market_sessions, first_session_closing_after, market_for_country
from investmentagent.market_price_cache import FileHistoricalPriceCache
from investmentagent.market_prices import EODHD_MISSING_KEY_DETAIL, EodhdHistoricalPriceProvider, SecurityReference
from investmentagent.symbol_mapping import SYMBOL_LIST_REFRESH_DAYS, SYMBOL_MAPPING_FILE, SymbolMappings, _name_words
from test_evaluation_outcomes import _snapshot


UTC = timezone.utc
FIRST = datetime(2026, 8, 11, 18, tzinfo=UTC)
TOKEN = "synthetic-key"
WORKFLOW = Path(".github/workflows/daily-public-watchlist.yml")


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    def denied(*args, **kwargs):
        raise AssertionError("symbol mapping tests must stay offline")
    monkeypatch.setattr(socket.socket, "connect", denied)
    monkeypatch.setattr(socket.socket, "connect_ex", denied)
    monkeypatch.setattr(socket, "create_connection", denied)


def day(offset):
    return FIRST + timedelta(days=offset)


def history_rows(snapshot):
    market = market_for_country(snapshot.rows[0].country)
    entry = first_session_closing_after(snapshot.decision_at, market).day
    sessions = [entry, *(advance_market_sessions(entry, d.sessions, market).day
                         for d in DEFAULT_STRATEGY_HORIZONS[snapshot.strategy])]
    return [{"date": s.isoformat(), "close": 50.0 + i, "adjusted_close": 50.0 + i} for i, s in enumerate(sessions)]


def listing(code, isin, name, currency="EUR"):
    return {"Code": code, "Name": name, "Country": "Finland", "Exchange": "HE", "Currency": currency,
            "Type": "Common Stock", "Isin": isin}


class FakeEodhd:
    """Serves one exchange list and per-symbol histories; unknown symbols answer like EODHD's 404."""

    def __init__(self, snapshot, symbols_with_data, listings, *, list_error=None, empty=()):
        self.rows, self.symbols, self.listings = history_rows(snapshot), set(symbols_with_data), listings
        self.list_error, self.empty, self.urls = list_error, set(empty), []

    def __call__(self, url):
        self.urls.append(url)
        if "/exchange-symbol-list/" in url:
            if self.list_error:
                raise OSError(self.list_error)
            return json.dumps(self.listings)
        symbol = unquote(url.split("/api/eod/")[1].split("?")[0])
        if symbol in self.empty:
            return "[]"
        if symbol not in self.symbols:
            raise OSError("HTTP Error 404: Not Found")
        query = parse_qs(urlsplit(url).query)
        start, end = query["from"][0], query["to"][0]
        return json.dumps([row for row in self.rows if start <= row["date"] <= end])

    def list_requests(self):
        return [url for url in self.urls if "/exchange-symbol-list/" in url]

    def symbols_requested(self):
        return [unquote(url.split("/api/eod/")[1].split("?")[0]) for url in self.urls if "/api/eod/" in url]


def refresh(root, snapshot, at, fetcher, *, budget=20, dry_run=False, key=TOKEN):
    save_evaluation_snapshot(root / "evaluations", snapshot)
    provider = EodhdHistoricalPriceProvider(key, fetcher=fetcher, clock=lambda: at)
    summary = refresh_outcome_store(
        root / "evaluations", root / "outcomes", provider, retrieved_at=at,
        price_cache=FileHistoricalPriceCache(root / "prices.json"), max_price_api_calls=budget, dry_run=dry_run,
    )
    return provider, summary


def outcomes_of(root, snapshot, company_id):
    store = load_outcome_set(outcome_store_path(root / "outcomes", snapshot))
    return [o for o in store.outcomes if o.company_id == company_id and o.status != "not_due"]


def mapping_file(root):
    return root / "outcomes" / SYMBOL_MAPPING_FILE


@pytest.fixture
def case():
    """Two FI securities: C000 resolves by ticker; C001 is listed by EODHD under another code."""
    snapshot = _snapshot(2, strategy="trading", countries=("FI",))
    good, renamed = snapshot.rows
    listings = [
        listing("C000", good.isin, good.name),
        listing("C001B", renamed.isin, "Company 001 Oyj"),
        listing("ELSE", "FI9999999999", "Someone Else Oyj"),
    ]
    return snapshot, good, renamed, listings


def test_a_failing_never_priced_security_is_priced_through_its_isin(tmp_path, case):
    snapshot, good, renamed, listings = case
    fake = FakeEodhd(snapshot, {"C000.HE", "C001B.HE"}, listings)
    refresh(tmp_path, snapshot, day(0), fake)
    # The first failure is an ordinary ticker attempt: no list request, nothing recorded.
    assert fake.list_requests() == [] and not mapping_file(tmp_path).exists()
    assert {o.status for o in outcomes_of(tmp_path, snapshot, renamed.company_id)} == {"provider_error"}

    fake.urls.clear()
    provider, summary = refresh(tmp_path, snapshot, day(1), fake)
    assert len(fake.list_requests()) == 1 and fake.symbols_requested() == ["C001B.HE"]
    assert (summary.symbol_list_calls, summary.isin_symbol_fetches, summary.provider_calls_executed) == (1, 1, 2)
    assert provider.api_call_count == 2
    priced = outcomes_of(tmp_path, snapshot, renamed.company_id)
    assert priced and all(o.status == "priced" and o.provider_symbol == "C001B.HE" for o in priced)
    stored = json.loads(mapping_file(tmp_path).read_text())
    decision = stored["decisions"][renamed.isin]
    assert decision["decision"] == "mapped" and decision["symbol"] == "C001B.HE"
    assert decision["listed"] == [{"code": "C001B", "name": "Company 001 Oyj", "exchange": "HE",
                                   "currency": "EUR", "type": "Common Stock"}]
    assert stored["exchange_lists"]["HE"]["status"] == "ok" and stored["exchange_lists"]["HE"]["rows"] == 3
    assert stored["exchange_lists"]["HE"]["attempted_at"] == day(1).isoformat()
    assert TOKEN not in mapping_file(tmp_path).read_text()

    fake.urls.clear()
    _, later = refresh(tmp_path, snapshot, day(7), fake)
    assert fake.list_requests() == [] and later.symbol_list_calls == 0


def test_an_established_symbol_never_changes(tmp_path, case):
    snapshot, good, renamed, listings = case
    # EODHD's list now claims another code for the already priced security; it must not matter.
    listings[0] = listing("C000X", good.isin, good.name)
    fake = FakeEodhd(snapshot, {"C000.HE", "C000X.HE", "C001B.HE"}, listings)
    refresh(tmp_path, snapshot, day(0), fake)
    refresh(tmp_path, snapshot, day(1), fake)
    later_run = _snapshot(2, strategy="trading", countries=("FI",), decision_at=datetime(2026, 8, 12, 8, tzinfo=UTC))
    save_evaluation_snapshot(tmp_path / "evaluations", later_run)
    fake.urls.clear()
    refresh(tmp_path, snapshot, day(7), FakeEodhd(later_run, {"C000.HE", "C000X.HE", "C001B.HE"}, listings))
    good_outcomes = outcomes_of(tmp_path, snapshot, good.company_id) + outcomes_of(tmp_path, later_run, good.company_id)
    assert good_outcomes and {o.provider_symbol for o in good_outcomes if o.status == "priced"} == {"C000.HE"}
    decisions = json.loads(mapping_file(tmp_path).read_text())["decisions"]
    assert good.isin not in decisions


@pytest.mark.parametrize(("rows", "decision"), [
    ([], "not_listed"),
    ([listing("C001B", "FI0000000001", "Company 001"), listing("C001C", "fi0000000001 ", "Company 001")], "ambiguous"),
    ([listing("C001B", "FI0000000001", "Company 001", currency="SEK")], "currency_mismatch"),
    ([listing("C001B", "FI0000000001", "Unrelated Holding Oyj")], "name_mismatch"),
    ([listing("", "FI0000000001", "Company 001")], "invalid_code"),
    ([listing("C001B", "FI0000000001", "Company 001")], "mapped"),
])
def test_only_one_exact_isin_match_in_the_right_currency_and_name_maps(rows, decision):
    security = SecurityReference("isin:FI0000000001", "FI0000000001", "C001", "FI", "Nasdaq Helsinki", "EUR")
    mappings = SymbolMappings()
    record = mappings.decide(security, "Company 001", rows, "HE", FIRST)
    assert record["decision"] == decision
    assert mappings.mapped_symbols() == ({"FI0000000001": "C001B.HE"} if decision == "mapped" else {})


def test_name_words_ignore_accents_case_and_legal_forms():
    assert _name_words("Ilkka-Yhtymä Oyj II") == {"ilkka", "yhtyma"}
    assert _name_words("KPY osk") == {"kpy"}
    assert _name_words("Lehto Group Oyj") & _name_words("LEHTO GROUP OYJ") == {"lehto"}
    assert not _name_words("Oyj Group AB") and not _name_words(None)


def test_an_unmatched_security_keeps_its_ticker_guesses_and_the_list_waits_for_the_next_period(tmp_path, case):
    snapshot, good, renamed, listings = case
    fake = FakeEodhd(snapshot, {"C000.HE"}, [listings[0], listings[2]])
    refresh(tmp_path, snapshot, day(0), fake)
    fake.urls.clear()
    refresh(tmp_path, snapshot, day(1), fake)
    assert len(fake.list_requests()) == 1 and fake.symbols_requested() == ["C001.HE"]
    assert json.loads(mapping_file(tmp_path).read_text())["decisions"][renamed.isin]["decision"] == "not_listed"
    lists = {}
    for offset in range(2, SYMBOL_LIST_REFRESH_DAYS + 6):
        fake.urls.clear()
        refresh(tmp_path, snapshot, day(offset), fake)
        lists[offset] = len(fake.list_requests())
    # The list is requested again 28 days after the first request (day 29), although the security
    # itself is in backoff until day 31; its ticker retries keep their backoff days.
    assert [offset for offset, count in lists.items() if count] == [1 + SYMBOL_LIST_REFRESH_DAYS]


def test_a_failed_mapped_attempt_does_not_pin_the_symbol(tmp_path, case):
    snapshot, good, renamed, listings = case
    fake = FakeEodhd(snapshot, {"C000.HE"}, listings, empty={"C001B.HE"})
    refresh(tmp_path, snapshot, day(0), fake)
    refresh(tmp_path, snapshot, day(1), fake)
    failed = outcomes_of(tmp_path, snapshot, renamed.company_id)
    assert failed and {(o.status, o.provider_symbol) for o in failed} == {("symbol_unresolved", None)}


@pytest.mark.parametrize("budget,list_calls,priced", [(0, 0, False), (1, 1, False), (2, 1, True)])
def test_the_list_request_comes_first_and_stays_inside_the_budget(tmp_path, case, budget, list_calls, priced):
    snapshot, good, renamed, listings = case
    fake = FakeEodhd(snapshot, {"C000.HE", "C001B.HE"}, listings)
    refresh(tmp_path, snapshot, day(0), fake)
    fake.urls.clear()
    provider, summary = refresh(tmp_path, snapshot, day(1), fake, budget=budget)
    assert summary.symbol_list_calls == list_calls
    assert summary.provider_calls_executed == provider.api_call_count == len(fake.urls) <= budget
    statuses = {o.status for o in outcomes_of(tmp_path, snapshot, renamed.company_id)}
    assert (statuses == {"priced"}) is priced


def test_a_failed_list_request_is_recorded_without_the_token_and_not_repeated(tmp_path, case):
    snapshot, good, renamed, listings = case
    fake = FakeEodhd(snapshot, {"C000.HE", "C001B.HE"}, listings, list_error=f"HTTP Error 500 api_token={TOKEN}")
    refresh(tmp_path, snapshot, day(0), fake)
    fake.urls.clear()
    _, summary = refresh(tmp_path, snapshot, day(1), fake)
    assert summary.symbol_list_calls == 1 and fake.symbols_requested() == ["C001.HE"]
    text = mapping_file(tmp_path).read_text()
    stored = json.loads(text)
    assert stored["exchange_lists"]["HE"]["status"] == "error" and TOKEN not in text and "[redacted]" in text
    assert stored["decisions"] == {}
    fake.urls.clear()
    refresh(tmp_path, snapshot, day(3), fake)
    assert fake.list_requests() == []


def test_a_request_that_was_never_sent_is_not_an_attempt(tmp_path, case):
    snapshot, good, renamed, listings = case
    provider = EodhdHistoricalPriceProvider(None)
    with pytest.raises(RuntimeError, match=EODHD_MISSING_KEY_DETAIL):
        provider.exchange_symbol_list("HE")
    assert provider.api_call_count == 0
    fake = FakeEodhd(snapshot, {"C000.HE"}, listings)
    refresh(tmp_path, snapshot, day(0), fake)
    refresh(tmp_path, snapshot, day(1), fake, key=None)
    assert not mapping_file(tmp_path).exists()


def test_a_dry_run_reserves_the_list_call_without_requesting_or_writing(tmp_path, case):
    snapshot, good, renamed, listings = case
    fake = FakeEodhd(snapshot, {"C000.HE"}, listings)
    refresh(tmp_path, snapshot, day(0), fake)
    fake.urls.clear()
    _, summary = refresh(tmp_path, snapshot, day(1), fake, dry_run=True)
    assert fake.urls == [] and not mapping_file(tmp_path).exists()
    assert summary.symbol_list_calls == 1 and summary.provider_calls_executed == 0
    assert summary.provider_calls_planned == 2


def test_one_list_request_decides_every_seeking_security_of_the_exchange(tmp_path):
    snapshot = _snapshot(3, strategy="trading", countries=("FI",))
    rows = snapshot.rows
    listings = [listing(f"{row.ticker}B", row.isin, row.name) for row in rows[1:]]
    fake = FakeEodhd(snapshot, {rows[0].ticker + ".HE", *(f"{row.ticker}B.HE" for row in rows[1:])}, listings)
    refresh(tmp_path, snapshot, day(0), fake)
    fake.urls.clear()
    _, summary = refresh(tmp_path, snapshot, day(1), fake)
    assert len(fake.list_requests()) == 1 and summary.isin_symbol_fetches == 2
    assert sorted(fake.symbols_requested()) == sorted(f"{row.ticker}B.HE" for row in rows[1:])
    plan = {item.company_id: item for item in summary.fetch_plan}
    assert {plan[row.company_id].as_dict()["isin_symbol"] for row in rows[1:]} == {f"{row.ticker}B.HE" for row in rows[1:]}


def test_decisions_are_published_with_the_outcome_root():
    workflow = WORKFLOW.read_text()
    records = workflow[workflow.index("- name: Commit performance records"):]
    assert 'git add "$OUTCOME_ROOT"' in records
    assert not SYMBOL_MAPPING_FILE.is_absolute() and SYMBOL_MAPPING_FILE.parts[0] == "symbol-mappings"
