from __future__ import annotations

from pathlib import Path

from cdmw.models import ModelPreviewRenderSettings, clamp_model_preview_render_settings


GIZMO_FIELDS = (
    "gizmo_x_axis_color",
    "gizmo_y_axis_color",
    "gizmo_z_axis_color",
    "gizmo_highlight_color",
    "gizmo_label_color",
    "gizmo_line_thickness_pixels",
    "gizmo_size_scale",
    "gizmo_label_size_pixels",
    "gizmo_handle_size_pixels",
)


def _source(name: str) -> str:
    root = Path(__file__).resolve().parents[1]
    return (
        root / "tools" / "dotnet_mesh_editor_experiment" / name
    ).read_text(encoding="utf-8")


def _repo_source(path: str) -> str:
    return (Path(__file__).resolve().parents[1] / path).read_text(encoding="utf-8")


def test_gizmo_appearance_controls_are_owned_by_preview_settings_and_main_config() -> None:
    appearance = _source("GizmoAppearance.cs")
    program = _source("Program.cs")
    panel = _repo_source("cdmw/ui/model_preview_gizmo_settings.py")
    dialog = _repo_source("cdmw/ui/model_preview_settings_dialog.py")
    settings_reader = _repo_source("cdmw/ui/archive_browser/preview_settings.py")
    settings_writer = _repo_source("cdmw/ui/shell/settings_persistence.py")
    transport = _repo_source("cdmw/ui/archive_browser/static_replacement_dotnet_presentation.py")
    parser = _source("MeshViewport.GizmoAppearance.cs")
    viewport = _source("MeshViewport.GizmoAppearance.cs")
    renderer = _source("MeshViewport.Renderer.cs")

    assert "GizmoPreviewSettingsPanel" in dialog
    assert "settings_changed.connect(self._emit_settings_changed)" in dialog
    assert "saved with Preview Settings" in panel
    assert "dataclasses.asdict(self._current_model_preview_render_settings())" in settings_writer
    assert "schedule_settings_save()" in settings_reader
    for key in GIZMO_FIELDS:
        assert hasattr(ModelPreviewRenderSettings(), key)
        assert f'"{key}"' in panel
        assert f'"{key}"' in transport
        assert f'"{key}"' in parser
        assert f'"preview/{key}"' in settings_reader
    assert "GizmoAppearancePreferences" not in appearance
    assert "GizmoAppearanceControls()" not in program
    assert not (Path(__file__).resolve().parents[1] / "tools/dotnet_mesh_editor_experiment/ExperimentForm.GizmoAppearance.cs").exists()
    assert "public void SetGizmoAppearance(GizmoAppearance appearance)" in viewport
    assert "viewport.SetGizmoAppearance(_gizmoAppearance)" in renderer


def test_gizmo_preview_settings_normalize_colors_and_sizes() -> None:
    settings = clamp_model_preview_render_settings(
        ModelPreviewRenderSettings(
            gizmo_x_axis_color="#abcdef",
            gizmo_y_axis_color="not-a-color",
            gizmo_line_thickness_pixels=99.0,
            gizmo_size_scale=0.01,
            gizmo_label_size_pixels=100.0,
            gizmo_handle_size_pixels=-5.0,
        )
    )

    assert settings.gizmo_x_axis_color == "#ABCDEF"
    assert settings.gizmo_y_axis_color == ModelPreviewRenderSettings().gizmo_y_axis_color
    assert settings.gizmo_line_thickness_pixels == 6.0
    assert settings.gizmo_size_scale == 0.5
    assert settings.gizmo_label_size_pixels == 32.0
    assert settings.gizmo_handle_size_pixels == 4.0


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


def test_edit_mesh_suppresses_gizmo_rendering_and_interaction() -> None:
    panes = _source("D3D11MaterialViewport.Panes.cs")
    picking = _source("MeshViewport.Gizmo.cs")
    controls = _source("ExperimentForm.Controls.cs")

    assert '_scene.InteractionMode, "mesh_edit"' in panes
    assert "private bool PlacementGizmoEnabled" in picking
    assert "if (!PlacementGizmoEnabled" in picking
    assert "SuppressPlacementGizmoInteraction" in picking
    assert "_viewport.SuppressPlacementGizmoInteraction();" in controls
