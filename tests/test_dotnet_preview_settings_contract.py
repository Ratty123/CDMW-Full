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
    parser = "\n".join(
        (
            _source("MeshViewport.PresentationSettings.cs"),
            _source("MeshViewport.GizmoAppearance.cs"),
        )
    )
    renderer = "\n".join(
        (
            _source("D3D11MaterialViewport.PresentationSettings.cs"),
            _source("D3D11MaterialViewport.Panes.cs"),
            _source("D3D11MaterialViewport.cs"),
            _source("D3D11MaterialShaders.hlsl"),
            _source("MeshViewport.Input.cs"),
            _source("MeshViewport.Presentation.cs"),
            _source("MeshViewport.Gizmo.cs"),
            _source("D3D11MaterialViewport.Gizmo.cs"),
            _source("D3D11MaterialViewport.Metrics.cs"),
            _source("GizmoAppearance.cs"),
        )
    )
    consumer_tokens = {
        "orbit_sensitivity": ("OrbitSensitivity",),
        "pan_sensitivity": ("PanSensitivity",),
        "invert_orbit_x": ("InvertOrbitX",),
        "invert_orbit_y": ("InvertOrbitY",),
        "invert_pan_x": ("InvertPanX",),
        "invert_pan_y": ("InvertPanY",),
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


def test_dotnet_material_diffuse_depth_matches_native_reference_operator() -> None:
    shader = _source("D3D11MaterialShaders.hlsl")
    viewport = _source("D3D11MaterialViewport.PresentationSettings.cs")

    assert '"standard" or "standard_v2" => 4.0f' in viewport
    assert '"emissive" or "emissive_v2" => 6.0f' in viewport
    assert "materialFamilyCode);" in viewport
    assert "float materialCategoryCode = MaterialBaseTintPolicy.y;" in shader
    assert "float categoryMetalCap = categoryMetal" in shader
    assert "float categorySpecularCap = categoryMetal" in shader
    assert "float categoryRoughnessFloor = categoryMetal" in shader
    assert "float categoryEnvironmentScale = categoryMetal" in shader
    assert "parameters.RoughnessHint ?? 0.0f" in viewport
    assert "parameters.MetalnessHint ?? 0.0f" in viewport
    assert "parameters.SpecularHint ?? 0.0f" in viewport
    packed_hints = viewport[
        viewport.index("var materialRoughnessHint =") : viewport.index("var azimuth =")
    ]
    assert "RoughnessScale" not in packed_hints
    assert "MetalnessScale" not in packed_hints
    assert "float materialRoughnessHint = saturate(MaterialBasePost.y);" in shader
    assert "saturate(materialMetalnessHint * max(PresentationSurfaceTuning.y, 0.0f))" in shader
    assert "MaterialHintPresenceMask(NetMaterialParameters parameters)" in viewport
    assert "parameters.RoughnessHint.HasValue ? 1.0f : 0.0f" in viewport
    assert "parameters.MetalnessHint.HasValue ? 2.0f : 0.0f" in viewport
    assert "parameters.SpecularHint.HasValue ? 4.0f : 0.0f" in viewport
    assert "uint materialHintPresence = (uint)round(MaterialChannelSelectors.w);" in shader
    assert "bool hasMaterialRoughnessHint = (materialHintPresence & 1u) != 0u;" in shader
    assert "bool hasMaterialMetalnessHint = (materialHintPresence & 2u) != 0u;" in shader
    assert "bool hasMaterialSpecularHint = (materialHintPresence & 4u) != 0u;" in shader
    assert "bool explicitMaterialAuthorityHint = hasMaterialRoughnessHint" in shader
    authority_contract = shader[
        shader.index("bool explicitMaterialAuthorityHint =") :
        shader.index("if (explicitMaterialAuthorityHint && !conservativeNonmetal)")
    ]
    assert "MaterialSurfaceOverrideFlags.w > 0.5f" in authority_contract
    assert "MaterialSurfaceOverrides.w > 0.02f" in authority_contract
    assert "MaterialHeightScale" not in authority_contract
    assert "float glossHint = saturate(" in shader
    assert "lerp(roughness, materialRoughnessHint, 0.55f)" in shader
    assert "roughness = saturate(roughness + familyRoughnessBias);" in shader
    assert "metallic = saturate(metallic * familyMetalScale);" in shader
    assert "specularColor *= familySpecularScale;" in shader
    for expected_family_operator in (
        "familyMetalScale = 1.15f;",
        "familySpecularScale = 1.35f;",
        "familyRoughnessBias = -0.04f;",
        "familyMetalScale = 1.05f;",
        "familyMetalScale = 0.55f;",
    ):
        assert expected_family_operator in shader
    assert "float mattePreview = saturate((materialRoughnessHint - 0.62f) * 2.63f);" in shader
    assert "float authorityGlossCue = (explicitMaterialAuthorityHint && !conservativeNonmetal)" in shader
    assert "environmentMaterialScale = max(environmentMaterialScale, authorityGlossCue * 0.32f);" in shader
    assert "float3 sourceStableF0 = lerp(" in shader
    assert "float3 resolvedSurfaceF0 = sourceStableF0;" in shader
    assert "float3 resolvedSurfaceF0 = categoryMetal" not in shader
    assert "SourceStableFresnel(ndotv, resolvedSurfaceF0)" in shader
    assert "return FresnelSchlick(cosTheta, reflectanceAtNormal);" in shader
    assert "float glossyCue = glossyNonmetal" in shader
    assert "litDiffuse += materialReferenceAlbedo * glossyCue * 0.22f;" in shader
    for expected_scale in (
        "categoryGlass ? 0.26f",
        "categoryGem ? 0.30f",
        "categoryEye ? 0.24f",
        "categoryLeather ? 0.06f",
        "categoryWood ? 0.06f",
        "categoryCloth ? 0.025f",
        "categorySkin ? 0.075f",
        "categoryHair ? 0.08f",
        "categoryStone ? 0.04f",
        "categoryTooth ? 0.08f",
    ):
        assert expected_scale in shader
    assert "roughness = max(roughness, categoryRoughnessFloor);" in shader
    assert "metallic = min(metallic, categoryMetalCap);" in shader
    assert "categoryRoughnessFloor = min(categoryRoughnessFloor, 0.08f);" in shader
    assert "|| (hasMaterialMetalnessHint && materialMetalnessHint > 0.16f)" in shader
    assert "specularColor = min(specularColor, categorySpecularCap.xxx);" in shader
    assert "float3 materialReferenceAlbedo = saturate(" in shader
    assert "float3 heightNormal = normalize(" in shader
    assert "float reliefEdge = saturate(" in shader
    assert "float heightRelief = (heightValue - 0.5f)" in shader
    assert "heightStrength = saturate(MaterialHeightScale + declaredHeight * 0.04f);" in shader
    assert "* saturate(MaterialHeightScale);" in shader
    assert "heightX * heightStrength" not in shader
    assert "uv += viewDirection.xy * height * MaterialHeightScale;" not in shader
    assert "float3 metalTintBias = clamp(" in shader
    assert "materialReferenceAlbedo * metalTintBias" in shader
    assert "lerp(0.05f, 1.25f, neutralMetalTint)" in shader
    assert "float colorizeStrength = lerp(0.58f, 0.96f, neutralMetalTint);" in shader
    assert (
        "materialReferenceAlbedo * metalTintBias,\n"
        "            0.34f * saturate(MaterialBaseTintPolicy.x)));"
    ) in shader
    assert "float metalTintBlend = lerp(" not in shader
    assert "float ambientFloor = categoryMetal ? 0.24f" in shader
    assert "float diffuseDepth = saturate(" in shader
    assert "float depthAuthority = categoryMetal" in shader
    assert "glossyNonmetal ? 0.72f" in shader
    assert "categoryLeather ? 0.52f" in shader
    assert "MaterialFamilyPolicy.w > 0.0f ? MaterialFamilyPolicy.w" not in shader
    assert "float nonmetalTextureScale = conservativeNonmetal ? 1.03f : 1.0f;" in shader
    assert "float3 litDiffuse = materialReferenceAlbedo" in shader
    assert "float3 metalNormal = dot(normal, viewDirection) < 0.0f ? -normal : normal;" in shader
    assert "float metalDistribution = DistributionGGX(metalNormal, metalHalfVector, roughness);" in shader
    assert "float metalGeometry = GeometrySmith(" in shader
    assert "float3 metalFresnel = SourceStableFresnel(metalHdotV, specularColor);" in shader
    assert "float metalDirectSpecularScale = 0.35f + metallic * 0.35f;" in shader
    assert "float3(0.85f, 0.85f, 0.85f)" in shader
    assert "float metalDirectLobe = pow(" not in shader
    assert "float broadMetalLobe = pow(" not in shader
    assert "float nonmetalDirectSpecularScale = glossyNonmetal" in shader
    assert "conservativeNonmetal ? 0.025f : 0.08f" in shader
    assert "float3 sourceStableF0 = lerp(" in shader
    assert "float3 PreviewEnvironmentRadiance(float3 reflectedView, float roughness)" in shader
    assert "float3 radiance = float3(0.016f, 0.017f, 0.020f);" in shader
    assert "float3(1.25f, 1.25f, 1.25f)" in shader
    assert "PreviewEnvironmentIntensity" not in shader
    assert "float environmentMaterialScale = categoryMetal" in shader
    assert "glossyNonmetal ? 0.18f" in shader
    assert "conservativeNonmetal ? 0.018f" in shader
    assert "* categoryEnvironmentScale" in shader
    assert "float metalCue = categoryMetal" in shader
    assert "float metalDiffuseScale = lerp(1.0f, 0.34f, saturate(metallic));" in shader
    assert "litDiffuse += materialReferenceAlbedo * metalCue * 0.16f;" in shader
    assert "0.14f + roughness * 0.06f + (1.0f - ndotv) * 0.30f" in shader
    assert "if (categoryMetal)" in shader
    assert "float3(0.035f, 0.035f, 0.035f)" in shader
    assert "materialReferenceAlbedo," in shader
    assert "float3 spec = float3(0.0f, 0.0f, 0.0f);" in shader
    assert "float3 fresnel = SourceStableFresnel(" not in shader
    assert "float3 ambient = baseColor.rgb * AmbientColor" not in shader


def test_dotnet_material_category_authority_reaches_native_response_fallback() -> None:
    shader = _source("D3D11MaterialShaders.hlsl")
    viewport = _source("D3D11MaterialViewport.PresentationSettings.cs")
    material_set = _source("NetMaterialSet.cs")
    resident_material_set = _source("NetMaterialSet.Resident.cs")

    for field in (
        '"material_category"',
        '"material_category_confidence"',
        '"material_category_reason"',
        '"material_response_promoted"',
    ):
        assert field in material_set
        assert field in resident_material_set
    assert "MaterialCategoryCodeForSubmesh" in viewport
    assert "MaterialCategoryConfidenceForSubmesh" in viewport
    assert "MaterialResponsePromotedForSubmesh" in viewport
    assert "parameters.BaseTintMetallic == true" in viewport
    assert "bool earlyCategoryMetal = MaterialBaseTintPolicy.y > 0.5f" in shader
    assert "MaterialBaseTintPolicy.y < 1.5f" in shader
    assert "float categoryMetalFallback = categoryMetal" in shader
    assert "metallic = max(metallic, categoryMetalFallback);" in shader
    assert "|| MaterialHasMetallic > 0.5f" in shader
    assert "MaterialBaseTintPolicy.w > 0.5f" in shader
    source_fresnel = shader.index("float3 sourceStableF0 = lerp(")
    sampled_specular = shader.index("SpecularTexture.Sample(MaterialSampler, uv).rgb")
    metal_fresnel_use = shader.index("float3 metalFresnel = SourceStableFresnel(metalHdotV, specularColor);")
    environment_fresnel_use = shader.index(
        "float3 environmentFresnel = SourceStableFresnel(ndotv, resolvedSurfaceF0);"
    )
    assert sampled_specular < source_fresnel < metal_fresnel_use < environment_fresnel_use
    assert "SourceStableFresnel(\n            nonmetalCameraShape,\n            resolvedSurfaceF0)" in shader
    assert "float3 resolvedSurfaceF0 = sourceStableF0;" in shader


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
    assert "const float minimumIllumination = 0.38f;" in shader
    assert "keyLight * 0.48f" in shader
    assert "rimShape * 0.025f" in shader
    assert "MathF.Sin(azimuth) * cosElevation" in settings
    assert "-MathF.Cos(azimuth) * cosElevation" in settings
    assert "float3 lightDirection = normalize(LightDirection);" in shader
    assert "normalize(-LightDirection)" not in shader
    assert "CameraPosition = new Vector3(0.0f, 0.0f, -cameraDistance)" in settings


def test_textured_material_lighting_uses_the_orthographic_view_direction() -> None:
    shader = _source("D3D11MaterialShaders.hlsl")

    assert "const float3 viewDirection = float3(0.0f, 0.0f, -1.0f);" in shader
    assert "normalize(CameraPosition - input.WorldPosition)" not in shader


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
    assert "TexturesEnabled = pane.TexturesEnabled" in panes
    assert 'string.Equals(mode, "textured", StringComparison.OrdinalIgnoreCase)' in panes
    assert 'string.Equals(mode, "textured_wire", StringComparison.OrdinalIgnoreCase)' in panes


def test_builder_uv_transforms_apply_only_to_the_editable_preview_role() -> None:
    settings = _source("D3D11MaterialViewport.PresentationSettings.cs")

    assert "var applyEditableUvTransform = _scene.IsEditable(batch.SubmeshIndex);" in settings
    assert "var uvOffset = applyEditableUvTransform ? settings.UvOffset : Vector2.Zero;" in settings
    assert "var flipU = applyEditableUvTransform && settings.FlipU;" in settings
    assert "var flipV = (applyEditableUvTransform && settings.FlipV)" in settings
    assert "^ _materials.TextureFlipVerticalForSubmesh(materialSubmeshIndex);" in settings


def test_only_side_by_side_uses_two_resident_role_panes() -> None:
    split = _source("MeshViewport.SplitView.cs")

    assert 'string.Equals(comparisonMode, "side_by_side", StringComparison.OrdinalIgnoreCase)' in split
    assert '"original_only" => "reference"' in split
    assert '"replacement_only" => "editable"' in split
