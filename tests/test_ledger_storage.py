"""The partitioned Performance v1 ledger reconstructs the exact single-file ledger, offline."""
from copy import deepcopy
from datetime import date, timedelta
import hashlib
import json
import socket
from pathlib import Path

import pytest
from typer.testing import CliRunner

from investmentagent.cli import DEFAULT_LEDGER_DIR, LEGACY_LEDGER_PATH, app
from investmentagent.ledger_storage import LEDGER_INDEX_NAME, serialize_ledger
from investmentagent.performance import (
    _add_trading_days,
    add_report_picks,
    empty_ledger,
    load_ledger,
    record_market_snapshot,
    render_scorecard_markdown,
    save_ledger,
    update_due_outcomes,
)


GENERATED = "2026-05-19 08:00 EEST"
DAYS = [date(2026, 5, 11) + timedelta(days=offset) for offset in (0, 1, 2, 3, 4, 7, 8)]
COMPANIES = [
    ("KESKO B", "Kesko Oyj B", "FI", "EUR"),
    ("ÖRE", "Öresundskraft AB", "SE", "SEK"),
    ("STABL", "Stayble Therapeutics", "SE", "SEK"),
]


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    def denied(*args, **kwargs):
        raise AssertionError("ledger storage tests must stay offline")
    monkeypatch.setattr(socket.socket, "connect", denied)
    monkeypatch.setattr(socket.socket, "connect_ex", denied)
    monkeypatch.setattr(socket, "create_connection", denied)


def report(strategy, day_index, companies=COMPANIES):
    return {
        "metadata": {"generated_at": "2026-05-11T05:00:00+00:00", "strategy": strategy},
        "items": [{
            "rank": rank,
            "company": {"ticker": ticker, "name": name, "country": country, "exchange": "Nasdaq",
                        "segment": "main_market", "sector": "Industrials"},
            "financials": {"price": 10.0 + rank, "currency": currency},
            "score": {"total": 30 - rank, "reasons": ["High live turnover"], "warnings": []},
            "risks": [], "data_quality": "partial",
        } for rank, (ticker, name, country, currency) in enumerate(companies, 1)],
    }


def prices(day_index, companies=COMPANIES):
    return {(ticker.upper(), country): {
        "price": round(10.0 + rank + day_index * 0.37, 2), "currency": currency, "name": name,
        "segment": "main_market", "sector": "Industrials",
        "catalysts": ["Intraday momentum"] if rank == 1 else [], "risks": [],
    } for rank, (ticker, name, country, currency) in enumerate(companies, 1)}


def daily_update(ledger, day_index, day, companies=COMPANIES):
    for strategy in ("trading", "long-term"):
        ledger = add_report_picks(ledger, report(strategy, day_index, companies), report_date=day,
                                  report_url=f"../reports/{strategy}/{day.isoformat()}.html")
    lookup = prices(day_index, companies)
    ledger = record_market_snapshot(ledger, as_of_date=day, price_lookup=lookup)
    return update_due_outcomes(ledger, as_of_date=day, price_lookup=lookup)


def build_ledger(count=len(DAYS)):
    ledger = empty_ledger()
    for index, day in enumerate(DAYS[:count]):
        ledger = daily_update(ledger, index, day)
    return ledger


def files(directory):
    return {path.relative_to(directory).as_posix(): path.read_bytes() for path in sorted(directory.rglob("*.json"))}


def test_round_trip_matches_the_single_file_bytes_key_order_and_scorecard(tmp_path):
    ledger = build_ledger()
    single, directory = tmp_path / "ledger.json", tmp_path / "ledger"
    save_ledger(single, ledger)
    save_ledger(directory, ledger)
    parsed, rebuilt = load_ledger(single), load_ledger(directory)
    assert serialize_ledger(rebuilt) == single.read_text(encoding="utf-8")
    assert json.dumps(rebuilt, ensure_ascii=False) == json.dumps(parsed, ensure_ascii=False)
    assert render_scorecard_markdown(rebuilt, generated_at=GENERATED) == render_scorecard_markdown(
        parsed, generated_at=GENERATED)
    assert any(outcome.get("excess_return_pct") is not None
               for pick in rebuilt["picks"] for outcome in pick["outcomes"].values())
    index = json.loads((directory / LEDGER_INDEX_NAME).read_text(encoding="utf-8"))
    assert "picks" not in index and "market_snapshots" not in index
    storage = index["ledger_storage"]
    assert (storage["pick_count"], storage["market_snapshot_count"]) == (len(ledger["picks"]), len(DAYS))
    assert [ref["path"] for ref in storage["pick_partitions"]] == [f"picks/2026/{day}.json" for day in DAYS]
    assert [ref["path"] for ref in storage["market_snapshot_partitions"]] == [
        f"market-snapshots/2026/{day}.json" for day in DAYS]
    assert len(files(directory)) == 1 + 2 * len(DAYS)
    assert max(map(len, files(directory).values())) < single.stat().st_size


def test_a_new_day_rewrites_only_the_partitions_it_changes(tmp_path):
    directory, previous, current = tmp_path / "ledger", build_ledger(len(DAYS) - 1), build_ledger()
    save_ledger(directory, previous)
    before = files(directory)
    stamps = {path: (directory / path).stat().st_mtime_ns for path in before}
    save_ledger(directory, current)
    after = files(directory)

    def by_day(ledger):
        return {day.isoformat(): [pick for pick in ledger["picks"] if pick["report_date"] == day.isoformat()]
                for day in DAYS}
    changed_days = {day for day, picks in by_day(current).items() if picks != by_day(previous)[day]}
    assert DAYS[-1].isoformat() in changed_days and len(changed_days) < len(DAYS)
    assert {path for path in after if before.get(path) != after[path]} == {
        LEDGER_INDEX_NAME, f"market-snapshots/2026/{DAYS[-1]}.json",
        *(f"picks/2026/{day}.json" for day in changed_days)}
    unchanged = [path for path in before if before[path] == after[path]]
    assert unchanged and all((directory / path).stat().st_mtime_ns == stamps[path] for path in unchanged)
    assert serialize_ledger(load_ledger(directory)) == serialize_ledger(current)


def test_rewriting_the_same_ledger_changes_no_file(tmp_path):
    ledger, directory = build_ledger(), tmp_path / "ledger"
    save_ledger(directory, ledger)
    stamps = {path: path.stat().st_mtime_ns for path in directory.rglob("*.json")}
    save_ledger(directory, load_ledger(directory))
    assert {path: path.stat().st_mtime_ns for path in directory.rglob("*.json")} == stamps


def test_published_picks_and_snapshots_cannot_be_dropped(tmp_path):
    ledger, directory = build_ledger(), tmp_path / "ledger"
    save_ledger(directory, ledger)
    before = files(directory)
    for damaged in (
        {**ledger, "picks": [pick for pick in ledger["picks"] if pick["report_date"] != "2026-05-12"]},
        {**ledger, "picks": ledger["picks"][1:]},
        {**ledger, "market_snapshots": {k: v for k, v in ledger["market_snapshots"].items() if k != "2026-05-12"}},
    ):
        with pytest.raises(ValueError, match="drop"):
            save_ledger(directory, damaged)
    assert files(directory) == before
    # A snapshot re-recorded on the same date may list fewer companies; it is still never removed.
    re_recorded = deepcopy(ledger)
    re_recorded["market_snapshots"][DAYS[-1].isoformat()] = {}
    save_ledger(directory, re_recorded)
    assert serialize_ledger(load_ledger(directory)) == serialize_ledger(re_recorded)


def _edit_partition(directory):
    victim = directory / f"picks/2026/{DAYS[0]}.json"
    victim.write_text(victim.read_text(encoding="utf-8").replace('"rank": 1', '"rank": 2', 1), encoding="utf-8")


def _edit_index(directory, change):
    index_path = directory / LEDGER_INDEX_NAME
    index = json.loads(index_path.read_text(encoding="utf-8"))
    change(index["ledger_storage"])
    index_path.write_text(json.dumps(index), encoding="utf-8")


@pytest.mark.parametrize(("damage", "message"), [
    (_edit_partition, "does not match its index digest"),
    (lambda directory: (directory / f"market-snapshots/2026/{DAYS[1]}.json").unlink(), "missing ledger partition"),
    (lambda directory: _edit_index(directory, lambda storage: storage["pick_partitions"][0].update(
        path=f"picks/2026/../2026/{DAYS[0]}.json")), "unexpected path"),
    (lambda directory: _edit_index(directory, lambda storage: storage["pick_partitions"].reverse()), "date order"),
    (lambda directory: _edit_index(directory, lambda storage: storage.update(pick_count=1)), "count mismatch"),
    (lambda directory: _edit_index(directory, lambda storage: storage.update(reconstructed_sha256="0" * 64)),
     "does not match the index digest"),
    (lambda directory: _edit_index(directory, lambda storage: storage.update(layout="other")), "layout"),
])
def test_tampered_missing_or_misplaced_partitions_fail_closed(tmp_path, damage, message):
    directory = tmp_path / "ledger"
    save_ledger(directory, build_ledger())
    damage(directory)
    with pytest.raises(ValueError, match=message):
        load_ledger(directory)


@pytest.mark.parametrize(("mutate", "message"), [
    (lambda ledger: ledger["picks"].reverse(), "ascending report date"),
    (lambda ledger: ledger["picks"][0].update(report_date="2026-5-11"), "YYYY-MM-DD"),
    (lambda ledger: ledger["market_snapshots"].update({"20260520": {}}), "YYYY-MM-DD"),
    (lambda ledger: ledger.pop("market_snapshots"), "market_snapshots mapping"),
    (lambda ledger: ledger.update(ledger_storage={}), "storage manifest"),
])
def test_ledgers_the_layout_cannot_reproduce_are_rejected_before_writing(tmp_path, mutate, message):
    ledger = build_ledger()
    mutate(ledger)
    with pytest.raises(ValueError, match=message):
        save_ledger(tmp_path / "ledger", ledger)
    assert not (tmp_path / "ledger").exists()


def test_a_directory_without_an_index_is_never_reseeded(tmp_path):
    directory, seed = tmp_path / "ledger", tmp_path / "ledger.json"
    save_ledger(directory, build_ledger())
    save_ledger(seed, build_ledger(2))
    (directory / LEDGER_INDEX_NAME).unlink()
    with pytest.raises(ValueError, match="no index"):
        load_ledger(directory, legacy_seed=seed)
    with pytest.raises(ValueError, match="no index"):
        save_ledger(directory, build_ledger(), legacy_seed=seed)


def test_the_legacy_ledger_seeds_the_partitions_once_and_is_never_written(tmp_path):
    directory, seed = tmp_path / "ledger", tmp_path / "ledger.json"
    save_ledger(seed, build_ledger(len(DAYS) - 1))
    seed_bytes = seed.read_bytes()
    ledger = load_ledger(directory, legacy_seed=seed)
    assert ledger == load_ledger(seed)
    ledger = daily_update(ledger, len(DAYS) - 1, DAYS[-1])
    save_ledger(directory, ledger, legacy_seed=seed)
    assert seed.read_bytes() == seed_bytes
    storage = json.loads((directory / LEDGER_INDEX_NAME).read_text(encoding="utf-8"))["ledger_storage"]
    assert storage["legacy_seed_sha256"] == hashlib.sha256(seed_bytes).hexdigest()
    assert serialize_ledger(load_ledger(directory, legacy_seed=seed)) == serialize_ledger(ledger)

    seed.write_bytes(seed_bytes + b"\n")
    with pytest.raises(ValueError, match="diverge"):
        load_ledger(directory, legacy_seed=seed)
    with pytest.raises(ValueError, match="diverge"):
        save_ledger(directory, ledger, legacy_seed=seed)
    seed.unlink()
    assert serialize_ledger(load_ledger(directory, legacy_seed=seed)) == serialize_ledger(ledger)
    with pytest.raises(ValueError, match="single-file"):
        load_ledger(directory, legacy_seed=tmp_path / "ledger-copy")


def test_a_ledger_created_without_a_seed_rejects_one_that_appears_later(tmp_path):
    directory, seed = tmp_path / "ledger", tmp_path / "ledger.json"
    save_ledger(directory, build_ledger(), legacy_seed=seed)
    assert json.loads((directory / LEDGER_INDEX_NAME).read_text())["ledger_storage"]["legacy_seed_sha256"] is None
    save_ledger(seed, build_ledger(2))
    with pytest.raises(ValueError, match="diverge"):
        load_ledger(directory, legacy_seed=seed)


def test_single_file_paths_keep_their_previous_behaviour(tmp_path):
    ledger, path = build_ledger(), tmp_path / "nested" / "ledger.json"
    save_ledger(path, ledger)
    assert path.read_text(encoding="utf-8") == json.dumps(ledger, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    assert load_ledger(path) == json.loads(path.read_text(encoding="utf-8"))
    assert load_ledger(tmp_path / "missing.json") == empty_ledger()
    assert load_ledger(tmp_path / "missing") == empty_ledger()
    legacy = {key: value for key, value in ledger.items() if key != "market_snapshots"}
    path.write_text(json.dumps(legacy), encoding="utf-8")
    assert load_ledger(path)["market_snapshots"] == {}


def test_no_partition_grows_with_the_number_of_dates(tmp_path):
    # After 60 trading days every horizon of the first report dates has resolved: from then on their
    # partitions never change and the largest partition stops growing, while the single file still
    # grows with every date.
    companies = [(f"T{number:03d}", f"Company {number}", "SE" if number % 2 else "FI", "SEK" if number % 2 else "EUR")
                 for number in range(20)]
    directory, ledger, observed = tmp_path / "ledger", empty_ledger(), {}
    for index in range(70):
        day = _add_trading_days(date(2026, 11, 2), index + 1)
        ledger = daily_update(ledger, index, day, companies[:4] if index % 2 else companies[4:8])
        ledger = record_market_snapshot(ledger, as_of_date=day, price_lookup=prices(index, companies))
        if index + 1 in (10, 62, 70):
            save_ledger(directory, ledger)
            stored = files(directory)
            observed[index + 1] = (len(serialize_ledger(ledger)), stored, len(stored.pop(LEDGER_INDEX_NAME)))
    (single_10, _, index_10), (single_62, stored_62, _), (single_70, stored_70, index_70) = (
        observed[10], observed[62], observed[70])
    assert single_70 > 6 * single_10 and single_70 > 1.1 * single_62
    resolved = [path for path in stored_62 if path.startswith("picks/") and path[-15:-5] < "2026-11-05"]
    assert resolved and all(stored_70[path] == stored_62[path] for path in resolved)
    assert max(map(len, stored_70.values())) <= max(map(len, stored_62.values())) * 1.01
    assert (index_70 - index_10) / 60 < 500
    assert serialize_ledger(load_ledger(directory)) == serialize_ledger(ledger)


def test_cli_migrates_the_legacy_ledger_and_then_reads_only_the_partitions(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    for index, day in enumerate(DAYS[:3]):
        for strategy in ("trading", "long-term"):
            Path(f"{strategy}-{day}.json").write_text(json.dumps(report(strategy, index)), encoding="utf-8")

    def update(day, *extra):
        return CliRunner().invoke(app, [
            "performance", "update", "--report-json", f"trading-{day}.json", "--report-json", f"long-term-{day}.json",
            "--report-date", day.isoformat(), "--price-provider", "fixture", "--generated-at", GENERATED, *extra])

    first = update(DAYS[0], "--ledger", LEGACY_LEDGER_PATH)
    assert first.exit_code == 0, first.output
    legacy = Path(LEGACY_LEDGER_PATH)
    legacy_bytes = legacy.read_bytes()
    single = tmp_path / "single"
    single.mkdir()
    (single / "ledger.json").write_bytes(legacy_bytes)

    second = update(DAYS[1])
    expected = update(DAYS[1], "--ledger", str(single / "ledger.json"), "--output", str(single / "index.md"))
    assert second.exit_code == 0 and expected.exit_code == 0, second.output + expected.output
    assert legacy.read_bytes() == legacy_bytes
    directory = Path(DEFAULT_LEDGER_DIR)
    assert (directory / LEDGER_INDEX_NAME).is_file()
    assert serialize_ledger(load_ledger(directory)) == (single / "ledger.json").read_text(encoding="utf-8")
    assert Path("docs/performance/index.md").read_text(encoding="utf-8") == (single / "index.md").read_text(
        encoding="utf-8")

    third = update(DAYS[2])
    assert third.exit_code == 0, third.output
    assert legacy.read_bytes() == legacy_bytes
    assert {pick["report_date"] for pick in load_ledger(directory)["picks"]} == {day.isoformat() for day in DAYS[:3]}

    legacy.write_bytes(legacy_bytes.replace(b'"schema_version": 1', b'"schema_version": 1 ', 1))
    refused = update(DAYS[2])
    assert refused.exit_code != 0
    assert isinstance(refused.exception, ValueError) and "diverge" in str(refused.exception)
