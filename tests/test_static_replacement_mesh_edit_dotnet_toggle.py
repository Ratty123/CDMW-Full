from __future__ import annotations

import ast
from pathlib import Path
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


def test_edit_mesh_toggle_attempts_dotnet_before_native_preview_transition() -> None:
    toggle_source = _function_source(
        "static_replacement_mesh_edit_selection.py", "_mesh_edit_enabled_toggled"
    )

    assert "start_dotnet()" in toggle_source
    assert '"_mesh_editor_embedded_stop_native_d3d11_preview"' not in toggle_source
    assert "stop_native_preview()" not in toggle_source
    assert "_start_mesh_edit_fallback(\"mesh_edit_dotnet_unavailable\")" in toggle_source
    assert "_start_mesh_edit_fallback(\"mesh_edit_dotnet_disabled\")" in toggle_source
    assert toggle_source.index("start_dotnet()") < toggle_source.index("_start_mesh_edit_fallback(\"mesh_edit_dotnet_unavailable\")")
    assert "_mesh_edit_apply_preview_mode_transition(\"mesh_edit_toggle\")" not in toggle_source


def test_dotnet_launching_ready_and_closing_hide_classic_toolbar() -> None:
    refresh_source = _function_source(
        "static_replacement_mesh_edit_controls_history.py",
        "_mesh_edit_control_runtime_state",
    )

    assert 'dotnet_state in {"launching", "ready", "closing"}' in refresh_source
    assert "dotnet_owns_or_is_starting" in refresh_source
    assert "not dotnet_owns_or_is_starting" in refresh_source
    assert "mesh_edit_dotnet_toolbar_ownership" in refresh_source


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


def test_dotnet_close_defers_mesh_finalize_until_process_finishes() -> None:
    toggle_source = _function_source(
        "static_replacement_mesh_edit_selection.py", "_mesh_edit_enabled_toggled"
    )

    assert "bool(stop_dotnet())" in toggle_source
    assert toggle_source.index("bool(stop_dotnet())") < toggle_source.index(
        "_callbacks._mesh_editor_finalize_edit_mode_exit"
    )
    assert "_callbacks._refresh_mesh_edit_controls()\n            return" in toggle_source


def test_dotnet_ready_and_failed_callbacks_own_embedded_state() -> None:
    source = (MESH_OWNER_ROOT / "static_replacement_mesh_edit_selection.py").read_text(
        encoding="utf-8"
    )

    assert "def _mesh_editor_embedded_dotnet_ready" in source
    assert "def _mesh_editor_embedded_dotnet_failed" in source
    assert '"_mesh_editor_embedded_dotnet_active", True' in source
    assert '"_mesh_editor_embedded_dotnet_active", False' in source
    assert "_start_mesh_edit_fallback(\"mesh_edit_dotnet_fallback\")" in source
    assert "Launching embedded Mesh .NET editor" in source


def test_texture_reapply_reads_latest_original_reference_model() -> None:
    source = static_replacement_callback_implementation_source(ROOT)

    assert "def _current_original_reference_preview_model" in source
    assert "original_reference_preview_model=_state._current_original_reference_preview_model()" in source
    assert "has_original_reference_model=_state._current_original_reference_preview_model() is not None" in source
