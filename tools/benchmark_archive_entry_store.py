from __future__ import annotations

import argparse
import gc
import hashlib
import json
import os
import pickle
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Sequence

import psutil


ROOT = Path(__file__).resolve().parents[1]
SCHEMA_VERSION = 1
FIRST_ROWS_TARGET = 1_000
TIME_REDUCTION_TARGET_PERCENT = 50.0
RSS_REDUCTION_TARGET_PERCENT = 40.0


def _append_root() -> None:
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))


def _synthetic_entries(count: int, root: Path) -> list[object]:
    _append_root()
    from cdmw.models import ArchiveEntry

    pamt_paths = tuple(root / "archives" / f"{index:04d}" / f"{index}.pamt" for index in range(36))
    extensions = (".pac", ".pam", ".pamlod", ".dds", ".hkx", ".xml", ".bin")
    return [
        ArchiveEntry(
            path=f"asset/group_{index % 4096:04d}/item_{index:08d}{extensions[index % len(extensions)]}",
            pamt_path=pamt_paths[index % len(pamt_paths)],
            paz_file=pamt_paths[index % len(pamt_paths)].parent / f"{index % 8}.paz",
            offset=index * 64,
            comp_size=48 + (index % 64),
            orig_size=96 + (index % 128),
            flags=index % 5,
            paz_index=index % 8,
        )
        for index in range(max(0, int(count)))
    ]


def _legacy_rows(entries: Sequence[object]) -> list[tuple[object, ...]]:
    return [
        (
            str(getattr(entry, "path", "") or ""),
            str(getattr(entry, "pamt_path", "") or ""),
            int(getattr(entry, "offset", 0) or 0),
            int(getattr(entry, "comp_size", 0) or 0),
            int(getattr(entry, "orig_size", 0) or 0),
            int(getattr(entry, "flags", 0) or 0),
            int(getattr(entry, "paz_index", 0) or 0),
        )
        for entry in entries
    ]


def _rss_bytes() -> int:
    return int(psutil.Process(os.getpid()).memory_info().rss)


def _entry_checksum(entries: Sequence[object]) -> str:
    digest = hashlib.sha256()
    for entry in entries:
        row = (
            str(getattr(entry, "path", "") or ""),
            str(getattr(entry, "pamt_path", "") or ""),
            str(getattr(entry, "paz_file", "") or ""),
            int(getattr(entry, "offset", 0) or 0),
            int(getattr(entry, "comp_size", 0) or 0),
            int(getattr(entry, "orig_size", 0) or 0),
            int(getattr(entry, "flags", 0) or 0),
            int(getattr(entry, "paz_index", 0) or 0),
        )
        digest.update(json.dumps(row, separators=(",", ":")).encode("utf-8"))
        digest.update(b"\n")
    return digest.hexdigest()


def _legacy_probe(path: Path) -> dict[str, object]:
    _append_root()
    from cdmw.models import ArchiveEntry

    gc.collect()
    before = _rss_bytes()
    started = time.perf_counter()
    with path.open("rb") as stream:
        rows = pickle.load(stream)
    entries = [
        ArchiveEntry(
            path=str(row[0]),
            pamt_path=Path(str(row[1])),
            paz_file=Path(str(row[1])).parent / f"{int(row[6])}.paz",
            offset=int(row[2]),
            comp_size=int(row[3]),
            orig_size=int(row[4]),
            flags=int(row[5]),
            paz_index=int(row[6]),
        )
        for row in rows
    ]
    first_rows = entries[: min(FIRST_ROWS_TARGET, len(entries))]
    elapsed_ms = (time.perf_counter() - started) * 1000.0
    after = _rss_bytes()
    return {
        "entry_count": len(entries),
        "first_row_count": len(first_rows),
        "elapsed_ms": elapsed_ms,
        "rss_delta_bytes": max(0, after - before),
        "checksum": _entry_checksum(first_rows),
    }


def _compact_probe(path: Path) -> dict[str, object]:
    _append_root()
    from cdmw.core.archive_entry_store import ArchiveEntryStore

    gc.collect()
    before = _rss_bytes()
    started = time.perf_counter()
    with ArchiveEntryStore(path) as store:
        first_rows = list(store.iter_entries(range(min(FIRST_ROWS_TARGET, len(store)))))
        entry_count = len(store)
    elapsed_ms = (time.perf_counter() - started) * 1000.0
    after = _rss_bytes()
    return {
        "entry_count": entry_count,
        "first_row_count": len(first_rows),
        "elapsed_ms": elapsed_ms,
        "rss_delta_bytes": max(0, after - before),
        "checksum": _entry_checksum(first_rows),
    }


def _legacy_shards_probe(path: Path) -> dict[str, object]:
    _append_root()
    from cdmw.core.archive_scan_cache import (
        _archive_base_dir,
        _decode_archive_scan_cache_rows,
        _deserialize_archive_scan_shard_cache_payload_from_path,
    )

    gc.collect()
    before = _rss_bytes()
    started = time.perf_counter()
    entries = []
    for shard_path in sorted(Path(path).glob("*.bin")):
        payload = _deserialize_archive_scan_shard_cache_payload_from_path(shard_path)
        package_root = Path(str(payload.get("package_root", "") or ""))
        entries.extend(
            _decode_archive_scan_cache_rows(
                _archive_base_dir(package_root),
                payload.get("rows"),
            )
        )
    first_rows = entries[: min(FIRST_ROWS_TARGET, len(entries))]
    elapsed_ms = (time.perf_counter() - started) * 1000.0
    after = _rss_bytes()
    return {
        "entry_count": len(entries),
        "first_row_count": len(first_rows),
        "elapsed_ms": elapsed_ms,
        "rss_delta_bytes": max(0, after - before),
        "checksum": _entry_checksum(first_rows),
    }


def _run_child(kind: str, path: Path) -> dict[str, object]:
    completed = subprocess.run(
        [sys.executable, str(Path(__file__).resolve()), "--child", kind, "--input", str(path)],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=120,
    )
    if completed.returncode != 0:
        raise RuntimeError(completed.stderr or completed.stdout)
    return json.loads(completed.stdout.splitlines()[-1])


def _reduction_percent(before: float, after: float) -> float:
    return 100.0 * (float(before) - float(after)) / max(float(before), 1.0)


def build_benchmark(entry_count: int) -> dict[str, object]:
    _append_root()
    from cdmw.core.archive_entry_store import write_archive_entry_store

    with tempfile.TemporaryDirectory(prefix="cdmw-entry-store-benchmark-") as temp_dir:
        root = Path(temp_dir)
        entries = _synthetic_entries(entry_count, root)
        legacy_path = root / "legacy-rows.pkl"
        with legacy_path.open("wb") as stream:
            pickle.dump(_legacy_rows(entries), stream, protocol=pickle.HIGHEST_PROTOCOL)
        compact_path = write_archive_entry_store(root / "compact-store", entries)
        del entries
        gc.collect()
        legacy = _run_child("legacy", legacy_path)
        compact = _run_child("compact", compact_path)
        time_reduction = _reduction_percent(legacy["elapsed_ms"], compact["elapsed_ms"])
        rss_reduction = _reduction_percent(legacy["rss_delta_bytes"], compact["rss_delta_bytes"])
        return {
            "schema_version": SCHEMA_VERSION,
            "entry_count": int(entry_count),
            "first_rows": FIRST_ROWS_TARGET,
            "legacy": legacy,
            "compact": compact,
            "time_reduction_percent": round(time_reduction, 3),
            "rss_reduction_percent": round(rss_reduction, 3),
            "gates": {
                "cache_to_first_rows_at_least_50_percent_lower": time_reduction >= TIME_REDUCTION_TARGET_PERCENT,
                "peak_rss_at_least_40_percent_lower": rss_reduction >= RSS_REDUCTION_TARGET_PERCENT,
                "row_parity": legacy["checksum"] == compact["checksum"],
            },
        }


def build_shard_benchmark(shard_dir: Path) -> dict[str, object]:
    _append_root()
    from cdmw.core.archive_entry_store import write_archive_entry_store
    from cdmw.core.archive_scan_cache import (
        _archive_base_dir,
        _decode_archive_scan_cache_rows,
        _deserialize_archive_scan_shard_cache_payload_from_path,
    )

    source_dir = Path(shard_dir).expanduser().resolve()
    shard_paths = tuple(sorted(source_dir.glob("*.bin")))
    if not shard_paths:
        raise ValueError(f"No archive scan shards were found under {source_dir}.")
    with tempfile.TemporaryDirectory(prefix="cdmw-entry-store-shard-benchmark-") as temp_dir:
        entries = []
        for shard_path in shard_paths:
            payload = _deserialize_archive_scan_shard_cache_payload_from_path(shard_path)
            package_root = Path(str(payload.get("package_root", "") or ""))
            entries.extend(
                _decode_archive_scan_cache_rows(
                    _archive_base_dir(package_root),
                    payload.get("rows"),
                )
            )
        compact_path = write_archive_entry_store(Path(temp_dir) / "compact-store", entries)
        entry_count = len(entries)
        del entries
        gc.collect()
        legacy = _run_child("legacy-shards", source_dir)
        compact = _run_child("compact", compact_path)
        time_reduction = _reduction_percent(legacy["elapsed_ms"], compact["elapsed_ms"])
        rss_reduction = _reduction_percent(legacy["rss_delta_bytes"], compact["rss_delta_bytes"])
        return {
            "schema_version": SCHEMA_VERSION,
            "source": "archive_scan_shards",
            "shard_count": len(shard_paths),
            "entry_count": entry_count,
            "first_rows": FIRST_ROWS_TARGET,
            "legacy": legacy,
            "compact": compact,
            "time_reduction_percent": round(time_reduction, 3),
            "rss_reduction_percent": round(rss_reduction, 3),
            "gates": {
                "cache_to_first_rows_at_least_50_percent_lower": time_reduction >= TIME_REDUCTION_TARGET_PERCENT,
                "peak_rss_at_least_40_percent_lower": rss_reduction >= RSS_REDUCTION_TARGET_PERCENT,
                "row_parity": legacy["checksum"] == compact["checksum"],
            },
        }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Compare legacy ArchiveEntry loading with the mmap prototype.")
    parser.add_argument("--entries", type=int, default=200_000)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--legacy-shard-dir", type=Path)
    parser.add_argument("--child", choices=("legacy", "legacy-shards", "compact"), help=argparse.SUPPRESS)
    parser.add_argument("--input", type=Path, help=argparse.SUPPRESS)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.child:
        if args.input is None:
            raise SystemExit("--input is required for a child probe")
        if args.child == "legacy":
            payload = _legacy_probe(args.input)
        elif args.child == "legacy-shards":
            payload = _legacy_shards_probe(args.input)
        else:
            payload = _compact_probe(args.input)
        print(json.dumps(payload, sort_keys=True))
        return 0
    if args.entries < 1:
        raise SystemExit("--entries must be at least 1")
    payload = (
        build_shard_benchmark(args.legacy_shard_dir)
        if args.legacy_shard_dir is not None
        else build_benchmark(args.entries)
    )
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0 if all(payload["gates"].values()) else 2


if __name__ == "__main__":
    raise SystemExit(main())
