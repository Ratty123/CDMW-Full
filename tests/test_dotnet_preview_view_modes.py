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
        assert display["mode"] == "untextured_faces"
        assert display["material_debug_mode"] == debug_mode
        assert quality["dotnet_view_mode"] == view_mode
        assert quality["d3d11_view_mode"] == view_mode
        assert "render_diagnostic_mode" not in quality


def test_dotnet_renderer_contract_matches_the_python_view_menu() -> None:
    contract_source = (DOTNET_ROOT / "DotNetPreviewViewModes.cs").read_text(encoding="utf-8")
    supported_block = contract_source.split("public static IReadOnlyList<string> Supported", maxsplit=1)[1]
    supported_block = supported_block.split("];", maxsplit=1)[0]
    assert tuple(re.findall(r'"([a-z_]+)"', supported_block)) == DOTNET_PREVIEW_VIEW_MODES

    debug_block = contract_source.split("public static int MaterialDebugMode", maxsplit=1)[1]
    debug_block = debug_block.split("};", maxsplit=1)[0]
    parsed_nonzero = {
        key: int(value)
        for key, value in re.findall(r'"([a-z_]+)"\s*=>\s*(\d+)', debug_block)
    }
    assert parsed_nonzero == {
        key: value for key, value in EXPECTED_DEBUG_MODES.items() if value != 0
    }

    parser_source = (DOTNET_ROOT / "MeshViewport.PresentationSettings.cs").read_text(encoding="utf-8")
    assert 'quality.TryGetProperty("dotnet_view_mode", out _)' in parser_source
    assert "var defaults = _residentPresentationSettings;" in parser_source
    assert "DotNetPreviewViewModes.Normalize(requestedViewMode)" in parser_source
    assert "MaterialDebugMode = DotNetPreviewViewModes.MaterialDebugMode(viewMode);" in parser_source

    proof_source = (DOTNET_ROOT / "HeadlessGpuSparseSoak.ViewModes.cs").read_text(encoding="utf-8")
    soak_source = (DOTNET_ROOT / "HeadlessGpuSparseSoak.cs").read_text(encoding="utf-8")
    assert "foreach (var mode in DotNetPreviewViewModes.Supported)" in proof_source
    assert "viewport.TryRunHeadlessFrame" in proof_source
    assert "viewport.TryCaptureReplacementPng" in proof_source
    assert "outputHashes.Add(sha256)" in proof_source
    assert '["all_non_lit_outputs_change_from_lit"]' in proof_source
    assert 'gates["resident_dotnet_view_modes_rendered"]' in soak_source
    assert 'report["dotnet_view_mode_proof"]' in soak_source


def test_each_exposed_material_debug_mode_has_a_vortice_shader_output() -> None:
    shader_source = (DOTNET_ROOT / "D3D11MaterialShaders.hlsl").read_text(encoding="utf-8")
    for debug_mode in sorted({value for value in EXPECTED_DEBUG_MODES.values() if value > 0}):
        lower = debug_mode - 0.5
        upper = debug_mode + 0.5
        assert f"MaterialDebugMode > {lower:.1f}f && MaterialDebugMode < {upper:.1f}f" in shader_source

    settings_source = (DOTNET_ROOT / "D3D11MaterialViewport.PresentationSettings.cs").read_text(
        encoding="utf-8"
    )
    assert "settings.GameOutdoorApprox" in settings_source


def test_builder_copy_names_the_control_as_a_dotnet_view() -> None:
    shell_source = (
        ROOT / "cdmw" / "ui" / "archive_browser" / "static_replacement_dialog_preview_shell.py"
    ).read_text(encoding="utf-8")
    text_source = (
        ROOT / "cdmw" / "ui" / "archive_browser" / "static_replacement_preview_status_state.py"
    ).read_text(encoding="utf-8")
    assert "DOTNET_PREVIEW_VIEW_MODE_OPTIONS" in shell_source
    assert "D3D11_PREVIEW_VIEW_MODES" not in shell_source
    assert '"dotnet_view_label": ".NET view"' in text_source
    assert "Only renderer-backed modes are listed." in text_source
