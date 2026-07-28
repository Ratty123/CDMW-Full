from pathlib import Path


def test_dotnet_material_channels_and_embedded_panel_source_contracts() -> None:
    dotnet_root = Path(__file__).resolve().parents[1] / "tools" / "dotnet_mesh_editor_experiment"
    source = "\n".join(
        path.read_text(encoding="utf-8")
        for path in sorted(dotnet_root.glob("*.cs"))
        if path.name != "Cdmw.MeshEditorExperiment.GlobalUsings.g.cs"
    )
    hlsl_source = (dotnet_root / "D3D11MaterialShaders.hlsl").read_text(encoding="utf-8")

    assert "MaterialChannelSelectors" in hlsl_source
    assert "MaterialBaseTint.w > 0.5f" in hlsl_source
    assert "MaterialTint.w > 0.5f ? float4(1.0f, 1.0f, 1.0f, 1.0f)" in hlsl_source
    assert "float tintLuma = max(dot(previewTint" in hlsl_source
    # An authored base tint opts out of the metal damping; the category band is still
    # bounded at both ends. Asserted as three facts rather than one exact line, which
    # is what went stale when the `!authoredBaseTint` term was added.
    assert "bool earlyCategoryMetal = !authoredBaseTint" in hlsl_source
    assert "MaterialBaseTintPolicy.y > 0.5f" in hlsl_source
    assert "MaterialBaseTintPolicy.y < 1.5f" in hlsl_source
    assert "roughnessSample[(int)MaterialChannelSelectors.x]" in hlsl_source
    assert "metallicSample[(int)MaterialChannelSelectors.y]" in hlsl_source
    assert "ChannelComponentIndexForSubmesh" in source
    assert all(key in source for key in ('"BC4" or "BC4U" or "ATI1"', '"BC5" or "BC5U" or "ATI2"'))
    assert "if (!options.Embedded)" not in source
    assert "DotNetMeshEditorLeftToolScroll" in source
    assert "DotNetMeshEditorRightToolScroll" in source
    assert 'SetWindowTheme(control.Handle, "DarkMode_Explorer", null)' in source
    assert source.index("_ = _textureSet.LoadAsync(_materials);") < source.index("_viewport = new MeshViewport")
    assert 'AddSection(stack, "Clipboard"' not in source


def test_builder_presentation_fields_are_consumed_by_the_vortice_renderer() -> None:
    dotnet_root = Path(__file__).resolve().parents[1] / "tools" / "dotnet_mesh_editor_experiment"
    source = "\n".join(path.read_text(encoding="utf-8") for path in sorted(dotnet_root.glob("*.cs")))
    hlsl_source = (dotnet_root / "D3D11MaterialShaders.hlsl").read_text(encoding="utf-8")

    assert "ApplyPresentationQualityAndUv(display, root)" in source
    assert "ApplyPresentationPartStates(root)" in source
    assert "SetPresentationPartMatrices" in source
    assert "_presentationHighlightedOriginals" in source
    assert "ForceNearestSampling" in source
    assert "CullBackFaces" in source
    assert "TextureAddressMode.Clamp" in source
    assert '"force_flip" => 1.0f' in source
    assert "PresentationUvScaleOffset" in hlsl_source
    assert "PresentationUvRotationFlip" in hlsl_source
    assert "PresentationLightingTuning" in hlsl_source
    assert "PresentationMaterialTuning" in hlsl_source
    assert "NormalTexture.Sample(MaterialSampler, uv)" in hlsl_source
    assert "float3 exposedColor = max(" in hlsl_source
    assert "finalColor * max(PresentationToneTuning.x, 0.05f)" in hlsl_source
    assert "finalColor = exposedColor * (mappedLuma / max(exposedLuma, 1e-5f));" in hlsl_source
    assert "PreviewEnvironmentRadiance" in hlsl_source
    assert "PreviewEnvironmentIntensity" not in hlsl_source
    assert "DistributionGGX(metalNormal, metalHalfVector, roughness)" in hlsl_source
    assert "GeometrySmith(" in hlsl_source
    assert "return FresnelSchlick(cosTheta, reflectanceAtNormal);" in hlsl_source
    assert "SourceStableFresnel" in hlsl_source
    assert "environmentSpecular" in hlsl_source
    assert "bool isFrontFace : SV_IsFrontFace" in hlsl_source
    assert "MaterialAlphaPolicy.z > 0.5f && !isFrontFace" in hlsl_source
    assert "materialAlpha *= saturate(MaterialAlphaPolicy.w)" in hlsl_source
    assert "OpacityFactorForSubmesh" in source
    assert "float mappedLuma = AcesToneMap(exposedLuma.xxx).r;" in hlsl_source
    assert "contrastedLuma = max(contrastedLuma, currentLuma * 0.55f)" in hlsl_source
