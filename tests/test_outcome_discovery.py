"""Outcome discovery reads only the store layout, so supporting documents cannot break analysis.

The 2026-11-05 and 2026-11-06 analyses stopped with "unsupported outcome-store schema: None":
discovery parsed every JSON file under the outcome root, including the ISIN symbol mappings that
the outcome refresh keeps in symbol-mappings/. Stores are now found by the layout
outcome_store_path writes; everything there is still parsed strictly, the mapping directory is
skipped, and any other JSON document fails closed.
"""
from __future__ import annotations

import json
import shutil
import socket
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from typer.testing import CliRunner

from investmentagent import evaluation_analysis, evaluation_outcomes
from investmentagent.analysis_storage import serialize_analysis
from investmentagent.cli import app
from investmentagent.evaluation_analysis import analyze_outcome_store
from investmentagent.evaluation_outcomes import (
    OUTCOME_ROOT_AUXILIARY_DIRECTORIES, EvaluationOutcomeSet, discover_outcome_sets, load_outcome_set,
    outcome_store_files, outcome_store_path, save_outcome_set,
)
from investmentagent.price_histories import COHERENT_RETURN_METHOD, LEGACY_RETURN_METHOD
from investmentagent.symbol_mapping import SYMBOL_MAPPING_FILE, SymbolMappings
from test_analysis_storage import _write_inputs
from test_challenger_experiment import _priced_outcomes, _research
from test_coherent_price_histories import _legacy
from test_evaluation_outcomes import _snapshot, _timestamp
from test_fixed_decision_membership import GENERATED, production_case
from test_isin_symbol_mapping import FakeEodhd, day, listing, refresh


UTC = timezone.utc
# The mapping document the 2026-11-05 production refresh published (commit af4f2d3).
PRODUCTION_MAPPINGS = {
    "exchange_lists": {"HE": {
        "attempted_at": "2026-11-05T06:27:53+00:00",
        "response_sha256": "3ae2551c2934781d3c1966381b270182f4622daab673acfe5b60b76afe7d011c",
        "rows": 195, "rows_with_isin": 161, "status": "ok",
    }},
    "decisions": {
        isin: {"company_id": f"isin:{isin}", "decided_at": "2026-11-05T06:27:53+00:00",
               "decision": "not_listed", "exchange": "HE", "listed": [], "name": name, "ticker": ticker}
        for isin, name, ticker in (
            ("FI0009014708", "KPY osk", "KPYOSK"),
            ("FI0009800205", "Ilkka Oyj 2", "ILKKA"),
            ("FI4000081138", "Lehto Group Oyj", "LEHTO"),
            ("FI4000575048", "Pallas Air Oyj", "PALLAS"),
            ("FI4000602958", "Savox Communications Oyj", "SAVOX"),
        )
    },
}


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    def denied(*args, **kwargs):
        raise AssertionError("outcome discovery tests must stay offline")
    monkeypatch.setattr(socket.socket, "connect", denied)
    monkeypatch.setattr(socket.socket, "connect_ex", denied)
    monkeypatch.setattr(socket, "create_connection", denied)


def write_production_mappings(outcome_root: Path) -> Path:
    """Writes the mapping document through the production writer, at the production path."""
    path = outcome_root / SYMBOL_MAPPING_FILE
    SymbolMappings(json.loads(json.dumps(PRODUCTION_MAPPINGS["exchange_lists"])),
                   json.loads(json.dumps(PRODUCTION_MAPPINGS["decisions"]))).save(path)
    return path


def pre_repair_discovery(root: Path) -> tuple[EvaluationOutcomeSet, ...]:
    """The rule the failed production runs used: every JSON file under the root is a store."""
    if not root.exists():
        return ()
    stores = tuple(load_outcome_set(path) for path in sorted(root.rglob("*.json")))
    run_ids = [(store.evaluation_run_id, store.return_methodology) for store in stores]
    if len(run_ids) != len(set(run_ids)):
        raise ValueError("duplicate outcome stores discovered")
    return stores


@dataclass
class Layout:
    root: Path
    stores: dict[str, Path]
    mapping: Path

    def relative(self, name: str) -> str:
        return self.stores[name].relative_to(self.root).as_posix()


@pytest.fixture
def layout(tmp_path):
    """A production-shaped outcome root: dated strategy directories, a legacy schema-1 store with
    its coherent repair, schema-2 stores, and the published ISIN mapping document."""
    root, stores = tmp_path / "data" / "evaluation-outcomes", {}
    for name, strategy, day_of_month in (
        ("legacy", "long-term", 10), ("trading-10", "trading", 10),
        ("long-term-11", "long-term", 11), ("trading-11", "trading", 11), ("trading-12", "trading", 12),
    ):
        snapshot = _snapshot(3, strategy=strategy, decision_at=_timestamp(day_of_month))
        store = _priced_outcomes(snapshot, [1.0, 2.0, 3.0])
        path = outcome_store_path(root, snapshot)
        if name == "legacy":
            stores[name] = save_outcome_set(path, _legacy(store))
            stores["repair"] = save_outcome_set(path.with_name(f"{path.stem}.coherent-v1.json"), store)
        else:
            stores[name] = save_outcome_set(path, store)
    return Layout(root, stores, write_production_mappings(root))


def test_valid_outcome_store_is_discovered(tmp_path):
    snapshot = _snapshot(3, strategy="trading")
    store = _priced_outcomes(snapshot, [1.0, 2.0, 3.0])
    path = save_outcome_set(outcome_store_path(tmp_path, snapshot), store)
    assert outcome_store_files(tmp_path) == (path,)
    assert discover_outcome_sets(tmp_path) == (store,)


def test_missing_or_empty_root_discovers_nothing(tmp_path):
    assert outcome_store_files(tmp_path / "absent") == () and discover_outcome_sets(tmp_path / "absent") == ()
    assert outcome_store_files(tmp_path) == () and discover_outcome_sets(tmp_path) == ()


def test_legacy_schema_1_store_is_discovered(layout):
    legacy = load_outcome_set(layout.stores["legacy"])
    assert layout.relative("legacy").endswith(f"long-term/{legacy.evaluation_run_id}.json")
    assert (legacy.schema_version, legacy.return_methodology) == (1, LEGACY_RETURN_METHOD)
    assert legacy in discover_outcome_sets(layout.root)


def test_coherent_schema_2_stores_and_the_legacy_repair_are_discovered(layout):
    discovered = discover_outcome_sets(layout.root)
    coherent = [store for store in discovered if store.schema_version == 2]
    assert len(coherent) == 5 and {store.return_methodology for store in coherent} == {COHERENT_RETURN_METHOD}
    repair = load_outcome_set(layout.stores["repair"])
    assert layout.relative("repair").endswith(".coherent-v1.json") and repair in coherent
    # The legacy store and its repair share a run but not a methodology, so neither is a duplicate.
    assert repair.evaluation_run_id == load_outcome_set(layout.stores["legacy"]).evaluation_run_id


def test_stores_in_multiple_dated_directories_are_discovered(layout):
    by_directory = {}
    for path in outcome_store_files(layout.root):
        date_directory, strategy, _ = path.relative_to(layout.root).parts
        by_directory.setdefault(date_directory, set()).add(strategy)
    assert by_directory == {"2026-08-10": {"long-term", "trading"}, "2026-08-11": {"long-term", "trading"},
                            "2026-08-12": {"trading"}}
    assert {store.report_date.isoformat() for store in discover_outcome_sets(layout.root)} == set(by_directory)


def test_isin_mapping_document_coexists_with_valid_stores(layout):
    before = layout.mapping.read_bytes()
    assert layout.mapping.relative_to(layout.root).as_posix() == "symbol-mappings/eodhd-isin-v1.json"
    assert len(discover_outcome_sets(layout.root)) == len(layout.stores) == 6
    # Discovery neither consumes nor rewrites the document the next refresh reads.
    assert layout.mapping.read_bytes() == before
    mappings = SymbolMappings.load(layout.mapping)
    assert {d["decision"] for d in mappings.decisions.values()} == {"not_listed"} and len(mappings.decisions) == 5
    assert mappings.exchange_lists["HE"]["rows"] == 195 and mappings.exchange_lists["HE"]["rows_with_isin"] == 161


def test_mapping_documents_are_never_parsed_as_outcome_stores(layout, monkeypatch):
    parsed = []
    original = evaluation_outcomes.load_outcome_set
    monkeypatch.setattr(evaluation_outcomes, "load_outcome_set", lambda path: parsed.append(path) or original(path))
    discover_outcome_sets(layout.root)
    assert layout.mapping not in parsed and sorted(parsed) == sorted(layout.stores.values())
    # Nothing in the mapping directory is read at all, not even an unreadable document.
    (layout.mapping.parent / "eodhd-isin-v2.json").write_text("{not json", encoding="utf-8")
    assert len(discover_outcome_sets(layout.root)) == 6
    assert OUTCOME_ROOT_AUXILIARY_DIRECTORIES == {"symbol-mappings"} == {SYMBOL_MAPPING_FILE.parts[0]}


def test_the_production_layout_fails_under_the_pre_repair_rule(layout):
    with pytest.raises(ValueError, match="unsupported outcome-store schema: None"):
        pre_repair_discovery(layout.root)
    shutil.rmtree(layout.mapping.parent)
    assert pre_repair_discovery(layout.root) == discover_outcome_sets(layout.root)


@pytest.mark.parametrize("content", ["{not json", "[]", '{"schema_version": 2}', "", "NaN"])
def test_malformed_store_at_a_store_path_still_fails_closed(layout, content):
    layout.stores["trading-11"].write_text(content, encoding="utf-8")
    with pytest.raises(ValueError, match="malformed outcome.store"):
        discover_outcome_sets(layout.root)


@pytest.mark.parametrize("version", [None, 0, 3, "2"])
def test_unsupported_store_schema_at_a_store_path_still_fails_closed(layout, version):
    path = layout.stores["trading-11"]
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["schema_version"] = version
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match="unsupported outcome-store schema"):
        discover_outcome_sets(layout.root)


def test_a_mapping_document_at_a_store_path_is_still_rejected(layout):
    # Only the mapping directory is exempt; the same document anywhere in the store layout fails.
    shutil.copyfile(layout.mapping, layout.stores["trading-12"].with_name("eodhd-isin-v1.json"))
    with pytest.raises(ValueError, match="unsupported outcome-store schema: None"):
        discover_outcome_sets(layout.root)


@pytest.mark.parametrize("copy_to", ["2026-08-11/trading/evaluation-copy.json", "2026-08-13/trading/{name}"])
def test_duplicate_outcome_stores_are_still_rejected(layout, copy_to):
    source = layout.stores["trading-11"]
    target = layout.root / copy_to.format(name=source.name)
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, target)
    with pytest.raises(ValueError, match="duplicate outcome stores discovered"):
        discover_outcome_sets(layout.root)


@pytest.mark.parametrize("relative", [
    "notes.json",
    "symbol-mappings.json",
    "2026-08-10/evaluation-x.json",
    "2026-08-10/trading/extra/evaluation-x.json",
    "2026-8-10/trading/evaluation-x.json",
    "20260810/trading/evaluation-x.json",
    "2026-02-30/trading/evaluation-x.json",
    "2026-08-10/global-ai/evaluation-x.json",
    "trading/2026-08-10/evaluation-x.json",
])
def test_documents_outside_the_store_layout_fail_closed(layout, relative):
    target = layout.root / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("{}", encoding="utf-8")
    with pytest.raises(ValueError, match="unexpected document outside the outcome-store layout"):
        outcome_store_files(layout.root)
    with pytest.raises(ValueError, match="unexpected document outside the outcome-store layout"):
        discover_outcome_sets(layout.root)


def test_a_genuine_store_outside_the_layout_fails_closed_instead_of_disappearing(layout):
    misplaced = layout.root / "misplaced" / layout.stores["trading-12"].name
    misplaced.parent.mkdir()
    layout.stores["trading-12"].rename(misplaced)
    assert load_outcome_set(misplaced).schema_version == 2
    with pytest.raises(ValueError, match="unexpected document outside the outcome-store layout"):
        discover_outcome_sets(layout.root)


def test_discovery_omits_no_outcome_store(layout):
    every_json = sorted(layout.root.rglob("*.json"))
    discovered = outcome_store_files(layout.root)
    # Exactly the JSON files outside the mapping directory, in the same order as before the repair.
    assert discovered == tuple(path for path in every_json if path != layout.mapping)
    assert set(discovered) == set(layout.stores.values())
    assert discover_outcome_sets(layout.root) == tuple(load_outcome_set(path) for path in discovered)
    # Non-JSON files (atomic-write temporaries, notes) were never discovered and still are not.
    (layout.stores["trading-11"].parent / ".evaluation-x.json.abc123.tmp").write_text("partial")
    (layout.root / "README.md").write_text("notes")
    assert outcome_store_files(layout.root) == discovered


@pytest.fixture(scope="module")
def case():
    return production_case(count=60, research=[
        _research(i, country="SE" if i < 40 else "FI", pe_ratio=None) for i in range(60)])


@pytest.fixture
def inputs(case, tmp_path):
    """Champion, challenger and benchmark inputs twice: as before 2026-11-05 and with the mappings.

    The inputs are written once and copied, because fixture outcomes record a wall-clock
    calculation time and so differ byte for byte between two writes."""
    plain, mapped = tmp_path / "plain", tmp_path / "mapped"
    _write_inputs(case, plain)
    shutil.copytree(plain, mapped)
    write_production_mappings(mapped / "data/evaluation-outcomes")
    return plain, mapped


def analyze(root: Path, cutoff: datetime = GENERATED) -> dict:
    return analyze_outcome_store(
        root / "data/evaluations", root / "data/evaluation-outcomes", generated_at=cutoff, data_cutoff=cutoff,
        return_methodology=COHERENT_RETURN_METHOD, experiment_root=root / "data/evaluation-experiments",
    )


def pre_repair_analysis(monkeypatch, root: Path, cutoff: datetime = GENERATED) -> dict:
    with monkeypatch.context() as patch:
        patch.setattr(evaluation_analysis, "discover_outcome_sets", pre_repair_discovery)
        return analyze(root, cutoff)


def test_analysis_is_identical_with_or_without_the_mapping_document(inputs, monkeypatch):
    plain, mapped = inputs
    reference = pre_repair_analysis(monkeypatch, plain)
    with pytest.raises(ValueError, match="unsupported outcome-store schema: None"):
        pre_repair_analysis(monkeypatch, mapped)
    assert serialize_analysis(analyze(mapped)) == serialize_analysis(reference)
    assert serialize_analysis(analyze(plain)) == serialize_analysis(reference)


def test_champion_challenger_and_benchmark_analysis_are_unchanged(inputs, monkeypatch):
    plain, mapped = inputs
    reference, repaired = pre_repair_analysis(monkeypatch, plain), analyze(mapped)
    for key in ("groups", "run_metrics", "lifecycle", "methodology", "benchmark_methodology"):
        assert repaired[key] == reference[key]
    portfolios = {side for group in repaired["groups"] for side in group["portfolios"]}
    assert {"champion", "challenger"} <= portfolios
    assert repaired["benchmark_methodology"] == "representative-benchmarks-v1"
    assert repaired["lifecycle"]["mature_priced"] > 0


def test_historical_cutoffs_are_unchanged(inputs, monkeypatch):
    plain, mapped = inputs
    results = {}
    for cutoff in (datetime(2026, 8, 20, tzinfo=UTC), GENERATED, GENERATED + timedelta(days=30)):
        reference = pre_repair_analysis(monkeypatch, plain, cutoff)
        results[cutoff] = analyze(mapped, cutoff)
        assert serialize_analysis(results[cutoff]) == serialize_analysis(reference)
    # The cutoff is exercised: outcomes retrieved after the earliest cutoff are not yet visible.
    early, late = results[datetime(2026, 8, 20, tzinfo=UTC)], results[GENERATED]
    assert early["lifecycle"]["mature_priced"] < late["lifecycle"]["mature_priced"]


def test_cli_analysis_completes_with_the_production_mapping_document(inputs, monkeypatch):
    plain, mapped = inputs
    outputs = {}
    for root in (plain, mapped):
        monkeypatch.chdir(root)
        result = CliRunner().invoke(app, [
            "evaluate", "analyze", "--output-dir", "out/performance-v2",
            "--return-methodology", COHERENT_RETURN_METHOD,
            "--data-cutoff", GENERATED.isoformat(), "--generated-at", GENERATED.isoformat(),
        ])
        assert result.exit_code == 0, result.output
        outputs[root] = {path.relative_to(root / "out").as_posix(): path.read_bytes()
                         for path in sorted((root / "out").rglob("*")) if path.is_file()}
    assert outputs[plain] and outputs[plain] == outputs[mapped]


def test_isin_mappings_written_by_a_refresh_leave_analysis_intact(tmp_path, monkeypatch):
    """End to end: the resolver writes symbol-mappings/ under the outcome root, then analysis runs."""
    snapshot = _snapshot(2, strategy="trading", countries=("FI",))
    good, renamed = snapshot.rows
    fake = FakeEodhd(snapshot, {"C000.HE", "C001B.HE"}, [
        listing("C000", good.isin, good.name), listing("C001B", renamed.isin, "Company 001 Oyj")])
    refresh(tmp_path, snapshot, day(0), fake)
    _, summary = refresh(tmp_path, snapshot, day(1), fake)
    mapping = tmp_path / "outcomes" / SYMBOL_MAPPING_FILE
    assert summary.symbol_list_calls == 1 and mapping.is_file()
    cutoff = day(1) + timedelta(hours=1)

    def run(discovery=None):
        with monkeypatch.context() as patch:
            if discovery is not None:
                patch.setattr(evaluation_analysis, "discover_outcome_sets", discovery)
            return analyze_outcome_store(tmp_path / "evaluations", tmp_path / "outcomes", generated_at=cutoff,
                                         data_cutoff=cutoff, return_methodology=COHERENT_RETURN_METHOD)

    with pytest.raises(ValueError, match="unsupported outcome-store schema: None"):
        run(pre_repair_discovery)
    repaired = run()
    assert repaired["lifecycle"]["mature_priced"] > 0
    shutil.rmtree(mapping.parent)
    assert serialize_analysis(run(pre_repair_discovery)) == serialize_analysis(repaired)
