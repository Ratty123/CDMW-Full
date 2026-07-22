from __future__ import annotations

from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]
DOTNET_ROOT = ROOT / "tools" / "dotnet_mesh_editor_experiment"


def _source(name: str) -> str:
    return (DOTNET_ROOT / name).read_text(encoding="utf-8")


def _source_family(pattern: str) -> str:
    return "\n".join(
        path.read_text(encoding="utf-8")
        for path in sorted(DOTNET_ROOT.glob(pattern))
    )


def test_dotnet_wheel_zoom_is_reversible_and_uses_fit_relative_bounds() -> None:
    policy = _source("CameraZoomPolicy.cs")
    input_source = _source("MeshViewport.Input.cs")
    presentation_source = _source("MeshViewport.Presentation.cs")
    renderer_source = _source("MeshViewport.Renderer.cs")
    split_view_source = _source("MeshViewport.SplitView.cs")
    host_presentation_source = (
        ROOT / "cdmw" / "ui" / "mesh_editor" / "tab_dotnet_presentation.py"
    ).read_text(encoding="utf-8")

    expected_steps = (
        0.1,
        0.25,
        0.5,
        0.75,
        1.0,
        1.5,
        2.0,
        3.0,
        4.0,
        6.0,
        8.0,
        12.0,
        16.0,
        24.0,
        32.0,
        48.0,
        64.0,
    )
    dotnet_step_block = policy.split(
        "ArchiveBrowserZoomSteps =", maxsplit=1
    )[1].split("};", maxsplit=1)[0]

    assert tuple(float(value) for value in re.findall(r"([0-9.]+)f", dotnet_step_block)) == expected_steps
    assert "MathF.Pow(" not in policy
    assert "MinimumFitZoomRatio = 0.1f" in policy
    assert "MaximumFitZoomRatio = 64.0f" in policy
    assert "safeFitZoom * MinimumFitZoomRatio" in policy
    assert "safeFitZoom * MaximumFitZoomRatio" in policy
    assert "delta > 0 ? 1 : -1" in policy
    assert "PreserveWorldPan(" in policy
    assert "projectedPan * (targetZoom / currentZoom)" in policy
    assert "_zoom *= e.Delta > 0 ? 1.1f : 0.9f;" not in input_source
    assert "Math.Clamp(_zoom, 1.0f, 500000.0f)" not in input_source
    assert "CameraZoomPolicy.ApplyZoomFactor(" in presentation_source
    assert "Math.Clamp(_zoom * zoomFactor, 1.0f, 500000.0f)" not in presentation_source
    assert "CameraBoundsForContext" in split_view_source
    assert "context.CameraMinimum" in split_view_source
    assert 'stamped_camera["command_generation"] = generation' in host_presentation_source
    assert 'set(state or {}) == {"camera"}' in host_presentation_source

    wheel_handler = input_source.split(
        "protected override void OnMouseWheel", maxsplit=1
    )[1].split("private static bool IsPanGesture", maxsplit=1)[0]
    assert "InteractionMode" not in wheel_handler
    assert "ApplyWheelZoomToPane(paneId, e.Delta)" in wheel_handler
    assert "FocusPresentationPane(" not in wheel_handler
    assert "PaneMouseEvent(" not in wheel_handler
    assert wheel_handler.count("UpdateGpuViewport();") == 1
    assert renderer_source.count("ForwardRendererMouseWheel(e)") == 2
    assert "handled.Handled = true;" in renderer_source
    assert "MouseWheel += (_, e) => OnMouseWheel(e)" not in renderer_source

    pane_zoom_handler = split_view_source.split(
        "private bool ApplyWheelZoomToPane", maxsplit=1
    )[1].split("private static string NormalizePaneId", maxsplit=1)[0]
    assert "SaveActivePresentationContext();" in pane_zoom_handler
    assert "ApplyWheelZoomToContext(context, delta);" in pane_zoom_handler
    assert "LoadPresentationContext(" not in pane_zoom_handler
    assert "_activeCameraContextId" in pane_zoom_handler
    assert "_zoom = context.Zoom;" in pane_zoom_handler
    assert "_panX = context.PanX;" in pane_zoom_handler
    assert "_panY = context.PanY;" in pane_zoom_handler
    assert "ApplyZoomToContext(context, targetZoom);" in pane_zoom_handler
    assert pane_zoom_handler.count("CameraZoomPolicy.PreserveWorldPan(") == 2
    assert "ApplyZoomToContext(context, targetZoom);" in presentation_source


def test_hidden_runtime_proof_covers_shared_reversible_zoom_policy() -> None:
    soak = _source_family("HeadlessGpuSparseSoak*.cs")
    real_input = (
        ROOT / "tools" / "mesh_harness" / "real_dotnet_input.py"
    ).read_text(encoding="utf-8")

    assert "CameraZoomProof()" in soak
    assert 'gates["placement_and_mesh_edit_wheel_zoom_reversible"]' in soak
    assert 'gates["archive_browser_zoom_step_parity"]' in soak
    assert 'gates["wheel_zoom_panned_anchor_stable"]' in soak
    assert 'gates["side_by_side_wheel_zoom_target_isolated"]' in soak
    assert 'gates["programmatic_zoom_clamped_fit_relative"]' in soak
    assert '["archive_browser_step_table_exact"]' in soak
    assert '["high_resolution_delta_single_step"]' in soak
    assert '["panned_anchor_proof"]' in soak
    assert "UnprojectFramingCenter(" in soak
    assert "CameraWorldPan(" in soak
    assert "_camera_preserves_native_zoom_anchor(" in real_input
    assert '"target_panned_anchor_locked"' in real_input
    assert '"models_remained_visible_and_panned_anchor_locked"' in real_input
    assert '["pane_isolation_proof"]' in soak
    assert 'new[] { 0.0005f, fitZoom, 226.707f }' in soak
    for angle in ("front", "back", "top", "side", "oblique"):
        assert f'("{angle}",' in soak
    assert '["reciprocal_error"]' in soak
