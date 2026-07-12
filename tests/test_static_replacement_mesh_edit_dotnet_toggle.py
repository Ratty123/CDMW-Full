from __future__ import annotations

import ast
from pathlib import Path
from types import SimpleNamespace

from cdmw.ui.archive_browser.static_replacement_mesh_edit_selection import (
    _mesh_editor_embedded_dotnet_failed,
    _mesh_editor_embedded_dotnet_ready,
    _stop_legacy_native_preview_after_dotnet_ready,
)
from cdmw.ui.archive_browser.static_replacement_mesh_edit_controls_history import (
    _mesh_edit_control_runtime_state,
)
from tests.static_replacement_source_support import static_replacement_callback_implementation_source


ROOT = Path(__file__).resolve().parents[1]
MESH_OWNER_ROOT = ROOT / "cdmw" / "ui" / "archive_browser"
CALLBACK_SOURCE = ROOT / "cdmw" / "ui" / "archive_browser" / "static_replacement_dialog_callback_factories.py"


def _function_source(owner: str, function_name: str) -> str:
    source = (MESH_OWNER_ROOT / owner).read_text(encoding="utf-8")
    tree = ast.parse(source)
    node = next(
        candidate
        for candidate in tree.body
        if isinstance(candidate, ast.FunctionDef) and candidate.name == function_name
    )
    return ast.get_source_segment(source, node) or ""


def test_edit_mesh_toggle_has_no_legacy_preview_fallback() -> None:
    toggle_source = _function_source(
        "static_replacement_mesh_edit_selection.py", "_mesh_edit_enabled_toggled"
    )

    assert "start_dotnet()" in toggle_source
    assert '"_mesh_editor_embedded_stop_native_d3d11_preview"' not in toggle_source
    assert "stop_native_preview()" not in toggle_source
    assert "_start_mesh_edit_fallback" not in toggle_source
    assert "preview cannot start" in toggle_source
    assert "preview is disabled by configuration" in toggle_source
    assert "_mesh_edit_apply_preview_mode_transition(\"mesh_edit_toggle\")" not in toggle_source


def test_dotnet_edit_hides_legacy_toolbar_and_qt_controls_owned_by_dotnet() -> None:
    refresh_source = _function_source(
        "static_replacement_mesh_edit_controls_history.py",
        "_mesh_edit_control_runtime_state",
    )

    assert 'dotnet_state in {"launching", "ready", "closing"}' in refresh_source
    assert "dotnet_owns_or_is_starting" in refresh_source
    assert "and not dotnet_owns_or_is_starting" in refresh_source
    assert "classic_toolbar_enabled" in refresh_source
    assert "_mesh_editor_embedded_set_controls_visible" in refresh_source
    assert "_mesh_editor_legacy_preview_rows" in refresh_source
    assert "legacy_preview_rows_visible" in refresh_source
    assert "mesh_edit_dotnet_toolbar_ownership" in refresh_source


def test_preview_shell_groups_legacy_top_rows_under_hideable_widgets() -> None:
    source = (MESH_OWNER_ROOT / "static_replacement_dialog_preview_shell.py").read_text(
        encoding="utf-8"
    )

    assert 'legacy_preview_controls_widget.setObjectName("MeshAlignmentLegacyPreviewControls")' in source
    assert 'legacy_preview_camera_widget.setObjectName("MeshAlignmentLegacyPreviewCameraControls")' in source
    assert "preview_header.addWidget(legacy_preview_controls_widget)" in source
    assert "preview_header.addWidget(legacy_preview_camera_widget)" in source
    assert '"_mesh_editor_legacy_preview_rows"' in source


def test_ready_dotnet_runtime_hides_all_legacy_qt_control_surfaces() -> None:
    class _Widget:
        def __init__(self) -> None:
            self.visible = None
            self.enabled = None

        def setVisible(self, value: bool) -> None:
            self.visible = bool(value)

        def setEnabled(self, value: bool) -> None:
            self.enabled = bool(value)

        def isChecked(self) -> bool:
            return True

    toolbar = _Widget()
    preview_controls_row = _Widget()
    preview_camera_row = _Widget()
    embedded_visibility: list[bool] = []
    dialog = SimpleNamespace(
        _mesh_editor_embedded_dotnet_state="ready",
        _mesh_editor_embedded_dotnet_active=True,
        _mesh_editor_embedded_set_controls_visible=embedded_visibility.append,
        _mesh_editor_use_embedded_dotnet_viewport=True,
        _mesh_editor_dotnet_available=True,
        _mesh_editor_legacy_preview_rows=(preview_controls_row, preview_camera_row),
    )
    state = SimpleNamespace(
        dialog=dialog,
        mesh_edit_group=_Widget(),
        mesh_edit_supported=True,
        mesh_edit_enabled_checkbox=_Widget(),
        classic_mesh_edit_toolbar=toolbar,
    )
    callbacks = SimpleNamespace(
        _mesh_edit_worker_active=lambda: False,
        _mesh_edit_can_edit_scope=lambda: (True, ""),
        _alignment_d3d11_process_active=lambda: False,
        _embedded_dotnet_parent_hwnd=lambda: 123,
        _record_mesh_edit_event=lambda *_args, **_kwargs: None,
    )

    _mesh_edit_control_runtime_state(state, callbacks)

    assert toolbar.visible is False
    assert toolbar.enabled is False
    assert preview_controls_row.visible is False
    assert preview_camera_row.visible is False
    assert embedded_visibility == [False]

    dialog._mesh_editor_embedded_dotnet_state = "closing"
    dialog._mesh_editor_embedded_dotnet_active = False
    _mesh_edit_control_runtime_state(state, callbacks)

    assert preview_controls_row.visible is True
    assert preview_camera_row.visible is True

    dialog._mesh_editor_embedded_dotnet_state = "failed"
    _mesh_edit_control_runtime_state(state, callbacks)

    assert preview_controls_row.visible is True
    assert preview_camera_row.visible is True


def test_dotnet_toolbar_ownership_does_not_require_qprocess_symbol() -> None:
    helper_source = _function_source(
        "static_replacement_mesh_edit_controls_history.py",
        "_alignment_d3d11_process_active",
    )

    assert "QProcess" not in helper_source
    assert "int(process_state) != 0" in helper_source


def test_dotnet_launch_can_stop_native_d3d11_preview_process() -> None:
    source = static_replacement_callback_implementation_source(ROOT)

    assert "_alignment_d3d11_stop_process" in source
    assert "setattr(_state.dialog, '_mesh_editor_embedded_stop_native_d3d11_preview', _state._alignment_d3d11_stop_process)" in source


def test_alignment_native_preview_queue_is_unconditionally_disabled() -> None:
    source = (MESH_OWNER_ROOT / "static_replacement_dialog_callbacks_d3d11_package_lifecycle_part_01.py").read_text(
        encoding="utf-8"
    )
    start = source.index("def _queue_alignment_d3d11_preview(")
    body = source[start : source.index("_state._queue_alignment_d3d11_preview =", start)]

    assert "reason='dotnet_authoritative'" in body
    assert "_mesh_editor_auto_dotnet_preview" not in body
    assert "_alignment_d3d11_queue_preview_request_helper" not in body
    assert "_safe_start_alignment_timer" not in body


def test_edit_mesh_off_keeps_dotnet_resident_and_switches_to_placement() -> None:
    toggle_source = _function_source(
        "static_replacement_mesh_edit_selection.py", "_mesh_edit_enabled_toggled"
    )

    assert "stop_dotnet" not in toggle_source
    assert '_mesh_editor_embedded_set_scene_state' in toggle_source
    assert 'interaction_mode="placement"' in toggle_source
    assert 'interaction_mode="mesh_edit"' in toggle_source
    assert "_callbacks._mesh_editor_finalize_edit_mode_exit" in toggle_source


def test_dotnet_ready_and_failed_callbacks_own_embedded_state() -> None:
    source = (MESH_OWNER_ROOT / "static_replacement_mesh_edit_selection.py").read_text(
        encoding="utf-8"
    )

    assert "def _mesh_editor_embedded_dotnet_ready" in source
    assert "def _mesh_editor_embedded_dotnet_failed" in source
    assert '"_mesh_editor_embedded_dotnet_active", True' in source
    assert '"_mesh_editor_embedded_dotnet_active", False' in source
    assert "def _start_mesh_edit_fallback" not in source
    assert '"mesh_edit_dotnet_failed"' in source
    assert "Launching embedded Mesh .NET editor" in source


def test_dotnet_ready_stops_legacy_native_preview_once() -> None:
    stopped: list[str] = []
    events: list[str] = []
    dialog = SimpleNamespace(
        _mesh_editor_embedded_stop_native_d3d11_preview=lambda: stopped.append("stopped")
    )
    state = SimpleNamespace(dialog=dialog)
    callbacks = SimpleNamespace(
        _record_mesh_edit_event=lambda event, **_payload: events.append(event),
        _refresh_mesh_edit_controls=lambda: None,
    )
    callbacks._stop_legacy_native_preview_after_dotnet_ready = lambda: (
        _stop_legacy_native_preview_after_dotnet_ready(state, callbacks)
    )

    _mesh_editor_embedded_dotnet_ready(state, callbacks)
    _mesh_editor_embedded_dotnet_ready(state, callbacks)

    assert stopped == ["stopped"]
    assert events.count("mesh_edit_legacy_native_preview_stopped") == 1
    assert dialog._mesh_editor_embedded_dotnet_active is True
    assert dialog._mesh_editor_embedded_dotnet_state == "ready"


def test_dotnet_failure_keeps_preview_unavailable_without_legacy_fallback() -> None:
    stopped: list[str] = []
    visibility: list[bool] = []
    statuses: list[tuple[str, bool]] = []
    events: list[tuple[str, dict[str, object]]] = []
    dialog = SimpleNamespace(
        _mesh_editor_embedded_stop_native_d3d11_preview=lambda: stopped.append("stopped")
    )
    state = SimpleNamespace(
        dialog=dialog,
        controls_panel=SimpleNamespace(setVisible=lambda value: visibility.append(bool(value))),
        self=SimpleNamespace(
            set_status_message=lambda message, error=False: statuses.append((str(message), bool(error)))
        ),
    )
    callbacks = SimpleNamespace(
        _record_mesh_edit_event=lambda event, **payload: events.append((str(event), dict(payload))),
        _refresh_mesh_edit_controls=lambda: None,
    )

    _mesh_editor_embedded_dotnet_failed(state, callbacks, "launch_failed", "boom")

    assert stopped == []
    assert visibility == [True]
    assert statuses == [("Mesh .NET preview failed: boom", True)]
    assert events == [("mesh_edit_dotnet_failed", {"reason": "launch_failed", "diagnostics": "boom"})]
    assert dialog._mesh_editor_embedded_dotnet_active is False
    assert dialog._mesh_editor_embedded_dotnet_state == "failed"


def test_dotnet_edit_uses_full_width_then_failure_restores_setup_panel() -> None:
    visibility: list[bool] = []
    state = SimpleNamespace(
        controls_panel=SimpleNamespace(setVisible=lambda value: visibility.append(bool(value))),
        dialog=SimpleNamespace(),
        _mesh_edit_apply_preview_mode_transition=lambda _reason: None,
    )
    callbacks = SimpleNamespace(
        _stop_legacy_native_preview_after_dotnet_ready=lambda: None,
        _record_mesh_edit_event=lambda *_args, **_kwargs: None,
        _refresh_mesh_edit_controls=lambda: None,
    )
    state.self = SimpleNamespace(set_status_message=lambda *_args, **_kwargs: None)

    _mesh_editor_embedded_dotnet_ready(state, callbacks)
    _mesh_editor_embedded_dotnet_failed(state, callbacks, "test", "failed")

    assert visibility == [False, True]


def test_texture_reapply_reads_latest_original_reference_model() -> None:
    source = static_replacement_callback_implementation_source(ROOT)

    assert "def _current_original_reference_preview_model" in source
    assert "original_reference_preview_model=_state._current_original_reference_preview_model()" in source
    assert "has_original_reference_model=_state._current_original_reference_preview_model() is not None" in source


def test_dotnet_exit_always_queues_material_texture_restore_after_preview_transition() -> None:
    restore_source = _function_source(
        "static_replacement_mesh_edit_session.py",
        "_mesh_editor_queue_post_edit_textured_preview_rebuild",
    )

    assert "_state._queue_texture_preview_refresh()" in restore_source
    assert restore_source.index("_mesh_edit_apply_preview_mode_transition") < restore_source.index(
        "_queue_texture_preview_refresh"
    )
