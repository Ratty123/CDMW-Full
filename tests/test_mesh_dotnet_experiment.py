from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from cdmw.modding.mesh_parser import ParsedMesh, SubMesh
from cdmw.services import mesh_dotnet_experiment
from cdmw.services.mesh_dotnet_experiment import (
    MESH_DOTNET_EXPERIMENT_BINARY_NAME,
    MeshDotNetExperimentPackage,
    build_mesh_dotnet_experiment_package,
    default_mesh_dotnet_experiment_editor_path,
    find_mesh_dotnet_experiment_editor,
    import_mesh_dotnet_experiment_output,
    mesh_dotnet_experiment_command,
    mesh_dotnet_experiment_evaluation_path,
    mesh_dotnet_experiment_output_obj_path,
    mesh_dotnet_material_parity_warnings,
    mesh_dotnet_renderer_blockers,
    write_mesh_dotnet_experiment_evaluation,
)
from cdmw.workers import mesh_editor_workers
from scripts.release_preflight import classify_git_status, release_blockers


def _mesh() -> ParsedMesh:
    return ParsedMesh(
        path="character/body.pac",
        format="pac",
        submeshes=[
            SubMesh(
                name="body",
                material="skin",
                texture="skin.dds",
                vertices=[(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0)],
                uvs=[(0.0, 0.0), (1.0, 0.0), (0.0, 1.0)],
                normals=[(0.0, 0.0, 1.0)] * 3,
                faces=[(0, 1, 2)],
                source_vertex_map=[0, 1, 2],
                source_index_count=3,
            )
        ],
        total_vertices=3,
        total_faces=1,
        has_uvs=True,
    )


def test_dotnet_experiment_editor_finder_prefers_env_path(tmp_path: Path, monkeypatch) -> None:
    exe_path = tmp_path / MESH_DOTNET_EXPERIMENT_BINARY_NAME
    exe_path.write_text("fake", encoding="utf-8")
    monkeypatch.setenv("CDMW_MESH_DOTNET_EXPERIMENT_EXE", str(exe_path))

    assert find_mesh_dotnet_experiment_editor() == exe_path


def test_dotnet_experiment_editor_finder_prefers_source_build_before_stale_publish(
    tmp_path: Path,
    monkeypatch,
) -> None:
    tools_exe = tmp_path / "tools" / "dotnet_mesh_editor_experiment" / "bin" / "Release" / "net8.0-windows" / MESH_DOTNET_EXPERIMENT_BINARY_NAME
    native_exe = tmp_path / "native" / "cdmw_mesh_dotnet_editor" / "build" / "Release" / MESH_DOTNET_EXPERIMENT_BINARY_NAME
    tools_exe.parent.mkdir(parents=True)
    native_exe.parent.mkdir(parents=True)
    tools_exe.write_text("fresh", encoding="utf-8")
    native_exe.write_text("stale", encoding="utf-8")
    monkeypatch.delenv("CDMW_MESH_DOTNET_EXPERIMENT_EXE", raising=False)
    monkeypatch.setattr(mesh_dotnet_experiment, "_repo_root", lambda: tmp_path)

    assert find_mesh_dotnet_experiment_editor() == tools_exe


def test_dotnet_experiment_editor_finder_finds_pyinstaller_nested_native_build(
    tmp_path: Path,
    monkeypatch,
) -> None:
    exe_path = tmp_path / "native" / "cdmw_mesh_dotnet_editor" / "build" / "Release" / MESH_DOTNET_EXPERIMENT_BINARY_NAME
    exe_path.parent.mkdir(parents=True)
    exe_path.write_text("bundled", encoding="utf-8")
    monkeypatch.delenv("CDMW_MESH_DOTNET_EXPERIMENT_EXE", raising=False)
    monkeypatch.setattr(mesh_dotnet_experiment.sys, "_MEIPASS", str(tmp_path), raising=False)

    assert find_mesh_dotnet_experiment_editor() == exe_path


def test_dotnet_experiment_default_editor_path_points_at_packaged_build_dir() -> None:
    path = default_mesh_dotnet_experiment_editor_path(release=True)

    assert path.parts[-5:] == ("native", "cdmw_mesh_dotnet_editor", "build", "Release", MESH_DOTNET_EXPERIMENT_BINARY_NAME)


def test_dotnet_experiment_packaging_scripts_publish_and_bundle_helper() -> None:
    root = Path(__file__).resolve().parents[1]
    build_script = (root / "build_pyside6_app.ps1").read_text(encoding="utf-8")
    spec_source = (root / "CrimsonDesertModWorkbench.spec").read_text(encoding="utf-8")
    csproj_source = (root / "tools" / "dotnet_mesh_editor_experiment" / "Cdmw.MeshEditorExperiment.csproj").read_text(encoding="utf-8")

    assert "<UseWPF>true</UseWPF>" in csproj_source
    assert "Vortice.Direct3D11" in csproj_source
    assert "Vortice.DXGI" in csproj_source
    assert "Vortice.D3DCompiler" in csproj_source
    assert "D3D11MaterialShaders.hlsl" in csproj_source
    assert "EmbeddedResource Include=\"D3D11MaterialShaders.hlsl\"" in csproj_source
    assert "Invoke-DotNetMeshEditorBuild -Configuration $nativeConfig" in build_script
    assert "dotnet_mesh_editor_experiment\\Cdmw.MeshEditorExperiment.csproj" in build_script
    assert "native\\cdmw_mesh_dotnet_editor\\build\\$Configuration" in build_script
    assert (root / "schemas" / "mesh" / "mesh.cdmeta.schema.json").is_file()
    assert '_add_data_tree_if_exists(datas, "schemas", "schemas", suffixes={".json"})' in spec_source
    assert "_add_native_binary_tree" in spec_source
    assert "native/cdmw_mesh_dotnet_editor/build/Release" in spec_source
    assert "native/cdmw_mesh_dotnet_editor/build/Debug" in spec_source
    assert "native/cdmw_d3d11_preview/build/bin/Release/texconv.exe" in spec_source
    assert "native/cdmw_d3d11_preview/build/bin/Debug/texconv.exe" in spec_source
    assert "suffixes={\".exe\", \".dll\", \".json\", \".pdb\"}" in spec_source


def test_dotnet_experiment_headless_smoke_reports_metrics() -> None:
    root = Path(__file__).resolve().parents[1]
    dotnet_root = root / "tools" / "dotnet_mesh_editor_experiment"
    source = "\n".join(
        path.read_text(encoding="utf-8")
        for path in sorted(dotnet_root.glob("*.cs"))
        if path.name != "Cdmw.MeshEditorExperiment.GlobalUsings.g.cs"
    )
    gpu_source = (root / "tools" / "dotnet_mesh_editor_experiment" / "WpfGpuMeshViewport.cs").read_text(encoding="utf-8")
    d3d_source = (root / "tools" / "dotnet_mesh_editor_experiment" / "D3D11MaterialViewport.cs").read_text(encoding="utf-8")
    d3d_overlay_source = (root / "tools" / "dotnet_mesh_editor_experiment" / "D3D11MaterialViewport.Overlay.cs").read_text(encoding="utf-8")
    hlsl_source = (root / "tools" / "dotnet_mesh_editor_experiment" / "D3D11MaterialShaders.hlsl").read_text(encoding="utf-8")
    camera_source = (root / "tools" / "dotnet_mesh_editor_experiment" / "NetViewportCamera.cs").read_text(encoding="utf-8")
    build_script = (root / "build_pyside6_app.ps1").read_text(encoding="utf-8")

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
    assert "Material debug" in source
    assert "_textureSrvCache" in d3d_source
    assert "TextureCacheKey" in d3d_source
    assert "ClearTextureCache" in d3d_source
    assert "UnbindGeometryResources" in d3d_source
    assert "CDMW_MESH_DOTNET_D3D11_NO_VSYNC" in d3d_source
    assert "AveragePresentMs" in source
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
    assert "DecodeDdsWithTexconv" in source
    assert "FindTexconvExecutable" in source
    assert "CDMW_TEXCONV_EXE" in source
    assert "DecodeDdsWithCdTextureDx" in source
    assert "FindCdTextureDxExecutable" in source
    assert "CDMW_CD_TEXTURE_DX_EXE" in source
    assert "batch-preview-json" in source
    assert "cd-texture-dx.exe" in source
    assert '"dds_resources"]' in source
    assert '"dds_decoded_resources"]' in source
    assert '"dds_upload_mode"] = "bitmap_rgba_upload"' in source
    assert '"native_dds_parity"] = false' in source
    assert '"dds_native_dxgi_upload"] = false' in source
    assert '"renderer_blocked"]' in source
    assert '"blocked_renderer_unavailable"' in source
    assert "ProductionD3D11Required" in source
    assert "DeveloperRendererFallback" in source
    assert "developer-renderer-fallback" in source
    assert '"dds_upload_format"] = "B8G8R8A8_UNorm"' in source
    assert '"bitmap_decode_then_bgra32_upload"' in source
    assert '"dds_decode_tools"]' in source
    assert '"header_verified_not_sampled"' in source
    assert '"material_contract_gap"]' in source
    assert "ApplyHeadlessSmokeEdit(document)" in source
    assert "X = vertex.X + 0.001f" in source
    assert "HeadlessRenderer.Measure(document)" in source
    assert '"replace_positions_same_count"' in source
    assert '"average_fps"' in source
    assert '"frame_time_ms"' in source
    assert '"responsiveness_ms"' in source
    assert "public void RefreshBounds()" in source
    assert "public bool ShowSolid" in source
    assert "public bool ShowWire" in source
    assert '"parent-hwnd"' in source
    assert "dotnet_close_requested.txt" in source
    assert "FormBorderStyle.None" in source
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
    assert "WorldViewProjection()" in source
    assert "ApplyPreviewVertexUpdate" in source
    assert "ApplyPreviewTriangleUpdate" in source
    assert "BuildToolPanel()" in source
    assert "DotNetMeshEditorToolPanel" in source
    assert "Mesh Edit Session" in source
    assert "Preview mode" in source
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
    tab_source = (root / "cdmw" / "ui" / "mesh_editor" / "tab.py").read_text(encoding="utf-8")
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
    assert "DisabledButton(\"Copy\"" in source
    assert "metadata-preserving paste" in source
    assert "authority_contract" in source
    assert "dotnet_viewport_python_cpp_validation" in source
    assert "native_authoritative_operation_required" in source
    assert "release_preflight.py" in build_script
    assert "private PointF Project" not in source
    assert "MathF.Cos(_yaw)" not in source
    assert "MathF.Sin(_yaw)" not in source
    assert "_document.Bounds()" not in camera_source


def test_dotnet_experiment_package_reuses_obj_sidecar_contract(tmp_path: Path, monkeypatch) -> None:
    def fake_export_obj(mesh: ParsedMesh, output_dir: str, name: str = "", **_kwargs: object) -> list[str]:
        root = Path(output_dir)
        obj = root / f"{name}.obj"
        mtl = root / f"{name}.mtl"
        sidecar = root / f"{name}.obj.meta.json"
        obj.write_text("o body\nv 0 0 0\nv 1 0 0\nv 0 1 0\nf 1 2 3\n", encoding="utf-8")
        mtl.write_text("newmtl skin\n", encoding="utf-8")
        sidecar.write_text(
            json.dumps(
                {
                    "format": "mesh_roundtrip_manifest_v2",
                    "source_asset_hash": "abc123",
                    "source_format": mesh.format,
                }
            ),
            encoding="utf-8",
        )
        return [str(obj), str(mtl), str(sidecar)]

    monkeypatch.setattr(mesh_dotnet_experiment, "export_obj", fake_export_obj)

    mesh = _mesh()
    preview_png = tmp_path / "skin_preview.png"
    preview_dds = tmp_path / "skin_n.dds"
    emissive_png = tmp_path / "skin_emissive.png"
    preview_png.write_bytes(b"preview-png")
    preview_dds.write_bytes(b"preview-dds")
    emissive_png.write_bytes(b"emissive-png")
    mesh.submeshes[0].preview_texture_path = str(preview_png)
    mesh.submeshes[0].preview_normal_texture_dds_path = str(preview_dds)
    mesh.submeshes[0].preview_material_texture_inputs = (SimpleNamespace(semantic_type="emissive", source_path=emissive_png),)
    package = build_mesh_dotnet_experiment_package(mesh, output_root=tmp_path)

    assert package.mesh_path.name == "mesh.obj"
    assert package.cdmeta_path.read_text(encoding="utf-8") == package.obj_sidecar_path.read_text(encoding="utf-8")
    assert package.original_asset_hash_path.read_text(encoding="utf-8") == "abc123"
    launch = json.loads(package.launch_manifest_path.read_text(encoding="utf-8"))
    assert launch["format"] == "cdmw_mesh_dotnet_experiment_handoff_v1"
    assert launch["interchange_format"] == "obj_sidecar"
    assert launch["metadata_risk"] is True
    assert launch["requires_edit_operations"] is True
    assert launch["output"]["edit_operations_required"] is True
    assert launch["parser_authority"] == "cdmw_python_cpp"
    assert launch["rebuild_authority"] == "cdmw_python_cpp"
    assert launch["input"]["metadata"] == "mesh.cdmeta.json"
    assert launch["input"]["materials"] == "net_materials.json"
    material_payload = json.loads((package.package_dir / "net_materials.json").read_text(encoding="utf-8"))
    assert material_payload["format"] == "cdmw_mesh_dotnet_materials_v1"
    assert material_payload["renderer_authority"] == "dotnet_mesh_editor"
    assert material_payload["material_slots"][0]["texture"] == "skin.dds"
    assert material_payload["material_slots"][0]["channels"]["normal"] == "skin_n.dds"
    assert material_payload["submeshes"][0]["resolved_channels"]["base"].endswith("skin_preview.png")
    assert material_payload["submeshes"][0]["resolved_channels"]["normal"].endswith("skin_n.dds")
    assert material_payload["submeshes"][0]["resolved_channels"]["emissive"].endswith("skin_emissive.png")
    packaged_base = material_payload["submeshes"][0]["packaged_channels"]["base"]
    packaged_normal = material_payload["submeshes"][0]["packaged_channels"]["normal"]
    packaged_emissive = material_payload["submeshes"][0]["packaged_channels"]["emissive"]
    assert packaged_base.startswith("textures/base_")
    assert packaged_normal.startswith("textures/normal_")
    assert packaged_emissive.startswith("textures/emissive_")
    assert (package.package_dir / packaged_base).is_file()
    assert (package.package_dir / packaged_normal).is_file()
    assert (package.package_dir / packaged_emissive).is_file()
    assert material_payload["submeshes"][0]["packaged_texture_count"] >= 3
    assert "emissive" in material_payload["texture_channels"]

    program, args = mesh_dotnet_experiment_command("C:/tools/MeshEditorExperiment.exe", package)
    assert Path(program) == Path("C:/tools/MeshEditorExperiment.exe")
    assert "--input-package" in args
    assert str(package.package_dir) in args
    assert "--edit-operations" in args
    assert str(package.edit_operations_path) in args
    assert "--evaluation" in args
    assert str(mesh_dotnet_experiment_evaluation_path(package)) in args
    _program, embedded_args = mesh_dotnet_experiment_command(
        "C:/tools/MeshEditorExperiment.exe",
        package,
        embedded_parent_hwnd=12345,
    )
    assert "--embedded" in embedded_args
    assert "--parent-hwnd" in embedded_args
    assert "12345" in embedded_args
    _program, developer_args = mesh_dotnet_experiment_command(
        "C:/tools/MeshEditorExperiment.exe",
        package,
        embedded_parent_hwnd=12345,
        developer_renderer_fallback=True,
    )
    assert "--developer-renderer-fallback" in developer_args


def test_dotnet_renderer_status_blocks_degraded_embedded_production_backend() -> None:
    payload = {"renderer": {"backend": "wpf_viewport3d_gpu"}}

    blockers = mesh_dotnet_renderer_blockers(payload, embedded=True, developer_override=False)

    assert blockers == ("embedded production .NET renderer cannot use degraded backend: wpf_viewport3d_gpu",)
    assert mesh_dotnet_renderer_blockers(payload, embedded=True, developer_override=True) == ()


def test_dotnet_renderer_status_blocks_missing_material_parity_when_required() -> None:
    payload = {
        "renderer": {
            "backend": "d3d11_vortice_shader",
            "native_dds_parity": False,
            "dds_native_dxgi_upload": False,
            "dds_upload_mode": "bitmap_rgba_upload",
            "material_contract_gap": ["direct compressed DDS upload parity"],
        }
    }

    warnings = mesh_dotnet_material_parity_warnings(payload)
    blockers = mesh_dotnet_renderer_blockers(payload, require_material_parity=True)

    assert "native DDS parity is not available" in warnings
    assert "native DXGI DDS upload is not available" in warnings
    assert blockers
    assert blockers[0].startswith("material parity incomplete:")
    assert mesh_dotnet_renderer_blockers(payload, require_material_parity=True, developer_override=True) == ()


def test_dotnet_renderer_status_blocks_explicit_renderer_unavailable() -> None:
    payload = {"renderer": {"backend": "blocked_renderer_unavailable", "renderer_block_reason": "D3D11 failed"}}

    assert mesh_dotnet_renderer_blockers(payload) == ("blocked_renderer_unavailable: D3D11 failed",)


def test_dotnet_experiment_output_import_uses_output_obj_sidecar_and_operations(
    tmp_path: Path,
    monkeypatch,
) -> None:
    package_dir = tmp_path / "package"
    output_dir = package_dir / "output"
    output_dir.mkdir(parents=True)
    package = MeshDotNetExperimentPackage(
        package_dir=package_dir,
        mesh_path=package_dir / "mesh.obj",
        obj_sidecar_path=package_dir / "mesh.obj.meta.json",
        cdmeta_path=package_dir / "mesh.cdmeta.json",
        original_asset_hash_path=package_dir / "original_asset_hash.txt",
        status_path=package_dir / "dotnet_status.json",
        output_dir=output_dir,
        edit_operations_path=output_dir / "edit_operations.json",
        launch_manifest_path=package_dir / "dotnet_launch.json",
    )
    package.mesh_path.write_text("input", encoding="utf-8")
    package.obj_sidecar_path.write_text(json.dumps({"format": "mesh_roundtrip_manifest_v2"}), encoding="utf-8")
    output_obj = output_dir / "mesh.obj"
    output_obj.write_text("edited", encoding="utf-8")
    package.edit_operations_path.write_text(
        json.dumps(
            [
                {
                    "operation": "replace_positions_same_count",
                    "lod_index": 0,
                    "submesh_index": 0,
                    "vertex_count": 3,
                    "source": "mesh.obj",
                }
            ]
        ),
        encoding="utf-8-sig",
    )

    imported = _mesh()

    def fake_import_obj(path: str) -> ParsedMesh:
        assert Path(path) == output_obj
        assert Path(f"{path}.meta.json").is_file()
        return imported

    monkeypatch.setattr(mesh_dotnet_experiment, "import_obj", fake_import_obj)

    assert mesh_dotnet_experiment_output_obj_path(package, {"edited_package": "output"}) == output_obj
    mesh = import_mesh_dotnet_experiment_output(package, {"edited_package": "output"})

    assert mesh is imported
    assert getattr(mesh, "_cdmw_edit_operations")[0]["operation"] == "replace_positions_same_count"
    assert getattr(mesh, "_cdmw_dotnet_authority_contract") == "dotnet_viewport_python_cpp_validation"


def test_dotnet_experiment_output_import_rejects_missing_operation_records(
    tmp_path: Path,
    monkeypatch,
) -> None:
    package_dir = tmp_path / "package"
    output_dir = package_dir / "output"
    output_dir.mkdir(parents=True)
    package = MeshDotNetExperimentPackage(
        package_dir=package_dir,
        mesh_path=package_dir / "mesh.obj",
        obj_sidecar_path=package_dir / "mesh.obj.meta.json",
        cdmeta_path=package_dir / "mesh.cdmeta.json",
        original_asset_hash_path=package_dir / "original_asset_hash.txt",
        status_path=package_dir / "dotnet_status.json",
        output_dir=output_dir,
        edit_operations_path=output_dir / "edit_operations.json",
        launch_manifest_path=package_dir / "dotnet_launch.json",
    )
    package.mesh_path.write_text("input", encoding="utf-8")
    package.obj_sidecar_path.write_text(json.dumps({"format": "mesh_roundtrip_manifest_v2"}), encoding="utf-8")
    (output_dir / "mesh.obj").write_text("edited", encoding="utf-8")
    monkeypatch.setattr(mesh_dotnet_experiment, "import_obj", lambda _path: _mesh())

    try:
        import_mesh_dotnet_experiment_output(package, {"edited_package": "output"})
    except ValueError as exc:
        assert "authoritative edit operation records" in str(exc)
    else:
        raise AssertionError("missing edit operations should be rejected")


def test_release_preflight_blocks_generated_and_unclassified_source() -> None:
    inventory = classify_git_status(
        [
            "?? tools/dotnet_mesh_editor_experiment/bin/Release/app.dll",
            "?? cdmw/new_feature.py",
            "?? scratch/new_feature.py",
            "?? tests/test_new_feature.py",
            " M cdmw/services/mesh_service.py",
            "?? notes.tmp",
        ]
    )

    assert inventory["generated_output"] == ["tools/dotnet_mesh_editor_experiment/bin/Release/app.dll"]
    assert inventory["unclassified_untracked_source"] == ["scratch/new_feature.py"]
    assert inventory["required_source_or_docs"] == [
        "cdmw/new_feature.py",
        "cdmw/services/mesh_service.py",
        "tests/test_new_feature.py",
    ]
    assert release_blockers(inventory) == ["generated_output_present", "unclassified_untracked_source_present"]


def test_dotnet_experiment_evaluation_writes_keep_drop_note(tmp_path: Path) -> None:
    package_dir = tmp_path / "package"
    output_dir = package_dir / "output"
    output_dir.mkdir(parents=True)
    package = MeshDotNetExperimentPackage(
        package_dir=package_dir,
        mesh_path=package_dir / "mesh.obj",
        obj_sidecar_path=package_dir / "mesh.obj.meta.json",
        cdmeta_path=package_dir / "mesh.cdmeta.json",
        original_asset_hash_path=package_dir / "original_asset_hash.txt",
        status_path=package_dir / "dotnet_status.json",
        output_dir=output_dir,
        edit_operations_path=output_dir / "edit_operations.json",
        launch_manifest_path=package_dir / "dotnet_launch.json",
    )

    path = write_mesh_dotnet_experiment_evaluation(
        package,
        {
            "event": "saved",
            "metrics": {"average_fps": 75.0, "frame_time_ms": 13.3, "memory_mb": 512},
            "native_baseline": {"average_fps": 60.0, "frame_time_ms": 16.6, "memory_mb": 400},
        },
        validation_report=SimpleNamespace(ok=True, blockers=(), warnings=("missing_tangents",)),
    )
    text = path.read_text(encoding="utf-8")

    assert path == package_dir / "dotnet_evaluation.md"
    assert "FPS" in text
    assert "75.0" in text
    assert "60.0" in text
    assert "Validation warnings: 1" in text
    assert "Keep/drop Recommendation:" in text


def test_dotnet_experiment_import_worker_writes_drop_evaluation_on_import_failure(
    tmp_path: Path,
    monkeypatch,
) -> None:
    package_dir = tmp_path / "package"
    output_dir = package_dir / "output"
    output_dir.mkdir(parents=True)
    package = MeshDotNetExperimentPackage(
        package_dir=package_dir,
        mesh_path=package_dir / "mesh.obj",
        obj_sidecar_path=package_dir / "mesh.obj.meta.json",
        cdmeta_path=package_dir / "mesh.cdmeta.json",
        original_asset_hash_path=package_dir / "original_asset_hash.txt",
        status_path=package_dir / "dotnet_status.json",
        output_dir=output_dir,
        edit_operations_path=output_dir / "edit_operations.json",
        launch_manifest_path=package_dir / "dotnet_launch.json",
    )

    def fail_import(_package: MeshDotNetExperimentPackage, _payload: object) -> ParsedMesh:
        raise ValueError("bad edit operations")

    monkeypatch.setattr(mesh_editor_workers, "import_mesh_dotnet_experiment_output", fail_import)
    worker = mesh_editor_workers.MeshDotNetExperimentOutputImportWorker(
        12,
        SimpleNamespace(),
        "session",
        package,
        {"event": "saved", "metrics": {"average_fps": 72.0}},
    )
    errors: list[tuple[int, str]] = []
    worker.error.connect(lambda request_id, message: errors.append((int(request_id), str(message))))

    worker.run()

    assert errors
    assert errors[0][0] == 12
    assert "Evaluation:" in errors[0][1]
    text = (package_dir / "dotnet_evaluation.md").read_text(encoding="utf-8")
    assert "Output validation: `blocked`" in text
    assert "Validation blockers: 1" in text
    assert "drop .NET output" in text
