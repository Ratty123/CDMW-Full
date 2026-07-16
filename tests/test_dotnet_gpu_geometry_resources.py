from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DOTNET_EDITOR = ROOT / "tools" / "dotnet_mesh_editor_experiment"


def _source(name: str) -> str:
    return (DOTNET_EDITOR / name).read_text(encoding="utf-8")


def _source_family(pattern: str) -> str:
    return "\n".join(
        path.read_text(encoding="utf-8")
        for path in sorted(DOTNET_EDITOR.glob(pattern))
    )


def _method(source: str, signature: str, next_signature: str) -> str:
    return source.split(signature, maxsplit=1)[1].split(next_signature, maxsplit=1)[0]


def test_sparse_vertex_refresh_retains_topology_and_uploads_only_incident_ranges() -> None:
    geometry = _source("D3D11MaterialViewport.Geometry.cs")
    topology = _source("MeshViewport.Topology.cs")
    sparse_refresh = _method(
        topology,
        "public void RefreshVertexGeometry(IReadOnlyDictionary<int, IReadOnlyCollection<int>> changedVertices)",
        "public void RefreshVertexGeometry(IEnumerable<int> changedSubmeshes)",
    )

    assert "SourceVertexToRenderCorners" in geometry
    assert "renderCorner / 3" in geometry
    assert "PatchBatchVertexRanges" in geometry
    assert "UploadFaceRange" in geometry
    assert "ArrayPool<D3D11MaterialVertex>.Shared.Rent" in geometry
    assert "UpdateSubresource(" in geometry
    assert "new Box(byteStart, 0, 0, byteEnd, 1, 1)" in geometry
    assert "batch.TopologyGeneration != _topologyGeneration" in geometry
    assert "RefreshModelBounds" not in sparse_refresh
    assert "RebuildEdgeTopology" not in sparse_refresh
    assert "ExpandModelBounds(changed)" in sparse_refresh
    expand_bounds = _method(topology, "private void ExpandModelBounds(", "private void RefreshModelBounds()")
    assert "_document.Bounds()" not in expand_bounds
    assert "var viewCenter = _center;" in expand_bounds
    assert "_center = viewCenter;" in expand_bounds


def test_topology_refresh_rebuilds_buffers_but_camera_frame_does_not() -> None:
    geometry = _source("D3D11MaterialViewport.Geometry.cs")
    topology = _source("MeshViewport.Topology.cs")
    refresh = _method(topology, "public void RefreshBounds()", "public void RefreshVertexGeometry(")
    frame = _method(topology, "public void FrameMesh()", "private static void ReplaceSelectionMap")

    assert "_d3d11Viewport.RefreshGeometry();" in refresh
    assert "RebuildEdgeTopology();" in refresh
    assert "RebuildPartAdjacency();" in refresh
    assert "var nextGeneration = _topologyGeneration + 1;" in geometry
    assert "DisposeBatches();" in geometry
    assert "RefreshBounds();" not in frame


def test_draw_resources_and_renderer_metrics_are_cached_and_exposed() -> None:
    renderer = _source("D3D11MaterialViewport.cs")
    resources = _source("D3D11MaterialViewport.Resources.cs")
    metrics = _source("D3D11MaterialViewport.Metrics.cs")
    viewport_metrics = _source("MeshViewport.RendererResources.cs")
    status = _source("MeshViewport.Status.cs")

    assert "batch.Materials.ShaderResources" in renderer
    assert "ToSrvArray" not in renderer
    assert "ShaderResources = new[]" in resources
    assert "RefreshTextures()" in resources
    assert "_geometryDirty = true" not in _method(resources, "public void RefreshTextures()", "private void RebuildMaterialResourcesIfDirty()")
    assert '"full_geometry_rebuilds"' in metrics
    assert '"sparse_vertex_updates"' in metrics
    assert '"peak_geometry_old_plus_new_bytes_estimate"' in metrics
    assert '"oldest_live_texture_srv_ms"' in metrics
    assert '"peak_old_plus_new_vram_bytes_estimate"' in metrics
    assert "RendererResourceMetricsPayload" in viewport_metrics
    assert '["geometry_resources"] = RendererResourceMetricsPayload()' in status


def test_native_dds_mips_color_space_and_semantic_shading_are_explicit() -> None:
    native = _source("NetTextureSet.NativeDds.cs")
    decode = _source("NetTextureSet.Dds.cs")
    incremental = _source("NetTextureSet.Incremental.cs")
    resources = _source("D3D11MaterialViewport.Resources.cs")
    regions = _source("D3D11MaterialViewport.TextureRegions.cs")
    constants = _source("D3D11MaterialViewport.Constants.cs")
    presentation = _source("D3D11MaterialViewport.PresentationSettings.cs")
    material_set = _source("NetMaterialSet.Resident.cs")
    shader = _source("D3D11MaterialShaders.hlsl")
    status = _source("MeshViewport.Status.cs")

    assert "BuildNativeDdsTextureData" in native
    assert "new NetDdsSubresource" in native
    assert '"BC7"' in native and '99 => ("BC7", 0, 16, true)' in native
    assert "native_subresource_size_overflow" in native
    assert "non_2d_or_array_dx10_dds" in native
    assert "NativeDds" in decode
    assert "Task.Run(() =>" in incremental
    assert "CreateNativeDdsSrv" in resources
    assert "ResourceUsage.Immutable" in resources
    assert "nativeDds.MipCount" in resources
    assert "B8G8R8A8_UNorm_SRgb" in resources
    bitmap_upload = _method(
        resources,
        "var bitmap = _textureSet.BitmapForReference(reference);",
        "private unsafe D3D11TextureBinding CreateNativeDdsSrv(",
    )
    assert "var mipCount = EditableMipLevelCount(converted.Width, converted.Height);" in bitmap_upload
    assert "MipLevels = (uint)mipCount" in bitmap_upload
    assert "Usage = ResourceUsage.Default" in bitmap_upload
    assert "BindFlags = BindFlags.ShaderResource | BindFlags.RenderTarget" in bitmap_upload
    assert "MiscFlags = ResourceOptionFlags.GenerateMips" in bitmap_upload
    assert "_context.GenerateMips(view);" in bitmap_upload
    assert '"bitmap_bgra32_generated_mip_chain"' in bitmap_upload
    assert '"bitmap_bgra32_generated_mip_chain_v1"' in status
    textured_metal_proof = _source("D3D11TexturedMetalReadabilityProof.cs")
    assert '"bitmap_fallback_generated_full_mip_chain"' in textured_metal_proof
    assert '"texture_resource_diagnostics"' in textured_metal_proof
    assert '"texture_resource_diagnostics"' in _source("D3D11MaterialViewport.Metrics.cs")
    assert "CopyResource(texture, source.Texture)" not in regions
    assert "BitmapForReference(references[0])" in regions
    assert "ResourceOptionFlags.GenerateMips" in regions
    assert "_context.GenerateMips(editable.View)" in regions
    assert "_context.GenerateMips(view)" in regions
    assert "MaterialAlphaPolicy" in constants
    assert "AlphaModeForSubmesh" in presentation
    assert "OpacityFactorForSubmesh" in presentation
    assert "DoubleSidedForSubmesh" in presentation
    assert "ShaderFamilyForSubmesh" in material_set
    assert "MaterialFamilyPolicy" in constants
    assert '"skin" => new Vector4(1.0f, 0.30f, 0.34f, 0.40f)' in presentation
    assert '"cloth" or "cloth_v2" => new Vector4(1.0f, 0.48f, 0.28f, 0.46f)' in presentation
    assert '"hair" => new Vector4(1.0f, 0.36f, 0.46f, 0.38f)' in presentation
    assert "roughness = max(roughness, MaterialFamilyPolicy.y)" in shader
    assert "if (MaterialFamilyPolicy.x > 0.5f)" in shader
    assert "specularColor = min(neutralSpecular, MaterialFamilyPolicy.z).xxx" in shader
    assert "float diffuseDepth = saturate(" in shader
    assert "diffuseDepth = lerp(1.0f, diffuseDepth, depthAuthority);" in shader
    assert "DistributionGGX" in shader
    assert "GeometrySmith" in shader
    assert "FresnelSchlick" in shader
    assert "clip(baseColor.a - MaterialAlphaPolicy.y)" in shader
    assert "materialAlpha *= saturate(MaterialAlphaPolicy.w)" in shader
    assert '"native_dds_2d_mip_chain_upload_v1"' in status
    assert '"resident_texture_mip_regeneration_v1"' in status
    assert '"native_dds_parity"] = false' in status


def test_d3d11_preview_and_capture_use_offscreen_msaa_resolve() -> None:
    viewport = _source("D3D11MaterialViewport.cs")
    targets = _source("D3D11MaterialViewport.RenderTargets.cs")
    capture = _source("D3D11MaterialViewport.Capture.cs")
    presentation = _source("D3D11MaterialViewport.PresentationSettings.cs")
    metrics = _source("D3D11MaterialViewport.Metrics.cs")
    status = _source("MeshViewport.Status.cs")
    audit = _source("VisualAuditBatch.cs")
    readability = _source("D3D11TexturedMetalReadabilityProof.cs")

    assert "SwapEffect = SwapEffect.FlipDiscard" in viewport
    assert "SampleDescription = new SampleDescription(1, 0)" in viewport
    assert "PreferredRenderSampleCount = 4" in targets
    assert "CheckMultisampleQualityLevels" in targets
    assert "RenderTargetViewDimension.Texture2DMultisampled" in targets
    assert "DepthStencilViewDimension.Texture2DMultisampled" in targets
    assert "ResolveSubresource(" in targets
    assert "ResolveRenderTargetForPresentation();" in viewport
    assert "MultisampleEnable = true" in presentation
    assert "CurrentRenderSampleDescription" in capture
    assert "ResolveSubresource(" in capture
    assert "MultisampleResolved" in capture
    assert '"render_sample_count"' in metrics
    assert '"multisample_resolve_count"' in metrics
    assert '"peak_resident_plus_capture_vram_bytes_estimate"' in metrics
    assert "public int RenderSurfaceIdentity => CurrentRenderSurfaceIdentity();" in targets
    assert '"anti_aliasing_mode"' in status
    assert '"d3d11_offscreen_msaa_resolve_v1"' in status
    assert '["sample_count"] = renderedCamera.SampleCount' in audit
    assert '"capture_msaa_resolve_active"' in readability
    assert '"live_frame_after_capture_resolved"' in readability


def test_hidden_gpu_sparse_soak_uses_real_d3d_resources_and_versioned_evidence() -> None:
    entry = _source("ProgramEntry.cs")
    soak = _source_family("HeadlessGpuSparseSoak*.cs")
    options = _source("HeadlessGpuSparseSoakOptions.cs")
    headless = _source("D3D11MaterialViewport.Headless.cs")
    viewport = _source("D3D11MaterialViewport.cs")
    metrics = _source("D3D11MaterialViewport.Metrics.cs")
    readability = _source("D3D11UntexturedReadabilityProof.cs")
    textured_metal_readability = _source("D3D11TexturedMetalReadabilityProof.cs")

    assert entry.index("HeadlessGpuSparseSoak.IsRequested(args)") < entry.index("LaunchOptions.Parse(args)")
    assert '"--headless-gpu-sparse-soak"' in entry
    assert '"cdmw_dotnet_gpu_sparse_soak_v1"' in soak
    assert 'Integer(values, "gpu-soak-vertices", 1_000_000' in options
    assert 'Integer(values, "gpu-soak-updates", 1_000' in options
    assert 'TargetUpdatesPerSecond)\n' in options
    assert "BuildSyntheticDocument(options.VertexCount)" in soak
    assert "durations[update] = ApplySparseUpdate(" in soak
    assert "Hidden D3D11 final sparse frame failed" in soak
    assert '"frame_sample_count"' in soak
    assert "checked_in_asset_used" in soak
    assert "Application.Run" not in soak
    assert "Show()" not in soak
    assert "IsWindowVisible(host.Handle)" in soak
    assert 'gates["native_windows_remained_hidden"]' in soak
    assert 'gates["production_d3d11_backend"]' in soak
    assert 'gates["untextured_faces_readable_front_back_and_oblique"]' in soak
    assert '"untextured_readability_proof"' in soak
    assert 'gates["textured_metal_readable_front_back_and_oblique"]' in soak
    assert '"textured_metal_readability_proof"' in soak
    assert 'gates["resident_gizmo_moves_only_editable_role"]' in soak
    assert '"editable_matrix_changed_at_input_cadence"' in soak
    assert '"reference_matrix_unchanged"' in soak
    assert '"nonzero_source_anchor_stayed_at_gizmo_pivot"' in soak
    assert '"stale_authority_retained_newer_provisional_drag"' in soak
    assert '"overlay_vertex_buffer_reused_across_frames"' in soak
    assert '"vertex_markers_rendered_in_smoke"' in soak
    assert '"vertices"' in soak and "UpdateRenderPanes" in soak
    assert '"vertex_marker_size_pixels"' in metrics
    assert "TryRunHeadlessFrame" in headless
    assert "RenderFrame()" in headless
    assert "_lastDrawnMaterialAuthority.Clear();" in viewport
    assert "_lastDrawnMaterialAuthority[batch.MaterialSubmeshIndex] = constants.MaterialBaseTintPolicy;" in viewport
    assert "TryGetLastDrawnMaterialAuthority" in viewport
    assert '"geometry_buffer_identity"' in metrics
    assert '"dxgi_local_memory_current_usage_bytes"' in metrics
    assert '"material_binding_array_identity"' in metrics
    assert '"overlay_vertex_buffer_creates"' in metrics
    assert '"overlay_vertex_buffer_maps"' in metrics
    assert '"cdmw_untextured_readability_v1"' in readability
    assert '"hidden_synthetic_gpu_regression"' in readability
    assert '("front", 0.0f, 0.0f)' in readability
    assert '("back", MathF.PI, 0.0f)' in readability
    assert "MinimumCenterP10Luma" in readability
    assert "MaximumCenterBackgroundFraction" in readability
    assert "TryCaptureReplacementPng" in readability
    assert "IsWindowVisible(viewport.Handle)" in readability
    assert '"cdmw_textured_metal_readability_v4"' in textured_metal_readability
    assert '"cdmw_textured_metal_readability_v3"' not in textured_metal_readability
    assert '"hidden_synthetic_gpu_regression"' in textured_metal_readability
    assert '["material_category"] = "metal"' in textured_metal_readability
    assert '["material_category_confidence"] = 1.0' in textured_metal_readability
    assert '["material_response_promoted"] = true' in textured_metal_readability
    assert "materials.MaterialCategoryCodeForSubmesh(0)" in textured_metal_readability
    assert "materials.MaterialCategoryConfidenceForSubmesh(0)" in textured_metal_readability
    assert "materials.MaterialResponsePromotedForSubmesh(0)" in textured_metal_readability
    assert "runtimeMaterialCategoryCode > 0.5f" in textured_metal_readability
    assert "runtimeMaterialCategoryCode < 1.5f" in textured_metal_readability
    assert '["runtime_material_category_is_metal"] = runtimeMetalCategoryBranch' in textured_metal_readability
    assert '["runtime_material_category_confident"] = runtimeMaterialCategoryConfidence >= 0.99f' in textured_metal_readability
    assert '["runtime_material_response_promoted"] = runtimeMaterialResponsePromoted' in textured_metal_readability
    assert '["runtime_material_authority"]' in textured_metal_readability
    assert "TryGetLastDrawnMaterialAuthority(0, out drawnMaterialAuthority)" in textured_metal_readability
    assert '["captured_draw_material_authority"]' in textured_metal_readability
    assert '["captured_draw_material_authority_recorded"]' in textured_metal_readability
    assert '["captured_draw_material_category_is_metal"]' in textured_metal_readability
    assert '["captured_draw_material_category_confident"]' in textured_metal_readability
    assert '["captured_draw_material_response_promoted"]' in textured_metal_readability
    assert '["metalness"] = 1.0' in textured_metal_readability
    assert '["double_sided"] = true' in textured_metal_readability
    assert 'textures.BitmapForPath(texturePath) is not null' in textured_metal_readability
    assert '"double_sided_opposite_views_balanced"' in textured_metal_readability
    assert '"angle_color_identity_stable"' in textured_metal_readability
    assert '"angle_brightness_stable"' in textured_metal_readability
    assert "viewport.MaterialDebugMode = 6;" in textured_metal_readability
    assert "viewport.MaterialDebugMode = 0;" in textured_metal_readability
    assert '$"{view.Name}_specular.png"' in textured_metal_readability
    assert '"specular_captures"' in textured_metal_readability
    assert '"specular_debug_captures_complete"' in textured_metal_readability
    assert '"specular_debug_view_response_varies"' in textured_metal_readability
    assert '"specular_debug_response_bounded"' in textured_metal_readability
    assert "MinimumSpecularMeanLuma = 1.0" in textured_metal_readability
    assert "MinimumSpecularMeanLumaViewSpan = 3.0" in textured_metal_readability
    assert "MaximumSpecularWhiteFraction = 0.12" in textured_metal_readability
    assert '"specular_mean_luma_view_span"' in textured_metal_readability
    assert "MinimumAllViewLumaRatio" in textured_metal_readability
    assert "MaximumViewChromaticityDistance" in textured_metal_readability
    assert "center_chromaticity_span" in textured_metal_readability
    assert "center_white_fraction" in textured_metal_readability
    assert 'TryCaptureReplacementPng' in textured_metal_readability
    assert 'IsWindowVisible(viewport.Handle)' in textured_metal_readability


def test_sparse_bounds_rebase_when_an_extremum_moves_inward() -> None:
    topology = _source("MeshViewport.Topology.cs")
    bounds = _source("MeshViewport.Bounds.cs")
    soak = _source_family("HeadlessGpuSparseSoak*.cs")

    assert "SparseBounds.Update(changedVertices);" in topology
    assert "ApplySparseBounds();" in topology
    assert "TouchesExtremumOwner(changedVertices)" in bounds
    assert "BoundaryTriggeredRebaseCount++" in bounds
    assert "Rebase();" in bounds
    assert "Center = BoundsCenter(min, max);" in bounds
    assert "SparseBoundsProof()" in soak
    assert '"inward_bounds_and_center_exact"' in soak
