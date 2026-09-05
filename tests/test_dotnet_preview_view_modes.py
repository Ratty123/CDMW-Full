from __future__ import annotations

import re
from pathlib import Path

from cdmw.models import ModelPreviewRenderSettings
from cdmw.ui.archive_browser.static_replacement_dotnet_presentation import (
    builder_presentation_state,
)
from cdmw.ui.archive_browser.static_replacement_dotnet_view_modes import (
    DOTNET_PREVIEW_VIEW_MODE_DEBUG_MODES,
    DOTNET_PREVIEW_VIEW_MODE_OPTIONS,
    DOTNET_PREVIEW_VIEW_MODES,
    dotnet_preview_material_debug_mode,
    normalize_dotnet_preview_view_mode,
)


ROOT = Path(__file__).resolve().parents[1]
DOTNET_ROOT = ROOT / "tools" / "dotnet_mesh_editor_experiment"

EXPECTED_DEBUG_MODES = {
    "lit": 0,
    "game_outdoor": 0,
    "base_direct": 1,
    "normal": 2,
    "uv_checker": 8,
    "base_alpha": 9,
    "part_id": 10,
    "material_response": 11,
    "layer_mask": 12,
}


def test_dotnet_view_menu_is_an_exact_renderer_backed_allow_list() -> None:
    assert DOTNET_PREVIEW_VIEW_MODE_DEBUG_MODES == EXPECTED_DEBUG_MODES
    assert DOTNET_PREVIEW_VIEW_MODES == tuple(EXPECTED_DEBUG_MODES)
    assert tuple(value for _label, value in DOTNET_PREVIEW_VIEW_MODE_OPTIONS) == DOTNET_PREVIEW_VIEW_MODES
    assert normalize_dotnet_preview_view_mode("specular") == "lit"
    assert normalize_dotnet_preview_view_mode("wireframe") == "lit"
    assert dotnet_preview_material_debug_mode("base_direct") == 1
    assert dotnet_preview_material_debug_mode("unsupported") == 0


def test_builder_sends_the_selected_dotnet_mode_without_legacy_diagnostic_override() -> None:
    for view_mode, debug_mode in EXPECTED_DEBUG_MODES.items():
        state = builder_presentation_state(
            comparison_mode="side_by_side",
            camera=None,
            render_settings=ModelPreviewRenderSettings(
                d3d11_view_mode=view_mode,
                render_diagnostic_mode="wireframe",
                use_textures_by_default=True,
            ),
            grid_visible=True,
            gizmo_visible=True,
            part_pick_enabled=True,
        )
        display = state["display"]
        quality = display["quality"]
        assert display["mode"] == "untextured_wire"
        assert display["material_debug_mode"] == debug_mode
        assert quality["dotnet_view_mode"] == view_mode
        assert quality["d3d11_view_mode"] == view_mode
        assert "render_diagnostic_mode" not in quality






def test_builder_copy_names_the_control_as_a_preview_mode() -> None:
    shell_source = (
        ROOT / "cdmw" / "ui" / "archive_browser" / "static_replacement_dialog_preview_shell.py"
    ).read_text(encoding="utf-8")
    text_source = (
        ROOT / "cdmw" / "ui" / "archive_browser" / "static_replacement_preview_status_state.py"
    ).read_text(encoding="utf-8")
    assert "DOTNET_PREVIEW_VIEW_MODE_OPTIONS" in shell_source
    assert "D3D11_PREVIEW_VIEW_MODES" not in shell_source
    assert '"dotnet_view_label": "Preview mode"' in text_source
    assert "Only renderer-backed modes are listed." in text_source
