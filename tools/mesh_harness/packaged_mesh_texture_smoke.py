"""Packaged proof for the production Mesh Editor viewport, textures, and Select."""

from __future__ import annotations

import hashlib
import json
import os
import struct
import sys
import time
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from types import SimpleNamespace

from PySide6.QtCore import QTimer, Qt
from PySide6.QtWidgets import QApplication

from cdmw.core.archive_format import parse_archive_pamt
from cdmw.models import ArchiveEntry
from cdmw.services.mesh_dotnet_experiment import resolve_mesh_dotnet_experiment_editor
from cdmw.ui.archive_browser.mesh_builder_startup_smoke import (
    configure_synthetic_archive_context,
)
from tools.mesh_harness.constants import (
    _MK_LBUTTON,
    _WM_LBUTTONDOWN,
    _WM_LBUTTONUP,
    _WM_MOUSEMOVE,
)
from tools.mesh_harness.real_dotnet_capture import capture_dotnet_viewport
from tools.mesh_harness.win32_input import (
    _click_button_by_text,
    _desktop_input_isolation_evidence,
    _desktop_input_snapshot,
    _enumerate_child_windows,
    _host_window_rect,
    _scoped_input_target_matches,
    _select_combo_item_by_text,
    _send_mouse_message,
    _show_window_without_activation,
    _window_process_id,
    _window_parent_hwnd,
)


# This PHW model is the escaped packaged-runtime regression: its visible body
# textures arrive as exact native ``embedded_mesh_reference`` bindings.
_PACKAGED_TEXTURE_SAMPLE = (
    "character/model/1_pc/2_phw/nude/cd_phw_00_nude_00_4001.pac"
)


def _normalized_archive_key(value: object) -> str:
    return str(value or "").replace("\\", "/").strip("/").casefold()


def _entry_indexes(
    entries: Sequence[ArchiveEntry],
) -> tuple[
    dict[str, tuple[ArchiveEntry, ...]],
    dict[str, tuple[ArchiveEntry, ...]],
    dict[str, tuple[ArchiveEntry, ...]],
]:
    by_path: dict[str, list[ArchiveEntry]] = {}
    by_basename: dict[str, list[ArchiveEntry]] = {}
    by_extension: dict[str, list[ArchiveEntry]] = {}
    for entry in entries:
        by_path.setdefault(_normalized_archive_key(entry.path), []).append(entry)
        by_basename.setdefault(str(entry.basename or "").casefold(), []).append(entry)
        by_extension.setdefault(str(entry.extension or "").casefold(), []).append(entry)
    return (
        {key: tuple(values) for key, values in by_path.items()},
        {key: tuple(values) for key, values in by_basename.items()},
        {key: tuple(values) for key, values in by_extension.items()},
    )


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _pump_until(
    app: QApplication,
    predicate: Callable[[], bool],
    *,
    timeout_seconds: float,
    label: str,
    desktop_observations: list[Mapping[str, object]] | None = None,
) -> float:
    started = time.perf_counter()
    deadline = started + max(0.1, float(timeout_seconds))
    while time.perf_counter() < deadline:
        app.processEvents()
        if desktop_observations is not None and len(desktop_observations) < 8192:
            desktop_observations.append(_desktop_input_snapshot())
        if predicate():
            return max(0.0, (time.perf_counter() - started) * 1000.0)
        time.sleep(0.01)
    app.processEvents()
    if predicate():
        return max(0.0, (time.perf_counter() - started) * 1000.0)
    raise RuntimeError(f"Packaged Mesh Editor smoke timed out: {label}.")


def _proof_screen(app: QApplication) -> object:
    requested = str(os.environ.get("CDMW_HARNESS_SCREEN", "") or "").strip()
    primary = app.primaryScreen()
    if not requested:
        return primary
    screens = list(app.screens() or ())
    for screen in screens:
        if str(screen.name() or "").strip().casefold() == requested.casefold():
            return screen
    if requested.lstrip("-").isdigit():
        index = int(requested)
        if 0 <= index < len(screens):
            return screens[index]
    available = ", ".join(
        f"[{index}] {screen.name()!r}" for index, screen in enumerate(screens)
    )
    raise RuntimeError(
        f"CDMW_HARNESS_SCREEN={requested!r} matches no screen. "
        f"Available: {available or '(none)'}."
    )


def _place_window_without_activation(
    window: object,
    app: QApplication,
) -> tuple[int, int, int, int]:
    screen = _proof_screen(app)
    available = screen.availableGeometry()
    full = screen.geometry()
    bounds = (
        int(full.x()),
        int(full.y()),
        int(full.x() + full.width()),
        int(full.y() + full.height()),
    )
    width = max(960, min(1600, int(available.width()) - 48))
    height = max(640, min(940, int(available.height()) - 48))
    window.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
    window.setWindowFlag(Qt.WindowType.WindowDoesNotAcceptFocus, True)
    window.setGeometry(int(available.x()) + 24, int(available.y()) + 24, width, height)
    app.processEvents()
    if not _show_window_without_activation(int(window.winId())):
        raise RuntimeError("The packaged app window could not be shown without activation.")
    app.processEvents()
    return bounds


def _protocol_events(mesh_editor_tab: object) -> tuple[dict[str, object], ...]:
    return tuple(
        dict(event)
        for event in tuple(
            getattr(mesh_editor_tab, "standalone_dotnet_protocol_events", ()) or ()
        )
        if isinstance(event, Mapping)
    )


def _latest_event(
    mesh_editor_tab: object,
    event_name: str,
    *,
    cursor: int = 0,
    predicate: Callable[[Mapping[str, object]], bool] | None = None,
) -> dict[str, object]:
    for event in reversed(_protocol_events(mesh_editor_tab)[max(0, int(cursor)) :]):
        if str(event.get("event", "") or "").strip().lower() != event_name:
            continue
        if predicate is None or predicate(event):
            return event
    return {}


def _renderer_state(mesh_editor_tab: object) -> dict[str, object]:
    status = getattr(mesh_editor_tab, "standalone_dotnet_status_payload", {})
    renderer = status.get("renderer", {}) if isinstance(status, Mapping) else {}
    return dict(renderer) if isinstance(renderer, Mapping) else {}


def _renderer_texture_state(mesh_editor_tab: object) -> dict[str, object]:
    renderer = _renderer_state(mesh_editor_tab)
    geometry = renderer.get("geometry_resources", {})
    if not isinstance(geometry, Mapping):
        geometry = {}
    live = renderer.get("live_metrics", {})
    live_geometry = live.get("geometry_resources", {}) if isinstance(live, Mapping) else {}
    if not isinstance(live_geometry, Mapping):
        live_geometry = {}
    presentation = renderer.get("presentation", {})
    if not isinstance(presentation, Mapping):
        presentation = {}
    edit_operator = renderer.get("edit_operator", {})
    if not isinstance(edit_operator, Mapping):
        edit_operator = {}
    result: dict[str, object] = {
        "backend": str(renderer.get("backend", "") or ""),
        "display_mode": str(renderer.get("display_mode", "") or ""),
        "textures_enabled": bool(renderer.get("textures_enabled", False)),
        "viewport": dict(renderer.get("viewport", {}))
        if isinstance(renderer.get("viewport"), Mapping)
        else {},
        "draw_counter_source": "renderer.live_metrics.geometry_resources",
        "presentation_generation": int(
            presentation.get("presentation_generation", 0) or 0
        ),
        "last_applied_edit_revision": int(
            renderer.get("last_applied_edit_revision", 0) or 0
        ),
        "edit_operator": dict(edit_operator),
    }
    for result_key, counters, geometry_key in (
        ("live_texture_srvs", geometry, "live_texture_srvs"),
        ("texture_srv_creates", geometry, "texture_srv_creates"),
        ("textured_draw_calls", live_geometry, "textured_solid_batch_draws"),
        (
            "committed_selection_overlay_primitives",
            live_geometry,
            "committed_selection_overlay_primitives",
        ),
    ):
        try:
            result[result_key] = max(0, int(counters.get(geometry_key, 0) or 0))
        except (TypeError, ValueError, OverflowError):
            result[result_key] = 0
    for key in (
        "device_identity",
        "geometry_buffer_identity",
        "render_surface_identity",
        "render_surface_create_count",
        "render_surface_dispose_count",
        "swap_chain_resize_commit_count",
        "device_reset_count",
    ):
        try:
            result[key] = int(geometry.get(key, 0) or 0)
        except (TypeError, ValueError, OverflowError):
            result[key] = 0
    identity = live_geometry or geometry
    result.update(
        {
            "driver_type": str(identity.get("driver_type", "") or ""),
            "adapter_description": str(
                identity.get("adapter_description", "") or ""
            ),
            "feature_level": str(identity.get("feature_level", "") or ""),
            "debug_layer_requested": bool(
                identity.get("debug_layer_requested", False)
            ),
            "debug_layer_state": str(
                identity.get("debug_layer_state", "") or ""
            ),
        }
    )
    return result


def _mesh_geometry_snapshot(mesh_editor_tab: object) -> dict[str, object]:
    target = mesh_editor_tab._dotnet_target_controller()
    if target is None:
        raise RuntimeError("The production Mesh Editor has no authoritative session.")
    view = target.session_view()
    mesh = target.working_mesh(clone=False)
    digest = hashlib.sha256()
    vertex_count = 0
    for submesh_index, submesh in enumerate(tuple(mesh.submeshes or ())):
        vertices = tuple(submesh.vertices or ())
        digest.update(struct.pack("<QQ", int(submesh_index), len(vertices)))
        for vertex in vertices:
            x, y, z = tuple(vertex)
            digest.update(struct.pack("<ddd", float(x), float(y), float(z)))
        vertex_count += len(vertices)
    return {
        "sha256": digest.hexdigest(),
        "resident_revision": int(view.resident_revision),
        "history_cursor": int(view.history_cursor),
        "history_entry_count": len(tuple(view.history_entries or ())),
        "undo_count": int(view.undo_count),
        "redo_count": int(view.redo_count),
        "vertex_count": vertex_count,
        "submesh_count": len(tuple(mesh.submeshes or ())),
    }


def _request_renderer_status(
    app: QApplication,
    mesh_editor_tab: object,
    *,
    label: str,
    desktop_observations: list[Mapping[str, object]],
) -> dict[str, object]:
    target = mesh_editor_tab._dotnet_target_controller()
    session_id = str(target.session_view().session_id) if target is not None else ""
    status_request_id = int(time.monotonic_ns() & 0x7FFFFFFF) or 1
    if not mesh_editor_tab._send_dotnet_protocol_message(
        {
            "event": "renderer_status_request",
            "request_id": status_request_id,
            "session_id": session_id,
            "process_generation": int(mesh_editor_tab.standalone_dotnet_process_generation),
            "protocol_version": 2,
        }
    ):
        raise RuntimeError(
            f"Packaged Mesh Editor smoke could not request renderer status for {label}."
        )
    _pump_until(
        app,
        lambda: int(
            (
                getattr(mesh_editor_tab, "standalone_dotnet_status_payload", {})
                .get("renderer_status_response", {})
                .get("request_id", 0)
            )
            or 0
        )
        == status_request_id,
        timeout_seconds=15.0,
        label=f"{label} renderer status",
        desktop_observations=desktop_observations,
    )
    return _renderer_texture_state(mesh_editor_tab)


def _renderer_reached_textured_draw(renderer: Mapping[str, object]) -> bool:
    return bool(
        str(renderer.get("display_mode", "") or "") == "textured"
        and renderer.get("textures_enabled") is True
        and int(renderer.get("live_texture_srvs", 0) or 0) > 0
        and int(renderer.get("textured_draw_calls", 0) or 0) > 0
    )


def _wait_for_textured_renderer(
    app: QApplication,
    mesh_editor_tab: object,
    *,
    desktop_observations: list[Mapping[str, object]],
) -> tuple[dict[str, object], float, int]:
    started = time.perf_counter()
    deadline = started + 10.0
    attempts = 0
    renderer: dict[str, object] = {}
    while True:
        attempts += 1
        renderer = _request_renderer_status(
            app,
            mesh_editor_tab,
            label="production Solid (Textured)",
            desktop_observations=desktop_observations,
        )
        if _renderer_reached_textured_draw(renderer):
            return renderer, max(0.0, (time.perf_counter() - started) * 1000.0), attempts
        if time.perf_counter() >= deadline:
            raise RuntimeError(
                "The real Solid (Textured) control did not reach a textured "
                f"D3D11 draw after {attempts} renderer snapshots: {renderer!r}"
            )
        next_snapshot = time.perf_counter() + 0.1
        _pump_until(
            app,
            lambda: time.perf_counter() >= next_snapshot,
            timeout_seconds=0.5,
            label="next post-paint renderer snapshot",
            desktop_observations=desktop_observations,
        )


def _viewport_shell_state(mesh_editor_tab: object) -> dict[str, object]:
    host = getattr(mesh_editor_tab, "standalone_native_host_frame", None)
    stack = getattr(mesh_editor_tab, "workspace_stack", None)
    host_rect = _host_window_rect(int(host.winId())) if host is not None else None
    empty_state = getattr(mesh_editor_tab, "empty_state", None)
    return {
        "standalone_workspace_current": bool(
            stack is not None
            and stack.currentWidget() is getattr(mesh_editor_tab, "standalone_workspace", None)
        ),
        "empty_guidance_visible": bool(empty_state is not None and not empty_state.isHidden()),
        "host_visible": bool(host is not None and host.isVisible()),
        "host_rect": list(host_rect) if host_rect else [],
        "host_size": [int(host.width()), int(host.height())] if host is not None else [0, 0],
    }


def _viewport_window_state(viewport_hwnd: int, expected_pid: int) -> dict[str, object]:
    rect = _host_window_rect(viewport_hwnd)
    visible = False
    if viewport_hwnd and os.name == "nt":
        import ctypes

        visible = bool(
            ctypes.windll.user32.IsWindowVisible(ctypes.c_void_p(viewport_hwnd))
        )
    return {
        "hwnd": int(viewport_hwnd),
        "pid": _window_process_id(viewport_hwnd),
        "expected_pid": int(expected_pid),
        "owned": _window_process_id(viewport_hwnd) == int(expected_pid),
        "visible": visible,
        "rect": list(rect) if rect else [],
        "nonzero": bool(rect and rect[2] - rect[0] >= 32 and rect[3] - rect[1] >= 32),
    }


def _continuity_identity(
    renderer: Mapping[str, object],
    *,
    viewport_hwnd: int,
    expected_pid: int,
) -> dict[str, object]:
    viewport = dict(renderer.get("viewport", {})) if isinstance(
        renderer.get("viewport"), Mapping
    ) else {}
    window = _viewport_window_state(viewport_hwnd, expected_pid)
    return {
        "backend": str(renderer.get("backend", "") or ""),
        "viewport_hwnd": int(viewport.get("hwnd", 0) or 0),
        "viewport_parent_hwnd": _window_parent_hwnd(viewport_hwnd),
        "viewport_rect": list(window.get("rect", ()) or ()),
        "viewport_visible": bool(window.get("visible")),
        "viewport_nonzero": bool(window.get("nonzero")),
        "device_identity": int(renderer.get("device_identity", 0) or 0),
        "geometry_buffer_identity": int(
            renderer.get("geometry_buffer_identity", 0) or 0
        ),
        "render_surface_identity": int(
            renderer.get("render_surface_identity", 0) or 0
        ),
        "render_surface_create_count": int(
            renderer.get("render_surface_create_count", 0) or 0
        ),
        "render_surface_dispose_count": int(
            renderer.get("render_surface_dispose_count", 0) or 0
        ),
        "swap_chain_resize_commit_count": int(
            renderer.get("swap_chain_resize_commit_count", 0) or 0
        ),
        "device_reset_count": int(renderer.get("device_reset_count", 0) or 0),
        "driver_type": str(renderer.get("driver_type", "") or ""),
        "adapter_description": str(
            renderer.get("adapter_description", "") or ""
        ),
        "feature_level": str(renderer.get("feature_level", "") or ""),
        "debug_layer_requested": bool(
            renderer.get("debug_layer_requested", False)
        ),
        "debug_layer_state": str(
            renderer.get("debug_layer_state", "") or ""
        ),
        "presentation_generation": int(
            renderer.get("presentation_generation", 0) or 0
        ),
        "last_applied_edit_revision": int(
            renderer.get("last_applied_edit_revision", 0) or 0
        ),
    }


def _exercise_actual_control_continuity(
    app: QApplication,
    mesh_editor_tab: object,
    *,
    form_hwnd: int,
    viewport_hwnd: int,
    helper_pid: int,
    output_root: Path,
    desktop_observations: list[Mapping[str, object]],
) -> dict[str, object]:
    cases: list[dict[str, object]] = []
    transition_ms: list[float] = []
    # Visit the visible rail from bottom to top. Opening a row inserts its body
    # below that row, so this order keeps the next real control on screen and
    # measures activation rather than an automation-only scroll/layout pass.
    controls = (
        *(("page", text, "") for text in ("Viewport", "Morph & Refit", "Topology")),
        *(("tool", text, tool) for text, tool in (
            ("Pinch", "pinch"),
            ("Inflate", "inflate"),
            ("Smooth", "smooth"),
            ("Grab", "grab"),
            ("Move", "move"),
            ("Select", "select"),
        )),
    )
    capture_state = SimpleNamespace(
        app=app,
        tab=mesh_editor_tab,
        viewport_hwnd=viewport_hwnd,
        production_process_pid=helper_pid,
    )
    for index, (kind, text, expected_tool) in enumerate(controls, start=1):
        before = _request_renderer_status(
            app,
            mesh_editor_tab,
            label=f"before actual {text} activation",
            desktop_observations=desktop_observations,
        )
        before_identity = _continuity_identity(
            before,
            viewport_hwnd=viewport_hwnd,
            expected_pid=helper_pid,
        )
        cursor = len(_protocol_events(mesh_editor_tab))
        control = _click_button_by_text(form_hwnd, text, expected_pid=helper_pid)
        if control.get("ok") is not True:
            raise RuntimeError(f"The real {text} control could not be pressed: {control!r}")
        post_dispatch_started = time.perf_counter()
        if kind == "tool":
            _pump_until(
                app,
                lambda: bool(
                    _latest_event(
                        mesh_editor_tab,
                        "tool_changed",
                        cursor=cursor,
                        predicate=lambda event, tool=expected_tool: str(
                            event.get("tool", "") or ""
                        ).lower() == tool,
                    )
                ),
                timeout_seconds=10.0,
                label=f"actual {text} activation",
                desktop_observations=desktop_observations,
            )
        else:
            app.processEvents()
        settled_ms = float(control.get("message_dispatch_ms", 0.0) or 0.0) + max(
            0.0,
            (time.perf_counter() - post_dispatch_started) * 1000.0,
        )
        transition_ms.append(settled_ms)
        after = _request_renderer_status(
            app,
            mesh_editor_tab,
            label=f"after actual {text} activation",
            desktop_observations=desktop_observations,
        )
        after_identity = _continuity_identity(
            after,
            viewport_hwnd=viewport_hwnd,
            expected_pid=helper_pid,
        )
        operator = dict(after.get("edit_operator", {})) if isinstance(
            after.get("edit_operator"), Mapping
        ) else {}
        capture_path = output_root / f"control-{index:02d}-{expected_tool or text.lower().replace(' ', '-')}.png"
        capture = capture_dotnet_viewport(capture_state, capture_path)
        stable = bool(
            before_identity == after_identity
            and after_identity["backend"] == "d3d11_vortice_shader"
            and after_identity["viewport_hwnd"] == viewport_hwnd
            and after_identity["viewport_visible"]
            and after_identity["viewport_nonzero"]
            and int(after_identity["device_identity"]) != 0
            and int(after_identity["render_surface_identity"]) != 0
            and after_identity["driver_type"] == "hardware"
            and bool(after_identity["adapter_description"])
            and bool(after_identity["feature_level"])
            and after_identity["debug_layer_requested"] is False
            and after_identity["debug_layer_state"] == "disabled"
            and str(operator.get("state", "") or "").lower() == "idle"
            and capture.get("ok") is True
        )
        case = {
            "kind": kind,
            "control_text": text,
            "expected_tool": expected_tool,
            "actual_control": control,
            "settled_ms": round(settled_ms, 3),
            "before": before_identity,
            "after": after_identity,
            "edit_operator": operator,
            "capture": {**capture, "path": str(capture_path)},
            "stable": stable,
        }
        cases.append(case)
        if not stable:
            raise RuntimeError(
                f"The real {text} activation changed the resident viewport: {case!r}"
            )
    ordered = sorted(transition_ms)
    p95_index = max(0, min(len(ordered) - 1, int(len(ordered) * 0.95 + 0.999999) - 1))
    p95_ms = ordered[p95_index]
    if p95_ms > 50.0:
        timings = [
            {
                "control": str(case.get("control_text", "") or ""),
                "settled_ms": float(case.get("settled_ms", 0.0) or 0.0),
                "dispatch_ms": float(
                    dict(case.get("actual_control", {})).get("message_dispatch_ms", 0.0)
                    or 0.0
                ),
            }
            for case in cases
        ]
        raise RuntimeError(
            f"Tool/page activation p95 exceeded 50 ms: {p95_ms:.3f} ms; "
            f"cases={timings!r}."
        )
    return {
        "ok": True,
        "actual_controls": True,
        "case_count": len(cases),
        "settlement_p95_ms": round(p95_ms, 3),
        "threshold_ms": 50.0,
        "cases": cases,
    }


def _activate_solid_textured_control(
    app: QApplication,
    mesh_editor_tab: object,
    *,
    form_hwnd: int,
    helper_pid: int,
    desktop_observations: list[Mapping[str, object]],
) -> dict[str, object]:
    page_control = _click_button_by_text(form_hwnd, "Viewport", expected_pid=helper_pid)
    if page_control.get("ok") is not True:
        raise RuntimeError(f"The real Viewport control could not be pressed: {page_control!r}")
    app.processEvents()

    untextured_cursor = len(_protocol_events(mesh_editor_tab))
    untextured_control = _select_combo_item_by_text(
        form_hwnd,
        "Faces (No Textures)",
        expected_pid=helper_pid,
    )
    if untextured_control.get("ok") is not True:
        raise RuntimeError(
            f"The real preview-mode control could not select Faces (No Textures): {untextured_control!r}"
        )
    _pump_until(
        app,
        lambda: bool(
            _latest_event(
                mesh_editor_tab,
                "viewport_display_request",
                cursor=untextured_cursor,
                predicate=lambda event: str(event.get("mode", "") or "").lower()
                == "untextured_faces",
            )
        ),
        timeout_seconds=10.0,
        label="actual Faces (No Textures) control request",
        desktop_observations=desktop_observations,
    )

    textured_cursor = len(_protocol_events(mesh_editor_tab))
    textured_control = _select_combo_item_by_text(
        form_hwnd,
        "Solid (Textured)",
        expected_pid=helper_pid,
    )
    if textured_control.get("ok") is not True:
        raise RuntimeError(
            f"The real preview-mode control could not select Solid (Textured): {textured_control!r}"
        )
    control_request_ms = _pump_until(
        app,
        lambda: bool(
            _latest_event(
                mesh_editor_tab,
                "viewport_display_request",
                cursor=textured_cursor,
                predicate=lambda event: str(event.get("mode", "") or "").lower()
                == "textured",
            )
        ),
        timeout_seconds=10.0,
        label="actual Solid (Textured) control request",
        desktop_observations=desktop_observations,
    )
    settled_ms = _pump_until(
        app,
        lambda: bool(
            not getattr(mesh_editor_tab, "standalone_dotnet_pending_textured_view", False)
            and getattr(mesh_editor_tab, "standalone_dotnet_scene_pending", None) is None
            and getattr(mesh_editor_tab, "standalone_dotnet_presentation_pending", None)
            is None
            and not bool(
                getattr(mesh_editor_tab, "standalone_dotnet_presentation_queued", False)
            )
            and not bool(mesh_editor_tab._standalone_dotnet_package_worker_active())
            and not bool(mesh_editor_tab._dotnet_material_compile_active())
            and bool(mesh_editor_tab._dotnet_active_material_role_ready())
        ),
        timeout_seconds=180.0,
        label="production Solid (Textured) material settlement",
        desktop_observations=desktop_observations,
    )
    renderer, draw_settled_ms, renderer_status_attempts = _wait_for_textured_renderer(
        app,
        mesh_editor_tab,
        desktop_observations=desktop_observations,
    )
    return {
        "actual_controls": True,
        "page_control": page_control,
        "untextured_control": untextured_control,
        "textured_control": textured_control,
        "control_request_ms": round(control_request_ms, 3),
        "settled_ms": round(settled_ms, 3),
        "draw_settled_ms": round(draw_settled_ms, 3),
        "renderer_status_attempts": renderer_status_attempts,
        "selected_mode": "textured",
        "renderer_resources": renderer,
        "active_material_role": str(mesh_editor_tab._dotnet_active_material_role()),
        "required_material_roles": list(mesh_editor_tab._dotnet_required_material_roles()),
        "roles_ready": dict(
            getattr(mesh_editor_tab, "standalone_dotnet_texture_resources_ready_by_role", {})
        ),
        "applied_generation_by_role": dict(
            getattr(mesh_editor_tab, "standalone_dotnet_applied_material_generation_by_role", {})
        ),
    }


def _selection_is_nonempty(payload: Mapping[str, object]) -> bool:
    if tuple(payload.get("source_indices", ()) or ()):
        return True
    for key in ("vertices_by_submesh", "edges_by_submesh", "faces_by_submesh"):
        values = payload.get(key)
        if isinstance(values, Mapping) and any(tuple(row or ()) for row in values.values()):
            return True
    return False


def _query_helper_selection(
    app: QApplication,
    mesh_editor_tab: object,
    *,
    desktop_observations: list[Mapping[str, object]],
) -> dict[str, object]:
    applied: dict[str, object] = {}
    for _attempt in range(4):
        cursor = len(_protocol_events(mesh_editor_tab))
        if not mesh_editor_tab._send_dotnet_protocol_message(
            {"event": "tool_state", "tool": "select"}
        ):
            break
        _pump_until(
            app,
            lambda: bool(_latest_event(mesh_editor_tab, "tool_state_applied", cursor=cursor)),
            timeout_seconds=5.0,
            label="selection state readback",
            desktop_observations=desktop_observations,
        )
        applied = _latest_event(mesh_editor_tab, "tool_state_applied", cursor=cursor)
        local_selection = applied.get("local_selection", {})
        if isinstance(local_selection, Mapping) and _selection_is_nonempty(local_selection):
            return applied
        time.sleep(0.05)
        app.processEvents()
    return applied


def _perform_actual_select_attempt(
    app: QApplication,
    mesh_editor_tab: object,
    *,
    viewport_hwnd: int,
    start: tuple[int, int],
    desktop_observations: list[Mapping[str, object]],
) -> tuple[dict[str, object], dict[str, object]]:
    end = (start[0] + 8, start[1])
    cursor = len(_protocol_events(mesh_editor_tab))
    moved = _send_mouse_message(viewport_hwnd, _WM_MOUSEMOVE, *start)
    down = _send_mouse_message(
        viewport_hwnd,
        _WM_LBUTTONDOWN,
        *start,
        wparam=_MK_LBUTTON,
    )
    drag = bool(
        down
        and _send_mouse_message(
            viewport_hwnd,
            _WM_MOUSEMOVE,
            start[0] + 4,
            start[1],
            wparam=_MK_LBUTTON,
        )
    )
    up = _send_mouse_message(viewport_hwnd, _WM_LBUTTONUP, *end)
    _pump_until(
        app,
        lambda: bool(
            _latest_event(
                mesh_editor_tab,
                "resident_interaction_transaction",
                cursor=cursor,
            )
        ),
        timeout_seconds=5.0,
        label="physical Select resident transaction",
        desktop_observations=desktop_observations,
    )
    terminal = _latest_event(
        mesh_editor_tab,
        "resident_interaction_transaction",
        cursor=cursor,
    )
    request_id = int(terminal.get("request_id", 0) or 0)
    ack_ms = _pump_until(
        app,
        lambda: bool(
            _latest_event(
                mesh_editor_tab,
                "resident_mutation_batch_ack",
                cursor=cursor,
                predicate=lambda event: int(event.get("request_id", 0) or 0)
                == request_id
                and str(event.get("status", "") or "").lower()
                in {"applied", "already_applied"},
            )
        ),
        timeout_seconds=15.0,
        label="authoritative Select acknowledgement",
        desktop_observations=desktop_observations,
    )
    acknowledgement = _latest_event(
        mesh_editor_tab,
        "resident_mutation_batch_ack",
        cursor=cursor,
        predicate=lambda event: int(event.get("request_id", 0) or 0) == request_id,
    )
    applied = _query_helper_selection(
        app,
        mesh_editor_tab,
        desktop_observations=desktop_observations,
    )
    local_selection = applied.get("local_selection", {})
    local_selection = dict(local_selection) if isinstance(local_selection, Mapping) else {}
    return (
        {
            "point": list(start),
            "mouse_move_sent": bool(moved),
            "mouse_down_sent": bool(down),
            "drag_sent": bool(drag),
            "mouse_up_sent": bool(up),
            "request_id": request_id,
            "resident_interaction_transaction": terminal,
            "authority_acknowledgement": acknowledgement,
            "authority_ack_ms": round(ack_ms, 3),
            "tool_state_applied": applied,
            "selection_nonempty": _selection_is_nonempty(local_selection),
        },
        local_selection,
    )


def _exercise_actual_select_control(
    app: QApplication,
    mesh_editor_tab: object,
    *,
    form_hwnd: int,
    viewport_hwnd: int,
    helper_pid: int,
    desktop_observations: list[Mapping[str, object]],
) -> dict[str, object]:
    tool_cursor = len(_protocol_events(mesh_editor_tab))
    select_control = _click_button_by_text(form_hwnd, "Select", expected_pid=helper_pid)
    if select_control.get("ok") is not True:
        raise RuntimeError(f"The real Select control could not be pressed: {select_control!r}")
    tool_changed_ms = _pump_until(
        app,
        lambda: bool(
            _latest_event(
                mesh_editor_tab,
                "tool_changed",
                cursor=tool_cursor,
                predicate=lambda event: str(event.get("tool", "") or "").lower()
                == "select",
            )
        ),
        timeout_seconds=10.0,
        label="actual Select control tool change",
        desktop_observations=desktop_observations,
    )
    rect = _host_window_rect(viewport_hwnd)
    if rect is None or not _scoped_input_target_matches(viewport_hwnd, helper_pid):
        raise RuntimeError("The D3D11 viewport is not a safe helper-owned input target.")
    width = int(rect[2] - rect[0])
    height = int(rect[3] - rect[1])
    if not _show_window_without_activation(viewport_hwnd):
        raise RuntimeError("The D3D11 viewport could not be shown without activation.")

    attempts: list[dict[str, object]] = []
    points = (
        (0.50, 0.50),
        (0.50, 0.42),
        (0.45, 0.52),
        (0.55, 0.52),
        (0.50, 0.62),
    )
    for x_ratio, y_ratio in points:
        start = (
            max(2, min(width - 10, int(round(width * x_ratio)))),
            max(2, min(height - 4, int(round(height * y_ratio)))),
        )
        attempt, local_selection = _perform_actual_select_attempt(
            app,
            mesh_editor_tab,
            viewport_hwnd=viewport_hwnd,
            start=start,
            desktop_observations=desktop_observations,
        )
        attempts.append(attempt)
        if attempt["selection_nonempty"]:
            return {
                "ok": True,
                "actual_control": True,
                "select_control": select_control,
                "tool_changed": _latest_event(
                    mesh_editor_tab,
                    "tool_changed",
                    cursor=tool_cursor,
                    predicate=lambda event: str(event.get("tool", "") or "").lower()
                    == "select",
                ),
                "tool_changed_ms": round(tool_changed_ms, 3),
                "input_backend": "scoped_hwnd_messages_no_global_cursor",
                "input_target_hwnd": int(viewport_hwnd),
                "input_target_pid": _window_process_id(viewport_hwnd),
                "attempts": attempts,
                "selected": local_selection,
            }
    raise RuntimeError(
        "The real Select control armed, but physical helper-owned viewport gestures "
        f"produced no authoritative mesh selection: {attempts!r}"
    )


def _button_available(
    root_hwnd: int,
    text: str,
    *,
    expected_pid: int,
) -> bool:
    requested = " ".join(text.split()).casefold()
    matches = [
        row
        for row in _enumerate_child_windows(root_hwnd, expected_pid=expected_pid)
        if "button" in str(row.get("class_name", "") or "").casefold()
        and (
            (actual := " ".join(str(row.get("text", "") or "").split()).casefold())
            == requested
            or actual.endswith(f" {requested}")
        )
    ]
    return len(matches) == 1 and matches[0].get("visible") is True and matches[0].get("enabled") is True


def _wait_for_authoritative_request(
    app: QApplication,
    mesh_editor_tab: object,
    *,
    cursor: int,
    event_name: str,
    command: str = "",
    desktop_observations: list[Mapping[str, object]],
) -> tuple[dict[str, object], dict[str, object]]:
    predicate = (
        (lambda event: str(event.get("command", "") or "").lower() == command)
        if command
        else None
    )
    _pump_until(
        app,
        lambda: bool(
            _latest_event(
                mesh_editor_tab,
                event_name,
                cursor=cursor,
                predicate=predicate,
            )
        ),
        timeout_seconds=10.0,
        label=f"actual {command or event_name} request",
        desktop_observations=desktop_observations,
    )
    request = _latest_event(
        mesh_editor_tab,
        event_name,
        cursor=cursor,
        predicate=predicate,
    )
    request_id = int(request.get("request_id", 0) or 0)
    if request_id <= 0:
        raise RuntimeError(f"The {event_name} request had no correlation id: {request!r}")
    _pump_until(
        app,
        lambda: bool(
            _latest_event(
                mesh_editor_tab,
                "resident_mutation_batch_ack",
                cursor=cursor,
                predicate=lambda event: int(event.get("request_id", 0) or 0)
                == request_id
                and str(event.get("status", "") or "").lower()
                in {"applied", "already_applied"},
            )
        ),
        timeout_seconds=20.0,
        label=f"authoritative {command or event_name} acknowledgement",
        desktop_observations=desktop_observations,
    )
    acknowledgement = _latest_event(
        mesh_editor_tab,
        "resident_mutation_batch_ack",
        cursor=cursor,
        predicate=lambda event: int(event.get("request_id", 0) or 0) == request_id,
    )
    return request, acknowledgement


def _perform_actual_grab(
    app: QApplication,
    mesh_editor_tab: object,
    *,
    form_hwnd: int,
    viewport_hwnd: int,
    helper_pid: int,
    start: tuple[int, int],
    desktop_observations: list[Mapping[str, object]],
) -> dict[str, object]:
    rail_cursor = len(_protocol_events(mesh_editor_tab))
    if not mesh_editor_tab._send_dotnet_protocol_message(
        {"event": "tool_state", "tool": "orbit"}
    ):
        raise RuntimeError("The production helper rejected the scoped Orbit rail reset.")
    rail_reset_ms = _pump_until(
        app,
        lambda: bool(
            _latest_event(
                mesh_editor_tab,
                "tool_state_applied",
                cursor=rail_cursor,
                predicate=lambda event: str(event.get("tool", "") or "").lower()
                == "orbit",
            )
        ),
        timeout_seconds=5.0,
        label="visible Grab rail reset",
        desktop_observations=desktop_observations,
    )
    rail_reset = _latest_event(
        mesh_editor_tab,
        "tool_state_applied",
        cursor=rail_cursor,
        predicate=lambda event: str(event.get("tool", "") or "").lower() == "orbit",
    )
    tool_cursor = len(_protocol_events(mesh_editor_tab))
    grab_control = _click_button_by_text(form_hwnd, "Grab", expected_pid=helper_pid)
    if grab_control.get("ok") is not True:
        raise RuntimeError(f"The real Grab control could not be pressed: {grab_control!r}")
    _pump_until(
        app,
        lambda: bool(
            _latest_event(
                mesh_editor_tab,
                "tool_changed",
                cursor=tool_cursor,
                predicate=lambda event: str(event.get("tool", "") or "").lower()
                == "grab",
            )
        ),
        timeout_seconds=10.0,
        label="actual Grab activation",
        desktop_observations=desktop_observations,
    )
    rect = _host_window_rect(viewport_hwnd)
    if rect is None or not _scoped_input_target_matches(viewport_hwnd, helper_pid):
        raise RuntimeError("The D3D11 viewport is not a safe Grab input target.")
    width = int(rect[2] - rect[0])
    height = int(rect[3] - rect[1])
    start_x = max(4, min(width - 64, int(start[0])))
    start_y = max(4, min(height - 16, int(start[1])))
    end = (min(width - 4, start_x + 48), max(4, start_y - 8))
    cursor = len(_protocol_events(mesh_editor_tab))
    moved = _send_mouse_message(viewport_hwnd, _WM_MOUSEMOVE, start_x, start_y)
    down = _send_mouse_message(
        viewport_hwnd,
        _WM_LBUTTONDOWN,
        start_x,
        start_y,
        wparam=_MK_LBUTTON,
    )
    drag_points: list[list[int]] = []
    for step in range(1, 7):
        x = start_x + round((end[0] - start_x) * step / 6)
        y = start_y + round((end[1] - start_y) * step / 6)
        if not _send_mouse_message(
            viewport_hwnd,
            _WM_MOUSEMOVE,
            x,
            y,
            wparam=_MK_LBUTTON,
        ):
            raise RuntimeError("The helper-owned Grab drag message was rejected.")
        drag_points.append([x, y])
        app.processEvents()
        time.sleep(0.02)
    up = _send_mouse_message(viewport_hwnd, _WM_LBUTTONUP, *end)
    request, acknowledgement = _wait_for_authoritative_request(
        app,
        mesh_editor_tab,
        cursor=cursor,
        event_name="resident_interaction_transaction",
        desktop_observations=desktop_observations,
    )
    renderer = _request_renderer_status(
        app,
        mesh_editor_tab,
        label="after actual Grab commit",
        desktop_observations=desktop_observations,
    )
    operator = dict(renderer.get("edit_operator", {})) if isinstance(
        renderer.get("edit_operator"), Mapping
    ) else {}
    snapshot = _mesh_geometry_snapshot(mesh_editor_tab)
    if str(operator.get("state", "") or "").lower() != "idle":
        raise RuntimeError(f"Grab left its edit operator active: {operator!r}")
    if int(renderer.get("last_applied_edit_revision", 0) or 0) != int(
        snapshot["resident_revision"]
    ):
        raise RuntimeError(
            "Grab renderer and service revisions diverged: "
            f"renderer={renderer.get('last_applied_edit_revision')!r}, service={snapshot!r}."
        )
    return {
        "ok": bool(moved and down and up),
        "actual_control": grab_control,
        "visible_control_rail_reset": rail_reset,
        "visible_control_rail_reset_ms": round(rail_reset_ms, 3),
        "input_backend": "scoped_hwnd_messages_no_global_cursor",
        "start": [start_x, start_y],
        "drag_points": drag_points,
        "end": list(end),
        "request": request,
        "acknowledgement": acknowledgement,
        "operator": operator,
        "snapshot": snapshot,
    }


def _perform_actual_history_command(
    app: QApplication,
    mesh_editor_tab: object,
    *,
    form_hwnd: int,
    helper_pid: int,
    command_text: str,
    desktop_observations: list[Mapping[str, object]],
) -> dict[str, object]:
    command = command_text.lower()
    _pump_until(
        app,
        lambda: _button_available(
            form_hwnd,
            command_text,
            expected_pid=helper_pid,
        ),
        timeout_seconds=10.0,
        label=f"actual {command_text} control enabled",
        desktop_observations=desktop_observations,
    )
    cursor = len(_protocol_events(mesh_editor_tab))
    control = _click_button_by_text(
        form_hwnd,
        command_text,
        expected_pid=helper_pid,
    )
    if control.get("ok") is not True:
        raise RuntimeError(f"The real {command_text} control could not be pressed: {control!r}")
    request, acknowledgement = _wait_for_authoritative_request(
        app,
        mesh_editor_tab,
        cursor=cursor,
        event_name="command_request",
        command=command,
        desktop_observations=desktop_observations,
    )
    renderer = _request_renderer_status(
        app,
        mesh_editor_tab,
        label=f"after actual {command_text}",
        desktop_observations=desktop_observations,
    )
    snapshot = _mesh_geometry_snapshot(mesh_editor_tab)
    operator = dict(renderer.get("edit_operator", {})) if isinstance(
        renderer.get("edit_operator"), Mapping
    ) else {}
    if str(operator.get("state", "") or "").lower() != "idle":
        raise RuntimeError(f"{command_text} left the edit operator active: {operator!r}")
    if int(renderer.get("last_applied_edit_revision", 0) or 0) != int(
        snapshot["resident_revision"]
    ):
        raise RuntimeError(
            f"{command_text} renderer and service revisions diverged: "
            f"renderer={renderer.get('last_applied_edit_revision')!r}, service={snapshot!r}."
        )
    return {
        "ok": True,
        "actual_control": control,
        "request": request,
        "acknowledgement": acknowledgement,
        "operator": operator,
        "snapshot": snapshot,
    }


def _exercise_actual_grab_undo_redo(
    app: QApplication,
    mesh_editor_tab: object,
    *,
    form_hwnd: int,
    viewport_hwnd: int,
    helper_pid: int,
    selection: Mapping[str, object],
    desktop_observations: list[Mapping[str, object]],
) -> dict[str, object]:
    attempts = tuple(selection.get("attempts", ()) or ())
    successful = next(
        (
            attempt
            for attempt in reversed(attempts)
            if isinstance(attempt, Mapping) and attempt.get("selection_nonempty") is True
        ),
        None,
    )
    if not isinstance(successful, Mapping):
        raise RuntimeError("Grab proof has no selected on-mesh input point.")
    point = tuple(int(value) for value in tuple(successful.get("point", ()) or ()))
    if len(point) != 2:
        raise RuntimeError(f"Grab proof received an invalid selected point: {point!r}")

    baseline = _mesh_geometry_snapshot(mesh_editor_tab)
    first_grab = _perform_actual_grab(
        app,
        mesh_editor_tab,
        form_hwnd=form_hwnd,
        viewport_hwnd=viewport_hwnd,
        helper_pid=helper_pid,
        start=(point[0], point[1]),
        desktop_observations=desktop_observations,
    )
    first = dict(first_grab["snapshot"])
    first_undo = _perform_actual_history_command(
        app,
        mesh_editor_tab,
        form_hwnd=form_hwnd,
        helper_pid=helper_pid,
        command_text="Undo",
        desktop_observations=desktop_observations,
    )
    undone = dict(first_undo["snapshot"])
    second_grab = _perform_actual_grab(
        app,
        mesh_editor_tab,
        form_hwnd=form_hwnd,
        viewport_hwnd=viewport_hwnd,
        helper_pid=helper_pid,
        start=(point[0], point[1]),
        desktop_observations=desktop_observations,
    )
    second = dict(second_grab["snapshot"])
    second_undo = _perform_actual_history_command(
        app,
        mesh_editor_tab,
        form_hwnd=form_hwnd,
        helper_pid=helper_pid,
        command_text="Undo",
        desktop_observations=desktop_observations,
    )
    second_undone = dict(second_undo["snapshot"])
    redo = _perform_actual_history_command(
        app,
        mesh_editor_tab,
        form_hwnd=form_hwnd,
        helper_pid=helper_pid,
        command_text="Redo",
        desktop_observations=desktop_observations,
    )
    redone = dict(redo["snapshot"])
    gates = {
        "first_grab_changed_geometry": first["sha256"] != baseline["sha256"],
        "first_grab_one_history_entry": first["history_cursor"]
        == baseline["history_cursor"] + 1,
        "first_undo_restored_exact_baseline": undone["sha256"] == baseline["sha256"],
        "first_undo_restored_history_cursor": undone["history_cursor"]
        == baseline["history_cursor"],
        "grab_rearmed_after_undo": second["sha256"] != undone["sha256"],
        "second_grab_one_history_entry": second["history_cursor"]
        == baseline["history_cursor"] + 1,
        "second_undo_restored_exact_baseline": second_undone["sha256"]
        == baseline["sha256"],
        "redo_restored_exact_second_commit": redone["sha256"] == second["sha256"],
        "redo_restored_history_cursor": redone["history_cursor"]
        == second["history_cursor"],
    }
    if not all(gates.values()):
        raise RuntimeError(
            "The actual Grab/Undo/Redo controls violated history invariants: "
            f"gates={gates!r}, baseline={baseline!r}, first={first!r}, "
            f"undone={undone!r}, second={second!r}, redone={redone!r}."
        )
    return {
        "ok": True,
        "actual_controls": True,
        "gates": gates,
        "baseline": baseline,
        "first_grab": first_grab,
        "first_undo": first_undo,
        "second_grab": second_grab,
        "second_undo": second_undo,
        "redo": redo,
    }


def _helper_identity(mesh_editor_tab: object) -> dict[str, object]:
    host = getattr(mesh_editor_tab, "standalone_native_host_frame", None)
    controller = getattr(host, "controller", None)
    configured = getattr(controller, "_configured_executable", None)
    resolution = resolve_mesh_dotnet_experiment_editor(configured)
    helper_path = Path(resolution.resolved_path) if resolution.resolved_path else None
    return {
        "path": str(helper_path or ""),
        "sha256": _sha256(helper_path) if helper_path is not None and helper_path.is_file() else "",
        "source": str(resolution.source or ""),
        "process_id": int(getattr(controller, "process_id", 0) or 0),
        "process_generation": int(getattr(controller, "process_generation", 0) or 0),
        "capabilities": sorted(str(value) for value in getattr(controller, "capabilities", ())),
        "applied_package_path": str(getattr(controller, "applied_package_path", "") or ""),
        "serving_prewarm_placeholder": bool(
            getattr(controller, "serving_prewarm_placeholder", False)
        ),
    }


def _application_identity(helper: Mapping[str, object]) -> dict[str, object]:
    executable = Path(sys.executable).resolve()
    bundle_root_text = str(getattr(sys, "_MEIPASS", "") or "").strip()
    bundle_root = Path(bundle_root_text).resolve() if bundle_root_text else None
    helper_path_text = str(helper.get("path", "") or "").strip()
    helper_path = Path(helper_path_text).resolve() if helper_path_text else None
    return {
        "frozen": bool(getattr(sys, "frozen", False)),
        "executable_path": str(executable),
        "executable_sha256": _sha256(executable) if executable.is_file() else "",
        "bundle_root": str(bundle_root or ""),
        "helper_inside_bundle_root": bool(
            bundle_root is not None
            and helper_path is not None
            and helper_path.is_relative_to(bundle_root)
        ),
    }


def _raise_packaged_smoke_failure(
    exc: Exception,
    *,
    input_timer: QTimer,
    desktop_observations: list[Mapping[str, object]],
    window: object,
    form_hwnd: int,
    viewport_hwnd: int,
    helper_pid: int,
    harness_screen_bounds: tuple[int, int, int, int],
    entry: ArchiveEntry,
    pamt_path: Path,
    mesh_editor_tab: object,
    events: Sequence[tuple[str, Mapping[str, object]]],
    fingerprints_before: Mapping[str, str],
    fingerprint_paths: Sequence[Path],
    output_root: Path,
) -> None:
    input_timer.stop()
    desktop_observations.append(_desktop_input_snapshot())
    try:
        desktop_input = _desktop_input_isolation_evidence(
            desktop_observations,
            forbidden_hwnds=(int(window.winId()), form_hwnd, viewport_hwnd),
            harness_screen_bounds=harness_screen_bounds,
        )
    except Exception as isolation_exc:
        desktop_input = {"ok": False, "error": str(isolation_exc)}
    helper = _helper_identity(mesh_editor_tab)
    failure_diagnostics = {
        "schema": "cdmw_packaged_mesh_editor_controls_failure_v2",
        "error": str(exc),
        "model_path": entry.path,
        "pamt_path": str(pamt_path),
        "helper": helper,
        "application": _application_identity(helper),
        "viewport_shell": _viewport_shell_state(mesh_editor_tab),
        "renderer": _renderer_texture_state(mesh_editor_tab),
        "form_hwnd": form_hwnd,
        "viewport_hwnd": viewport_hwnd,
        "helper_pid": helper_pid,
        "controls": list(_enumerate_child_windows(form_hwnd, expected_pid=helper_pid))
        if form_hwnd and helper_pid
        else [],
        "desktop_input": desktop_input,
        "harness_screen_bounds": list(harness_screen_bounds),
        "status_payload": getattr(mesh_editor_tab, "standalone_dotnet_status_payload", {}),
        "lifecycle_counts": getattr(mesh_editor_tab, "standalone_dotnet_lifecycle_counts", {}),
        "texture_resources_ready_by_role": getattr(
            mesh_editor_tab,
            "standalone_dotnet_texture_resources_ready_by_role",
            {},
        ),
        "material_errors_by_role": getattr(
            mesh_editor_tab, "standalone_dotnet_material_error_by_role", {}
        ),
        "recent_protocol_events": _protocol_events(mesh_editor_tab)[-200:],
        "recent_runtime_events": [
            {"event": event, **fields} for event, fields in events[-200:]
        ],
        "archive_fingerprints_before": dict(fingerprints_before),
        "archive_fingerprints_after": {
            str(path): _sha256(path) for path in fingerprint_paths if path.is_file()
        },
    }
    failure_path = output_root / "failure-diagnostics.json"
    try:
        failure_path.write_text(
            json.dumps(failure_diagnostics, indent=2, sort_keys=True, default=str),
            encoding="utf-8",
        )
    except OSError as write_exc:
        raise RuntimeError(
            f"{exc} Failure diagnostics could not be written: {write_exc}"
        ) from exc
    raise RuntimeError(f"{exc} Failure diagnostics: {failure_path}") from exc


def verify_packaged_mesh_texture_smoke_target(
    window: object,
    app: QApplication,
) -> dict[str, object]:
    """Exercise the real direct Mesh Editor route inside the running app."""

    source_text = os.environ.get("CDMW_GUI_STARTUP_SMOKE_MESH_ASSET", "").strip()
    if not source_text:
        raise RuntimeError(
            "Packaged Mesh Editor smoke requires CDMW_GUI_STARTUP_SMOKE_MESH_ASSET "
            "to name the game root or 0009/0.pamt."
        )
    source = Path(source_text).expanduser().resolve()
    pamt_path = source / "0009" / "0.pamt" if source.is_dir() else source
    if not pamt_path.is_file() or pamt_path.name.casefold() != "0.pamt":
        raise RuntimeError(f"Packaged Mesh Editor smoke could not read PAMT: {pamt_path}")

    entries = tuple(parse_archive_pamt(pamt_path))
    by_path, by_basename, by_extension = _entry_indexes(entries)
    entry = next(iter(by_path.get(_normalized_archive_key(_PACKAGED_TEXTURE_SAMPLE), ())), None)
    if not isinstance(entry, ArchiveEntry):
        raise RuntimeError(
            f"Packaged Mesh Editor smoke sample was not found: {_PACKAGED_TEXTURE_SAMPLE}"
        )

    fingerprint_paths = tuple(
        path
        for path in (
            pamt_path,
            Path(entry.paz_file) if entry.paz_file is not None else None,
        )
        if isinstance(path, Path) and path.is_file()
    )
    fingerprints_before = {str(path): _sha256(path) for path in fingerprint_paths}
    result_path = Path(os.environ.get("CDMW_GUI_STARTUP_SMOKE_RESULT", "")).expanduser()
    output_root = (
        result_path.parent / "mesh-editor-production-smoke"
        if str(result_path)
        else Path(os.environ.get("TEMP", ".")) / "mesh-editor-production-smoke"
    )
    output_root.mkdir(parents=True, exist_ok=True)

    desktop_observations: list[Mapping[str, object]] = [_desktop_input_snapshot()]
    input_timer = QTimer(window)
    input_timer.setInterval(25)

    def sample_desktop_input() -> None:
        if len(desktop_observations) < 8192:
            desktop_observations.append(_desktop_input_snapshot())

    input_timer.timeout.connect(sample_desktop_input)
    input_timer.start()
    events: list[tuple[str, dict[str, object]]] = []
    mesh_editor_tab = window.mesh_editor_tab

    def capture_runtime_event(event: str, fields: dict[str, object]) -> None:
        events.append((event, dict(fields)))

    mesh_editor_tab.runtime_event_requested.connect(capture_runtime_event)
    form_hwnd = viewport_hwnd = helper_pid = 0
    harness_screen_bounds = (0, 0, 0, 0)
    try:
        harness_screen_bounds = _place_window_without_activation(window, app)
        configure_synthetic_archive_context(window, entry)
        window.archive_entries = list(entries)
        window.archive_entries_by_normalized_path = by_path
        window.archive_entries_by_basename = by_basename
        window.archive_entries_by_extension = by_extension
        window.archive_sidecar_entries_by_texture_path = {}
        window.archive_sidecar_entries_by_texture_basename = {}

        window._activate_tool_widget(mesh_editor_tab)
        app.processEvents()
        empty_viewport = _viewport_shell_state(mesh_editor_tab)
        if not (
            empty_viewport["standalone_workspace_current"]
            and empty_viewport["empty_guidance_visible"]
            and empty_viewport["host_visible"]
            and empty_viewport["host_size"][0] >= 160
            and empty_viewport["host_size"][1] >= 120
        ):
            raise RuntimeError(
                f"Mesh Editor did not keep its viewport available before a session: {empty_viewport!r}"
            )

        protocol_cursor = len(_protocol_events(mesh_editor_tab))
        window._launch_archive_mesh_editor_for_entry(entry)
        load_ms = _pump_until(
            app,
            lambda: bool(
                getattr(mesh_editor_tab, "standalone_controller", None) is not None
                and getattr(mesh_editor_tab, "standalone_native_host_frame", None)
                is not None
                and getattr(mesh_editor_tab.standalone_native_host_frame, "controller", None)
                is not None
                and mesh_editor_tab.standalone_native_host_frame.controller.is_running
                and _latest_event(mesh_editor_tab, "ready", cursor=protocol_cursor)
            ),
            timeout_seconds=120.0,
            label="production Mesh Editor session and helper ready",
            desktop_observations=desktop_observations,
        )
        helper = _helper_identity(mesh_editor_tab)
        application = _application_identity(helper)
        helper_pid = int(helper.get("process_id", 0) or 0)
        renderer = _request_renderer_status(
            app,
            mesh_editor_tab,
            label="production Mesh Editor ready",
            desktop_observations=desktop_observations,
        )
        viewport = renderer.get("viewport", {})
        viewport = dict(viewport) if isinstance(viewport, Mapping) else {}
        form_hwnd = int(viewport.get("form_hwnd", 0) or 0)
        viewport_hwnd = int(viewport.get("hwnd", 0) or 0)
        if not form_hwnd or not viewport_hwnd or not helper_pid:
            raise RuntimeError(
                f"The production helper did not publish owned form/viewport handles: {renderer!r}"
            )
        if _window_process_id(form_hwnd) != helper_pid or _window_process_id(viewport_hwnd) != helper_pid:
            raise RuntimeError("Published Mesh Editor HWNDs do not belong to the running helper.")
        viewport_before_controls = _viewport_window_state(viewport_hwnd, helper_pid)
        if not (
            viewport_before_controls["owned"]
            and viewport_before_controls["visible"]
            and viewport_before_controls["nonzero"]
        ):
            raise RuntimeError(
                f"The production D3D11 viewport is not visibly available: {viewport_before_controls!r}"
            )

        textured = _activate_solid_textured_control(
            app,
            mesh_editor_tab,
            form_hwnd=form_hwnd,
            helper_pid=helper_pid,
            desktop_observations=desktop_observations,
        )
        control_continuity = _exercise_actual_control_continuity(
            app,
            mesh_editor_tab,
            form_hwnd=form_hwnd,
            viewport_hwnd=viewport_hwnd,
            helper_pid=helper_pid,
            output_root=output_root,
            desktop_observations=desktop_observations,
        )
        viewport_after_textured = _viewport_window_state(viewport_hwnd, helper_pid)
        capture_state = SimpleNamespace(
            app=app,
            tab=mesh_editor_tab,
            viewport_hwnd=viewport_hwnd,
            production_process_pid=helper_pid,
        )
        capture_path = output_root / "solid-textured-production-viewport.png"
        capture = capture_dotnet_viewport(capture_state, capture_path)
        if capture.get("ok") is not True:
            raise RuntimeError(f"The production textured viewport could not be captured: {capture!r}")
        selection_before = _request_renderer_status(
            app,
            mesh_editor_tab,
            label="before actual Select gesture",
            desktop_observations=desktop_observations,
        )

        selection = _exercise_actual_select_control(
            app,
            mesh_editor_tab,
            form_hwnd=form_hwnd,
            viewport_hwnd=viewport_hwnd,
            helper_pid=helper_pid,
            desktop_observations=desktop_observations,
        )
        selection_capture_path = output_root / "selected-production-viewport.png"
        selection_capture = capture_dotnet_viewport(capture_state, selection_capture_path)
        if selection_capture.get("ok") is not True:
            raise RuntimeError(
                f"The selected production viewport could not be captured: {selection_capture!r}"
            )
        selection_after = _request_renderer_status(
            app,
            mesh_editor_tab,
            label="after actual Select gesture",
            desktop_observations=desktop_observations,
        )
        overlay_before = int(selection_before["committed_selection_overlay_primitives"])
        overlay_after = int(selection_after["committed_selection_overlay_primitives"])
        if overlay_after <= overlay_before:
            raise RuntimeError(
                "Select was acknowledged, but no new committed selection highlight was drawn: "
                f"before={overlay_before}, after={overlay_after}."
            )
        selection["overlay"] = {
            "counter_source": "renderer.live_metrics.geometry_resources",
            "committed_primitives_before": overlay_before,
            "committed_primitives_after": overlay_after,
        }
        selection["capture"] = {**selection_capture, "path": str(selection_capture_path)}
        viewport_after_select = _viewport_window_state(viewport_hwnd, helper_pid)
        grab_history = _exercise_actual_grab_undo_redo(
            app,
            mesh_editor_tab,
            form_hwnd=form_hwnd,
            viewport_hwnd=viewport_hwnd,
            helper_pid=helper_pid,
            selection=selection,
            desktop_observations=desktop_observations,
        )
        history_capture_path = output_root / "grab-redo-production-viewport.png"
        history_capture = capture_dotnet_viewport(capture_state, history_capture_path)
        if history_capture.get("ok") is not True:
            raise RuntimeError(
                f"The Grab/Redo production viewport could not be captured: {history_capture!r}"
            )
        viewport_after_history = _viewport_window_state(viewport_hwnd, helper_pid)
        if not (
            viewport_after_textured["visible"]
            and viewport_after_textured["nonzero"]
            and viewport_after_select["visible"]
            and viewport_after_select["nonzero"]
            and viewport_after_history["visible"]
            and viewport_after_history["nonzero"]
        ):
            raise RuntimeError("The D3D11 viewport disappeared during a real tool/page transition.")

        material_updates = [
            dict(fields)
            for event, fields in events
            if event == "mesh_dotnet_material_state_update"
        ]
        material_failures = [
            dict(fields)
            for event, fields in events
            if event
            in {
                "mesh_dotnet_material_compile_failed",
                "mesh_dotnet_material_state_failed",
                "mesh_dotnet_textured_view_failed",
            }
        ]
        if not material_updates:
            raise RuntimeError("Production Mesh Editor emitted no resident material update.")
        latest_update = material_updates[-1]
        if int(latest_update.get("resource_count", 0) or 0) <= 0:
            raise RuntimeError("Production Mesh Editor compiled zero texture resources.")
        if int(latest_update.get("resource_file_count", 0) or 0) != int(
            latest_update.get("resource_count", 0) or 0
        ):
            raise RuntimeError("Production Mesh Editor compiled a missing texture resource.")
        if material_failures:
            raise RuntimeError(
                f"Production Mesh Editor recorded material failures: {material_failures!r}"
            )

        fingerprints_after = {str(path): _sha256(path) for path in fingerprint_paths}
        archives_unchanged = fingerprints_before == fingerprints_after
        if not archives_unchanged:
            raise RuntimeError("Production Mesh Editor smoke changed a source archive.")

        mesh_editor_tab.show_empty_state("Production Mesh Editor smoke complete.")
        app.processEvents()
        closed_viewport = _viewport_shell_state(mesh_editor_tab)
        if not (
            closed_viewport["standalone_workspace_current"]
            and closed_viewport["empty_guidance_visible"]
            and closed_viewport["host_visible"]
            and closed_viewport["host_size"][0] >= 160
            and closed_viewport["host_size"][1] >= 120
        ):
            raise RuntimeError(
                f"Mesh Editor removed its viewport after closing the session: {closed_viewport!r}"
            )

        input_timer.stop()
        desktop_observations.append(_desktop_input_snapshot())
        desktop_input = _desktop_input_isolation_evidence(
            desktop_observations,
            forbidden_hwnds=(int(window.winId()), form_hwnd, viewport_hwnd),
            harness_screen_bounds=harness_screen_bounds,
        )
        if desktop_input.get("ok") is not True:
            raise RuntimeError(
                f"The production smoke interfered with desktop input isolation: {desktop_input!r}"
            )
        return {
            "schema": "cdmw_packaged_mesh_editor_controls_smoke_v3",
            "read_only": True,
            "production_route": "MainWindow._launch_archive_mesh_editor_for_entry",
            "actual_csharp_controls": True,
            "global_mouse_input_used": False,
            "model_path": entry.path,
            "pamt_path": str(pamt_path),
            "load_ms": round(load_ms, 3),
            "helper": helper,
            "application": application,
            "viewport_availability": {
                "before_session": empty_viewport,
                "before_controls": viewport_before_controls,
                "after_textured": viewport_after_textured,
                "after_select": viewport_after_select,
                "after_grab_history": viewport_after_history,
                "after_close": closed_viewport,
            },
            "control_continuity": control_continuity,
            "solid_textured": textured,
            "select": selection,
            "grab_undo_redo": grab_history,
            "grab_redo_capture": {
                **history_capture,
                "path": str(history_capture_path),
            },
            "capture": {**capture, "path": str(capture_path)},
            "material_update": latest_update,
            "material_update_count": len(material_updates),
            "material_failures": material_failures,
            "lifecycle_counts": dict(mesh_editor_tab.standalone_dotnet_lifecycle_counts),
            "desktop_input": desktop_input,
            "harness_screen_bounds": list(harness_screen_bounds),
            "archive_fingerprints_before": fingerprints_before,
            "archive_fingerprints_after": fingerprints_after,
            "archive_sources_unchanged": archives_unchanged,
        }
    except Exception as exc:
        _raise_packaged_smoke_failure(
            exc,
            input_timer=input_timer,
            desktop_observations=desktop_observations,
            window=window,
            form_hwnd=form_hwnd,
            viewport_hwnd=viewport_hwnd,
            helper_pid=helper_pid,
            harness_screen_bounds=harness_screen_bounds,
            entry=entry,
            pamt_path=pamt_path,
            mesh_editor_tab=mesh_editor_tab,
            events=events,
            fingerprints_before=fingerprints_before,
            fingerprint_paths=fingerprint_paths,
            output_root=output_root,
        )
    finally:
        input_timer.stop()
        mesh_editor_tab.runtime_event_requested.disconnect(capture_runtime_event)
        try:
            if getattr(mesh_editor_tab, "standalone_controller", None) is not None:
                mesh_editor_tab.show_empty_state("Production Mesh Editor smoke stopped.")
                app.processEvents()
        except RuntimeError:
            pass


__all__ = ["verify_packaged_mesh_texture_smoke_target"]
