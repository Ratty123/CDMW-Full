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
    panel = _repo_source("cdmw/ui/model_preview_gizmo_settings.py")
    dialog = _repo_source("cdmw/ui/model_preview_settings_dialog.py")
    settings_reader = _repo_source("cdmw/ui/archive_browser/preview_settings.py")
    settings_writer = _repo_source("cdmw/ui/shell/settings_persistence.py")
    transport = _repo_source("cdmw/ui/archive_browser/static_replacement_dotnet_presentation.py")

    assert "GizmoPreviewSettingsPanel" in dialog
    assert "settings_changed.connect(self._emit_settings_changed)" in dialog
    assert "saved with Preview Settings" in panel
    assert "dataclasses.asdict(self.archive._current_model_preview_render_settings())" in settings_writer
    assert "schedule_settings_save()" in settings_reader
    assert not (Path(__file__).resolve().parents[1] / "tools/dotnet_mesh_editor_experiment/ExperimentForm.GizmoAppearance.cs").exists()


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
