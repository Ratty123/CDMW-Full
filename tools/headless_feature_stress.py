from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, Sequence


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
DEFAULT_MODEL_ROOT = Path(r"E:\ModelCatalogue\downloads")
PROFILES = ("quick", "corpus", "soak")
SOAK_MINUTES_DEFAULT = 180.0
SOAK_MINUTES_MINIMUM = 120.0
NATIVE_HELPER_RELATIVE_PATHS = (
    Path("native/cd_texture_dx/build/Release/cd-texture-dx.exe"),
    Path("native/cdmw_d3d11_preview/build/Release/cdmw-d3d11-preview.exe"),
)
DEFAULT_CACHE_RUNS = 1


@dataclass(slots=True)
class Task:
    name: str
    kind: str
    output_dir: Path
    required: bool = True
    argv: list[str] = field(default_factory=list)
    env: dict[str, str] = field(default_factory=dict)
    skip_reason: str = ""
    artifacts: list[Path] = field(default_factory=list)
    cache_cycles: int = 1
    cache_real_root: Path | None = None


def _resolve(path: Path) -> Path:
    return path.expanduser().resolve(strict=False)


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def prepare_output_root(path: Path) -> Path:
    output_root = _resolve(path)
    if output_root.exists() and not output_root.is_dir():
        raise ValueError(f"--output must be a directory: {output_root}")
    output_root.mkdir(parents=True, exist_ok=True)
    return output_root


def safe_child_dir(output_root: Path, *parts: str) -> Path:
    child = _resolve(output_root.joinpath(*parts))
    if not _is_relative_to(child, output_root):
        raise ValueError(f"Refusing to write outside --output: {child}")
    child.mkdir(parents=True, exist_ok=True)
    return child


def _json_safe(value: Any) -> Any:
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, Mapping):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(_json_safe(payload), indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _python_tool(*parts: str) -> str:
    return str(REPO_ROOT.joinpath(*parts))


def _powershell() -> str | None:
    return shutil.which("powershell") or shutil.which("pwsh")


def _task_dir(output_root: Path, name: str, *, cycle: int | None = None) -> Path:
    parts = ("cycles", f"{cycle:05d}", "children", name) if cycle is not None else ("children", name)
    return safe_child_dir(output_root, *parts)


def _command_task(
    output_root: Path,
    name: str,
    argv: Sequence[str],
    *,
    required: bool = True,
    cycle: int | None = None,
    artifacts: Sequence[Path] = (),
    env: Mapping[str, str] | None = None,
) -> Task:
    return Task(
        name=name,
        kind="command",
        output_dir=_task_dir(output_root, name, cycle=cycle),
        required=required,
        argv=[str(part) for part in argv],
        artifacts=[Path(path) for path in artifacts],
        env=dict(env or {}),
    )


def _skip_task(output_root: Path, name: str, reason: str, *, cycle: int | None = None) -> Task:
    return Task(name=name, kind="skip", output_dir=_task_dir(output_root, name, cycle=cycle), required=False, skip_reason=reason)


def _probe_task(
    output_root: Path,
    name: str,
    kind: str,
    *,
    cycle: int | None = None,
    cache_cycles: int = 1,
    cache_real_root: Path | None = None,
) -> Task:
    return Task(name=name, kind=kind, output_dir=_task_dir(output_root, name, cycle=cycle), cache_cycles=cache_cycles, cache_real_root=cache_real_root)


def native_helper_paths() -> tuple[Path, ...]:
    return tuple(REPO_ROOT / path for path in NATIVE_HELPER_RELATIVE_PATHS)


def _codex_check_task(output_root: Path, area: str, *, cycle: int | None = None) -> Task:
    ps = _powershell()
    name = f"codex-{area}"
    if not ps:
        return _skip_task(output_root, name, "PowerShell is not available.", cycle=cycle)
    return _command_task(
        output_root,
        name,
        [ps, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", REPO_ROOT / "scripts" / "codex_check.ps1", "-Area", area],
        cycle=cycle,
    )


def _pytest_task(output_root: Path, name: str, tests: Sequence[str], *, cycle: int | None = None) -> Task:
    basetemp = safe_child_dir(output_root, "pytest-temp", name if cycle is None else f"{name}-{cycle:05d}")
    return _command_task(
        output_root,
        name,
        [sys.executable, "-m", "pytest", *tests, f"--basetemp={basetemp}"],
        cycle=cycle,
    )


def _model_audit_tasks(
    output_root: Path,
    model_root: Path,
    *,
    profile: str,
    cycle: int | None = None,
    max_files: int | None = None,
    max_zip_audits: int | None = None,
    audit_zip_contents: bool = False,
) -> list[Task]:
    if not model_root or not _resolve(model_root).exists():
        return [_skip_task(output_root, "external-model-audit", f"Model root not found: {model_root}", cycle=cycle)]
    audit_dir = _task_dir(output_root, "external-model-audit", cycle=cycle)
    check_dir = _task_dir(output_root, "external-model-audit-check", cycle=cycle)
    report_path = audit_dir / "external_model_material_audit.json"
    check_path = check_dir / "external_model_material_audit_check.json"
    files = max_files if max_files is not None else (50 if profile == "quick" else 10_000 if profile == "soak" else 50_000)
    audit_argv = [
        sys.executable,
        _python_tool("tools", "audit_external_model_catalogue.py"),
        "--root",
        str(model_root),
        "--out-json",
        str(report_path),
        "--max-files",
        str(files),
    ]
    if audit_zip_contents or profile in {"corpus", "soak"}:
        audit_argv.append("--audit-zip-contents")
    if max_zip_audits is not None:
        audit_argv.extend(["--max-zip-audits", str(max_zip_audits)])
    check_argv = [
        sys.executable,
        _python_tool("tools", "check_external_model_audit.py"),
        str(report_path),
        "--out-json",
        str(check_path),
    ]
    if profile == "quick":
        check_argv.append("--warn-only")
    return [
        Task(
            name="external-model-audit",
            kind="command",
            output_dir=audit_dir,
            argv=[str(part) for part in audit_argv],
            artifacts=[report_path],
        ),
        Task(
            name="external-model-audit-check",
            kind="command",
            output_dir=check_dir,
            argv=[str(part) for part in check_argv],
            artifacts=[check_path],
        ),
    ]


def _real_archive_tasks(output_root: Path, game_root: Path | None, *, cycle: int | None = None) -> list[Task]:
    scenarios = (
        "real-archive-rigging-smoke",
        "real-archive-animation-binding-smoke",
        "real-archive-sequence-binding-smoke",
        "real-archive-app-workflow-smoke",
    )
    if not game_root or not _resolve(game_root).exists():
        return [
            _skip_task(
                output_root,
                f"mesh-{scenario}",
                f"Game root not found: {game_root or '<not supplied>'}",
                cycle=cycle,
            )
            for scenario in scenarios
        ]
    tasks: list[Task] = []
    for scenario in scenarios:
        task_dir = _task_dir(output_root, f"mesh-{scenario}", cycle=cycle)
        tasks.append(
            Task(
                name=f"mesh-{scenario}",
                kind="command",
                output_dir=task_dir,
                argv=[
                    sys.executable,
                    _python_tool("tools", "mesh_editor_dev_harness.py"),
                    "--scenario",
                    scenario,
                    "--game-root",
                    str(game_root),
                    "--output",
                    str(task_dir),
                ],
                artifacts=[task_dir / "result.json", task_dir / "evidence_report.json"],
            )
        )
    return tasks


def build_profile_tasks(args: argparse.Namespace, output_root: Path, *, cycle: int | None = None) -> list[Task]:
    profile = str(args.profile)
    cache_runs = int(args.cache_runs or (3 if profile == "soak" else 2 if profile == "corpus" else DEFAULT_CACHE_RUNS))
    cache_real_root = Path(args.cache_real_root) if getattr(args, "cache_real_root", None) else None
    tasks: list[Task] = [
        _probe_task(output_root, "cache-probe", "cache-probe", cycle=cycle, cache_cycles=cache_runs, cache_real_root=cache_real_root),
        _probe_task(output_root, "worker-probe", "worker-probe", cycle=cycle),
    ]
    if bool(getattr(args, "cache_only", False)):
        return tasks[:1]

    if profile == "quick":
        mesh_dir = _task_dir(output_root, "mesh-service-smoke", cycle=cycle)
        texture_dir = _task_dir(output_root, "texture-preset-matrix", cycle=cycle)
        tasks.extend(
            [
                _command_task(
                    output_root,
                    "mesh-service-smoke",
                    [
                        sys.executable,
                        _python_tool("tools", "mesh_editor_dev_harness.py"),
                        "--scenario",
                        "service-smoke",
                        "--output",
                        str(mesh_dir),
                    ],
                    cycle=cycle,
                    artifacts=[mesh_dir / "result.json", mesh_dir / "evidence_report.json"],
                ),
                _command_task(
                    output_root,
                    "texture-preset-matrix",
                    [
                        sys.executable,
                        _python_tool("tools", "texture_editor_dev_harness.py"),
                        "--scenario",
                        "preset-matrix",
                        "--output",
                        str(texture_dir),
                    ],
                    cycle=cycle,
                    artifacts=[texture_dir / "result.json"],
                ),
                _codex_check_task(output_root, "smoke", cycle=cycle),
            ]
        )
        tasks.extend(
            _model_audit_tasks(
                output_root,
                Path(args.model_root),
                profile=profile,
                cycle=cycle,
                max_files=args.max_model_files,
                max_zip_audits=args.max_zip_audits,
                audit_zip_contents=bool(args.audit_zip_contents),
            )
        )
        return tasks

    mesh_dir = _task_dir(output_root, "mesh-full-suite-smoke", cycle=cycle)
    texture_dir = _task_dir(output_root, "texture-full-suite-smoke", cycle=cycle)
    tasks.extend(
        [
            _probe_task(output_root, "native-helper-preflight", "native-helper-preflight", cycle=cycle),
            _command_task(
                output_root,
                "mesh-full-suite-smoke",
                [
                    sys.executable,
                    _python_tool("tools", "mesh_editor_dev_harness.py"),
                    "--scenario",
                    "full-suite-smoke",
                    "--output",
                    str(mesh_dir),
                ],
                cycle=cycle,
                artifacts=[mesh_dir / "result.json", mesh_dir / "evidence_report.json"],
            ),
            _command_task(
                output_root,
                "texture-full-suite-smoke",
                [
                    sys.executable,
                    _python_tool("tools", "texture_editor_dev_harness.py"),
                    "--scenario",
                    "full-suite-smoke",
                    "--output",
                    str(texture_dir),
                ],
                cycle=cycle,
                artifacts=[texture_dir / "result.json"],
            ),
            _pytest_task(
                output_root,
                "mesh-replacement-pytest",
                (
                    "tests/test_static_replacement_preview_models.py",
                    "tests/test_static_replacement_accept_state.py",
                    "tests/test_static_replacement_build_footer.py",
                    "tests/test_full_import_model_replacement.py",
                ),
                cycle=cycle,
            ),
            _codex_check_task(output_root, "responsiveness", cycle=cycle),
            _codex_check_task(output_root, "archive", cycle=cycle),
            _codex_check_task(output_root, "mesh", cycle=cycle),
            _codex_check_task(output_root, "texture", cycle=cycle),
        ]
    )
    tasks.extend(
        _model_audit_tasks(
            output_root,
            Path(args.model_root),
            profile=profile,
            cycle=cycle,
            max_files=args.max_model_files,
            max_zip_audits=args.max_zip_audits,
            audit_zip_contents=bool(args.audit_zip_contents),
        )
    )
    tasks.extend(_real_archive_tasks(output_root, Path(args.game_root) if args.game_root else None, cycle=cycle))
    return tasks


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

    def entry(path: str, pamt_path: Path, paz_path: Path, payload: bytes) -> ArchiveEntry:
        return ArchiveEntry(path=path, pamt_path=pamt_path, paz_file=paz_path, offset=0, comp_size=len(payload), orig_size=len(payload), flags=0, paz_index=0)

    entries_by_pamt: dict[Path, list[ArchiveEntry]] = {
        pamt_a: [entry("character/model/a.pac", pamt_a, paz_a, b"a")],
        pamt_b: [entry("character/model/b.pac", pamt_b, paz_b, b"b")],
    }
    rows: list[dict[str, Any]] = []
    output_root = _resolve(output_dir)

    for cycle in range(1, max(1, int(cycles)) + 1):
        pre_deleted = invalidate_archive_browser_cache(archive_root, cache_root)
        initial_health = archive_scan_shard_cache_health(archive_root, cache_root)
        calls: list[str] = []

        def shard_scan(path: Path) -> list[ArchiveEntry]:
            calls.append(path.relative_to(archive_root).as_posix())
            return list(entries_by_pamt[path])

        cold_timings: dict[str, float] = {}
        cold_started = time.perf_counter()
        cold_entries, cold_source, _cold_dir = load_or_update_archive_scan_shards(
            archive_root,
            cache_root,
            shard_scan_func=shard_scan,
            timings=cold_timings,
        )
        cold_elapsed = time.perf_counter() - cold_started
        cold_scan_calls = list(calls)

        def no_scan(path: Path) -> list[ArchiveEntry]:
            raise AssertionError(f"warm cache should not rescan {path}")

        warm_timings: dict[str, float] = {}
        warm_started = time.perf_counter()
        warm_entries, warm_source, _warm_dir = load_or_update_archive_scan_shards(
            archive_root,
            cache_root,
            shard_scan_func=no_scan,
            timings=warm_timings,
        )
        warm_elapsed = time.perf_counter() - warm_started
        fresh_process = _fresh_process_cache_load(archive_root, cache_root)

        stale_calls: list[str] = []
        pamt_b.write_bytes(f"pamt:0001:cycle:{cycle}".encode("ascii"))
        entries_by_pamt[pamt_b] = [entry(f"character/model/b_changed_{cycle}.pac", pamt_b, paz_b, b"b")]

        def stale_scan(path: Path) -> list[ArchiveEntry]:
            stale_calls.append(path.relative_to(archive_root).as_posix())
            if path == pamt_a:
                raise AssertionError("unchanged shard should not rescan")
            return list(entries_by_pamt[path])

        stale_timings: dict[str, float] = {}
        stale_started = time.perf_counter()
        stale_entries, stale_source, _stale_dir = load_or_update_archive_scan_shards(
            archive_root,
            cache_root,
            shard_scan_func=stale_scan,
            timings=stale_timings,
        )
        stale_elapsed = time.perf_counter() - stale_started
        deleted = invalidate_archive_browser_cache(archive_root, cache_root)
        delete_within_output = all(_is_relative_to(_resolve(path), output_root) for path in deleted)
        rebuild_calls: list[str] = []

        def rebuild_scan(path: Path) -> list[ArchiveEntry]:
            rebuild_calls.append(path.relative_to(archive_root).as_posix())
            return list(entries_by_pamt[path])

        rebuild_timings: dict[str, float] = {}
        rebuild_started = time.perf_counter()
        rebuild_entries, rebuild_source, _rebuild_dir = load_or_update_archive_scan_shards(
            archive_root,
            cache_root,
            shard_scan_func=rebuild_scan,
            timings=rebuild_timings,
        )
        rebuild_elapsed = time.perf_counter() - rebuild_started
        shard_dir = resolve_archive_scan_shard_cache_dir(archive_root, cache_root)
        corrupt_target = next(iter(sorted(shard_dir.glob("*.bin"))), None) if shard_dir.is_dir() else None
        corrupt_calls: list[str] = []
        corrupt_timings: dict[str, float] = {}
        corrupt_entries: list[ArchiveEntry] = []
        corrupt_source = "missing_target"
        corrupt_elapsed = 0.0
        corrupt_health: Mapping[str, object] = {}
        if corrupt_target is not None:
            corrupt_target.write_bytes(b"corrupt shard")
            corrupt_health = archive_scan_shard_cache_health(archive_root, cache_root, deep=True)

            def corrupt_scan(path: Path) -> list[ArchiveEntry]:
                corrupt_calls.append(path.relative_to(archive_root).as_posix())
                return list(entries_by_pamt[path])

            corrupt_started = time.perf_counter()
            corrupt_entries, corrupt_source, _corrupt_dir = load_or_update_archive_scan_shards(
                archive_root,
                cache_root,
                shard_scan_func=corrupt_scan,
                timings=corrupt_timings,
            )
            corrupt_elapsed = time.perf_counter() - corrupt_started
        rows.append(
            {
                "cycle": cycle,
                "pre_delete": {"deleted_count": len(pre_deleted), "deleted_paths": [str(path) for path in pre_deleted]},
                "initial_health": initial_health,
                "cold": {"source": cold_source, "entries": len(cold_entries), "scan_calls": cold_scan_calls, "elapsed_s": cold_elapsed, "timings": cold_timings},
                "warm": {"source": warm_source, "entries": len(warm_entries), "elapsed_s": warm_elapsed, "timings": warm_timings},
                "fresh_process_warm": fresh_process,
                "stale": {"source": stale_source, "entries": len(stale_entries), "scan_calls": stale_calls, "elapsed_s": stale_elapsed, "timings": stale_timings},
                "delete": {"deleted_count": len(deleted), "deleted_paths": [str(path) for path in deleted], "within_output": delete_within_output},
                "rebuild": {"source": rebuild_source, "entries": len(rebuild_entries), "scan_calls": rebuild_calls, "elapsed_s": rebuild_elapsed, "timings": rebuild_timings},
                "corrupt_recovery": {
                    "source": corrupt_source,
                    "entries": len(corrupt_entries),
                    "scan_calls": corrupt_calls,
                    "elapsed_s": corrupt_elapsed,
                    "timings": corrupt_timings,
                    "target": str(corrupt_target) if corrupt_target else "",
                    "pre_recovery_health": corrupt_health,
                },
                "cache_size_bytes": _tree_size_bytes(cache_root),
                "final_health": archive_scan_shard_cache_health(archive_root, cache_root, deep=True),
            }
        )
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
        corrupt_target = next(iter(sorted(shard_dir.glob("*.bin"))), None) if shard_dir.is_dir() else None
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


def run_worker_probe(output_dir: Path) -> dict[str, Any]:
    started = time.perf_counter()
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    try:
        import threading

        from PySide6.QtCore import QCoreApplication, QEventLoop, QThread, QTimer

        from cdmw.workers.utility_workers import UtilityWorker
    except Exception as exc:
        result = {"status": "skipped", "ok": True, "reason": f"Qt worker probe unavailable: {exc}"}
        _write_json(output_dir / "worker_probe.json", result)
        return result

    app = QCoreApplication.instance() or QCoreApplication(["headless-feature-stress-worker-probe"])
    main_thread_id = threading.get_ident()
    payload: dict[str, Any] = {}
    errors: list[str] = []
    finished: list[bool] = []

    def task(_log: object) -> dict[str, Any]:
        worker_thread_id = threading.get_ident()
        return {
            "main_thread_id": main_thread_id,
            "worker_thread_id": worker_thread_id,
            "off_ui_thread": worker_thread_id != main_thread_id,
        }

    worker = UtilityWorker(task)
    thread = QThread()
    loop = QEventLoop()
    worker.moveToThread(thread)
    thread.started.connect(worker.run)
    worker.completed.connect(lambda result: payload.update(result if isinstance(result, dict) else {"result": result}))
    worker.error.connect(lambda message: errors.append(str(message)))
    worker.finished.connect(lambda: finished.append(True))
    worker.finished.connect(thread.quit)
    worker.finished.connect(loop.quit)
    QTimer.singleShot(5000, loop.quit)
    thread.start()
    loop.exec()
    if thread.isRunning():
        thread.quit()
    thread.wait(1000)
    app.processEvents()

    ok = bool(finished) and bool(payload.get("off_ui_thread")) and not errors
    result = {
        "status": "passed" if ok else "failed",
        "ok": ok,
        "elapsed_s": time.perf_counter() - started,
        "payload": payload,
        "errors": errors,
        "finished": bool(finished),
    }
    _write_json(output_dir / "worker_probe.json", result)
    return result


def run_native_helper_preflight(output_dir: Path, helpers: Sequence[Path] | None = None) -> dict[str, Any]:
    started = time.perf_counter()
    output_dir.mkdir(parents=True, exist_ok=True)
    required = tuple(Path(path) for path in (helpers if helpers is not None else native_helper_paths()))
    missing_before = [path for path in required if not path.is_file()]
    build_ran = False
    build_result: dict[str, Any] = {}
    stdout_path = output_dir / "build_native_stdout.log"
    stderr_path = output_dir / "build_native_stderr.log"
    if missing_before:
        ps = _powershell()
        script = REPO_ROOT / "build_native_windows.ps1"
        if not ps:
            result = {"status": "failed", "ok": False, "reason": "PowerShell is not available.", "missing_before": missing_before}
            _write_json(output_dir / "native_helper_preflight.json", result)
            return result
        if not script.is_file():
            result = {"status": "failed", "ok": False, "reason": f"Native build script not found: {script}", "missing_before": missing_before}
            _write_json(output_dir / "native_helper_preflight.json", result)
            return result
        completed = subprocess.run(
            [ps, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(script), "-Configuration", "Release"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            shell=False,
        )
        stdout_path.write_text(completed.stdout or "", encoding="utf-8")
        stderr_path.write_text(completed.stderr or "", encoding="utf-8")
        build_ran = True
        build_result = {"returncode": completed.returncode, "stdout_log": stdout_path, "stderr_log": stderr_path}
    missing_after = [path for path in required if not path.is_file()]
    ok = not missing_after and (not build_ran or build_result.get("returncode") == 0)
    result = {
        "status": "passed" if ok else "failed",
        "ok": ok,
        "elapsed_s": time.perf_counter() - started,
        "build_ran": build_ran,
        "required": required,
        "missing_before": missing_before,
        "missing_after": missing_after,
        "build": build_result,
    }
    _write_json(output_dir / "native_helper_preflight.json", result)
    return result


def run_task(task: Task) -> dict[str, Any]:
    started = time.perf_counter()
    task.output_dir.mkdir(parents=True, exist_ok=True)
    if task.skip_reason or task.kind == "skip":
        result = {
            "name": task.name,
            "kind": task.kind,
            "required": task.required,
            "status": "skipped",
            "skip_reason": task.skip_reason or "Skipped by profile.",
            "elapsed_s": 0.0,
            "output_dir": str(task.output_dir),
        }
        _write_json(task.output_dir / "summary.json", result)
        return result
    if task.kind == "cache-probe":
        probe = (
            run_real_cache_probe(task.output_dir, task.cache_real_root, cycles=task.cache_cycles)
            if task.cache_real_root is not None
            else run_cache_probe(task.output_dir, cycles=task.cache_cycles)
        )
        result = _task_result_from_probe(task, probe, started, task.output_dir / "cache_probe.json")
        _write_json(task.output_dir / "summary.json", result)
        return result
    if task.kind == "worker-probe":
        probe = run_worker_probe(task.output_dir)
        result = _task_result_from_probe(task, probe, started, task.output_dir / "worker_probe.json")
        _write_json(task.output_dir / "summary.json", result)
        return result
    if task.kind == "native-helper-preflight":
        probe = run_native_helper_preflight(task.output_dir)
        result = _task_result_from_probe(task, probe, started, task.output_dir / "native_helper_preflight.json")
        _write_json(task.output_dir / "summary.json", result)
        return result
    if task.kind != "command":
        result = {
            "name": task.name,
            "kind": task.kind,
            "required": task.required,
            "status": "failed",
            "error": f"Unknown task kind: {task.kind}",
            "elapsed_s": time.perf_counter() - started,
            "output_dir": str(task.output_dir),
        }
        _write_json(task.output_dir / "summary.json", result)
        return result

    stdout_path = task.output_dir / "stdout.log"
    stderr_path = task.output_dir / "stderr.log"
    env = os.environ.copy()
    env.update(task.env)
    env["PYTHONPATH"] = str(REPO_ROOT) + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
    try:
        completed = subprocess.run(
            task.argv,
            cwd=REPO_ROOT,
            env=env,
            capture_output=True,
            text=True,
            shell=False,
        )
        stdout_path.write_text(completed.stdout or "", encoding="utf-8")
        stderr_path.write_text(completed.stderr or "", encoding="utf-8")
        status = "passed" if completed.returncode == 0 else "failed"
        result: dict[str, Any] = {
            "name": task.name,
            "kind": task.kind,
            "required": task.required,
            "status": status,
            "returncode": completed.returncode,
            "argv": task.argv,
            "elapsed_s": time.perf_counter() - started,
            "output_dir": str(task.output_dir),
            "stdout_log": str(stdout_path),
            "stderr_log": str(stderr_path),
            "artifacts": [str(path) for path in task.artifacts if path.exists()],
        }
    except OSError as exc:
        result = {
            "name": task.name,
            "kind": task.kind,
            "required": task.required,
            "status": "failed",
            "argv": task.argv,
            "elapsed_s": time.perf_counter() - started,
            "output_dir": str(task.output_dir),
            "error": str(exc),
        }
    for artifact in task.artifacts:
        parsed = _read_json(artifact)
        if parsed is not None:
            result.setdefault("parsed_artifacts", {})[str(artifact)] = parsed
    _write_json(task.output_dir / "summary.json", result)
    return result


def _task_result_from_probe(task: Task, probe: Mapping[str, Any], started: float, artifact: Path) -> dict[str, Any]:
    status = str(probe.get("status") or ("passed" if probe.get("ok") else "failed"))
    result = {
        "name": task.name,
        "kind": task.kind,
        "required": task.required,
        "status": status,
        "elapsed_s": time.perf_counter() - started,
        "output_dir": str(task.output_dir),
        "artifacts": [str(artifact)] if artifact.exists() else [],
        "probe": dict(probe),
    }
    if status == "skipped":
        result["skip_reason"] = str(probe.get("reason") or "Skipped by probe.")
    return result


def merge_report(
    *,
    profile: str,
    argv: Sequence[str],
    output_root: Path,
    args: argparse.Namespace,
    task_results: Sequence[Mapping[str, Any]],
    started: float,
    cycles: int = 0,
) -> dict[str, Any]:
    counts = {"passed": 0, "failed": 0, "skipped": 0}
    for result in task_results:
        status = str(result.get("status") or "failed")
        counts[status] = counts.get(status, 0) + 1
    required_failures = [result for result in task_results if result.get("status") == "failed" and bool(result.get("required", True))]
    return {
        "ok": not required_failures,
        "profile": profile,
        "argv": list(argv),
        "output_root": str(output_root),
        "roots": {
            "game_root": str(args.game_root) if args.game_root else "",
            "model_root": str(args.model_root) if args.model_root else "",
        },
        "environment": {
            "python": sys.executable,
            "cwd": str(REPO_ROOT),
            "qt_qpa_platform": os.environ.get("QT_QPA_PLATFORM", ""),
        },
        "counts": counts,
        "required_failures": required_failures,
        "skip_reasons": [
            {"name": result.get("name"), "reason": result.get("skip_reason")}
            for result in task_results
            if result.get("status") == "skipped"
        ],
        "task_results": list(task_results),
        "timings": {
            "elapsed_s": time.perf_counter() - started,
            "task_elapsed_s": {str(result.get("name")): result.get("elapsed_s", 0.0) for result in task_results},
            "cycles": cycles,
        },
    }


def write_reports(output_root: Path, report: Mapping[str, Any]) -> None:
    _write_json(output_root / "result.json", report)
    timing_rows = [
        {"name": result.get("name"), "status": result.get("status"), "elapsed_s": result.get("elapsed_s", 0.0)}
        for result in report.get("task_results", [])
        if isinstance(result, Mapping)
    ]
    _write_json(output_root / "timings.json", {"profile": report.get("profile"), "rows": timing_rows, "summary": report.get("timings", {})})


def run_profile(args: argparse.Namespace, output_root: Path, argv: Sequence[str]) -> int:
    started = time.perf_counter()
    results = [run_task(task) for task in build_profile_tasks(args, output_root)]
    report = merge_report(profile=args.profile, argv=argv, output_root=output_root, args=args, task_results=results, started=started)
    write_reports(output_root, report)
    return 0 if report["ok"] else 1


def run_soak(args: argparse.Namespace, output_root: Path, argv: Sequence[str]) -> int:
    started = time.perf_counter()
    deadline = started + float(args.soak_minutes) * 60.0
    cycle = 0
    results: list[dict[str, Any]] = []
    while time.perf_counter() < deadline or cycle == 0:
        cycle += 1
        for task in build_profile_tasks(args, output_root, cycle=cycle):
            results.append(run_task(task))
            report = merge_report(profile=args.profile, argv=argv, output_root=output_root, args=args, task_results=results, started=started, cycles=cycle)
            write_reports(output_root, report)
    report = merge_report(profile=args.profile, argv=argv, output_root=output_root, args=args, task_results=results, started=started, cycles=cycle)
    write_reports(output_root, report)
    return 0 if report["ok"] else 1


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run headless feature stress checks without starting the full app.")
    parser.add_argument("--profile", choices=PROFILES, default="quick")
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--game-root", type=Path)
    parser.add_argument("--model-root", type=Path, default=DEFAULT_MODEL_ROOT)
    parser.add_argument("--soak-minutes", type=float, default=SOAK_MINUTES_DEFAULT)
    parser.add_argument("--max-model-files", type=int)
    parser.add_argument("--audit-zip-contents", action="store_true")
    parser.add_argument("--max-zip-audits", type=int)
    parser.add_argument("--cache-runs", type=int)
    parser.add_argument("--cache-only", action="store_true")
    parser.add_argument("--cache-real-root", type=Path)
    args = parser.parse_args(argv)
    if args.profile == "soak" and float(args.soak_minutes) < SOAK_MINUTES_MINIMUM:
        parser.error(f"--profile soak requires --soak-minutes >= {SOAK_MINUTES_MINIMUM:g}")
    if args.cache_runs is not None and args.cache_runs < 1:
        parser.error("--cache-runs must be >= 1")
    return args


def main(argv: Sequence[str] | None = None) -> int:
    raw_argv = list(argv if argv is not None else sys.argv[1:])
    args = parse_args(raw_argv)
    output_root = prepare_output_root(args.output)
    if args.profile == "soak":
        return run_soak(args, output_root, raw_argv)
    return run_profile(args, output_root, raw_argv)


if __name__ == "__main__":
    raise SystemExit(main())
