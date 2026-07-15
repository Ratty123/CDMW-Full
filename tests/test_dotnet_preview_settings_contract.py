from __future__ import annotations

from pathlib import Path

from cdmw.models import ModelPreviewRenderSettings
from cdmw.ui.model_preview_settings_visibility import (
    DOTNET_SUPPORTED_PREVIEW_SETTING_FIELDS,
)
from tools.mesh_harness.visual_audit_capture import _DOTNET_AUDIT_PRESENTATION_PROFILE


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


def test_default_vortice_presentation_preserves_unclassified_real_pac_faces() -> None:
    constants = _source("D3D11MaterialViewport.Constants.cs")
    parser = _source("MeshViewport.PresentationSettings.cs")
    viewport = _source("D3D11MaterialViewport.cs")
    viewport_settings = _source("D3D11MaterialViewport.PresentationSettings.cs")
    audit_batch = _source("VisualAuditBatch.cs")

    assert "public bool CullBackFaces { get; init; }" in constants
    assert "public bool CullBackFaces { get; init; } = true;" not in constants
    assert 'CullBackFaces = JsonBool(quality, "d3d11_cull_back_faces", defaults.CullBackFaces)' in parser
    assert "RebuildPresentationPipelineStates();" in viewport
    assert "_presentationSettings.CullBackFaces ? CullMode.Back : CullMode.None" in viewport_settings
    assert "new RasterizerDescription(CullMode.Back, FillMode.Solid)" not in viewport
    assert "public bool CullBackFaces => _presentationSettings.CullBackFaces;" in viewport_settings
    assert "viewport.ApplyPresentationSettings(new D3D11PresentationSettings());" in audit_batch
    assert '["presentation"] = viewport.PresentationEvidencePayload()' in audit_batch


def test_visual_audit_profile_matches_mesh_editor_production_defaults() -> None:
    defaults = ModelPreviewRenderSettings()
    constants = _source("D3D11MaterialViewport.Constants.cs")
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

    assert {
        key: _DOTNET_AUDIT_PRESENTATION_PROFILE[key]
        for key in expected
    } == expected
    assert _DOTNET_AUDIT_PRESENTATION_PROFILE["profile"] == "mesh_editor_default_v1"
    assert defaults.disable_tint is False
    assert _DOTNET_AUDIT_PRESENTATION_PROFILE["disable_tint"] is False
    assert "DisableTint { get; init; } = true;" not in constants
    assert _DOTNET_AUDIT_PRESENTATION_PROFILE["sampling_filter"] == "anisotropic"
    assert (
        _DOTNET_AUDIT_PRESENTATION_PROFILE["color_pipeline"]
        == "srgb_srv_linear_shader_srgb_rtv"
    )
    for token in (
        'DefaultProfile = "mesh_editor_default_v1"',
        "DisableTint { get; init; }",
        "DisableBrightness { get; init; } = true;",
        "DisableUvScale { get; init; } = true;",
        "AoStrength { get; init; } = 0.45f;",
        "RoughnessBias { get; init; } = -0.04f;",
        "MetalnessScale { get; init; } = 1.45f;",
        "EnvironmentStrength { get; init; } = 0.62f;",
        "EmissiveGain { get; init; } = 2.2f;",
        "ToneContrast { get; init; } = 1.08f;",
        "MipLodBias { get; init; } = -2.0f;",
        "AmbientStrength { get; init; } = 0.84f;",
        "DiffuseWrapBias { get; init; } = 0.58f;",
        "DiffuseLightScale { get; init; } = 0.62f;",
        "SpecularBase { get; init; } = 0.055f;",
        "SpecularMax { get; init; } = 0.52f;",
    ):
        assert token in constants


def test_dotnet_material_debug_range_covers_every_exposed_view_mode() -> None:
    viewport = _source("D3D11MaterialViewport.cs")
    panes = _source("D3D11MaterialViewport.Panes.cs")
    shader = _source("D3D11MaterialShaders.hlsl")

    assert "Math.Clamp(value, 0, 12)" in viewport
    assert "Math.Clamp(pane.MaterialDebugMode, 0, 12)" in panes
    for upper_bound in (8.5, 9.5, 10.5, 11.5, 12.5):
        assert f"{upper_bound:.1f}f" in shader


def test_dotnet_material_tone_mapping_matches_native_reference_operator() -> None:
    shader = _source("D3D11MaterialShaders.hlsl")

    assert "float3 AcesToneMap(float3 color)" in shader
    assert "2.51f * color + 0.03f" in shader
    assert "2.43f * color + 0.59f" in shader
    assert "float mappedLuma = AcesToneMap(exposedLuma.xxx).r;" in shader
    assert "float contrastedLuma = (currentLuma - 0.5f)" in shader


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
