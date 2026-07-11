from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Mapping, Sequence

from tools.headless_stress.cache_probe import run_cache_probe, run_real_cache_probe
from tools.headless_stress.probes import run_native_helper_preflight, run_worker_probe
from tools.headless_stress.task_builders import REPO_ROOT, Task, _read_json, _write_json, build_profile_tasks


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
