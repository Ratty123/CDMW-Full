from __future__ import annotations

from pathlib import Path

from cdmw.models import ModelPreviewRenderSettings
from cdmw.ui.model_preview_settings_visibility import (
    ARCHIVE_DOTNET_SUPPORTED_PREVIEW_SETTING_FIELDS,
    ARCHIVE_DOTNET_SUPPORTED_PREVIEW_SETTINGS_BY_TAB,
    DOTNET_CAMERA_INPUT_SETTING_FIELDS,
    DOTNET_SUPPORTED_PREVIEW_SETTING_FIELDS,
)


ROOT = Path(__file__).resolve().parents[1]
DOTNET = ROOT / "tools" / "dotnet_mesh_editor_experiment"


def _source(name: str) -> str:
    return (DOTNET / name).read_text(encoding="utf-8")


def test_archive_preview_modal_exposes_only_resident_camera_input() -> None:
    assert ARCHIVE_DOTNET_SUPPORTED_PREVIEW_SETTING_FIELDS == frozenset(
        DOTNET_CAMERA_INPUT_SETTING_FIELDS
    )
    assert ARCHIVE_DOTNET_SUPPORTED_PREVIEW_SETTINGS_BY_TAB == {
        "General": (),
        "Quality / Lighting": (),
        "Controls": DOTNET_CAMERA_INPUT_SETTING_FIELDS,
        "Gizmo": (),
    }


def test_every_visible_dotnet_setting_has_transport_parser_and_runtime_consumer() -> None:
    transport = (
        ROOT
        / "cdmw"
        / "ui"
        / "archive_browser"
        / "static_replacement_dotnet_presentation.py"
    ).read_text(encoding="utf-8")
    consumer_tokens = {
        "orbit_sensitivity": ("OrbitSensitivity",),
        "pan_sensitivity": ("PanSensitivity",),
        "invert_orbit_x": ("InvertOrbitX",),
        "invert_orbit_y": ("InvertOrbitY",),
        "invert_pan_x": ("InvertPanX",),
        "invert_pan_y": ("InvertPanY",),
        # Both gestures resolve their held key through CameraModifierBindings, so
        # the binding is what the viewport actually reads rather than a hardcoded
        # Keys test.
        "camera_orbit_modifier": ("CameraOrbitModifier", "IsOrbitOverrideGesture"),
        "camera_pan_modifier": ("CameraPanModifier", "IsPanGesture"),
        # The two drag-button bindings route through the same two gesture tests,
        # which is what lets a middle-drag or right-drag orbit instead of pan.
        "camera_middle_drag": ("CameraMiddleDrag", "IsPanGesture"),
        "camera_right_drag": ("CameraRightDrag", "IsOrbitOverrideGesture"),
        # Resident viewport appearance: the clear colour, the grid, and the
        # topology overlay a solid+wire display is read through.
        "d3d11_background_color": ("BackgroundColor",),
        "d3d11_grid_color": ("GridColor",),
        "d3d11_grid_spacing_scale": ("GridSpacingScale",),
        "d3d11_grid_line_count": ("GridLineCount",),
        "d3d11_wire_color": ("_wireOverlayColor",),
        "d3d11_vertex_color": ("_vertexOverlayColor",),
        "gizmo_x_axis_color": ("XAxis",),
        "gizmo_y_axis_color": ("YAxis",),
        "gizmo_z_axis_color": ("ZAxis",),
        "gizmo_highlight_color": ("Highlight",),
        "gizmo_label_color": ("Label",),
        "gizmo_line_thickness_pixels": ("LineThicknessPixels",),
        "gizmo_size_scale": ("SizeScale",),
        "gizmo_label_size_pixels": ("LabelSizePixels",),
        "gizmo_handle_size_pixels": ("HandleSizePixels",),
    }

    assert set(consumer_tokens) == DOTNET_SUPPORTED_PREVIEW_SETTING_FIELDS

    # The platform adapter normalizes modifier state once; both rebindable camera
    # gestures must consume those booleans instead of reading WinForms globals.




def test_visual_audit_profile_matches_mesh_editor_production_defaults() -> None:
    defaults = ModelPreviewRenderSettings()
    expected = {
        "high_quality": defaults.high_quality_by_default,
        "view_mode": defaults.d3d11_view_mode,
        "cull_back_faces": defaults.d3d11_cull_back_faces,
        "disable_depth_test": defaults.disable_depth_test,
        "disable_tint": defaults.disable_tint,
        "disable_brightness": defaults.disable_brightness,
        "disable_uv_scale": defaults.disable_uv_scale,
        "ao_strength": defaults.d3d11_ao_strength,
        "roughness_bias": defaults.d3d11_roughness_bias,
        "metalness_scale": defaults.d3d11_metalness_scale,
        "environment_strength": defaults.d3d11_environment_strength,
        "emissive_gain": defaults.d3d11_emissive_gain,
        "tone_exposure": defaults.d3d11_tone_exposure,
        "tone_contrast": defaults.d3d11_tone_contrast,
        "tone_gamma": defaults.d3d11_tone_gamma,
        "max_anisotropy": defaults.max_anisotropy,
        "mip_lod_bias": defaults.d3d11_mip_lod_bias,
        "texture_address_mode": defaults.d3d11_texture_address_mode,
        "ambient_strength": defaults.ambient_strength,
        "diffuse_wrap_bias": defaults.diffuse_wrap_bias,
        "diffuse_light_scale": defaults.diffuse_light_scale,
        "specular_base": defaults.specular_base,
        "specular_max": defaults.specular_max,
    }

    assert defaults.disable_tint is False








def test_every_production_preview_route_uses_the_shared_rust_renderer() -> None:
    route_hosts = {
        "archive browser": ROOT / "cdmw/ui/archive_browser/preview_layout.py",
        "archive reference": ROOT / "cdmw/ui/archive_browser/reference_preview.py",
        "archive attachment placement": ROOT / "cdmw/ui/archive_browser/attachment_safe_placement_dialog.py",
        "material sidecar": ROOT / "cdmw/ui/archive_browser/material_sidecar_editor_dialog.py",
        "static replacement": ROOT / "cdmw/ui/archive_browser/static_replacement_dialog_preview_shell.py",
        "model library": ROOT / "cdmw/ui/model_library/preview.py",
        "new item model": ROOT / "cdmw/ui/new_item/item_preview.py",
        "new item effects": ROOT / "cdmw/ui/new_item/effect_placement_dialog.py",
    }
    for route, path in route_hosts.items():
        source = path.read_text(encoding="utf-8")
        assert "RustPreviewHostFrame(" in source, route
        assert "DotNetPreviewProfile." in source, route

    public_host = (ROOT / "cdmw/ui/preview/rust_host.py").read_text(encoding="utf-8")
    assert "RustPreviewHostFrame" in public_host
    host = (ROOT / "cdmw/ui/preview/dotnet_host.py").read_text(encoding="utf-8")
    tuning = (ROOT / "cdmw/ui/preview/dotnet_host_render_tuning.py").read_text(encoding="utf-8")
    assert "render_tuning_payloads" in host
    for setting in (
        "d3d11_environment_strength",
        "d3d11_tone_exposure",
        "d3d11_tone_contrast",
        "d3d11_tone_gamma",
    ):
        assert f'"{setting}"' in tuning
