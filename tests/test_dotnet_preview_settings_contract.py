from __future__ import annotations

from pathlib import Path

from cdmw.ui.model_preview_settings_visibility import (
    DOTNET_SUPPORTED_PREVIEW_SETTING_FIELDS,
)


ROOT = Path(__file__).resolve().parents[1]
DOTNET = ROOT / "tools" / "dotnet_mesh_editor_experiment"


def _source(name: str) -> str:
    return (DOTNET / name).read_text(encoding="utf-8")


def test_every_visible_dotnet_setting_has_transport_parser_and_runtime_consumer() -> None:
    transport = (
        ROOT
        / "cdmw"
        / "ui"
        / "archive_browser"
        / "static_replacement_dotnet_presentation.py"
    ).read_text(encoding="utf-8")
    parser = _source("MeshViewport.PresentationSettings.cs")
    renderer = "\n".join(
        (
            _source("D3D11MaterialViewport.PresentationSettings.cs"),
            _source("D3D11MaterialViewport.Panes.cs"),
            _source("D3D11MaterialViewport.cs"),
            _source("D3D11MaterialShaders.hlsl"),
            _source("MeshViewport.Input.cs"),
            _source("MeshViewport.Presentation.cs"),
        )
    )
    consumer_tokens = {
        "use_textures_by_default": ("TexturesEnabled",),
        "high_quality_by_default": ("HighQuality",),
        "disable_all_support_maps": ("DisableAllSupportMaps",),
        "disable_normal_map": ("DisableNormalMap",),
        "disable_material_map": ("DisableMaterialMap",),
        "disable_height_map": ("DisableHeightMap",),
        "flip_texture_v": ("FlipTextureV",),
        "d3d11_cull_back_faces": ("CullBackFaces",),
        "disable_tint": ("DisableTint",),
        "disable_brightness": ("DisableBrightness",),
        "disable_uv_scale": ("DisableUvScale",),
        "disable_depth_test": ("DisableDepthTest",),
        "d3d11_view_mode": ("MaterialDebugMode", "GameOutdoorApprox"),
        "d3d11_normal_y_mode": ("NormalYMode",),
        "d3d11_texture_address_mode": ("TextureAddressMode",),
        "max_anisotropy": ("MaxAnisotropy",),
        "d3d11_mip_lod_bias": ("MipLodBias",),
        "force_nearest_no_mipmaps": ("ForceNearestSampling",),
        "disable_lighting": ("DisableLighting",),
        "ambient_strength": ("AmbientStrength",),
        "diffuse_light_scale": ("DiffuseLightScale",),
        "diffuse_wrap_bias": ("DiffuseWrapBias",),
        "d3d11_light_azimuth_degrees": ("LightAzimuthDegrees",),
        "d3d11_light_elevation_degrees": ("LightElevationDegrees",),
        "normal_strength_cap": ("NormalStrengthCap",),
        "height_effect_max": ("HeightEffectMax",),
        "specular_base": ("SpecularBase",),
        "specular_max": ("SpecularMax",),
        "shininess_max": ("ShininessMax",),
        "d3d11_ao_strength": ("AoStrength",),
        "d3d11_roughness_bias": ("RoughnessBias",),
        "d3d11_metalness_scale": ("MetalnessScale",),
        "d3d11_environment_strength": ("EnvironmentStrength",),
        "d3d11_emissive_gain": ("EmissiveGain",),
        "d3d11_tone_exposure": ("ToneExposure",),
        "d3d11_tone_contrast": ("ToneContrast",),
        "d3d11_tone_gamma": ("ToneGamma",),
        "orbit_sensitivity": ("OrbitSensitivity",),
        "pan_sensitivity": ("PanSensitivity",),
        "invert_orbit_x": ("InvertOrbitX",),
        "invert_orbit_y": ("InvertOrbitY",),
        "invert_pan_x": ("InvertPanX",),
        "invert_pan_y": ("InvertPanY",),
    }

    assert set(consumer_tokens) == DOTNET_SUPPORTED_PREVIEW_SETTING_FIELDS
    for field, tokens in consumer_tokens.items():
        assert f'"{field}"' in transport, field
        assert f'"{field}"' in parser, field
        for token in tokens:
            assert token in renderer, f"{field}: {token}"


def test_dotnet_material_debug_range_covers_every_exposed_view_mode() -> None:
    viewport = _source("D3D11MaterialViewport.cs")
    panes = _source("D3D11MaterialViewport.Panes.cs")
    shader = _source("D3D11MaterialShaders.hlsl")

    assert "Math.Clamp(value, 0, 12)" in viewport
    assert "Math.Clamp(pane.MaterialDebugMode, 0, 12)" in panes
    for upper_bound in (8.5, 9.5, 10.5, 11.5, 12.5):
        assert f"{upper_bound:.1f}f" in shader


def test_untextured_faces_use_angle_safe_two_sided_workbench_lighting() -> None:
    shader = _source("D3D11MaterialShaders.hlsl")
    constants = _source("D3D11MaterialViewport.Constants.cs")
    settings = _source("D3D11MaterialViewport.PresentationSettings.cs")

    assert "row_major float4x4 NormalWorld;" in shader
    assert "public Matrix4x4 NormalWorld;" in constants
    assert "Matrix4x4.Invert(world, out var inverseWorld)" in settings
    assert "Matrix4x4.Transpose(inverseWorld)" in settings
    assert "WorkbenchGeometryColor(input)" in shader
    assert "normal = dot(normal, viewDirection) < 0.0f ? -normal : normal;" in shader
    assert "const float minimumIllumination = 0.48f;" in shader
    assert "max(PresentationLightingTuning.y, 0.58f)" in shader
    assert "rimShape * 0.10f" in shader
    assert "MathF.Sin(azimuth) * cosElevation" in settings
    assert "-MathF.Cos(azimuth) * cosElevation" in settings
    assert "float3 lightDirection = normalize(LightDirection);" in shader
    assert "normalize(-LightDirection)" not in shader
    assert "CameraPosition = new Vector3(0.0f, 0.0f, -cameraDistance)" in settings


def test_texture_toggle_and_view_mode_are_synchronized_across_resident_role_panes() -> None:
    presentation = _source("MeshViewport.Presentation.cs")
    settings = _source("MeshViewport.PresentationSettings.cs")
    split = _source("MeshViewport.SplitView.cs")
    panes = _source("D3D11MaterialViewport.Panes.cs")

    assert "public bool TexturesEnabled { get; set; } = true;" in presentation
    assert "SynchronizePresentationDisplaySettings();" in presentation
    assert "foreach (var context in _presentationContexts.Values)" in settings
    assert "context.DisplayMode = DisplayMode;" in settings
    assert "context.MaterialDebugMode = MaterialDebugMode;" in settings
    assert "context.TexturesEnabled = TexturesEnabled;" in settings
    assert "context.TexturesEnabled," in split
    assert "pane.TexturesEnabled && mode is (\"textured\" or \"textured_wire\")" in panes


def test_only_side_by_side_uses_two_resident_role_panes() -> None:
    split = _source("MeshViewport.SplitView.cs")

    assert 'string.Equals(comparisonMode, "side_by_side", StringComparison.OrdinalIgnoreCase)' in split
    assert '"original_only" => "reference"' in split
    assert '"replacement_only" => "editable"' in split
