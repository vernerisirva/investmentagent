"""Partitioned analysis storage reconstructs the exact single-file analysis, offline."""
from copy import deepcopy
from datetime import timedelta
import json
import socket
from pathlib import Path

import pytest
from typer.testing import CliRunner

from investmentagent.analysis_storage import (
    ANALYSIS_INDEX_NAME, ANALYSIS_MARKDOWN_NAME, load_analysis, load_partitioned_analysis,
    save_partitioned_analysis, serialize_analysis,
)
from investmentagent.benchmark_analysis import build_benchmark_analysis
from investmentagent.benchmarks import build_benchmark_plan, save_benchmark_plan
from investmentagent.cli import DEFAULT_ANALYSIS_DIR, app
from investmentagent.evaluation import save_evaluation_snapshot
from investmentagent.evaluation_analysis import build_performance_v2_analysis, save_analysis_json
from investmentagent.evaluation_outcomes import outcome_store_path, save_outcome_set
from investmentagent.experiments import save_experiment_snapshot
from test_challenger_experiment import _priced_outcomes, _research
from test_evaluation_outcomes import _snapshot
from test_fixed_decision_membership import GENERATED, production_case


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    def denied(*args, **kwargs):
        raise AssertionError("analysis storage tests must stay offline")
    monkeypatch.setattr(socket.socket, "connect", denied)
    monkeypatch.setattr(socket.socket, "connect_ex", denied)
    monkeypatch.setattr(socket, "create_connection", denied)


@pytest.fixture(scope="module")
def case():
    return production_case(count=60, research=[
        _research(i, country="SE" if i < 40 else "FI", pe_ratio=None) for i in range(60)])


def inputs(case, *, trading=True):
    result, snapshot, experiment = case
    snapshots = [snapshot]
    stores = [_priced_outcomes(snapshot, [float(row.rank) for row in snapshot.rows])]
    if trading:
        # A run without Y is analysed over all four strategy horizons.
        snapshots.append(_snapshot(5, strategy="trading"))
    plans = {snapshot.run_id: build_benchmark_plan(snapshot, result=result, experiment=experiment)}
    return snapshots, stores, plans, experiment


def analysis(case, *, cutoff=GENERATED, trading=True):
    snapshots, stores, plans, experiment = inputs(case, trading=trading)
    return build_benchmark_analysis(snapshots, stores, generated_at=cutoff, data_cutoff=cutoff,
                                    experiment_snapshots=[experiment], plans=plans)


def partition_files(directory):
    return {path.relative_to(directory).as_posix(): path.read_bytes()
            for path in sorted((directory / "runs").rglob("*.json"))}


def test_round_trip_is_byte_identical_to_the_single_file_analysis(case, tmp_path):
    result = analysis(case)
    single = save_analysis_json(tmp_path / "performance-v2.json", result).read_text(encoding="utf-8")
    index = save_partitioned_analysis(tmp_path / "performance-v2", result)
    assert serialize_analysis(result) == single
    assert serialize_analysis(load_partitioned_analysis(tmp_path / "performance-v2")) == single
    assert serialize_analysis(load_analysis(index)) == single
    assert serialize_analysis(load_analysis(tmp_path / "performance-v2")) == single
    assert load_analysis(tmp_path / "performance-v2.json") == json.loads(single)
    stored = json.loads(index.read_text())
    assert "run_metrics" not in stored
    assert stored["analysis_storage"]["run_metric_count"] == len(result["run_metrics"]) == 5
    files = partition_files(tmp_path / "performance-v2")
    assert len(files) == 5
    for content in files.values():
        assert "status_cutoff" not in json.loads(content)["run_metric"]["lifecycle"]
    assert max(len(content) for content in files.values()) < len(single)


def test_unchanged_runs_keep_byte_identical_partitions_when_the_cutoff_moves(case, tmp_path):
    first, second = analysis(case), analysis(case, cutoff=GENERATED + timedelta(hours=1))
    assert first["lifecycle"]["status_cutoff"] != second["lifecycle"]["status_cutoff"]
    directory = tmp_path / "performance-v2"
    save_partitioned_analysis(directory, first)
    before, index_before = partition_files(directory), (directory / ANALYSIS_INDEX_NAME).read_bytes()
    save_partitioned_analysis(directory, second)
    assert partition_files(directory) == before
    assert (directory / ANALYSIS_INDEX_NAME).read_bytes() != index_before
    assert serialize_analysis(load_partitioned_analysis(directory)) == serialize_analysis(second)


def test_rewriting_the_same_analysis_changes_no_file(case, tmp_path):
    result, directory = analysis(case), tmp_path / "performance-v2"
    save_partitioned_analysis(directory, result)
    stamps = {path: path.stat().st_mtime_ns for path in directory.rglob("*.json")}
    save_partitioned_analysis(directory, result)
    assert {path: path.stat().st_mtime_ns for path in directory.rglob("*.json")} == stamps


@pytest.mark.parametrize("damage", ["edit", "delete"])
def test_tampered_or_missing_partition_fails_closed(case, tmp_path, damage):
    directory = tmp_path / "performance-v2"
    save_partitioned_analysis(directory, analysis(case))
    victim = next((directory / "runs").rglob("*.json"))
    if damage == "edit":
        victim.write_text(victim.read_text().replace('"is_due"', '"is_due" ', 1))
    else:
        victim.unlink()
    with pytest.raises(ValueError, match="partition"):
        load_partitioned_analysis(directory)


def test_published_run_horizons_cannot_be_dropped(case, tmp_path):
    directory = tmp_path / "performance-v2"
    save_partitioned_analysis(directory, analysis(case))
    before = partition_files(directory), (directory / ANALYSIS_INDEX_NAME).read_bytes()
    with pytest.raises(ValueError, match="drop"):
        save_partitioned_analysis(directory, analysis(case, trading=False))
    assert (partition_files(directory), (directory / ANALYSIS_INDEX_NAME).read_bytes()) == before


def test_only_schema_four_benchmark_analyses_are_partitioned(case, tmp_path):
    snapshots, stores, _, _ = inputs(case)
    legacy = build_performance_v2_analysis(snapshots, stores, generated_at=GENERATED)
    with pytest.raises(ValueError):
        save_partitioned_analysis(tmp_path / "legacy", legacy)
    assert not (tmp_path / "legacy").exists()


def test_existing_index_of_another_methodology_is_not_overwritten(case, tmp_path):
    directory = tmp_path / "performance-v2"
    save_partitioned_analysis(directory, analysis(case))
    index = json.loads((directory / ANALYSIS_INDEX_NAME).read_text())
    index["benchmark_methodology"] = "representative-benchmarks-v2"
    (directory / ANALYSIS_INDEX_NAME).write_text(json.dumps(index))
    with pytest.raises(ValueError):
        save_partitioned_analysis(directory, analysis(case))


@pytest.mark.parametrize("field,value,message", [
    ("status_cutoff", "2026-09-01T17:00:00Z", "status cutoff"),
    ("evaluation_run_id", "../escape", "safe partition path"),
    ("horizon_label", "20_sessions/../../x", "safe partition path"),
])
def test_inconsistent_or_unsafe_run_metrics_are_rejected(case, tmp_path, field, value, message):
    result = deepcopy(analysis(case))
    metric = result["run_metrics"][0]
    if field == "status_cutoff":
        metric["lifecycle"]["status_cutoff"] = value
    elif field == "horizon_label":
        metric["horizon"]["label"] = value
    else:
        metric[field] = value
    with pytest.raises(ValueError, match=message):
        save_partitioned_analysis(tmp_path / "performance-v2", result)
    assert not (tmp_path / "performance-v2" / ANALYSIS_INDEX_NAME).exists()


def _write_inputs(case, root):
    snapshots, stores, plans, experiment = inputs(case)
    for snapshot in snapshots:
        save_evaluation_snapshot(root / "data/evaluations", snapshot)
    for snapshot, store in zip(snapshots, stores):
        save_outcome_set(outcome_store_path(root / "data/evaluation-outcomes", snapshot), store)
    for run_id, plan in plans.items():
        save_benchmark_plan(root / "data/evaluations", next(s for s in snapshots if s.run_id == run_id), plan)
    save_experiment_snapshot(root / "data/evaluation-experiments", experiment)


def test_cli_publishes_the_partitioned_analysis_by_default(case, tmp_path, monkeypatch):
    _write_inputs(case, tmp_path)
    monkeypatch.chdir(tmp_path)
    result = CliRunner().invoke(app, ["evaluate", "analyze", "--generated-at", GENERATED.isoformat()])
    assert result.exit_code == 0, result.output
    directory = Path(DEFAULT_ANALYSIS_DIR)
    assert directory.name == "performance-v2" and directory.parent.name == "representative-benchmarks-v1"
    assert (directory / ANALYSIS_INDEX_NAME).is_file() and (directory / ANALYSIS_MARKDOWN_NAME).is_file()
    assert not directory.with_suffix(".json").exists()
    assert len(load_analysis(directory)["run_metrics"]) == 5


def test_cli_single_file_output_stays_opt_in(case, tmp_path, monkeypatch):
    _write_inputs(case, tmp_path)
    monkeypatch.chdir(tmp_path)
    result = CliRunner().invoke(app, ["evaluate", "analyze", "--generated-at", GENERATED.isoformat(),
                                      "--output-json", "out/analysis.json"])
    assert result.exit_code == 0, result.output
    assert Path("out/analysis.json").is_file() and Path("out/analysis.md").is_file()
    assert not Path(DEFAULT_ANALYSIS_DIR).exists()
    both = CliRunner().invoke(app, ["evaluate", "analyze", "--generated-at", GENERATED.isoformat(),
                                    "--output-json", "out/analysis.json", "--output-dir", "out/partitioned"])
    assert both.exit_code == 0, both.output
    assert serialize_analysis(load_analysis(Path("out/partitioned"))) == Path("out/analysis.json").read_text()
    assert Path("out/partitioned", ANALYSIS_MARKDOWN_NAME).is_file()
