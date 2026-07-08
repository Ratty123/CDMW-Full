from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "cdmw" / "ui" / "archive_browser" / "static_replacement_dialog_mesh_edit_callbacks.py"


def test_edit_mesh_toggle_attempts_dotnet_before_native_preview_transition() -> None:
    source = SOURCE.read_text(encoding="utf-8")
    toggle_start = source.index("def _mesh_edit_enabled_toggled")
    toggle_end = source.index("mesh_edit_enabled_checkbox.toggled.connect", toggle_start)
    toggle_source = source[toggle_start:toggle_end]

    assert "start_dotnet()" in toggle_source
    assert "_start_mesh_edit_fallback(\"mesh_edit_dotnet_unavailable\")" in toggle_source
    assert "_start_mesh_edit_fallback(\"mesh_edit_dotnet_disabled\")" in toggle_source
    assert toggle_source.index("start_dotnet()") < toggle_source.index("_start_mesh_edit_fallback(\"mesh_edit_dotnet_unavailable\")")
    assert "_mesh_edit_apply_preview_mode_transition(\"mesh_edit_toggle\")" not in toggle_source


def test_dotnet_ready_and_failed_callbacks_own_embedded_state() -> None:
    source = SOURCE.read_text(encoding="utf-8")

    assert "def _mesh_editor_embedded_dotnet_ready" in source
    assert "def _mesh_editor_embedded_dotnet_failed" in source
    assert '"_mesh_editor_embedded_dotnet_active", True' in source
    assert '"_mesh_editor_embedded_dotnet_active", False' in source
    assert "_start_mesh_edit_fallback(\"mesh_edit_dotnet_fallback\")" in source
    assert "Launching embedded Mesh .NET editor" in source
