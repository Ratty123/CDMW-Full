from __future__ import annotations

import hashlib
import json
import os
import subprocess
import time
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Callable


def run_archive_browser_capture_batch(
    runtime_assets: Sequence[Mapping[str, object]],
    output_root: Path,
    *,
    run_id: str,
    timeout_seconds: float = 45.0,
    progress: Callable[[int, int, str], None] | None = None,
) -> dict[str, object]:
    os.environ["QT_QPA_PLATFORM"] = "windows"
    from PySide6.QtCore import QProcess
    from PySide6.QtWidgets import QApplication
    from cdmw.ui.mesh_editor.native_preview_runtime import mesh_editor_native_preview_command
    from cdmw.ui.native_d3d11_preview_host import NativeD3D11PreviewHostFrame

    if not runtime_assets:
        raise ValueError("Archive Browser capture batch has no assets.")
    output_root = Path(output_root).resolve()
    output_root.mkdir(parents=True, exist_ok=True)
    app = QApplication.instance() or QApplication(["cdmw-mesh-visual-audit-native"])
    host = NativeD3D11PreviewHostFrame()
    screen = app.primaryScreen().availableGeometry()
    host.setGeometry(screen.x() + 32, screen.y() + 32, 800, 800)
    host.show()
    host.raise_()
    host.activateWindow()
    app.processEvents()
    events: list[dict[str, object]] = []
    host.native_event_received.connect(lambda payload: _append_bounded(events, payload))
    process = QProcess(host)
    process.setProcessChannelMode(QProcess.ProcessChannelMode.MergedChannels)
    host.track_renderer_process(process)
    first = runtime_assets[0]
    first_status = output_root / f"{first['id']}-status.json"
    first_status.unlink(missing_ok=True)
    executable, arguments = mesh_editor_native_preview_command(
        Path(str(first["archive_package_dir"])),
        first_status,
        host_widget=host,
        diagnostic_log=output_root / "native-diagnostic.jsonl",
    )
    startup_started = time.perf_counter()
    process.start(executable, arguments)
    rows: list[dict[str, object]] = []
    stdout_tail = bytearray()
    process_pid = 0
    restart_count = 0
    try:
        if not _wait_until(
            app,
            lambda: process.state() == QProcess.ProcessState.Running and host._host_hwnd() > 0,
            timeout_seconds,
            process=process,
            output_tail=stdout_tail,
        ):
            raise RuntimeError("Archive Browser renderer did not publish its resident window.")
        process_pid = int(process.processId())
        startup_ms = (time.perf_counter() - startup_started) * 1000.0
        for index, asset in enumerate(runtime_assets, 1):
            if progress is not None:
                progress(index, len(runtime_assets), str(asset["virtual_path"]))
            asset_started = time.perf_counter()
            asset_id = str(asset["id"])
            status_path = output_root / f"{asset_id}-status.json"
            load_started = time.perf_counter()
            if index > 1:
                status_path.unlink(missing_ok=True)
                if not host.load_package(
                    Path(str(asset["archive_package_dir"])),
                    status_path,
                    reset_view=True,
                ):
                    rows.append(_native_failure_row(asset, "Resident load_package command was rejected."))
                    continue
            loaded_status: dict[str, object] = {}

            def loaded() -> bool:
                nonlocal loaded_status
                loaded_status = _read_json(status_path)
                return str(loaded_status.get("event", "")).casefold() in {"resources_loaded", "loaded", "error"}

            if not _wait_until(
                app,
                loaded,
                timeout_seconds,
                process=process,
                output_tail=stdout_tail,
            ):
                rows.append(_native_failure_row(asset, "Archive Browser package readiness timed out."))
                continue
            if str(loaded_status.get("event", "")).casefold() == "error":
                rows.append(
                    _native_failure_row(
                        asset,
                        str(loaded_status.get("message", "") or "Archive Browser renderer load failed."),
                        status=loaded_status,
                    )
                )
                continue
            load_ms = (time.perf_counter() - load_started) * 1000.0
            captures: list[dict[str, object]] = []
            asset_error = ""
            for view in tuple(asset.get("views", ()) or ()):
                if not isinstance(view, Mapping):
                    continue
                view_name = str(view.get("name", "") or "view")
                yaw = float(view.get("yaw", 0.0) or 0.0)
                pitch = float(view.get("pitch", 0.0) or 0.0)
                cursor = len(events)
                camera_started = time.perf_counter()
                if not host.set_view(yaw=yaw, pitch=pitch, fit_to_view=True, pan=(0.0, 0.0, 0.0)):
                    asset_error = f"Camera command was rejected for {view_name}."
                    break
                camera_event: dict[str, object] = {}

                def camera_acknowledged() -> bool:
                    nonlocal camera_event
                    for event in events[cursor:]:
                        if str(event.get("event", "")).casefold() != "view_state":
                            continue
                        try:
                            if abs(float(event.get("yaw", 9999.0)) - yaw) <= 0.05 and abs(
                                float(event.get("pitch", 9999.0)) - pitch
                            ) <= 0.05:
                                camera_event = dict(event)
                                return True
                        except (TypeError, ValueError):
                            continue
                    return False

                if not _wait_until(
                    app,
                    camera_acknowledged,
                    min(8.0, timeout_seconds),
                    process=process,
                    output_tail=stdout_tail,
                ):
                    asset_error = f"Camera acknowledgement timed out for {view_name}."
                    break
                camera_ms = (time.perf_counter() - camera_started) * 1000.0
                capture_path = output_root / asset_id / f"{view_name}.png"
                capture_path.unlink(missing_ok=True)
                capture_cursor = len(events)
                capture_started = time.perf_counter()
                if not host.request_frame_capture(capture_path):
                    asset_error = f"Frame capture command was rejected for {view_name}."
                    break
                capture_event: dict[str, object] = {}

                def capture_completed() -> bool:
                    nonlocal capture_event
                    for event in events[capture_cursor:]:
                        if str(event.get("event", "")).casefold() != "frame_capture":
                            continue
                        if event.get("ok") is False:
                            capture_event = dict(event)
                            return True
                        event_path = str(event.get("path", "") or "")
                        if not event_path or Path(event_path).resolve() != capture_path.resolve():
                            continue
                        capture_event = dict(event)
                        return True
                    return False

                if not _wait_until(
                    app,
                    capture_completed,
                    min(12.0, timeout_seconds),
                    process=process,
                    output_tail=stdout_tail,
                ) or capture_event.get("ok") is not True or not capture_path.is_file():
                    asset_error = str(
                        capture_event.get("message", "")
                        or f"Direct renderer capture timed out or failed for {view_name}."
                    )
                    break
                captures.append(
                    {
                        "name": view_name,
                        "yaw": yaw,
                        "pitch": pitch,
                        "ok": capture_event.get("ok", True) is not False,
                        "path": str(capture_path),
                        "bytes": capture_path.stat().st_size,
                        "sha256": _sha256_file(capture_path),
                        "camera_ms": camera_ms,
                        "capture_ms": (time.perf_counter() - capture_started) * 1000.0,
                        "camera_ack": camera_event,
                        "capture_event": capture_event,
                    }
                )
            rows.append(
                {
                    "id": asset_id,
                    "virtual_path": str(asset["virtual_path"]),
                    "ok": (
                        not asset_error
                        and len(captures) == len(tuple(asset.get("views", ()) or ()))
                        and all(row.get("ok") is True for row in captures)
                    ),
                    "backend": str(loaded_status.get("backend", "") or ""),
                    "process_id": process_pid,
                    "load_ms": load_ms,
                    "total_ms": (time.perf_counter() - asset_started) * 1000.0,
                    "status": loaded_status,
                    "captures": captures,
                    "error": asset_error,
                }
            )
        return {
            "schema": "cdmw_mesh_visual_audit_archive_browser_batch_v1",
            "run_id": run_id,
            "ok": len(rows) == len(runtime_assets) and all(bool(row.get("ok")) for row in rows),
            "backend": "native_archive_browser_d3d11",
            "process_id": process_pid,
            "process_start_count": 1,
            "process_restart_count": restart_count,
            "startup_ms": startup_ms,
            "assets": rows,
            "event_tail": events[-128:],
            "stdout_tail": bytes(stdout_tail[-65536:]).decode("utf-8", errors="replace"),
        }
    finally:
        if process.state() != QProcess.ProcessState.NotRunning:
            process.terminate()
            if not _wait_until(app, lambda: process.state() == QProcess.ProcessState.NotRunning, 2.0):
                process.kill()
                _wait_until(app, lambda: process.state() == QProcess.ProcessState.NotRunning, 2.0)
        host.release_native_preview_package_cache_leases()
        host.close()
        host.deleteLater()
        app.processEvents()


def run_dotnet_capture_batch(
    runtime_assets: Sequence[Mapping[str, object]],
    output_root: Path,
    runtime_root: Path,
    *,
    run_id: str,
    assembly_path: Path,
    timeout_seconds: float = 900.0,
) -> dict[str, object]:
    output_root = Path(output_root).resolve()
    runtime_root = Path(runtime_root).resolve()
    output_root.mkdir(parents=True, exist_ok=True)
    runtime_root.mkdir(parents=True, exist_ok=True)
    manifest_path = runtime_root / "dotnet-batch-manifest.json"
    report_path = runtime_root / "dotnet-batch-report.json"
    report_path.unlink(missing_ok=True)
    manifest = {
        "schema": "cdmw_mesh_visual_audit_dotnet_batch_v1",
        "run_id": run_id,
        "output_root": str(output_root),
        "width": 768,
        "height": 768,
        "assets": [
            {
                "id": str(asset["id"]),
                "package_dir": str(asset["dotnet_package_dir"]),
                "views": [dict(view) for view in tuple(asset.get("views", ()) or ())],
            }
            for asset in runtime_assets
        ],
    }
    _atomic_write_json(manifest_path, manifest)
    command = [
        "dotnet",
        str(Path(assembly_path).resolve()),
        "--visual-audit-batch",
        str(manifest_path),
        "--visual-audit-report",
        str(report_path),
    ]
    started = time.perf_counter()
    try:
        completed = subprocess.run(
            command,
            cwd=Path(__file__).resolve().parents[2],
            capture_output=True,
            text=True,
            timeout=max(30.0, float(timeout_seconds)),
            check=False,
        )
        report = _read_json(report_path)
        expected_ids = [str(asset["id"]) for asset in runtime_assets]
        actual_ids = [
            str(row.get("id", ""))
            for row in tuple(report.get("assets", ()) or ())
            if isinstance(row, Mapping)
        ]
        current_ok = (
            completed.returncode == 0
            and report.get("ok") is True
            and str(report.get("run_id", "")) == run_id
            and actual_ids == expected_ids
        )
        return {
            **report,
            "ok": current_ok,
            "command": command,
            "exit_code": int(completed.returncode),
            "wall_ms": (time.perf_counter() - started) * 1000.0,
            "stdout_tail": completed.stdout[-65536:],
            "stderr_tail": completed.stderr[-65536:],
        }
    except subprocess.TimeoutExpired as exc:
        return {
            "schema": "cdmw_mesh_visual_audit_dotnet_batch_v1",
            "run_id": run_id,
            "ok": False,
            "command": command,
            "timeout_seconds": float(timeout_seconds),
            "wall_ms": (time.perf_counter() - started) * 1000.0,
            "stdout_tail": (exc.stdout or "")[-65536:] if isinstance(exc.stdout, str) else "",
            "stderr_tail": (exc.stderr or "")[-65536:] if isinstance(exc.stderr, str) else "",
            "fatal_error": "The resident .NET visual-audit batch timed out.",
        }


def _native_failure_row(
    asset: Mapping[str, object],
    error: str,
    *,
    status: Mapping[str, object] | None = None,
) -> dict[str, object]:
    return {
        "id": str(asset["id"]),
        "virtual_path": str(asset["virtual_path"]),
        "ok": False,
        "status": dict(status or {}),
        "captures": [],
        "error": str(error),
    }


def _wait_until(
    app: object,
    predicate: Callable[[], bool],
    timeout_seconds: float,
    *,
    process: object | None = None,
    output_tail: bytearray | None = None,
) -> bool:
    deadline = time.monotonic() + max(0.01, float(timeout_seconds))
    while time.monotonic() < deadline:
        getattr(app, "processEvents")()
        if process is not None and output_tail is not None:
            data = bytes(getattr(process, "readAllStandardOutput")())
            if data:
                output_tail.extend(data)
                del output_tail[:-65536]
        if predicate():
            return True
        time.sleep(0.01)
    getattr(app, "processEvents")()
    return bool(predicate())


def _append_bounded(events: list[dict[str, object]], payload: object) -> None:
    if isinstance(payload, Mapping):
        events.append(dict(payload))
        del events[:-2048]


def _read_json(path: Path) -> dict[str, object]:
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return dict(payload) if isinstance(payload, Mapping) else {}


def _atomic_write_json(path: Path, payload: object) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


__all__ = ["run_archive_browser_capture_batch", "run_dotnet_capture_batch"]
