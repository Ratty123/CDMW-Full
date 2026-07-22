from __future__ import annotations

from pathlib import Path

from tests.mesh_editor_source_support import mesh_editor_tab_source


def _dotnet_source_context() -> dict[str, object]:
    root = Path(__file__).resolve().parents[1]
    dotnet_root = root / "tools" / "dotnet_mesh_editor_experiment"
    source = "\n".join(
        path.read_text(encoding="utf-8")
        for path in sorted(dotnet_root.glob("*.cs"))
        if path.name != "Cdmw.MeshEditorExperiment.GlobalUsings.g.cs"
    )
    d3d_source = "\n".join(
        path.read_text(encoding="utf-8")
        for path in sorted(dotnet_root.glob("D3D11MaterialViewport*.cs"))
    )
    return {
        "root": root,
        "source": source,
        "gpu_source": (dotnet_root / "WpfGpuMeshViewport.cs").read_text(encoding="utf-8"),
        "d3d_source": d3d_source,
        "d3d_overlay_source": (dotnet_root / "D3D11MaterialViewport.Overlay.cs").read_text(encoding="utf-8"),
        "hlsl_source": (dotnet_root / "D3D11MaterialShaders.hlsl").read_text(encoding="utf-8"),
        "camera_source": (dotnet_root / "NetViewportCamera.cs").read_text(encoding="utf-8"),
        "build_script": (root / "build_pyside6_app.ps1").read_text(encoding="utf-8"),
    }


def test_dotnet_experiment_renderer_source_contract() -> None:
    context = _dotnet_source_context()
    source = context["source"]
    gpu_source = context["gpu_source"]
    d3d_source = context["d3d_source"]
    d3d_overlay_source = context["d3d_overlay_source"]
    hlsl_source = context["hlsl_source"]
    camera_source = context["camera_source"]
    assert "D3D11MaterialViewport" in d3d_source
    assert "Vortice.Direct3D11" in d3d_source
    assert "CreateSwapChainForHwnd" in d3d_source
    assert "CreateInputLayout" in d3d_source
    assert "CreateShaderResourceView" in d3d_source
    assert "D3D11MaterialShaders.hlsl" in d3d_source
    assert "ResolveShaderPath" in d3d_source
    assert "GetManifestResourceStream" in d3d_source
    assert "cdmw-dotnet-mesh-editor-shaders" in d3d_source
    assert "DrawD3D11Overlay()" in d3d_overlay_source
    assert "DrawD3D11Overlay(e.Graphics)" not in d3d_source
    assert "ProjectOverlayVertex" not in d3d_overlay_source
    assert "DrawOverlayPrimitive" in d3d_overlay_source
    assert "PrimitiveTopology.LineList" in d3d_overlay_source
    assert "PrimitiveTopology.TriangleList" in d3d_overlay_source
    assert "ResourceUsage.Dynamic" in d3d_overlay_source
    assert "CpuAccessFlags.Write" in d3d_overlay_source
    assert "MapMode.WriteDiscard" in d3d_overlay_source
    assert "MapMode.WriteNoOverwrite" not in d3d_overlay_source
    assert "using var vertexBuffer = _device.CreateBuffer" not in d3d_overlay_source
    assert "Graphics" not in d3d_overlay_source
    assert "VSOverlay" in hlsl_source
    assert "PSOverlay" in hlsl_source
    assert "TryInitialize(out string error)" in d3d_source
    assert "CDMW_MESH_DOTNET_FORCE_D3D11_FAILURE" in d3d_source
    assert "CDMW_MESH_DOTNET_FORCE_D3D11_PRESENT_FAILURE" in d3d_source
    assert "TryResetDeviceAfterLoss" in d3d_source
    assert "DeviceRemovedReason" in d3d_source
    assert "FrameRendered" in d3d_source
    assert "BackendUnavailable" in d3d_source
    assert "DrawD3D11WireOverlay" in d3d_overlay_source
    assert "DrawSelectedFacesOverlay" in d3d_overlay_source
    assert "DrawSelectedSourcesOverlay" in d3d_overlay_source
    assert "overlayDepthDescription.DepthFunc = ComparisonFunction.LessEqual" in d3d_source
    assert "DrawXRayOverlayMarker" in d3d_overlay_source
    assert "static NetViewportCamera Create" in camera_source
    assert "WorldViewProjectionRowMajorArray" in camera_source
    assert "Vector3.Cross(forward, right)" in camera_source
    assert "BuildCameraMatrices()" not in d3d_source
    assert "UpdateCamera(NetViewportCamera camera)" in d3d_source
    assert "UpdateCamera(NetViewportCamera camera)" in gpu_source
    assert "_camera.Project" in source
    assert "_pitch = -1.35f" in source
    assert "_pitch = 1.35f" in source
    assert "matrices.WorldViewProjection" not in d3d_overlay_source
    assert "MaterialDebugMode" in d3d_source
    assert "MaterialDebugMode" in hlsl_source
    assert "Material debug" not in source
    assert "float2 MarkerOffset : TEXCOORD0;" in hlsl_source
    assert "clip(1.0f - dot(input.MarkerOffset, input.MarkerOffset));" in hlsl_source
    assert "_textureSrvCache" in d3d_source
    assert "ClearTextureCache" in d3d_source
    assert "UnbindGeometryResources" in d3d_source
    assert "CDMW_MESH_DOTNET_D3D11_NO_VSYNC" in d3d_source
    assert "SetMaximumFrameLatency(1)" in d3d_source
    assert "SwapEffect.FlipDiscard" in d3d_source
    assert "SwapEffect.Discard" not in d3d_source
    assert "AveragePresentMs" in source
    assert "AverageRenderMs" in source
    assert "AverageFrameIntervalMs" in source
    assert "FrameIntervalP95Ms" in source
    assert "FramePacingJitterMs" in source
    assert "AverageDirtyToPresentMs" in source
    assert "DroppedFrames" in source
    assert "ConsumeRenderRequest" in source
    assert "SHA256.HashData" in d3d_source
    assert "shaderHash" in d3d_source
    assert "UpdateOverlay" in d3d_source
    assert "Texture2D NormalTexture" in hlsl_source
    assert "PSMain" in hlsl_source
    assert "SampleNormal" in hlsl_source
    assert "MaterialHasRoughness" in hlsl_source
    assert "WpfGpuMeshViewport" in gpu_source
    assert "Viewport3D" in gpu_source
    assert "OrthographicCamera" in gpu_source
    assert "MeshGeometry3D" in gpu_source
    assert "geometry.Normals.Add" in gpu_source
    assert "NormalForCorner" in gpu_source
    assert "NormalFromMap" in gpu_source
    assert "FaceTangentSpace" in gpu_source
    assert "FallbackTangentSpace" in gpu_source
    assert "FaceNormal" in gpu_source
    assert "DiffuseMaterial" in gpu_source
    assert "ImageBrush" in gpu_source
    assert "EmissiveMaterial" in gpu_source
    assert "TextureBrushForPath" in gpu_source
    assert "BitmapSourceFromBitmap" in gpu_source
    assert "SpecularBrushForSubmesh" in gpu_source
    assert "SpecularPowerForSubmesh" in gpu_source
    assert "AverageColorForPath" in source
    assert "AverageBrightnessForPath" in source
    assert "UpdateOverlay" in gpu_source
    assert "ElementHost" in source
    assert "InitializeGpuViewport" in source
    assert "RendererStatusPayload" in source
    assert "ActiveCapabilities()" in source
    assert "d3d11_overlay_vertices_edges_faces_parts_wire_xray" in source
    assert "wpf_viewport3d_gpu" in source
    assert "wpf_gpu_material_renderer" in source
    assert "d3d11_vortice_hlsl_material_renderer" in source
    assert "NetDdsTextureInfo" in source
    assert "DecodeDds" in source
    assert "DxgiDecodeKey" in source
    assert "DecodeBc1" in source
    assert "DecodeBc3" in source
    assert "DecodeBc4" in source
    assert "DecodeBc5" in source
    assert "DecodeRgba32" in source
    assert "DecodeBgra32" in source
    assert "DecodeR8" in source
    assert "DecodeRg8" in source
    assert "DecodeUncompressed32" in source
    assert "DdsDecodedCount" in source
    assert "DecodeDdsWithCdTextureDx" in source
    assert "FindCdTextureDxExecutable" in source
    assert "CDMW_CD_TEXTURE_DX_EXE" in source
    assert "batch-preview-json" in source
    assert "cd-texture-dx.exe" in source
    retired_name = "Tex" + "conv"
    assert f"DecodeDdsWith{retired_name}" not in source
    assert f"Find{retired_name}Executable" not in source
    assert ("CDMW_" + retired_name.upper() + "_EXE") not in source


def test_dotnet_wire_overlay_style_contract() -> None:
    context = _dotnet_source_context()
    source = context["source"]
    d3d_source = context["d3d_source"]
    d3d_overlay_source = context["d3d_overlay_source"]
    hlsl_source = context["hlsl_source"]

    assert "DefaultWireWidthPixels = 1.35f" in source
    assert "DefaultVertexMarkerSizePixels = 7.0f" in source
    assert "_wireOverlayColor = OverlayColor(0, 0, 0, 225)" in d3d_overlay_source
    assert "_vertexOverlayColor = OverlayColor(255, 174, 40, 255)" in d3d_overlay_source
    assert "XRayWireOverlayColor = OverlayColor(245, 248, 252, 240)" in d3d_overlay_source
    assert "XRayVertexOverlayColor = OverlayColor(255, 88, 214, 255)" in d3d_overlay_source
    assert "_overlayShowXRay ? XRayWireOverlayColor : _wireOverlayColor" in d3d_overlay_source
    assert "_overlayShowXRay ? XRayVertexOverlayColor : _vertexOverlayColor" in d3d_overlay_source
    assert "SetOverlaySettings(MeshOverlaySettings settings)" in d3d_overlay_source
    assert "lineWidthPixels: _overlaySettings.Sizing.WireWidthPixels" in d3d_overlay_source
    assert "command.LineWidthPixels > 1.0f" in d3d_overlay_source
    assert "GSWireLine" in hlsl_source
    assert "halfWidthPixels" in hlsl_source
    assert "_wireGeometryShader" in d3d_source
    assert '["wire_overlay_width_pixels"] = _overlaySettings.Sizing.WireWidthPixels' in d3d_source
    assert '["vertex_marker_fit_size_pixels"] = _overlaySettings.Sizing.VertexMarkerSizePixels' in d3d_source


def test_dotnet_experiment_headless_smoke_reports_metrics() -> None:
    context = _dotnet_source_context()
    root = context["root"]
    source = context["source"]
    gpu_source = context["gpu_source"]
    d3d_source = context["d3d_source"]
    d3d_overlay_source = context["d3d_overlay_source"]
    hlsl_source = context["hlsl_source"]
    camera_source = context["camera_source"]
    build_script = context["build_script"]
    assert '"dds_resources"]' in source
    assert '"dds_decoded_resources"]' in source
    assert '"native_dds_mip_chain_with_bitmap_generated_mips"' in source
    assert '"native_dds_mip_chain"' in source
    assert '"bitmap_bgra32_generated_mip_chain_or_unavailable"' in source
    assert '"native_dds_parity"] = false' in source
    assert "MaterialNormalYInverted" in source
    assert '"dds_native_dxgi_upload"] = _d3d11Viewport?.NativeDdsTextureCount > 0' in source
    assert '"renderer_blocked"]' in source
    assert '"blocked_renderer_unavailable"' in source
    assert "ProductionD3D11Required" in source
    assert "DeveloperRendererFallback" in source
    assert "developer-renderer-fallback" in source
    assert '"dds_upload_format"] = "per_resource_dxgi_view"' in source
    assert '"source_dds_native_mip_chain_with_optional_bitmap_edit_fallback"' in source
    assert '"bitmap_decode_then_bgra32_generated_mip_chain"' in source
    assert '"dds_decode_tools"]' in source
    assert '"header_verified_not_sampled"' in source
    assert '"material_contract_gap"]' in source
    assert "ApplyHeadlessSmokeEdit(document)" in source
    assert "X = vertex.X + 0.001f" in source
    assert "HeadlessRenderer.Measure(document)" in source
    assert '"replace_positions_same_count"' in source
    assert '"average_fps"' in source
    assert '"frame_time_ms"' in source
    assert '"render_time_ms"' in source
    assert '"frame_interval_ms"' in source
    assert '"frame_interval_p95_ms"' in source
    assert '"frame_pacing_jitter_ms"' in source
    assert '"responsiveness_ms"' in source
    assert "public void RefreshBounds()" in source
    assert "public bool ShowSolid" in source
    assert "public bool ShowWire" in source
    assert '"parent-hwnd"' in source
    assert "dotnet_close_requested.txt" in source
    assert "FormBorderStyle.None" in source
    assert "BringEmbeddedChildToFront" in source
    assert "SetFocus(form.Handle)" in source
    assert "EnableWindow(form.Handle, true)" in source
    assert "_viewport.Focus()" in source
    assert "WriteProtocolEvent(\"ready\"" in source
    assert "WriteProtocolEvent(\"metrics\"" in source
    assert "\"select_request\"" in source
    assert "\"stroke_begin\"" in source
    assert "\"command_request\"" in source
    assert "WriteCommandRequest(command);" in source
    assert "TryHandleLocalCommand(command, targetMode)" not in source
    assert "RequestTransformMove" in source
    assert "TranslateSelected" not in source
    assert "\"selection_depth_mode\"" in source
    assert "\"edges_by_submesh\"" in source
    assert "\"source_indices\"" in source
    assert "JsonEdgeSelectionMap" in source
    assert "EdgeByVertices" in source
    assert "Renderer ready, waiting for first frame" in source
    assert "\"has_rendered_frame\"" in source
    assert "\"frame_count\"" in source
    assert "WorldViewProjection" in camera_source
    assert "ApplyPreviewVertexUpdate" in source
    assert "ApplyPreviewTriangleUpdate" in source
    assert "BuildPresentationViewportRegion()" in source
    assert "Mesh Edit Session" in source
    assert "Preview mode" in source
    assert "_previewMode.SelectedIndex = 5;" in source
    assert "ShowXRay" in source
    assert "ApplySelectionUpdate" in source
    assert "UpdateSelection" in source
    assert "SelectVertexAt" in source
    assert "SelectFaceAt" in source
    assert "SelectPartAt" in source
    assert "PickVertexAt" in source
    assert "PickFaceAt" in source
    assert "PickPartAt" in source
    assert "PointInTriangle" in source
    assert "BeginSelectionDrag" in source
    assert "VertexIdsInRectangle" in source
    assert "FaceIdsInRectangle" in source
    assert "PartIdsInRectangle" in source
    assert "ApplySelectionMapOperation" in source
    assert "ApplyPartSelectionOperation" in source
    assert "SubmeshSelectedRequested" in source
    assert "TryHandleLocalCommand" in source
    assert "SelectionSnapshotPayload" in source
    assert "ClearSelectionForTarget" in source
    assert "SelectAllForTarget" in source
    assert "InvertSelectionForTarget" in source
    assert "GrowSelectionForTarget" in source
    assert "ShrinkSelectionForTarget" in source
    assert "RebuildPartAdjacency" in source
    assert "PartNeighbors" in source
    assert "SubmeshesAdjacent" in source
    assert "BoundsTouchOrOverlap" in source
    assert "EdgeById" in source
    assert "EditableVertexIndicesForSubmesh" in source
    assert "SetCameraPreset" in source
    assert "RotateYawDegrees" in source
    tab_source = mesh_editor_tab_source(root)
    assert "_confirm_dotnet_process_started" in tab_source
    assert "_dotnet_process_diagnostics" in tab_source
    assert "mesh_dotnet_renderer_blockers" in tab_source
    assert "mesh_dotnet_material_parity_warnings" in tab_source
    assert "mesh_editor/developer_renderer_fallback" in tab_source
    assert "NetEdgeTopology.Build" in source
    assert "stable_edge_descriptors" in source
    assert "edge_descriptors" in source
    assert "topology_generation" in source
    assert "StableKey" in source
    assert "EdgeByStableKey" in source
    assert "PickEdgeAt" in source
    assert "BeginEdgeDrag" in source
    assert "FinishEdgeDrag" in source
    assert "EdgeIdsInRectangle" in source
    assert "SegmentIntersectsRectangle" in source
    assert "DrawEdgeSelectionRectangle" in source
    assert "AddSelectionRectangle" in gpu_source
    assert "DrawSelectedEdges" in source
    assert "ApplyEdgeSelectionOperation" in source
    assert "NetMaterialSet.Load" in source
    assert "NetTextureSet.Load" in source
    assert "TryDrawTexturedFace" in source
    assert "DrawAffineTexturedTriangle" in source
    assert "MaterialsPath" in source
    assert "material_manifest" in source
    assert "decoded_texture_resources" in source
    assert "authority_contract" in source
    assert "dotnet_viewport_python_cpp_validation" in source
    assert "native_authoritative_operation_required" in source
    assert "release_preflight.py" in build_script
    assert "private PointF Project" not in source
    assert "MathF.Cos(_yaw)" not in source
    assert "MathF.Sin(_yaw)" not in source
    assert "_document.Bounds()" not in camera_source
