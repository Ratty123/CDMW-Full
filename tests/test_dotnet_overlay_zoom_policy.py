from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DOTNET_ROOT = ROOT / "tools" / "dotnet_mesh_editor_experiment"


def _source(name: str) -> str:
    return (DOTNET_ROOT / name).read_text(encoding="utf-8")


def _source_family(pattern: str) -> str:
    return "\n".join(
        path.read_text(encoding="utf-8")
        for path in sorted(DOTNET_ROOT.glob(pattern))
    )


def test_dotnet_vertex_and_wire_overlays_use_fit_relative_zoom() -> None:
    settings = _source("MeshOverlayColors.cs")
    policy = _source("FitRelativeOverlayPolicy.cs")
    camera_policy = _source("CameraZoomPolicy.cs")
    overlay = _source("D3D11MaterialViewport.Overlay.cs")
    metrics = _source("D3D11MaterialViewport.Metrics.cs")

    assert "FitZoomForSceneSize" in camera_policy
    assert "CameraZoomPolicy.FitRelativeRatio(currentZoom, fitZoom)" in policy
    assert "DefaultVertexMarkerSizePixels = 7.0f" in settings
    assert "MinimumVertexMarkerSizePixels = 1.0f" in settings
    assert "MinimumVertexMarkerSizePixels = 2.0f" in policy
    assert "MinimumWireOpacityScale = 0.2f" in policy
    assert "Math.Min(MinimumVertexMarkerSizePixels, normalizedFitSize)" in policy
    assert overlay.count("FitRelativeOverlayPolicy.ForCamera(_camera, _overlaySettings.Sizing)") == 2
    assert "overlayStyle.VertexMarkerSizePixels" in overlay
    assert "overlayStyle.WireOpacityScale" in overlay
    assert "lineWidthPixels: _overlaySettings.Sizing.WireWidthPixels" in overlay
    assert "SelectedVertexMarkerRadiusPixels = 7.0f" in overlay
    assert "ScaleOverlayAlpha(" in overlay
    assert '["fit_relative_overlay_zoom_ratio"] = overlayStyle.ZoomRatio' in metrics
    assert '["vertex_marker_size_pixels"] = overlayStyle.VertexMarkerSizePixels' in metrics
    assert '["vertex_marker_fit_size_pixels"] = _overlaySettings.Sizing.VertexMarkerSizePixels' in metrics
    assert '["wire_overlay_opacity_scale"] = overlayStyle.WireOpacityScale' in metrics
    assert '["wire_overlay_width_pixels"] = _overlaySettings.Sizing.WireWidthPixels' in metrics


def test_hidden_gpu_proof_covers_fit_relative_overlay_boundaries() -> None:
    soak = _source_family("HeadlessGpuSparseSoak*.cs")

    assert "FitRelativeOverlayProof()" in soak
    assert 'gates["fit_relative_vertex_markers_and_wire"]' in soak
    assert 'gates["configurable_wire_width_and_vertex_size"]' in soak
    assert 'report["fit_relative_overlay_proof"]' in soak
    assert 'new[] { 0.0005f, fitZoom, 226.707f }' in soak
    assert '["expected_rows_exact"] = expectedRowsExact' in soak
    assert '["fit_scale_independent"] = fitScaleIndependent' in soak
    assert '["minimum_vertex_marker_size_pixels"]' in soak
    assert '["minimum_wire_opacity_scale"]' in soak
    assert "WireWidthPixels: 2.75f" in soak
    assert "VertexMarkerSizePixels: 11.0f" in soak
    for ratio in ("0.1f", "0.25f", "0.5f", "0.75f", "1.0f", "1.5f", "64.0f"):
        assert f"({ratio}," in soak
