from __future__ import annotations

from pathlib import Path


def _source(name: str) -> str:
    root = Path(__file__).resolve().parents[1]
    return (
        root / "tools" / "dotnet_mesh_editor_experiment" / name
    ).read_text(encoding="utf-8")


def test_gizmo_appearance_controls_apply_live_and_persist_to_local_config() -> None:
    appearance = _source("GizmoAppearance.cs")
    controls = _source("ExperimentForm.GizmoAppearance.cs")
    program = _source("Program.cs")
    viewport = _source("MeshViewport.GizmoAppearance.cs")
    renderer = _source("MeshViewport.Renderer.cs")

    assert 'Schema = "cdmw_mesh_gizmo_appearance_v1"' in appearance
    assert '"mesh-editor-gizmo-appearance.json"' in appearance
    for key in (
        "x_axis_color",
        "y_axis_color",
        "z_axis_color",
        "highlight_color",
        "label_color",
        "line_thickness_pixels",
        "size_scale",
        "label_size_pixels",
        "handle_size_pixels",
    ):
        assert f'"{key}"' in appearance
    assert '"Gizmo appearance"' in controls
    assert '"Font size (px)"' in controls
    assert "ValueChanged +=" in controls
    assert "GizmoAppearancePreferences.TrySave" in controls
    assert "GizmoAppearancePreferences.Load()" in controls
    assert "_viewport.SetGizmoAppearance(_gizmoAppearance)" in program
    assert "public void SetGizmoAppearance(GizmoAppearance appearance)" in viewport
    assert "viewport.SetGizmoAppearance(_gizmoAppearance)" in renderer


def test_gizmo_rendering_and_picking_share_customized_geometry() -> None:
    appearance = _source("GizmoAppearance.cs")
    overlay = _source("D3D11MaterialViewport.Gizmo.cs")
    picking = _source("MeshViewport.Gizmo.cs")
    metrics = _source("D3D11MaterialViewport.Metrics.cs")

    assert "ScaleLength(float baseLength)" in appearance
    assert "_gizmoAppearance.ScaleLength(" in overlay
    assert "_gizmoAppearance.ScaleLength(" in picking
    assert "lineWidthPixels: _gizmoAppearance.LineThicknessPixels" in overlay
    assert "_gizmoAppearance.LabelSizePixels" in overlay
    assert "_gizmoAppearance.HandleSizePixels" in overlay
    assert "GizmoLineHitTolerancePixels" in picking
    assert "_gizmoAppearance.LabelSizePixels" in picking
    assert "_gizmoAppearance.HandleSizePixels" in picking
    assert '["gizmo_overlay_draws"]' in metrics
    assert '["gizmo_line_thickness_pixels"]' in metrics
