from __future__ import annotations

from pathlib import Path


def _source(name: str) -> str:
    root = Path(__file__).resolve().parents[1]
    return (
        root / "tools" / "dotnet_mesh_editor_experiment" / name
    ).read_text(encoding="utf-8")


def test_overlay_appearance_controls_persist_colors_and_bounded_sizes() -> None:
    settings = _source("MeshOverlayColors.cs")
    controls = _source("ExperimentForm.Controls.cs")
    program = _source("Program.cs")
    display_modes = _source("MeshViewport.DisplayModes.cs")
    painting = _source("MeshViewport.Painting.cs")
    wpf = _source("WpfGpuMeshViewport.cs")

    assert 'Schema = "cdmw_mesh_overlay_preferences_v2"' in settings
    assert 'LegacyColorSchema = "cdmw_mesh_overlay_colors_v1"' in settings
    assert '"mesh-editor-overlay-colors.json"' in settings
    assert "Color.FromArgb(0, 0, 0)" in settings
    assert "Color.FromArgb(255, 174, 40)" in settings
    assert "DefaultWireWidthPixels = 1.35f" in settings
    assert "MinimumWireWidthPixels = 1.0f" in settings
    assert "MaximumWireWidthPixels = 6.0f" in settings
    assert "DefaultVertexMarkerSizePixels = 7.0f" in settings
    assert "MinimumVertexMarkerSizePixels = 1.0f" in settings
    assert "MaximumVertexMarkerSizePixels = 24.0f" in settings
    assert '"wire_width_pixels"' in settings
    assert '"vertex_marker_size_pixels"' in settings
    assert "AutomaticXRayWire" in settings
    assert "Color.FromArgb(245, 248, 252)" in settings
    assert "AutomaticXRayVertex" in settings
    assert "Color.FromArgb(255, 88, 214)" in settings
    assert "ColorDialog" in controls
    assert '"Topology appearance"' in controls
    assert 'LabeledControl("Wire width (px)", _wireOverlayWidth)' in controls
    assert 'LabeledControl("Vertex size (px)", _vertexMarkerSize)' in controls
    assert "MeshOverlayPreferences.TrySave" in controls
    assert "_viewport.SetOverlaySettings(_overlaySettings)" in program
    assert "public void SetOverlaySettings(MeshOverlaySettings settings)" in display_modes
    assert "_d3d11Viewport?.SetOverlaySettings(_overlaySettings)" in display_modes
    assert "_gpuViewport?.SetOverlaySettings(_overlaySettings)" in display_modes
    assert "_overlaySettings.Sizing.WireWidthPixels" in painting
    assert "_overlaySettings.Sizing.WireWidthPixels" in wpf


def test_xray_state_reaches_each_render_pane_and_refreshes_the_gpu_viewport() -> None:
    program = _source("Program.cs")
    display_modes = _source("MeshViewport.DisplayModes.cs")
    presentation = _source("MeshViewport.Presentation.cs")
    split_view = _source("MeshViewport.SplitView.cs")
    panes = _source("D3D11MaterialViewport.Panes.cs")

    assert "_viewport.SetXRayEnabled(_xray.Checked)" in program
    assert "if (!_xray.Checked && _previewMode.SelectedIndex == 7)" in program
    assert "public void SetXRayEnabled(bool enabled)" in display_modes
    assert "context.XRay = enabled;" in display_modes
    assert "UpdateGpuViewport();" in display_modes
    assert '"xray" => (false, true, true, true, false)' in display_modes
    assert "public bool XRay { get; set; }" in presentation
    assert "context.XRay," in split_view
    assert "bool XRay," in panes
    assert "_overlayShowXRay = pane.XRay;" in panes


def test_xray_renderer_uses_no_depth_wire_and_vertex_passes_with_hidden_gpu_proof() -> None:
    overlay = _source("D3D11MaterialViewport.Overlay.cs")
    metrics = _source("D3D11MaterialViewport.Metrics.cs")
    selection = _source("MeshViewport.SelectionPicking.cs")
    headless = _source("HeadlessGpuSparseSoak.cs")

    no_depth = overlay.index("_overlayCommandDepthMode = 1;")
    xray_wire = overlay.index("DrawD3D11WireOverlay();", no_depth)
    xray_vertices = overlay.index("QueueD3D11VertexOverlay();", xray_wire)
    assert no_depth < xray_wire < xray_vertices
    assert "_xRayWireNoDepthDrawCount++" in overlay
    assert "_xRayVertexNoDepthPassCount++" in overlay
    assert '["xray_wire_no_depth_draws"]' in metrics
    assert '["xray_vertex_no_depth_passes"]' in metrics
    assert "!ShowXRay" in selection
    assert "ApplyXRayOverlayProof" in headless
    assert 'gates["xray_overlay_draws_wire_and_vertices_without_depth"]' in headless
    assert 'gates["configurable_wire_width_and_vertex_size"]' in headless
    assert '["automatic_palette_active"]' in headless
    assert '["configured_sizing_active"]' in headless
