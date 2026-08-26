"""Wireframe and vertex colours belong to Preview Settings.

The untextured solid renders blue-grey and the topology overlay drew close
enough to it that the wire melted into the surface. The colours existed, but
only inside the Edit Mesh colour buttons, so a reader who was previewing rather
than editing had no way to reach them.

These pin the whole lane: the field and its normalisation, the panel control,
both persistence paths, the presentation payload the viewport actually reads,
and the C# reader plus the precedence that keeps an in-editor choice from being
overwritten by the next republish.
"""

from __future__ import annotations

import dataclasses
from pathlib import Path

from cdmw.models import ModelPreviewRenderSettings, clamp_model_preview_render_settings
from cdmw.ui.model_preview_gizmo_settings import GIZMO_COLOR_SETTING_FIELDS
from cdmw.ui.model_preview_settings_visibility import (
    DOTNET_GIZMO_APPEARANCE_SETTING_FIELDS,
)


REPO_ROOT = Path(__file__).resolve().parents[1]
OVERLAY_COLOR_FIELDS = ("d3d11_wire_color", "d3d11_vertex_color")


def _repo_source(path: str) -> str:
    return (REPO_ROOT / path).read_text(encoding="utf-8")


def _dotnet_source(name: str) -> str:
    return (REPO_ROOT / "tools" / "dotnet_mesh_editor_experiment" / name).read_text(
        encoding="utf-8"
    )


def test_defaults_match_the_renderer_so_an_unset_preference_changes_nothing() -> None:
    defaults = ModelPreviewRenderSettings()
    overlay_defaults = _dotnet_source("MeshOverlayColors.cs")

    assert defaults.d3d11_wire_color == "#000000"
    assert defaults.d3d11_vertex_color == "#FFAE28"
    # MeshOverlayColors.Default: Wire (0,0,0), Vertex (255,174,40) == #FFAE28.
    assert "Color.FromArgb(0, 0, 0)" in overlay_defaults
    assert "Color.FromArgb(255, 174, 40)" in overlay_defaults


def test_malformed_overlay_colors_fall_back_instead_of_reaching_the_renderer() -> None:
    defaults = ModelPreviewRenderSettings()
    settings = clamp_model_preview_render_settings(
        ModelPreviewRenderSettings(
            d3d11_wire_color="not-a-color",
            d3d11_vertex_color="#12ab",
        )
    )

    assert settings.d3d11_wire_color == defaults.d3d11_wire_color
    assert settings.d3d11_vertex_color == defaults.d3d11_vertex_color


def test_valid_overlay_colors_are_normalized_to_uppercase_hex() -> None:
    settings = clamp_model_preview_render_settings(
        ModelPreviewRenderSettings(
            d3d11_wire_color="#ff00aa",
            d3d11_vertex_color="#00ccFF",
        )
    )

    assert settings.d3d11_wire_color == "#FF00AA"
    assert settings.d3d11_vertex_color == "#00CCFF"


def test_fields_exist_on_the_settings_dataclass() -> None:
    names = {field.name for field in dataclasses.fields(ModelPreviewRenderSettings)}

    assert set(OVERLAY_COLOR_FIELDS) <= names


def test_panel_offers_a_control_and_the_tab_lists_the_fields() -> None:
    panel = _repo_source("cdmw/ui/model_preview_gizmo_settings.py")

    for field in OVERLAY_COLOR_FIELDS:
        assert field in GIZMO_COLOR_SETTING_FIELDS, f"{field} is not a panel colour field"
        assert field in DOTNET_GIZMO_APPEARANCE_SETTING_FIELDS
    assert '("d3d11_wire_color", "Wireframe color")' in panel
    assert '("d3d11_vertex_color", "Vertex marker color")' in panel


def test_both_persistence_paths_round_trip_the_fields() -> None:
    reader = _repo_source("cdmw/ui/archive_browser/preview_settings.py")
    settings_tab = _repo_source("cdmw/ui/settings_tab.py")

    for field in OVERLAY_COLOR_FIELDS:
        assert f'"preview/{field}"' in reader, f"{field} is never read back"
        assert f'self.settings.setValue("preview/{field}"' in settings_tab, (
            f"{field} is never written"
        )
        assert f'"preview/{field}"' in settings_tab


def test_presentation_payload_carries_the_colors_to_the_viewport() -> None:
    host = _repo_source("cdmw/ui/preview/dotnet_host.py")
    tuning = _repo_source("cdmw/ui/preview/dotnet_host_render_tuning.py")
    transport = _repo_source(
        "cdmw/ui/archive_browser/static_replacement_dotnet_presentation.py"
    )
    change_detection = _repo_source("cdmw/ui/archive_browser/preview_settings_state.py")

    for field in OVERLAY_COLOR_FIELDS:
        assert "render_tuning_payloads" in host
        assert f'"{field}": str(getattr(settings, "{field}"' in tuning, (
            f"{field} never reaches the presentation quality payload"
        )
        assert f'"{field}"' in transport, f"{field} is not forwarded by the Builder"
        assert f'"{field}"' in change_detection, (
            f"a change to {field} would not re-tune the resident render"
        )


def test_viewport_reads_the_keys_and_only_pushes_a_changed_color() -> None:
    presentation = _dotnet_source("MeshViewport.PresentationSettings.cs")

    assert "ApplyOverlayColorsFromPresentation(quality)" in presentation
    assert 'PresentationOverlayColor(quality, "d3d11_wire_color"' in presentation
    assert 'PresentationOverlayColor(quality, "d3d11_vertex_color"' in presentation
    # The host republishes after every accepted frame, so an unconditional apply
    # would invalidate the viewport once per frame.
    assert "if (wire == current.Wire && vertex == current.Vertex)" in presentation


def test_an_edit_mesh_color_choice_outranks_preview_settings_for_the_session() -> None:
    presentation = _dotnet_source("MeshViewport.PresentationSettings.cs")
    controls = _dotnet_source("ExperimentForm.Controls.cs") + _dotnet_source(
        "ExperimentForm.AppearanceControls.cs"
    )

    assert "internal void PinOverlayColorsFromReader()" in presentation
    assert "if (_overlayColorsPinnedByReader)" in presentation
    # Both the colour picker and the reset button must pin, or the next
    # republish silently reverts what the reader just chose.
    assert controls.count("_viewport.PinOverlayColorsFromReader();") == 2
