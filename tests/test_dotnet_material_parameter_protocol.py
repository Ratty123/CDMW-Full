from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DOTNET_EDITOR = ROOT / "tools" / "dotnet_mesh_editor_experiment"


def _source(name: str) -> str:
    return (DOTNET_EDITOR / name).read_text(encoding="utf-8")


def _source_family(stem: str) -> str:
    return "\n".join(
        path.read_text(encoding="utf-8")
        for path in sorted(DOTNET_EDITOR.glob(f"{stem}*.cs"))
    )


def test_texture_criticality_blocks_required_ready_and_keeps_optional_fallbacks_diagnostic() -> None:
    program = _source("Program.cs")
    materials = _source("NetMaterialSet.Resident.cs")
    material_protocol = _source("ExperimentForm.MaterialProtocol.cs")
    texture_set = _source("NetTextureSet.Incremental.cs")

    assert program.index("FailedRequiredResources") < program.index("QueueReadyAfterFirstFrame")
    assert 'WriteProtocolEvent("textures_error"' in program
    assert '"optional_resource_failures"' in program
    assert "bool Required" in materials
    assert "string FallbackPolicy" in materials
    assert '"required_texture_decode_failed"' in material_protocol
    assert '"optional_resource_failures"' in material_protocol
    assert "resourceGroups[index]" in texture_set


def test_late_original_reference_completion_routes_to_resident_material_generation() -> None:
    callback_source = (
        ROOT / "cdmw" / "ui" / "archive_browser" / "static_replacement_dialog_remaining_callbacks.py"
    ).read_text(encoding="utf-8")
    helper_source = (
        ROOT / "cdmw" / "ui" / "archive_browser" / "static_replacement_preview_materials.py"
    ).read_text(encoding="utf-8")
    protocol_source = (
        ROOT / "cdmw" / "ui" / "mesh_editor" / "tab_dotnet_resources.py"
    ).read_text(encoding="utf-8")

    assert "preview_materials.apply_resolved_original_materials_to_resident_editor(" in callback_source
    assert "_mesh_editor_embedded_apply_reference_material_resources" in helper_source
    assert "apply_reference(preview_model)" in helper_source
    assert 'role="original_reference"' in protocol_source
    assert '"reason": "late_original_reference_resources"' in protocol_source
    assert "standalone_dotnet_pending_reference_material_model" in protocol_source


def test_late_modify_original_materials_also_route_to_the_exact_editable_clone() -> None:
    callback_source = (
        ROOT / "cdmw" / "ui" / "archive_browser" / "static_replacement_dialog_remaining_callbacks.py"
    ).read_text(encoding="utf-8")
    helper_source = (
        ROOT / "cdmw" / "ui" / "archive_browser" / "static_replacement_preview_materials.py"
    ).read_text(encoding="utf-8")
    protocol_source = (
        ROOT / "cdmw" / "ui" / "mesh_editor" / "tab_dotnet_resources.py"
    ).read_text(encoding="utf-8")

    assert "modify_original_clone_mode=bool(modify_original_clone_mode)" in callback_source
    assert "if modify_original_clone_mode:" in helper_source
    assert "copy_dotnet_preview_material_bindings(" in helper_source
    assert "_mesh_editor_embedded_apply_clone_material_resources" in helper_source
    assert "def apply_resident_clone_material_resources(" in protocol_source
    assert 'reason="late_exact_clone_resources"' in protocol_source
    assert "standalone_dotnet_pending_clone_material_model" in protocol_source
    launch_source = (
        ROOT / "cdmw" / "ui" / "mesh_editor" / "tab_dotnet_launch.py"
    ).read_text(encoding="utf-8")
    connect_source = (
        ROOT / "cdmw" / "ui" / "mesh_editor" / "tab_dotnet_protocol.py"
    ).read_text(encoding="utf-8")
    assert launch_source.index("standalone_dotnet_pending_clone_material_model = None") < launch_source.index(
        "standalone_dotnet_package_request_id += 1"
    )
    assert "standalone_dotnet_pending_clone_material_model = None" not in connect_source


def test_required_and_optional_resource_policy_has_an_executable_runtime_probe() -> None:
    probe = _source("MaterialResourcePolicyProbe.cs")
    entry = _source("ProgramEntry.cs")

    assert "NetMaterialSet.Load(manifestPath)" in probe
    assert "textures.LoadAsync(materials).GetAwaiter().GetResult()" in probe
    assert "FailedRequiredResources" in probe
    assert "FailedOptionalResources" in probe
    assert '"required_texture_decode_failed"' in probe
    assert '"optional_texture_fallback_applied"' in probe
    assert "MaterialResourcePolicyProbe.Run(args)" in entry


def test_parameter_protocol_is_versioned_session_scoped_and_independently_ordered() -> None:
    protocol = _source("ExperimentForm.Protocol.cs")
    material_protocol = _source("ExperimentForm.MaterialProtocol.cs")
    state = _source("NetMaterialSet.Parameters.cs")

    assert 'ResidentMaterialParameterUpdatesCapability = "resident_material_parameter_updates_v1"' in protocol
    assert 'case "material_parameter_update":' in protocol
    assert 'WriteProtocolEvent("material_parameter_applied"' in material_protocol
    assert 'WriteProtocolEvent("material_parameter_failed"' in material_protocol
    assert 'const string expectedSchema = "cdmw_mesh_material_parameters_v1"' in state
    assert 'if (version != 1)' in state
    assert 'RequiredParameterLong(root, "edit_revision")' in state
    assert 'RequiredParameterLong(root, "parameter_generation")' in state
    assert "AcceptMaterialSession(update.SessionId" in material_protocol
    assert "update.ParameterGeneration <= _lastRequestedMaterialParameterGeneration" in material_protocol
    assert "update.EditRevision < _lastAppliedEditRevision" in material_protocol
    assert "ValidateMutationEnvelope(root, out var envelopeError)" in material_protocol
    assert "CopyMutationEnvelope(root, payload)" in material_protocol
    assert 'CanApplyEditRevision(update.EditRevision, "material_parameter_update"' not in material_protocol
    assert 'MarkEditRevisionApplied(update.EditRevision, "material_parameter_update"' not in material_protocol


def test_parameter_groups_validate_atomically_and_preserve_null_zero_semantics() -> None:
    state = _source("NetMaterialSet.Parameters.cs")
    material_protocol = _source("ExperimentForm.MaterialProtocol.cs")

    parse = state.split("public static NetMaterialParameterUpdate ParseParameterUpdate", maxsplit=1)[1]
    apply = state.split("public void ApplyParameterUpdate", maxsplit=1)[1].split("public static NetMaterialParameterUpdate", maxsplit=1)[0]
    handler = material_protocol.split("private void HandleMaterialParameterUpdate", maxsplit=1)[1].split("private static long ProtocolParameterGeneration", maxsplit=1)[0]
    assert "ValidateParameterGroupFields(item);" in parse
    assert "replacement_preview" in parse
    assert "unique non-negative integers" in parse
    assert "an empty array means all submeshes" in parse
    assert "An all-submesh material parameter group must be the only group." in parse
    assert "affected.Order().ToArray()" in parse
    assert 'OptionalFloat(group, "metalness", 0.0f, 1.0f, "metallic")' in parse
    assert 'OptionalFloat(group, "roughness_hint", 0.0f, 1.0f)' in parse
    assert 'OptionalFloat(group, "metalness_hint", 0.0f, 1.0f)' in parse
    assert 'OptionalFloat(group, "specular_hint", 0.0f, 1.0f)' in parse
    assert 'OptionalColor(group, "base_tint_color", 0.0f, 1.5f, "base_color")' in parse
    assert 'OptionalFloat(group, "base_tint_strength", 0.0f, 1.0f)' in parse
    assert 'OptionalBoolean(group, "base_tint_metallic")' in parse
    assert 'OptionalBoolean(group, "emissive_color_authoritative")' in parse
    assert 'OptionalColor(group, "texture_tint", 0.0f, 4.0f, "tint_color", "tint")' in parse
    assert 'OptionalInteger(group, "base_color_lift", 0, 254)' in parse
    assert 'OptionalInteger(group, "value_max", 0, 255)' in parse
    assert 'OptionalInteger(group, "auto_balance", 0, 100)' in parse
    assert 'OptionalInteger(group, "shadow_lift", 0, 100)' in parse
    assert 'OptionalBoolean(group, "roughness_inverted", "roughness_invert")' in parse
    assert 'OptionalBoolean(group, "metalness_inverted", "metallic_inverted", "metalness_invert", "metallic_invert")' in parse
    assert 'OptionalFloat(group, "metalness_scale", 0.0f, 4.0f, "metallic_scale")' in parse
    assert 'OptionalInteger(group, "roughness_min", 0, 255)' in parse
    assert 'OptionalInteger(group, "metalness_max", 0, 255, "metallic_max")' in parse
    assert 'OptionalFloat(group, "roughness_blend_target", 0.0f, 1.0f)' in parse
    assert 'OptionalFloat(group, "metalness_blend_strength", 0.0f, 1.0f, "metallic_blend_strength")' in parse
    assert "MaterialRole = OptionalMaterialRole(group)" in parse
    assert 'Visible = OptionalBoolean(group, "visible")' in parse
    assert "value.ValueKind == JsonValueKind.Null" in parse
    assert "new NetOptionalParameter<float>(true, null)" in parse
    assert "new NetOptionalParameter<float>(true, (float)number)" in parse
    assert "new NetOptionalParameter<int>(true, null)" in parse
    assert "new NetOptionalParameter<bool>(true, null)" in parse
    assert "Material parameter material_role must be 1-64" in parse
    assert "var next = new Dictionary<int, NetMaterialParameters>(ParameterStates);" in apply
    assert apply.index("foreach (var group") < apply.index("ParameterStates = next;")
    assert handler.index("NetMaterialSet.ParseParameterUpdate(root)") < handler.index("_materials.ApplyParameterUpdate(update)")
    assert handler.index("update.AffectedSubmeshes.Any") < handler.index("_materials.ApplyParameterUpdate(update)")
    assert "_materials.ReplaceParameterState(previous);" in handler
    assert "ExpandAllSubmeshes(" in handler


def test_parameter_apply_updates_only_d3d_constants_and_exposes_counters_and_roles() -> None:
    renderer = _source_family("D3D11MaterialViewport")
    presentation = _source("D3D11MaterialViewport.PresentationSettings.cs")
    resources = _source("D3D11MaterialViewport.Resources.cs")
    metrics = _source("D3D11MaterialViewport.Metrics.cs")
    viewport = _source("MeshViewport.Renderer.cs")
    status = _source("MeshViewport.Status.cs")

    apply = renderer.split("public bool TryApplyMaterialParameters", maxsplit=1)[1].split("private void UnbindGeometryResources", maxsplit=1)[0]
    assert "_affectedMaterialParameterBatchCount" in apply
    assert "_materialParameterApplyCount++" in apply
    assert "Invalidate();" in apply
    for forbidden in ("RefreshTextures", "TryApplyMaterialState", "CreateTextureSrv", "RebuildGeometry", "DisposeBatches"):
        assert forbidden not in apply
    assert "BuildCameraConstants(batch)" in renderer
    assert "ParametersForSubmesh(batch.SubmeshIndex)" in renderer
    assert "ParametersForSubmesh(batch.SubmeshIndex).Visible is false" in renderer
    assert "MaterialSurfaceOverrideFlags" in presentation
    assert "MaterialBaseTint" in presentation
    assert "MaterialBaseTintPolicy" in presentation
    assert "MaterialBaseAdvanced" in presentation
    assert "MaterialBasePost" in presentation
    assert "var materialRoughnessHint = Math.Clamp(" in presentation
    assert "parameters.RoughnessHint ?? 0.0f" in presentation
    assert "var materialMetalnessHint = Math.Clamp(" in presentation
    assert "parameters.MetalnessHint ?? 0.0f" in presentation
    assert "var materialSpecularHint = Math.Clamp(parameters.SpecularHint ?? 0.0f, 0.0f, 1.0f);" in presentation
    base_post = presentation.index("MaterialBasePost = new Vector4(")
    assert base_post < presentation.index("materialRoughnessHint,", base_post)
    assert base_post < presentation.index("materialMetalnessHint,", base_post)
    assert base_post < presentation.index("materialSpecularHint),", base_post)
    assert "MaterialSurfaceTransforms" in presentation
    assert "MaterialSurfaceTransforms2" in presentation
    assert "MaterialSurfaceBlends" in presentation
    assert "(parameters.BaseColorLift ?? 0) / 255.0f" in presentation
    assert "(parameters.ValueMax ?? 255) / 255.0f" in presentation
    assert "(parameters.AutoBalance ?? 0) / 100.0f" in presentation
    assert "(parameters.RoughnessMin ?? 0) / 255.0f" in presentation
    assert "(parameters.MetalnessMax ?? 255) / 255.0f" in presentation
    assert "MaterialEmissiveOverrideFlags" in presentation
    assert '"material_parameter_apply_count"' in metrics
    assert '"affected_material_parameter_batches"' in metrics
    assert "TryApplyMaterialParameters" not in resources
    assert "WPF/GDI fallback is unsupported" in viewport
    assert 'capabilities.Add("resident_material_parameter_updates_v1")' in status
    assert '["material_parameter_roles"] = _materials.ParameterRoles' in status


def test_shader_applies_explicit_surface_base_and_emissive_parameters() -> None:
    shader = _source("D3D11MaterialShaders.hlsl")

    for constant in (
        "MaterialBaseAdjustments",
        "MaterialBaseTint",
        "MaterialBaseTintPolicy",
        "MaterialTint",
        "MaterialBaseAdvanced",
        "MaterialBasePost",
        "MaterialSurfaceOverrides",
        "MaterialSurfaceOverrideFlags",
        "MaterialSurfaceTransforms",
        "MaterialSurfaceTransforms2",
        "MaterialSurfaceBlends",
        "MaterialEmissiveOverride",
        "MaterialEmissiveOverrideFlags",
    ):
        assert constant in shader
    assert "roughness = MaterialSurfaceOverrides.x;" in shader
    assert "metallic = MaterialSurfaceOverrides.y;" in shader
    assert "specularColor *= saturate(MaterialSurfaceOverrides.z);" in shader
    assert "float tintLuma = max(dot(previewTint" in shader
    assert "float3 tintBias = clamp(" in shader
    assert "MaterialHasBase > 0.5f\n        ? BaseTexture.Sample(MaterialSampler, uv)\n        : (MaterialBaseTint.w > 0.5f" in shader
    assert "MaterialBaseTint.w > 0.5f && MaterialBaseTintPolicy.x" not in shader
    assert "bool earlyCategoryMetal = MaterialBaseTintPolicy.y > 0.5f" in shader
    assert "MaterialBaseTintPolicy.y < 1.5f" in shader
    assert "float neutralMetalTint = earlyCategoryMetal" in shader
    assert "float liftedLuma = saturate(albedoLuma * (1.05f + strength * 0.35f)" in shader
    assert "float neutralMetalLuma = saturate(albedoLuma * (0.55f + tintLuma * 0.45f) + 0.012f);" in shader
    assert "float colorizeStrength = lerp(0.58f, 0.96f, neutralMetalTint);" in shader
    assert "baseColor.rgb = lerp(baseColor.rgb, lerp(multiplied, colorized, colorizeStrength), strength);" in shader
    assert "baseColor.rgb = saturate(baseColor.rgb * max(MaterialBaseAdjustments.x" in shader
    base_tint = shader.index("float tintLuma = max(dot(previewTint")
    brightness = shader.index("baseColor.rgb = saturate(baseColor.rgb * max(MaterialBaseAdjustments.x")
    tint = shader.index("baseColor.rgb *= max(MaterialTint.rgb")
    gamma = shader.index("baseColor.rgb = pow(")
    lift = shader.index("float baseLift =")
    saturation = shader.index("baseColor.rgb = saturate(baseLuma.xxx")
    auto_balance = shader.index("float autoBalanceStrength =")
    shadow_lift = shader.index("float shadowMask =")
    contrast = shader.index("baseColor.rgb = saturate((baseColor.rgb - 0.5f)")
    post_brightness = shader.index("baseColor.rgb = saturate(baseColor.rgb * max(MaterialBasePost.x")
    value_cap = shader.index("float valueCap =")
    assert base_tint < brightness < tint < gamma < lift < saturation < auto_balance < shadow_lift < contrast < post_brightness < value_cap
    roughness_sample = shader.index("float roughness =")
    roughness_invert = shader.index("if (MaterialSurfaceTransforms.w > 0.5f)")
    roughness_scale = shader.index("roughness *=")
    roughness_min = shader.index("roughness = max(")
    roughness_max = shader.index("roughness = min(")
    roughness_blend = shader.index("roughness = lerp(")
    roughness_override = shader.index("roughness = MaterialSurfaceOverrides.x;")
    assert roughness_sample < roughness_invert < roughness_scale < roughness_min < roughness_max < roughness_blend < roughness_override
    metalness_sample = shader.index("float metallic =")
    metalness_invert = shader.index("if (MaterialSurfaceTransforms2.w > 0.5f)")
    metalness_scale = shader.index("metallic *=")
    metalness_min = shader.index("metallic = max(")
    metalness_max = shader.index("metallic = min(")
    metalness_blend = shader.index("metallic = lerp(")
    metalness_override = shader.index("metallic = MaterialSurfaceOverrides.y;")
    assert metalness_sample < metalness_invert < metalness_scale < metalness_min < metalness_max < metalness_blend < metalness_override
    assert "MaterialHasEmissive > 0.5f" in shader
    assert "float emissiveIntensity = saturate(" in shader
    assert "MaterialHasEmissive > 0.5f ? 4.0f : 0.0f" in shader
    assert "/ 12.0f);" in shader
    assert "float3(2.0f, 2.0f, 2.0f)" in shader
    assert "emissive = emissiveColor" in shader
    assert "* saturate(emissiveSample.r)" in shader
    assert "MaterialEmissiveOverrideFlags.w > 0.5f" in shader
    assert "emissive = saturate(emissiveSample.rgb)" in shader
    assert "* emissiveColor" in shader
    assert "float emissiveMask = max(" in shader
    assert "max(emissiveColor, emissiveSample.rgb)" in shader
    assert "* saturate(emissiveMask)" in shader
    assert "else if (MaterialEmissiveOverrideFlags.y > 0.5f)" in shader
    assert "max(PresentationSurfaceTuning.z, 0.0f) * 0.85f" in shader


def test_resident_material_state_replaces_parameter_snapshot_with_resource_state() -> None:
    resident = _source("NetMaterialSet.Resident.cs")
    probe = _source("MaterialResourcePolicyProbe.cs")

    assert "ParseResidentParameterStates(root)" in resident
    assert "update.ParameterStates.TryGetValue" in resident
    assert "ParameterStates = state.ParameterStates;" in resident
    assert "IReadOnlyDictionary<int, NetMaterialParameters> ParameterStates" in resident
    assert '["emissive_scalar_mask"] = true' in probe
    assert '["emissive_scalar_mask"] = false' in probe
    assert '["roughness_hint"] = 0.0f' in probe
    assert '["specular_hint"] = 0.25f' in probe
    assert '["hint_transport_accepted"] = hintTransportAccepted' in probe
    assert 'materials.ReplaceState(materials.BuildState(update));' in probe


def test_hidden_gpu_smoke_proves_parameter_updates_do_not_churn_resources() -> None:
    soak = _source_family("HeadlessGpuSparseSoak")

    assert "ApplyMaterialParameterProof(materials, viewport)" in soak
    assert '"cdmw_mesh_material_parameters_v1"' in soak
    assert '"metalness": 0.0' in soak
    assert '"specular": null' in soak
    assert '"base_color_lift": 0' in soak
    assert '"value_max": 222' in soak
    assert '"auto_balance": 100' in soak
    assert '"shadow_lift": 25' in soak
    assert '"roughness_inverted": true' in soak
    assert '"metalness_inverted": false' in soak
    assert '"roughness_scale": 0.0' in soak
    assert '"metalness_blend_strength": null' in soak
    assert 'gates["material_parameter_state_exact"]' in soak
    assert 'gates["material_parameter_no_resource_churn"]' in soak
    assert 'gates["material_parameter_apply_counted"]' in soak
