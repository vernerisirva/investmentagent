"""Bounded publication storage for schema-4 benchmark analyses.

The analysis values are unchanged. Only the persisted representation differs: one compact
index plus one file per run horizon, so no published file grows with the number of
evaluation dates. Loading the index reconstructs the exact monolithic analysis dictionary.
"""
from __future__ import annotations

import hashlib
import json
import re
from datetime import date
from pathlib import Path, PurePosixPath
from typing import Any

from investmentagent.evaluation_analysis import _atomic_write_if_changed, _validate_analysis_version


ANALYSIS_STORAGE_LAYOUT = "run-horizon-partitions-v1"
ANALYSIS_INDEX_NAME = "index.json"
ANALYSIS_MARKDOWN_NAME = "performance-v2.md"
STORAGE_KEY = "analysis_storage"
# Every run metric repeats the analysis status cutoff; storing it once keeps unchanged
# historical partitions byte-identical from one scheduled run to the next.
FACTORED_RUN_METRIC_FIELDS = ("lifecycle.status_cutoff",)
_SAFE_COMPONENT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
_STRATEGIES = ("trading", "long-term")


def serialize_analysis(analysis: dict[str, Any]) -> str:
    """The exact bytes `save_analysis_json` writes for a monolithic analysis."""
    return json.dumps(analysis, allow_nan=False, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def save_partitioned_analysis(directory: Path, analysis: dict[str, Any]) -> Path:
    from investmentagent.benchmark_analysis import BENCHMARK_ANALYSIS_SCHEMA
    _validate_analysis_version(analysis)
    if analysis.get("schema_version") != BENCHMARK_ANALYSIS_SCHEMA:
        raise ValueError("partitioned storage requires a schema-4 benchmark analysis")
    if STORAGE_KEY in analysis:
        raise ValueError("analysis already contains a storage manifest")
    if directory.exists() and not directory.is_dir():
        raise ValueError("partitioned analysis output must be a directory")
    cutoff = analysis["lifecycle"]["status_cutoff"]
    partitions, references, seen = [], [], set()
    for metric in analysis["run_metrics"]:
        run_id, label = metric["evaluation_run_id"], metric["horizon"]["label"]
        if (run_id, label) in seen:
            raise ValueError("duplicate run horizon in analysis")
        seen.add((run_id, label))
        if metric.get("lifecycle", {}).get("status_cutoff") != cutoff:
            raise ValueError("run metric status cutoff differs from the analysis status cutoff")
        stored = {**metric, "lifecycle": {k: v for k, v in metric["lifecycle"].items() if k != "status_cutoff"}}
        relative = _partition_path(metric)
        content = serialize_analysis({
            "analysis_storage_layout": ANALYSIS_STORAGE_LAYOUT, "schema_version": analysis["schema_version"],
            "evaluation_run_id": run_id, "horizon_label": label, "run_metric": stored,
        })
        partitions.append((relative, content))
        references.append({"evaluation_run_id": run_id, "horizon_label": label, "path": relative,
                           "sha256": hashlib.sha256(content.encode("utf-8")).hexdigest()})
    index_path = directory / ANALYSIS_INDEX_NAME
    if index_path.exists():
        existing = _read_index(index_path)
        if (existing["schema_version"], existing.get("benchmark_methodology")) != (
                analysis["schema_version"], analysis.get("benchmark_methodology")):
            raise ValueError("refusing to overwrite historical analysis; use a versioned output path")
        published = {(ref["evaluation_run_id"], ref["horizon_label"]) for ref in existing[STORAGE_KEY]["run_metric_partitions"]}
        if not published <= seen:
            raise ValueError("refusing to drop previously published run-horizon partitions")
    monolithic = serialize_analysis(analysis)
    index = {key: value for key, value in analysis.items() if key != "run_metrics"}
    index[STORAGE_KEY] = {
        "layout": ANALYSIS_STORAGE_LAYOUT,
        "run_metric_count": len(references),
        "run_metric_partitions": references,
        "factored_run_metric_fields": list(FACTORED_RUN_METRIC_FIELDS),
        "reconstruction": ("run_metrics are the partitions' run_metric objects in listed order, each with "
                           "lifecycle.status_cutoff restored from this index's lifecycle.status_cutoff"),
        "reconstructed_sha256": hashlib.sha256(monolithic.encode("utf-8")).hexdigest(),
    }
    for relative, content in partitions:
        _atomic_write_if_changed(directory / relative, content)
    _atomic_write_if_changed(index_path, serialize_analysis(index))
    if serialize_analysis(load_partitioned_analysis(directory)) != monolithic:
        raise ValueError("partitioned analysis does not reconstruct the computed analysis")
    return index_path


def load_partitioned_analysis(directory: Path) -> dict[str, Any]:
    index = _read_index(directory / ANALYSIS_INDEX_NAME)
    storage = index.pop(STORAGE_KEY)
    cutoff = index["lifecycle"]["status_cutoff"]
    metrics = []
    for reference in storage["run_metric_partitions"]:
        relative = reference["path"]
        if relative != _relative_path(relative):
            raise ValueError("unsafe analysis partition path")
        try:
            content = (directory / relative).read_text(encoding="utf-8")
        except OSError as exc:
            raise ValueError(f"missing analysis partition: {relative}") from exc
        if hashlib.sha256(content.encode("utf-8")).hexdigest() != reference["sha256"]:
            raise ValueError(f"analysis partition does not match its index digest: {relative}")
        partition = json.loads(content)
        if (partition.get("analysis_storage_layout"), partition.get("schema_version"),
                partition.get("evaluation_run_id"), partition.get("horizon_label")) != (
                storage["layout"], index["schema_version"], reference["evaluation_run_id"], reference["horizon_label"]):
            raise ValueError(f"analysis partition identity mismatch: {relative}")
        metric = partition["run_metric"]
        if "status_cutoff" in metric["lifecycle"]:
            raise ValueError(f"analysis partition repeats a factored field: {relative}")
        metric["lifecycle"]["status_cutoff"] = cutoff
        if _partition_path(metric) != relative:
            raise ValueError(f"analysis partition stored at an unexpected path: {relative}")
        metrics.append(metric)
    if len(metrics) != storage["run_metric_count"]:
        raise ValueError("analysis index partition count mismatch")
    analysis = {**index, "run_metrics": metrics}
    if hashlib.sha256(serialize_analysis(analysis).encode("utf-8")).hexdigest() != storage["reconstructed_sha256"]:
        raise ValueError("reconstructed analysis does not match the index digest")
    return analysis


def load_analysis(path: Path) -> dict[str, Any]:
    """Read either a partitioned analysis (directory or index) or a legacy monolithic JSON."""
    if path.is_dir():
        return load_partitioned_analysis(path)
    payload = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(payload, dict) and STORAGE_KEY in payload:
        return load_partitioned_analysis(path.parent)
    return payload


def _read_index(path: Path) -> dict[str, Any]:
    index = json.loads(path.read_text(encoding="utf-8"))
    storage = index.get(STORAGE_KEY) if isinstance(index, dict) else None
    if not isinstance(storage, dict) or storage.get("layout") != ANALYSIS_STORAGE_LAYOUT:
        raise ValueError("unsupported analysis storage layout")
    if storage.get("factored_run_metric_fields") != list(FACTORED_RUN_METRIC_FIELDS) or "run_metrics" in index:
        raise ValueError("unsupported analysis storage layout")
    _validate_analysis_version(index)
    return index


def _partition_path(metric: dict[str, Any]) -> str:
    decision_day = date.fromisoformat(metric["decision_at"][:10]).isoformat()
    strategy, run_id, label = metric["strategy"], metric["evaluation_run_id"], metric["horizon"]["label"]
    if strategy not in _STRATEGIES or not all(_SAFE_COMPONENT.match(value) for value in (run_id, label)):
        raise ValueError("run metric identity cannot form a safe partition path")
    return _relative_path(f"runs/{decision_day}/{strategy}/{run_id}/{label}.json")


def _relative_path(value: str) -> str:
    path = PurePosixPath(value)
    if path.is_absolute() or any(part in ("", ".", "..") for part in path.parts) or path.parts[0] != "runs":
        raise ValueError("unsafe analysis partition path")
    return path.as_posix()
