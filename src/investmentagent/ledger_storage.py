"""Bounded publication storage for the legacy Performance v1 ledger.

The ledger values are unchanged. Only the persisted representation differs: one compact
index, one file per report date of picks and one file per market-snapshot date, so no
published file grows with the number of dates. Loading the index reconstructs the exact
single-file ledger dictionary.
"""
from __future__ import annotations

import hashlib
import json
from datetime import date
from pathlib import Path
from typing import Any, NamedTuple

from investmentagent.evaluation_analysis import _atomic_write_if_changed


LEDGER_STORAGE_LAYOUT = "report-date-partitions-v1"
LEDGER_INDEX_NAME = "index.json"
STORAGE_KEY = "ledger_storage"


class _Collection(NamedTuple):
    folder: str
    key: str
    field: str
    listing: str
    payload_type: type


_PICKS = _Collection("picks", "report_date", "picks", "pick_partitions", list)
_SNAPSHOTS = _Collection("market-snapshots", "as_of_date", "market_snapshot", "market_snapshot_partitions", dict)


def serialize_ledger(ledger: dict[str, Any]) -> str:
    """The exact bytes the single-file ledger writer produces."""
    return json.dumps(ledger, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def save_partitioned_ledger(directory: Path, ledger: dict[str, Any], *, legacy_seed: Path | None = None) -> Path:
    if STORAGE_KEY in ledger:
        raise ValueError("ledger already contains a storage manifest")
    if directory.exists() and not directory.is_dir():
        raise ValueError("partitioned ledger must be a directory")
    picks, snapshots = ledger.get("picks"), ledger.get("market_snapshots")
    if not isinstance(picks, list) or not isinstance(snapshots, dict):
        raise ValueError("ledger needs a picks list and a market_snapshots mapping")
    report_days = [_iso_day(pick.get("report_date")) for pick in picks]
    if report_days != sorted(report_days):
        raise ValueError("ledger picks are not grouped by ascending report date")
    grouped: dict[_Collection, dict[str, Any]] = {_PICKS: {}, _SNAPSHOTS: {}}
    for day, pick in zip(report_days, picks):
        grouped[_PICKS].setdefault(day, []).append(pick)
    for day in sorted(snapshots):
        grouped[_SNAPSHOTS][_iso_day(day)] = snapshots[day]
    partitions, references = [], {}
    for collection, payloads in grouped.items():
        references[collection.listing] = []
        for day, payload in payloads.items():
            relative = _partition_path(collection, day)
            content = serialize_ledger({"ledger_storage_layout": LEDGER_STORAGE_LAYOUT,
                                        "schema_version": ledger.get("schema_version"),
                                        collection.key: day, collection.field: payload})
            partitions.append((relative, content))
            references[collection.listing].append(
                {collection.key: day, "path": relative, "entries": len(payload), "sha256": _sha256(content)})
    index_path = directory / LEDGER_INDEX_NAME
    if index_path.exists():
        existing = _read_index(index_path)[STORAGE_KEY]
        _check_legacy_seed(existing, legacy_seed)
        seed_sha256 = existing["legacy_seed_sha256"]
        # A report date never loses picks; a snapshot date can be re-recorded but never disappears.
        current = {ref["report_date"]: ref["entries"] for ref in references[_PICKS.listing]}
        if any(current.get(ref["report_date"], 0) < ref["entries"] for ref in existing[_PICKS.listing]) or not (
                {ref["as_of_date"] for ref in existing[_SNAPSHOTS.listing]} <= grouped[_SNAPSHOTS].keys()):
            raise ValueError("refusing to drop previously published ledger picks or market snapshots")
    elif directory.exists() and any(directory.iterdir()):
        raise ValueError("partitioned ledger directory has files but no index")
    else:
        seed_sha256 = _file_sha256(legacy_seed)
    monolithic = serialize_ledger(ledger)
    index = {key: value for key, value in ledger.items() if key not in ("picks", "market_snapshots")}
    index[STORAGE_KEY] = {
        "layout": LEDGER_STORAGE_LAYOUT,
        "legacy_seed_sha256": seed_sha256,
        "pick_count": len(picks),
        "market_snapshot_count": len(grouped[_SNAPSHOTS]),
        **references,
        "reconstruction": ("picks are the pick partitions' picks concatenated in listed order; market_snapshots "
                           "maps each listed as_of_date to its partition's market_snapshot"),
        "reconstructed_sha256": _sha256(monolithic),
    }
    for relative, content in partitions:
        _atomic_write_if_changed(directory / relative, content)
    _atomic_write_if_changed(index_path, serialize_ledger(index))
    # Reloading checks every partition digest and that the reconstruction serializes to bytes
    # with the computed ledger's digest.
    load_partitioned_ledger(directory)
    return index_path


def load_partitioned_ledger(directory: Path, *, legacy_seed: Path | None = None) -> dict[str, Any] | None:
    """Reconstruct the single-file ledger dictionary, or None when the directory holds no ledger yet.

    `legacy_seed` is the single-file ledger the store was created from. While it exists it must stay
    unchanged, so a writer of the old file can never silently diverge from the partitions.
    """
    index_path = directory / LEDGER_INDEX_NAME
    if not index_path.exists():
        if directory.exists() and any(directory.iterdir()):
            raise ValueError("partitioned ledger directory has files but no index")
        return None
    index = _read_index(index_path)
    storage = index.pop(STORAGE_KEY)
    _check_legacy_seed(storage, legacy_seed)
    picks: list[dict[str, Any]] = []
    snapshots: dict[str, Any] = {}
    for collection in (_PICKS, _SNAPSHOTS):
        days = [reference[collection.key] for reference in storage[collection.listing]]
        if days != sorted(set(days)):
            raise ValueError(f"ledger index lists {collection.folder} partitions out of date order")
        for reference in storage[collection.listing]:
            relative = reference["path"]
            if relative != _partition_path(collection, reference[collection.key]):
                raise ValueError(f"ledger partition stored at an unexpected path: {relative}")
            try:
                content = (directory / relative).read_text(encoding="utf-8")
            except OSError as exc:
                raise ValueError(f"missing ledger partition: {relative}") from exc
            if _sha256(content) != reference["sha256"]:
                raise ValueError(f"ledger partition does not match its index digest: {relative}")
            partition = json.loads(content)
            payload = partition.get(collection.field) if isinstance(partition, dict) else None
            if not isinstance(payload, collection.payload_type) or len(payload) != reference["entries"] or (
                    partition.get("ledger_storage_layout"), partition.get("schema_version"),
                    partition.get(collection.key)) != (storage["layout"], index.get("schema_version"), reference[collection.key]):
                raise ValueError(f"ledger partition identity mismatch: {relative}")
            if collection is _PICKS:
                if any(pick.get("report_date") != reference["report_date"] for pick in payload):
                    raise ValueError(f"ledger partition identity mismatch: {relative}")
                picks.extend(payload)
            else:
                snapshots[reference["as_of_date"]] = payload
    if (len(picks), len(snapshots)) != (storage["pick_count"], storage["market_snapshot_count"]):
        raise ValueError("ledger index partition count mismatch")
    # Sorted top-level keys give the same in-memory key order as parsing the single file.
    ledger = dict(sorted({**index, "picks": picks, "market_snapshots": snapshots}.items()))
    if _sha256(serialize_ledger(ledger)) != storage["reconstructed_sha256"]:
        raise ValueError("reconstructed ledger does not match the index digest")
    return ledger


def _read_index(path: Path) -> dict[str, Any]:
    index = json.loads(path.read_text(encoding="utf-8"))
    storage = index.get(STORAGE_KEY) if isinstance(index, dict) else None
    if not isinstance(storage, dict) or storage.get("layout") != LEDGER_STORAGE_LAYOUT:
        raise ValueError("unsupported ledger storage layout")
    if "picks" in index or "market_snapshots" in index:
        raise ValueError("unsupported ledger storage layout")
    return index


def _check_legacy_seed(storage: dict[str, Any], legacy_seed: Path | None) -> None:
    if legacy_seed is not None and legacy_seed.exists() and _file_sha256(legacy_seed) != storage["legacy_seed_sha256"]:
        raise ValueError(f"legacy ledger {legacy_seed} differs from the file that seeded the partitioned ledger; "
                         "refusing to let the two diverge")


def _partition_path(collection: _Collection, day: str) -> str:
    day = _iso_day(day)
    return f"{collection.folder}/{day[:4]}/{day}.json"


def _iso_day(value: Any) -> str:
    try:
        canonical = date.fromisoformat(value).isoformat() if isinstance(value, str) else None
    except ValueError:
        canonical = None
    if canonical != value:
        raise ValueError(f"ledger date is not a YYYY-MM-DD day: {value!r}")
    return value


def _file_sha256(path: Path | None) -> str | None:
    return hashlib.sha256(path.read_bytes()).hexdigest() if path is not None and path.exists() else None


def _sha256(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()
