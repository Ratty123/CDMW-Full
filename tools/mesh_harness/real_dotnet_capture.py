from __future__ import annotations

import ctypes
import hashlib
import time
from pathlib import Path
from types import SimpleNamespace

from tools.mesh_harness.native_protocol import (
    _activate_window_for_input,
    _foreground_window_matches,
    _host_window_rect,
    _window_at_screen_point,
    _window_is_same_or_child,
    _window_process_id,
)
from tools.mesh_harness.png_evidence import _png_capture_summary


def capture_dotnet_viewport(state: SimpleNamespace, path: Path) -> dict[str, object]:
    from PIL import ImageGrab

    rect = _host_window_rect(int(state.viewport_hwnd))
    if rect is None:
        return {"ok": False, "error": "The .NET viewport HWND has no current screen rectangle."}
    x, y, right, bottom = rect
    width, height = int(right - x), int(bottom - y)
    if width < 32 or height < 32:
        return {"ok": False, "error": "Invalid .NET viewport capture geometry."}
    state.tab.raise_()
    state.tab.activateWindow()
    try:
        ctypes.windll.user32.SetForegroundWindow(ctypes.c_void_p(int(state.tab.winId())))
    except Exception:
        pass
    activated = _activate_window_for_input(
        int(state.viewport_hwnd),
        root_hwnd=int(state.form_hwnd),
    )
    state.app.processEvents()
    time.sleep(0.08)
    visible_hwnd = _window_at_screen_point(x + width // 2, y + height // 2)
    visible_pid = _window_process_id(visible_hwnd)
    expected_pid = int(state.production_process_pid)
    if (
        not activated
        or not _foreground_window_matches(int(state.form_hwnd))
        or visible_pid != expected_pid
        or not _window_is_same_or_child(int(state.viewport_hwnd), visible_hwnd)
    ):
        return {
            "ok": False,
            "error": "The .NET viewport was not the foreground visible capture target.",
            "foreground_activated": bool(activated),
            "visible_hwnd": visible_hwnd,
            "visible_pid": visible_pid,
            "expected_pid": expected_pid,
        }
    try:
        image = ImageGrab.grab(bbox=(x, y, x + width, y + height), all_screens=True)
        path.parent.mkdir(parents=True, exist_ok=True)
        image.save(path, format="PNG")
    except Exception as exc:
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
    return {
        **_png_capture_summary(path),
        "hwnd": int(state.viewport_hwnd),
        "screen_rect": list(rect),
        "foreground_activated": True,
        "visible_hwnd": visible_hwnd,
        "visible_pid": visible_pid,
        "expected_pid": expected_pid,
    }


def exercise_deterministic_offscreen_capture(
    state: SimpleNamespace,
    *,
    pump_until: object,
    wait_protocol_event: object,
) -> dict[str, object]:
    """Capture the same resident state twice through the production offscreen path."""

    rows: list[dict[str, object]] = []
    package = state.tab.standalone_dotnet_experiment_package
    for _index in range(2):
        callback_results: list[object] = []
        cursor = len(state.tab.standalone_dotnet_protocol_events)
        request_id = int(state.tab.standalone_dotnet_capture_request_id) + 1
        output_path = package.output_dir / f"icon_capture_{request_id}.png"
        sent = bool(state.tab.request_resident_dotnet_icon_capture(callback_results.append))
        event = wait_protocol_event(state, "capture_result", cursor, 12.0) if sent else {}
        completed = bool(
            pump_until(state, lambda: bool(callback_results), 2.0)
            if sent and not callback_results
            else callback_results
        )
        try:
            file_hash = hashlib.sha256(output_path.read_bytes()).hexdigest() if output_path.is_file() else ""
            file_bytes = int(output_path.stat().st_size) if output_path.is_file() else 0
        except OSError:
            file_hash = ""
            file_bytes = 0
        rows.append(
            {
                "request_id": request_id,
                "sent": sent,
                "completed": completed,
                "status": str(event.get("status", "") or ""),
                "output_path": str(output_path),
                "bytes": file_bytes,
                "sha256": file_hash,
                "reported_sha256": str(event.get("sha256", "") or ""),
                "ui_excluded": event.get("ui_excluded") is True,
                "grid_excluded": event.get("grid_excluded") is True,
                "gizmo_excluded": event.get("gizmo_excluded") is True,
                "selection_excluded": event.get("selection_excluded") is True,
                "hover_excluded": event.get("hover_excluded") is True,
                "visible_view_mutated": bool(event.get("visible_view_mutated", True)),
            }
        )
    required_flags = (
        "ui_excluded",
        "grid_excluded",
        "gizmo_excluded",
        "selection_excluded",
        "hover_excluded",
    )
    ok = bool(
        len(rows) == 2
        and all(
            row["sent"]
            and row["completed"]
            and row["status"] == "captured"
            and int(row["bytes"]) > 0
            and row["sha256"] == row["reported_sha256"]
            and not row["visible_view_mutated"]
            and all(row[name] for name in required_flags)
            for row in rows
        )
        and rows[0]["sha256"] == rows[1]["sha256"]
    )
    return {
        "ok": ok,
        "captures": rows,
        "deterministic_pixel_hash": rows[0]["sha256"] if ok else "",
        "process_pid": int(state.tab.standalone_dotnet_editor_process.processId()),
        "window_identity": {
            "form_hwnd": int(state.form_hwnd),
            "viewport_hwnd": int(state.viewport_hwnd),
        },
    }


__all__ = ["capture_dotnet_viewport", "exercise_deterministic_offscreen_capture"]
