from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from tools.headless_stress.task_builders import (
    REPO_ROOT,
    _is_relative_to,
    _resolve,
    _write_json,
    safe_child_dir,
)


@dataclass(slots=True)
class _SyntheticCacheFixture:
    archive_root: Path
    cache_root: Path
    pamt_a: Path
    pamt_b: Path
    paz_b: Path
    entries_by_pamt: dict[Path, list[Any]]
    entry_type: Any


def _archive_entry(entry_type: Any, path: str, pamt_path: Path, paz_path: Path, payload: bytes) -> Any:
    return entry_type(
        path=path,
        pamt_path=pamt_path,
        paz_file=paz_path,
        offset=0,
        comp_size=len(payload),
        orig_size=len(payload),
        flags=0,
        paz_index=0,
    )


def _corrupt_cache_target(shard_dir: Path, cache_root: Path) -> Path | None:
    if not _is_relative_to(_resolve(shard_dir), _resolve(cache_root)):
        return None
    return next(iter(sorted(shard_dir.glob("*.bin"))), None) if shard_dir.is_dir() else None


def _build_synthetic_cache_fixture(output_dir: Path, entry_type: Any) -> _SyntheticCacheFixture:
    archive_root = safe_child_dir(output_dir, "synthetic_archive")
    cache_root = safe_child_dir(output_dir, "cache")

    def write_pair(group: str, payload: bytes) -> tuple[Path, Path]:
        group_dir = safe_child_dir(archive_root, group)
        pamt_path = group_dir / "0.pamt"
        paz_path = group_dir / "0.paz"
        pamt_path.write_bytes(b"pamt:" + group.encode("ascii"))
        paz_path.write_bytes(payload)
        return pamt_path, paz_path

    pamt_a, paz_a = write_pair("0000", b"a")
    pamt_b, paz_b = write_pair("0001", b"b")
    return _SyntheticCacheFixture(
        archive_root=archive_root,
        cache_root=cache_root,
        pamt_a=pamt_a,
        pamt_b=pamt_b,
        paz_b=paz_b,
        entries_by_pamt={
            pamt_a: [_archive_entry(entry_type, "character/model/a.pac", pamt_a, paz_a, b"a")],
            pamt_b: [_archive_entry(entry_type, "character/model/b.pac", pamt_b, paz_b, b"b")],
        },
        entry_type=entry_type,
    )


def _run_synthetic_cache_cycle(
    fixture: _SyntheticCacheFixture,
    cycle: int,
    output_root: Path,
    archive_scan_shard_cache_health: Any,
    invalidate_archive_browser_cache: Any,
    load_or_update_archive_scan_shards: Any,
    resolve_archive_scan_shard_cache_dir: Any,
) -> dict[str, Any]:
    archive_root = fixture.archive_root
    cache_root = fixture.cache_root
    entries_by_pamt = fixture.entries_by_pamt
    pre_deleted = invalidate_archive_browser_cache(archive_root, cache_root)
    initial_health = archive_scan_shard_cache_health(archive_root, cache_root)
    calls: list[str] = []

    def shard_scan(path: Path) -> list[Any]:
        calls.append(path.relative_to(archive_root).as_posix())
        return list(entries_by_pamt[path])

    cold_timings: dict[str, float] = {}
    cold_started = time.perf_counter()
    cold_entries, cold_source, _cold_dir = load_or_update_archive_scan_shards(
        archive_root, cache_root, shard_scan_func=shard_scan, timings=cold_timings
    )
    cold_elapsed = time.perf_counter() - cold_started

    def no_scan(path: Path) -> list[Any]:
        raise AssertionError(f"warm cache should not rescan {path}")

    warm_timings: dict[str, float] = {}
    warm_started = time.perf_counter()
    warm_entries, warm_source, _warm_dir = load_or_update_archive_scan_shards(
        archive_root, cache_root, shard_scan_func=no_scan, timings=warm_timings
    )
    warm_elapsed = time.perf_counter() - warm_started
    fresh_process = _fresh_process_cache_load(archive_root, cache_root)

    stale_calls: list[str] = []
    fixture.pamt_b.write_bytes(f"pamt:0001:cycle:{cycle}".encode("ascii"))
    entries_by_pamt[fixture.pamt_b] = [
        _archive_entry(
            fixture.entry_type,
            f"character/model/b_changed_{cycle}.pac",
            fixture.pamt_b,
            fixture.paz_b,
            b"b",
        )
    ]

    def stale_scan(path: Path) -> list[Any]:
        stale_calls.append(path.relative_to(archive_root).as_posix())
        if path == fixture.pamt_a:
            raise AssertionError("unchanged shard should not rescan")
        return list(entries_by_pamt[path])

    stale_timings: dict[str, float] = {}
    stale_started = time.perf_counter()
    stale_entries, stale_source, _stale_dir = load_or_update_archive_scan_shards(
        archive_root, cache_root, shard_scan_func=stale_scan, timings=stale_timings
    )
    stale_elapsed = time.perf_counter() - stale_started
    deleted = invalidate_archive_browser_cache(archive_root, cache_root)
    rebuild_calls: list[str] = []

    def rebuild_scan(path: Path) -> list[Any]:
        rebuild_calls.append(path.relative_to(archive_root).as_posix())
        return list(entries_by_pamt[path])

    rebuild_timings: dict[str, float] = {}
    rebuild_started = time.perf_counter()
    rebuild_entries, rebuild_source, _rebuild_dir = load_or_update_archive_scan_shards(
        archive_root, cache_root, shard_scan_func=rebuild_scan, timings=rebuild_timings
    )
    rebuild_elapsed = time.perf_counter() - rebuild_started
    shard_dir = resolve_archive_scan_shard_cache_dir(archive_root, cache_root)
    corrupt_target = _corrupt_cache_target(shard_dir, cache_root)
    corrupt_calls: list[str] = []
    corrupt_timings: dict[str, float] = {}
    corrupt_entries: list[Any] = []
    corrupt_source = "missing_target"
    corrupt_elapsed = 0.0
    corrupt_health: Mapping[str, object] = {}
    if corrupt_target is not None:
        corrupt_target.write_bytes(b"corrupt shard")
        corrupt_health = archive_scan_shard_cache_health(archive_root, cache_root, deep=True)

        def corrupt_scan(path: Path) -> list[Any]:
            corrupt_calls.append(path.relative_to(archive_root).as_posix())
            return list(entries_by_pamt[path])

        corrupt_started = time.perf_counter()
        corrupt_entries, corrupt_source, _corrupt_dir = load_or_update_archive_scan_shards(
            archive_root, cache_root, shard_scan_func=corrupt_scan, timings=corrupt_timings
        )
        corrupt_elapsed = time.perf_counter() - corrupt_started
    return {
        "cycle": cycle,
        "pre_delete": {"deleted_count": len(pre_deleted), "deleted_paths": [str(path) for path in pre_deleted]},
        "initial_health": initial_health,
        "cold": {"source": cold_source, "entries": len(cold_entries), "scan_calls": calls, "elapsed_s": cold_elapsed, "timings": cold_timings},
        "warm": {"source": warm_source, "entries": len(warm_entries), "elapsed_s": warm_elapsed, "timings": warm_timings},
        "fresh_process_warm": fresh_process,
        "stale": {"source": stale_source, "entries": len(stale_entries), "scan_calls": stale_calls, "elapsed_s": stale_elapsed, "timings": stale_timings},
        "delete": {"deleted_count": len(deleted), "deleted_paths": [str(path) for path in deleted], "within_output": all(_is_relative_to(_resolve(path), output_root) for path in deleted)},
        "rebuild": {"source": rebuild_source, "entries": len(rebuild_entries), "scan_calls": rebuild_calls, "elapsed_s": rebuild_elapsed, "timings": rebuild_timings},
        "corrupt_recovery": {"source": corrupt_source, "entries": len(corrupt_entries), "scan_calls": corrupt_calls, "elapsed_s": corrupt_elapsed, "timings": corrupt_timings, "target": str(corrupt_target) if corrupt_target else "", "pre_recovery_health": corrupt_health},
        "cache_size_bytes": _tree_size_bytes(cache_root),
        "final_health": archive_scan_shard_cache_health(archive_root, cache_root, deep=True),
    }


def run_cache_probe(output_dir: Path, *, cycles: int = 1) -> dict[str, Any]:
    started = time.perf_counter()
    output_dir.mkdir(parents=True, exist_ok=True)
    try:
        from cdmw.core.archive_scan_cache import (
            archive_scan_shard_cache_health,
            invalidate_archive_browser_cache,
            load_or_update_archive_scan_shards,
            resolve_archive_scan_shard_cache_dir,
        )
        from cdmw.models import ArchiveEntry
    except Exception as exc:
        result = {"status": "skipped", "ok": True, "reason": f"Cache APIs unavailable: {exc}"}
        _write_json(output_dir / "cache_probe.json", result)
        return result

    fixture = _build_synthetic_cache_fixture(output_dir, ArchiveEntry)
    output_root = _resolve(output_dir)
    rows = [
        _run_synthetic_cache_cycle(
            fixture,
            cycle,
            output_root,
            archive_scan_shard_cache_health,
            invalidate_archive_browser_cache,
            load_or_update_archive_scan_shards,
            resolve_archive_scan_shard_cache_dir,
        )
        for cycle in range(1, max(1, int(cycles)) + 1)
    ]
    ok = all(
        row["cold"]["source"] in {"cache+scan", "cache+native_scan"}
        and row["warm"]["source"] == "cache"
        and row["fresh_process_warm"].get("source") == "cache"
        and row["fresh_process_warm"].get("entries") == row["warm"]["entries"]
        and row["stale"]["source"] in {"cache+scan", "cache+native_scan"}
        and row["stale"]["scan_calls"] == ["0001/0.pamt"]
        and row["delete"]["deleted_count"] > 0
        and row["delete"]["within_output"]
        and row["rebuild"]["source"] in {"cache+scan", "cache+native_scan"}
        and row["corrupt_recovery"]["source"] in {"cache+scan", "cache+native_scan"}
        and row["corrupt_recovery"]["entries"] == row["rebuild"]["entries"]
        and row["final_health"].get("status") == "healthy"
        for row in rows
    )
    result = {
        "status": "passed" if ok else "failed",
        "ok": ok,
        "elapsed_s": time.perf_counter() - started,
        "cycles": rows,
        "summary": _cache_probe_summary(rows),
    }
    _write_json(output_dir / "cache_probe.json", result)
    return result


def run_real_cache_probe(output_dir: Path, archive_root: Path, *, cycles: int = 1) -> dict[str, Any]:
    started = time.perf_counter()
    output_dir.mkdir(parents=True, exist_ok=True)
    archive_root = _resolve(archive_root)
    if not archive_root.exists():
        result = {"status": "failed", "ok": False, "reason": f"Cache real root not found: {archive_root}"}
        _write_json(output_dir / "cache_probe.json", result)
        return result
    try:
        from cdmw.core.archive_accelerator import scan_archive_entries_cached_accelerated
        from cdmw.core.archive_scan_cache import (
            archive_scan_shard_cache_health,
            invalidate_archive_browser_cache,
            resolve_archive_scan_shard_cache_dir,
        )
    except Exception as exc:
        result = {"status": "skipped", "ok": True, "reason": f"Real cache APIs unavailable: {exc}"}
        _write_json(output_dir / "cache_probe.json", result)
        return result

    cache_root = safe_child_dir(output_dir, "real_cache")
    rows: list[dict[str, Any]] = []
    output_root = _resolve(output_dir)

    def cached_load() -> dict[str, Any]:
        load_started = time.perf_counter()
        entries, source, cache_dir, timings, metadata = scan_archive_entries_cached_accelerated(archive_root, cache_root)
        return {
            "source": source,
            "entries": len(entries),
            "elapsed_s": time.perf_counter() - load_started,
            "timings": timings,
            "metadata": metadata,
            "cache_dir": str(cache_dir or ""),
        }

    for cycle in range(1, max(1, int(cycles)) + 1):
        pre_deleted = invalidate_archive_browser_cache(archive_root, cache_root)
        cold = cached_load()
        warm = cached_load()
        fresh_process = _fresh_process_accelerated_cache_load(archive_root, cache_root)
        deleted = invalidate_archive_browser_cache(archive_root, cache_root)
        rebuild = cached_load()
        shard_dir = resolve_archive_scan_shard_cache_dir(archive_root, cache_root)
        corrupt_target = _corrupt_cache_target(shard_dir, cache_root)
        corrupt_health: Mapping[str, object] = {}
        corrupt = {"source": "missing_target", "entries": 0, "elapsed_s": 0.0, "timings": {}, "metadata": {}}
        if corrupt_target is not None:
            corrupt_target.write_bytes(b"corrupt shard")
            corrupt_health = archive_scan_shard_cache_health(archive_root, cache_root, deep=True)
            corrupt = cached_load()
        rows.append(
            {
                "cycle": cycle,
                "mode": "real",
                "archive_root": str(archive_root),
                "pre_delete": {"deleted_count": len(pre_deleted), "deleted_paths": [str(path) for path in pre_deleted]},
                "cold": cold,
                "warm": warm,
                "fresh_process_warm": fresh_process,
                "delete": {
                    "deleted_count": len(deleted),
                    "deleted_paths": [str(path) for path in deleted],
                    "within_output": all(_is_relative_to(_resolve(path), output_root) for path in deleted),
                },
                "rebuild": rebuild,
                "corrupt_recovery": {
                    **corrupt,
                    "target": str(corrupt_target) if corrupt_target else "",
                    "pre_recovery_health": corrupt_health,
                },
                "cache_size_bytes": _tree_size_bytes(cache_root),
                "final_health": archive_scan_shard_cache_health(archive_root, cache_root, deep=True),
            }
        )

    scan_sources = {"scan", "native_scan", "cache+scan", "cache+native_scan"}
    ok = all(
        row["cold"]["source"] in scan_sources
        and row["warm"]["source"] == "cache"
        and row["fresh_process_warm"].get("source") == "cache"
        and row["fresh_process_warm"].get("entries") == row["warm"]["entries"]
        and row["delete"]["deleted_count"] > 0
        and row["delete"]["within_output"]
        and row["rebuild"]["source"] in scan_sources
        and row["corrupt_recovery"]["source"] in scan_sources
        and row["corrupt_recovery"]["entries"] == row["rebuild"]["entries"]
        and row["final_health"].get("status") == "healthy"
        for row in rows
    )
    result = {
        "status": "passed" if ok else "failed",
        "ok": ok,
        "mode": "real",
        "archive_root": str(archive_root),
        "elapsed_s": time.perf_counter() - started,
        "cycles": rows,
        "summary": _cache_probe_summary(rows),
    }
    _write_json(output_dir / "cache_probe.json", result)
    return result


def _fresh_process_cache_load(archive_root: Path, cache_root: Path) -> dict[str, Any]:
    code = (
        "import json, sys, time\n"
        "from pathlib import Path\n"
        "from cdmw.core.archive_scan_cache import load_or_update_archive_scan_shards\n"
        "def no_scan(path):\n"
        "    raise AssertionError(f'fresh process warm cache should not rescan {path}')\n"
        "started=time.perf_counter(); timings={}\n"
        "entries, source, cache_dir = load_or_update_archive_scan_shards(Path(sys.argv[1]), Path(sys.argv[2]), shard_scan_func=no_scan, timings=timings)\n"
        "print(json.dumps({'source': source, 'entries': len(entries), 'elapsed_s': time.perf_counter()-started, 'timings': timings, 'cache_dir': str(cache_dir or '')}, sort_keys=True))\n"
    )
    env = os.environ.copy()
    env["PYTHONPATH"] = str(REPO_ROOT) + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
    started = time.perf_counter()
    completed = subprocess.run(
        [sys.executable, "-c", code, str(archive_root), str(cache_root)],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        shell=False,
    )
    elapsed = time.perf_counter() - started
    if completed.returncode != 0:
        return {"source": "failed", "entries": 0, "elapsed_s": elapsed, "returncode": completed.returncode, "stderr": completed.stderr}
    payload = json.loads(completed.stdout or "{}")
    payload["returncode"] = completed.returncode
    return payload


def _fresh_process_accelerated_cache_load(archive_root: Path, cache_root: Path) -> dict[str, Any]:
    code = (
        "import json, sys, time\n"
        "from pathlib import Path\n"
        "from cdmw.core.archive_accelerator import scan_archive_entries_cached_accelerated\n"
        "started=time.perf_counter()\n"
        "entries, source, cache_dir, timings, metadata = scan_archive_entries_cached_accelerated(Path(sys.argv[1]), Path(sys.argv[2]))\n"
        "print(json.dumps({'source': source, 'entries': len(entries), 'elapsed_s': time.perf_counter()-started, 'timings': timings, 'metadata': metadata, 'cache_dir': str(cache_dir or '')}, sort_keys=True))\n"
    )
    env = os.environ.copy()
    env["PYTHONPATH"] = str(REPO_ROOT) + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
    started = time.perf_counter()
    completed = subprocess.run(
        [sys.executable, "-c", code, str(archive_root), str(cache_root)],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        shell=False,
    )
    elapsed = time.perf_counter() - started
    if completed.returncode != 0:
        return {"source": "failed", "entries": 0, "elapsed_s": elapsed, "returncode": completed.returncode, "stderr": completed.stderr}
    payload = json.loads(completed.stdout or "{}")
    payload["returncode"] = completed.returncode
    return payload


def _tree_size_bytes(root: Path) -> int:
    if not root.exists():
        return 0
    return sum(path.stat().st_size for path in root.rglob("*") if path.is_file())


def _phase_stats(values: Sequence[float]) -> dict[str, float]:
    ordered = sorted(float(value) for value in values)
    if not ordered:
        return {"min_s": 0.0, "median_s": 0.0, "p95_s": 0.0, "max_s": 0.0}
    mid = len(ordered) // 2
    median = ordered[mid] if len(ordered) % 2 else (ordered[mid - 1] + ordered[mid]) / 2.0
    p95_index = min(len(ordered) - 1, max(0, int(len(ordered) * 0.95 + 0.999999) - 1))
    return {"min_s": ordered[0], "median_s": median, "p95_s": ordered[p95_index], "max_s": ordered[-1]}


def _cache_probe_summary(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    phases = ("cold", "warm", "fresh_process_warm", "stale", "rebuild", "corrupt_recovery")
    timings = {
        phase: _phase_stats([float(row.get(phase, {}).get("elapsed_s", 0.0) or 0.0) for row in rows])
        for phase in phases
    }
    cold_median = timings["cold"]["median_s"]
    warm_median = timings["warm"]["median_s"]
    fresh_median = timings["fresh_process_warm"]["median_s"]
    return {
        "runs": len(rows),
        "phase_timings": timings,
        "warm_vs_cold_speedup": cold_median / warm_median if warm_median > 0 else 0.0,
        "fresh_process_warm_vs_cold_speedup": cold_median / fresh_median if fresh_median > 0 else 0.0,
        "cache_size_bytes": max((int(row.get("cache_size_bytes", 0) or 0) for row in rows), default=0),
    }
