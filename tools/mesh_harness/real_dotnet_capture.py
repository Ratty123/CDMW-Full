from __future__ import annotations

import hashlib
import time
from pathlib import Path
from types import SimpleNamespace

from tools.mesh_harness.win32_input import (
    _host_window_rect,
    _restore_window_z_order,
    _show_window_without_activation,
    _top_level_window_hwnd,
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
    expected_pid = int(state.production_process_pid)
    harness_widget_hwnd = int(state.tab.winId())
    harness_root_hwnd = _top_level_window_hwnd(harness_widget_hwnd)
    if not harness_root_hwnd:
        return {
            "ok": False,
            "error": "The harness tab is not attached to a valid top-level window.",
            "foreground_activated": False,
            "harness_widget_hwnd": harness_widget_hwnd,
            "harness_root_hwnd": 0,
        }
    viewport_shown_without_activation = _show_window_without_activation(
        int(state.viewport_hwnd), topmost=False
    )
    host_shown_without_activation = _show_window_without_activation(
        harness_root_hwnd, topmost=True
    )
    shown_without_activation = bool(
        viewport_shown_without_activation and host_shown_without_activation
    )
    visible_hwnd = 0
    visible_pid = 0
    ownership_ok = False
    try:
        # The window is briefly topmost on its assigned monitor, but SWP_NOACTIVATE
        # preserves the user's foreground app. Ownership still has to prove that
        # the pixels at the capture point belong to the production helper.
        for attempt in range(10):
            state.app.processEvents()
            time.sleep(0.08)
            visible_hwnd = _window_at_screen_point(x + width // 2, y + height // 2)
            visible_pid = _window_process_id(visible_hwnd)
            ownership_ok = bool(
                shown_without_activation
                and visible_pid == expected_pid
                and _window_is_same_or_child(int(state.viewport_hwnd), visible_hwnd)
            )
            if ownership_ok:
                break
            viewport_shown_without_activation = _show_window_without_activation(
                int(state.viewport_hwnd), topmost=False
            )
            host_shown_without_activation = _show_window_without_activation(
                harness_root_hwnd, topmost=True
            )
            shown_without_activation = bool(
                viewport_shown_without_activation and host_shown_without_activation
            )
            time.sleep(min(0.4, 0.08 * (attempt + 1)))
        if not ownership_ok:
            reasons = []
            if not shown_without_activation:
                reasons.append("the harness window could not be shown without activation")
            if visible_pid != expected_pid:
                reasons.append(
                    f"the window at the capture point belongs to pid {visible_pid}, not {expected_pid}"
                )
            elif not _window_is_same_or_child(int(state.viewport_hwnd), visible_hwnd):
                reasons.append(
                    f"the window at the capture point ({visible_hwnd}) is not the viewport or its child"
                )
            return {
                "ok": False,
                "error": (
                    "The .NET viewport was not the visible owned capture target: "
                    + ("; ".join(reasons) if reasons else "ownership was lost before the grab")
                ),
                "foreground_activated": False,
                "window_shown_without_activation": bool(shown_without_activation),
                "host_shown_without_activation": bool(host_shown_without_activation),
                "viewport_shown_without_activation": bool(viewport_shown_without_activation),
                "visible_hwnd": visible_hwnd,
                "visible_pid": visible_pid,
                "expected_pid": expected_pid,
                "harness_widget_hwnd": harness_widget_hwnd,
                "harness_root_hwnd": harness_root_hwnd,
            }
        # A newly revealed D3D11 surface may need more than one presentation.
        summary: dict[str, object] = {}
        attempts = 0
        for attempt in range(12):
            attempts = attempt + 1
            try:
                image = ImageGrab.grab(
                    bbox=(x, y, x + width, y + height),
                    all_screens=True,
                )
                path.parent.mkdir(parents=True, exist_ok=True)
                image.save(path, format="PNG")
            except Exception as exc:
                return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
            summary = _png_capture_summary(path)
            if summary.get("ok"):
                break
            state.app.processEvents()
            time.sleep(min(0.5, 0.1 * (attempt + 1)))
        return {
            **summary,
            "hwnd": int(state.viewport_hwnd),
            "screen_rect": list(rect),
            "foreground_activated": False,
            "window_shown_without_activation": bool(shown_without_activation),
            "host_shown_without_activation": bool(host_shown_without_activation),
            "viewport_shown_without_activation": bool(viewport_shown_without_activation),
            "capture_attempts": attempts,
            "visible_hwnd": visible_hwnd,
            "visible_pid": visible_pid,
            "expected_pid": expected_pid,
            "harness_widget_hwnd": harness_widget_hwnd,
            "harness_root_hwnd": harness_root_hwnd,
        }
    finally:
        _restore_window_z_order(harness_root_hwnd)


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
