from __future__ import annotations

import argparse
import json
import math
import os
import platform
import queue
import statistics
import subprocess
import sys
import tempfile
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence


REPO_ROOT = Path(__file__).resolve().parents[1]
SCHEMA_VERSION = 1
PUBLIC_IMPORT_BUDGET_MS = 500.0
FIRST_WINDOW_IMPROVEMENT_PERCENT = 30.0
FIRST_USE_REGRESSION_PERCENT = 10.0
FORBIDDEN_PUBLIC_MODULES = (
    "PIL",
    "cv2",
    "numpy",
    "cdmw.rendering.model_preview_prepare",
    "cdmw.rendering.native_preview_core",
    "cdmw.ui.mesh_editor.tab",
    "cdmw.ui.shell.app_window",
    "cdmw.ui.shell.run_gui",
)
FIRST_TAB_PARENTS = {
    "item_icons_tab": "assets_tabs",
    "mesh_editor_tab": "assets_tabs",
    "model_library_tab": "assets_tabs",
    "mod_package_retrofit_tab": "tools_tabs",
    "recolor_variants_tab": "texture_tabs",
    "replace_assistant_tab": "texture_tabs",
    "research_tab": "research_tabs",
    "text_search_tab": "research_tabs",
    "texture_editor_tab": "texture_tabs",
}


def percentile(values: Sequence[float], quantile: float) -> float:
    ordered = sorted(float(value) for value in values)
    if not ordered:
        raise ValueError("percentile requires at least one value")
    position = (len(ordered) - 1) * min(1.0, max(0.0, float(quantile)))
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    weight = position - lower
    return ordered[lower] + (ordered[upper] - ordered[lower]) * weight


def summarize_timings(values: Sequence[float]) -> dict[str, object]:
    samples = [round(float(value), 3) for value in values]
    return {
        "samples_ms": samples,
        "minimum_ms": round(min(samples), 3),
        "median_ms": round(statistics.median(samples), 3),
        "p95_ms": round(percentile(samples, 0.95), 3),
        "maximum_ms": round(max(samples), 3),
    }


def _append_repo_root() -> None:
    if str(REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(REPO_ROOT))


def _public_import_probe() -> dict[str, object]:
    start = time.perf_counter()
    __import__("cdmw.ui.main_window")
    elapsed_ms = (time.perf_counter() - start) * 1000.0
    forbidden = sorted(name for name in FORBIDDEN_PUBLIC_MODULES if name in sys.modules)
    return {
        "elapsed_ms": elapsed_ms,
        "module_count": len(sys.modules),
        "forbidden_modules": forbidden,
    }


def _window_probe(settings_path: Path, first_tab: str) -> dict[str, object]:
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    os.environ["CDMW_GUI_STARTUP_SMOKE"] = "1"
    os.environ["CDMW_MAIN_WINDOW_CLASS_ONLY"] = "1"
    os.environ["CDMW_SINGLE_INSTANCE_SCOPE"] = f"startup-benchmark-{os.getpid()}"

    start = time.perf_counter()
    from cdmw.services import settings_service

    settings_imported = time.perf_counter()
    settings_service.resolve_settings_file_path = lambda **_kwargs: settings_path
    from PySide6.QtWidgets import QApplication
    import cdmw.ui.shell.app_window as app_window

    shell_imported = time.perf_counter()
    app_window.resolve_settings_file_path = lambda: settings_path
    MainWindow = app_window.run_gui()
    window_class_resolved = time.perf_counter()
    from cdmw.app.events import AppEventBus
    from cdmw.services.service_container import ServiceContainer
    from cdmw.ui.shell.app_context import AppContext

    app = QApplication.instance() or QApplication([])
    settings = settings_service.create_settings(settings_file_path=settings_path)
    context = AppContext(settings, ServiceContainer.create_default(settings=settings), AppEventBus())
    context_created = time.perf_counter()
    window = MainWindow(app_context=context)
    window_constructed = time.perf_counter()
    window.show()
    app.processEvents()
    first_window_shown = time.perf_counter()
    first_window_ms = (first_window_shown - start) * 1000.0

    container = getattr(window, first_tab)
    parent_tabs = getattr(window, FIRST_TAB_PARENTS[first_tab])
    tab_start = time.perf_counter()
    parent_tabs.setCurrentWidget(container)
    app.processEvents()
    first_tab_created = time.perf_counter()
    first_tab_ms = (first_tab_created - tab_start) * 1000.0
    created = container.widget_if_created() is not None

    payload = {
        "first_window_ms": first_window_ms,
        "first_tab_ms": first_tab_ms,
        "first_tab": first_tab,
        "first_tab_created": created,
        "module_count": len(sys.modules),
        "stages_ms": {
            "settings_service_import": (settings_imported - start) * 1000.0,
            "shell_module_import": (shell_imported - settings_imported) * 1000.0,
            "main_window_class_resolution": (window_class_resolved - shell_imported) * 1000.0,
            "application_context_creation": (context_created - window_class_resolved) * 1000.0,
            "window_construction": (window_constructed - context_created) * 1000.0,
            "first_show_event": (first_window_shown - window_constructed) * 1000.0,
            "first_tab_creation": (first_tab_created - tab_start) * 1000.0,
        },
    }
    window.hide()
    window._finalize_close()
    return payload


def _helper_mesh() -> object:
    from cdmw.modding.mesh_parser import ParsedMesh, SubMesh

    submesh = SubMesh(
        name="startup_benchmark_triangle",
        material="startup_benchmark_material",
        vertices=[(-0.5, -0.5, 0.0), (0.5, -0.5, 0.0), (0.0, 0.5, 0.0)],
        uvs=[(0.0, 0.0), (1.0, 0.0), (0.5, 1.0)],
        normals=[(0.0, 0.0, 1.0)] * 3,
        faces=[(0, 1, 2)],
        vertex_count=3,
        face_count=1,
    )
    return ParsedMesh(
        path="startup_benchmark.pac",
        format="pac",
        bbox_min=(-0.5, -0.5, 0.0),
        bbox_max=(0.5, 0.5, 0.0),
        submeshes=[submesh],
        total_vertices=3,
        total_faces=1,
        has_uvs=True,
    )


def _helper_protocol_probe(executable: Path, timeout_seconds: float) -> dict[str, object]:
    if os.name != "nt":
        return {"status": "skipped", "reason": "Windows helper probe"}
    if not executable.is_file():
        return {"status": "skipped", "reason": f"helper missing: {executable}"}

    # A real hidden Win32 parent is required for the helper's SetParent proof.
    os.environ["QT_QPA_PLATFORM"] = "windows"
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication, QWidget
    from cdmw.core.common import finish_process_tree
    from cdmw.services.mesh_dotnet_experiment import (
        build_mesh_dotnet_experiment_package,
        mesh_dotnet_experiment_command,
    )

    app = QApplication.instance() or QApplication([])
    parent = QWidget()
    parent.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
    parent.resize(32, 32)
    parent.createWinId()
    parent_hwnd = int(parent.winId())

    with tempfile.TemporaryDirectory(prefix="cdmw-helper-startup-benchmark-") as temp_dir:
        package = build_mesh_dotnet_experiment_package(_helper_mesh(), output_root=Path(temp_dir))
        program, arguments = mesh_dotnet_experiment_command(
            executable,
            package,
            embedded_parent_hwnd=parent_hwnd,
        )
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startupinfo.wShowWindow = 0
        started = time.perf_counter()
        process = subprocess.Popen(
            [program, *arguments],
            cwd=package.package_dir,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
            startupinfo=startupinfo,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        lines: queue.Queue[str] = queue.Queue()

        def _read_stdout() -> None:
            if process.stdout is None:
                return
            for line in process.stdout:
                lines.put(line)

        reader = threading.Thread(target=_read_stdout, name="CDMWStartupBenchmarkProtocol", daemon=True)
        reader.start()
        deadline = time.monotonic() + max(1.0, float(timeout_seconds))
        protocol_ready_ms: float | None = None
        seen_events: list[str] = []
        seen_payloads: list[dict[str, object]] = []
        try:
            while time.monotonic() < deadline:
                app.processEvents()
                try:
                    line = lines.get(timeout=0.05)
                except queue.Empty:
                    if process.poll() is not None:
                        break
                    continue
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if not isinstance(event, Mapping):
                    continue
                seen_payloads.append(dict(event))
                event_name = str(event.get("event") or event.get("type") or "")
                if event_name:
                    seen_events.append(event_name)
                if event_name == "protocol_ready":
                    protocol_ready_ms = (time.perf_counter() - started) * 1000.0
                    break
        finally:
            if process.stdin is not None and process.poll() is None:
                try:
                    process.stdin.write('{"event":"close_request"}\n')
                    process.stdin.flush()
                except OSError:
                    pass
            shutdown_errors: list[BaseException] = []

            def _finish_helper_tree() -> None:
                try:
                    finish_process_tree(process, grace_seconds=5.0, request_stop=False)
                except BaseException as exc:  # pragma: no cover - defensive teardown reporting
                    shutdown_errors.append(exc)

            finisher = threading.Thread(
                target=_finish_helper_tree,
                name="CDMWStartupBenchmarkShutdown",
                daemon=True,
            )
            finisher.start()
            while finisher.is_alive():
                app.processEvents()
                finisher.join(timeout=0.01)
            parent.close()
            if shutdown_errors:
                raise RuntimeError("Helper process-tree shutdown failed.") from shutdown_errors[0]

        if protocol_ready_ms is None:
            stderr = process.stderr.read()[-2000:] if process.stderr is not None else ""
            raise RuntimeError(
                f"Helper exited {process.returncode} before protocol_ready; "
                f"events={seen_payloads!r}; stderr={stderr!r}"
            )
        return {
            "status": "ok",
            "elapsed_ms": protocol_ready_ms,
            "events_before_ready": seen_events,
            "executable": str(executable.resolve()),
        }


def _child_probe(args: argparse.Namespace) -> int:
    _append_repo_root()
    if args.child_probe == "public":
        payload = _public_import_probe()
    elif args.child_probe == "window":
        if args.settings_path is None:
            raise ValueError("window probe requires --settings-path")
        payload = _window_probe(args.settings_path, args.first_tab)
    else:
        if args.helper_executable is None:
            raise ValueError("helper probe requires --helper-executable")
        payload = _helper_protocol_probe(args.helper_executable, args.helper_timeout)
    print(json.dumps(payload, sort_keys=True), flush=True)
    return 0


def _run_child(arguments: Sequence[str], *, timeout_seconds: float) -> dict[str, object]:
    completed = subprocess.run(
        [sys.executable, str(Path(__file__).resolve()), *arguments],
        cwd=REPO_ROOT,
        env={**os.environ, "QT_QPA_PLATFORM": "offscreen"},
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=max(1.0, float(timeout_seconds)),
    )
    if completed.returncode != 0:
        raise RuntimeError(
            f"Startup benchmark child failed ({' '.join(arguments)}).\n"
            f"STDOUT:\n{completed.stdout}\nSTDERR:\n{completed.stderr}"
        )
    for line in reversed(completed.stdout.splitlines()):
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            return payload
    raise RuntimeError(f"Startup benchmark child returned no JSON.\nSTDOUT:\n{completed.stdout}")


def _git_value(*arguments: str) -> str:
    try:
        completed = subprocess.run(
            ["git", *arguments],
            cwd=REPO_ROOT,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    return completed.stdout.strip() if completed.returncode == 0 else ""


def _probe_summary(rows: Sequence[Mapping[str, object]], field: str) -> dict[str, object]:
    result = summarize_timings([float(row[field]) for row in rows])
    result["status"] = "ok"
    return result


def _stage_probe_summaries(rows: Sequence[Mapping[str, object]]) -> dict[str, dict[str, object]]:
    if not rows:
        return {}
    stages_by_row = [row.get("stages_ms") for row in rows]
    if not all(isinstance(stages, Mapping) for stages in stages_by_row):
        raise ValueError("Every window probe row must contain stages_ms")
    stage_names = tuple(sorted(str(name) for name in stages_by_row[0]))  # type: ignore[union-attr]
    if any(tuple(sorted(str(name) for name in stages)) != stage_names for stages in stages_by_row):  # type: ignore[union-attr]
        raise ValueError("Window probe stage sets differ between runs")
    summaries: dict[str, dict[str, object]] = {}
    for name in stage_names:
        summary = summarize_timings([float(stages[name]) for stages in stages_by_row])  # type: ignore[index]
        summary["status"] = "ok"
        summaries[name] = summary
    return summaries


def _comparison(
    artifact: Mapping[str, object],
    baseline: Mapping[str, object] | None,
) -> tuple[dict[str, object], dict[str, object]]:
    gates: dict[str, object] = {
        "public_facade_import_under_500_ms": bool(
            artifact["probes"]["public_facade_import"]["p95_ms"] < PUBLIC_IMPORT_BUDGET_MS  # type: ignore[index]
        ),
        "public_facade_import_has_no_heavy_modules": not bool(
            artifact["probes"]["public_facade_import"]["forbidden_modules_seen"]  # type: ignore[index]
        ),
        "first_window_improved_at_least_30_percent": None,
        "first_tab_regression_within_10_percent": None,
        "helper_protocol_ready_regression_within_10_percent": None,
    }
    comparison: dict[str, object] = {}
    if baseline is None:
        return comparison, gates

    current_probes = artifact["probes"]  # type: ignore[assignment]
    baseline_probes = baseline.get("probes", {})
    baseline_window = float(baseline_probes["first_window"]["p95_ms"])  # type: ignore[index]
    current_window = float(current_probes["first_window"]["p95_ms"])  # type: ignore[index]
    window_improvement = 100.0 * (baseline_window - current_window) / max(baseline_window, 0.001)
    baseline_tab = float(baseline_probes["first_tab"]["p95_ms"])  # type: ignore[index]
    current_tab = float(current_probes["first_tab"]["p95_ms"])  # type: ignore[index]
    tab_regression = 100.0 * (current_tab - baseline_tab) / max(baseline_tab, 0.001)
    comparison.update(
        {
            "baseline_generated_at_utc": str(baseline.get("generated_at_utc", "")),
            "first_window_improvement_percent": round(window_improvement, 3),
            "first_tab_regression_percent": round(tab_regression, 3),
        }
    )
    gates["first_window_improved_at_least_30_percent"] = (
        window_improvement >= FIRST_WINDOW_IMPROVEMENT_PERCENT
    )
    gates["first_tab_regression_within_10_percent"] = tab_regression <= FIRST_USE_REGRESSION_PERCENT

    current_helper = current_probes.get("helper_protocol_ready", {})  # type: ignore[union-attr]
    baseline_helper = baseline_probes.get("helper_protocol_ready", {})  # type: ignore[union-attr]
    if current_helper.get("status") == baseline_helper.get("status") == "ok":
        helper_baseline = float(baseline_helper["p95_ms"])
        helper_current = float(current_helper["p95_ms"])
        helper_regression = 100.0 * (helper_current - helper_baseline) / max(helper_baseline, 0.001)
        comparison["helper_protocol_ready_regression_percent"] = round(helper_regression, 3)
        gates["helper_protocol_ready_regression_within_10_percent"] = (
            helper_regression <= FIRST_USE_REGRESSION_PERCENT
        )
    return comparison, gates


def build_artifact(args: argparse.Namespace) -> dict[str, object]:
    public_rows: list[dict[str, object]] = []
    window_rows: list[dict[str, object]] = []
    helper_rows: list[dict[str, object]] = []
    with tempfile.TemporaryDirectory(prefix="cdmw-app-startup-benchmark-") as temp_dir:
        temp_root = Path(temp_dir)
        for index in range(args.runs):
            public_rows.append(
                _run_child(["--child-probe", "public"], timeout_seconds=args.probe_timeout)
            )
            window_rows.append(
                _run_child(
                    [
                        "--child-probe",
                        "window",
                        "--settings-path",
                        str(temp_root / f"settings-{index}.ini"),
                        "--first-tab",
                        args.first_tab,
                    ],
                    timeout_seconds=args.probe_timeout,
                )
            )
            if args.include_helper:
                helper_rows.append(
                    _run_child(
                        [
                            "--child-probe",
                            "helper",
                            "--helper-executable",
                            str(args.helper_executable),
                            "--helper-timeout",
                            str(args.helper_timeout),
                        ],
                        timeout_seconds=args.probe_timeout,
                    )
                )

    public_probe = _probe_summary(public_rows, "elapsed_ms")
    public_probe["module_count_min"] = min(int(row["module_count"]) for row in public_rows)
    public_probe["module_count_max"] = max(int(row["module_count"]) for row in public_rows)
    public_probe["forbidden_modules_seen"] = sorted(
        {
            str(name)
            for row in public_rows
            for name in row.get("forbidden_modules", [])  # type: ignore[union-attr]
        }
    )
    first_window_probe = _probe_summary(window_rows, "first_window_ms")
    first_tab_probe = _probe_summary(window_rows, "first_tab_ms")
    stage_probes = _stage_probe_summaries(window_rows)
    first_window_probe["stages"] = {
        name: summary for name, summary in stage_probes.items() if name != "first_tab_creation"
    }
    first_tab_probe["stages"] = {"first_tab_creation": stage_probes["first_tab_creation"]}
    first_tab_probe["target"] = args.first_tab
    first_tab_probe["created_every_run"] = all(bool(row.get("first_tab_created")) for row in window_rows)

    helper_probe: dict[str, object]
    if helper_rows and all(row.get("status") == "ok" for row in helper_rows):
        helper_probe = _probe_summary(helper_rows, "elapsed_ms")
        helper_probe["executable"] = str(helper_rows[-1].get("executable", ""))
    elif args.include_helper:
        helper_probe = dict(helper_rows[-1]) if helper_rows else {"status": "skipped", "reason": "no runs"}
    else:
        helper_probe = {"status": "skipped", "reason": "pass --include-helper to measure"}

    artifact: dict[str, object] = {
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "environment": {
            "python": sys.version,
            "platform": platform.platform(),
            "machine": platform.machine(),
            "processor": platform.processor(),
            "git_head": _git_value("rev-parse", "HEAD"),
            "git_dirty": bool(_git_value("status", "--porcelain")),
        },
        "configuration": {
            "runs": args.runs,
            "first_tab": args.first_tab,
            "public_import_budget_ms": PUBLIC_IMPORT_BUDGET_MS,
            "required_first_window_improvement_percent": FIRST_WINDOW_IMPROVEMENT_PERCENT,
            "allowed_first_use_regression_percent": FIRST_USE_REGRESSION_PERCENT,
        },
        "probes": {
            "public_facade_import": public_probe,
            "first_window": first_window_probe,
            "first_tab": first_tab_probe,
            "helper_protocol_ready": helper_probe,
        },
    }
    baseline = json.loads(args.baseline.read_text(encoding="utf-8")) if args.baseline else None
    comparison, gates = _comparison(artifact, baseline)
    artifact["comparison"] = comparison
    artifact["gates"] = gates
    artifact["ok"] = all(value is not False for value in gates.values())
    return artifact


def write_artifact(path: Path, artifact: Mapping[str, object]) -> None:
    path = path.expanduser().resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temp_name = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    temp_path = Path(temp_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
            json.dump(artifact, stream, indent=2, sort_keys=True)
            stream.write("\n")
        temp_path.replace(path)
    finally:
        temp_path.unlink(missing_ok=True)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Measure cold CDMW import/window/tab/helper startup.")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--runs", type=int, default=7)
    parser.add_argument("--baseline", type=Path)
    parser.add_argument("--first-tab", choices=tuple(FIRST_TAB_PARENTS), default="mesh_editor_tab")
    parser.add_argument("--probe-timeout", type=float, default=90.0)
    parser.add_argument("--include-helper", action="store_true")
    parser.add_argument(
        "--helper-executable",
        type=Path,
        default=REPO_ROOT / "native" / "cdmw_mesh_dotnet_editor" / "build" / "Release" / "cdmw-mesh-dotnet-editor.exe",
    )
    parser.add_argument("--helper-timeout", type=float, default=30.0)
    parser.add_argument("--child-probe", choices=("public", "window", "helper"), help=argparse.SUPPRESS)
    parser.add_argument("--settings-path", type=Path, help=argparse.SUPPRESS)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.child_probe:
        return _child_probe(args)
    if args.output is None:
        raise SystemExit("--output is required")
    if args.runs < 1:
        raise SystemExit("--runs must be at least 1")
    artifact = build_artifact(args)
    write_artifact(args.output, artifact)
    print(json.dumps(artifact, indent=2, sort_keys=True))
    return 0 if artifact["ok"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
