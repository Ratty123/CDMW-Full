from __future__ import annotations

import json
import hashlib
import struct
from pathlib import Path
from types import SimpleNamespace

import pytest

from cdmw.domain.cancellation import RunCancelled
from cdmw.models import ModelPreviewData, ModelPreviewMesh
from cdmw.modding.mesh_parser import ParsedMesh, SubMesh
from cdmw.services import mesh_dotnet_experiment
from cdmw.services.mesh_dotnet_reference_composite import (
    apply_dotnet_native_reference_materials,
    append_dotnet_native_reference_composite,
    decode_dotnet_native_preview_package,
)
from cdmw.services.mesh_dotnet_preview_package import (
    build_dotnet_preview_prewarm_package,
    build_or_lookup_dotnet_preview_package,
    build_or_lookup_dotnet_preview_package_from_model,
    validate_dotnet_preview_package,
)
from cdmw.services.mesh_dotnet_experiment import (
    MESH_DOTNET_EXPERIMENT_BINARY_NAME,
    MeshDotNetExperimentPackage,
    build_mesh_dotnet_experiment_package,
    default_mesh_dotnet_experiment_editor_path,
    find_mesh_dotnet_experiment_editor,
    mesh_dotnet_experiment_command,
    mesh_dotnet_experiment_evaluation_path,
    mesh_dotnet_material_input_signature,
    mesh_dotnet_helper_provenance_blockers,
)


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


def test_cancelled_material_manifest_removes_partial_dotnet_package(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output_root = tmp_path / "cancelled-dotnet-package"

    def cancel_manifest(path: Path, **_kwargs: object) -> None:
        path.write_text("partial", encoding="utf-8")
        raise RunCancelled("synthetic mid-manifest cancellation")

    monkeypatch.setattr(
        mesh_dotnet_experiment,
        "_write_dotnet_material_manifest",
        cancel_manifest,
    )

    with pytest.raises(RunCancelled, match="mid-manifest cancellation"):
        build_mesh_dotnet_experiment_package(_mesh(), output_root=output_root)

    assert output_root.is_dir()
    assert not tuple(output_root.glob("package_*"))


def _provenance_payload(executable: Path, shader: Path, *, mode: str, manifest_id: str) -> dict[str, object]:
    capabilities = ["helper_build_provenance_v1", "resident_mutation_envelope_v2"]
    return {
        "capabilities": capabilities,
        "provenance": {
            "manifest_mode": mode,
            "manifest_id": manifest_id,
            "semantic_version": "2.0.0",
            "protocol_version": 2,
            "process_sha256": hashlib.sha256(executable.read_bytes()).hexdigest(),
            "shader_sha256": hashlib.sha256(shader.read_bytes()).hexdigest(),
            "renderer_backend": "d3d11_vortice_shader",
            "edit_backend": "cdmw_mesh_core_0.1",
            "capabilities": capabilities,
        },
    }


def test_helper_provenance_accepts_explicit_development_identity(tmp_path: Path) -> None:
    executable = tmp_path / "cdmw-mesh-dotnet-editor.exe"
    shader = tmp_path / "D3D11MaterialShaders.hlsl"
    executable.write_bytes(b"helper")
    shader.write_bytes(b"shader")
    payload = _provenance_payload(
        executable,
        shader,
        mode="development",
        manifest_id="development:helper:shader",
    )

    assert mesh_dotnet_helper_provenance_blockers(executable, payload) == ()


def test_helper_provenance_release_manifest_matches_all_runtime_identities(tmp_path: Path) -> None:
    executable = tmp_path / "cdmw-mesh-dotnet-editor.exe"
    shader = tmp_path / "D3D11MaterialShaders.hlsl"
    executable.write_bytes(b"release-helper")
    shader.write_bytes(b"release-shader")
    payload = _provenance_payload(executable, shader, mode="release_manifest", manifest_id="manifest-1")
    provenance = payload["provenance"]
    assert isinstance(provenance, dict)
    (tmp_path / "cdmw-mesh-dotnet-editor.manifest.json").write_text(
        json.dumps(
            {
                "manifest_id": "manifest-1",
                "semantic_version": "2.0.0",
                "protocol_version": 2,
                "executable_sha256": provenance["process_sha256"],
                "shader_sha256": provenance["shader_sha256"],
                "renderer_backend": "d3d11_vortice_shader",
                "edit_backend": "cdmw_mesh_core_0.1",
                "capabilities": provenance["capabilities"],
            }
        ),
        encoding="utf-8",
    )

    assert mesh_dotnet_helper_provenance_blockers(
        executable,
        payload,
        require_manifest=True,
    ) == ()


def test_helper_provenance_fails_closed_on_release_hash_or_manifest_mismatch(tmp_path: Path) -> None:
    executable = tmp_path / "cdmw-mesh-dotnet-editor.exe"
    shader = tmp_path / "D3D11MaterialShaders.hlsl"
    executable.write_bytes(b"release-helper")
    shader.write_bytes(b"release-shader")
    payload = _provenance_payload(executable, shader, mode="release_manifest", manifest_id="reported")
    (tmp_path / "cdmw-mesh-dotnet-editor.manifest.json").write_text(
        json.dumps(
            {
                "manifest_id": "expected",
                "semantic_version": "1.9.0",
                "protocol_version": 2,
                "executable_sha256": "0" * 64,
                "shader_sha256": "1" * 64,
                "renderer_backend": "d3d11_vortice_shader",
                "edit_backend": "cdmw_mesh_core_0.1",
                "capabilities": ["helper_build_provenance_v1"],
            }
        ),
        encoding="utf-8",
    )

    blockers = mesh_dotnet_helper_provenance_blockers(executable, payload, require_manifest=True)
    assert "helper provenance mismatch for manifest_id" in blockers
    assert "helper provenance mismatch for semantic_version" in blockers
    assert "helper provenance mismatch for executable_sha256" in blockers
    assert "helper provenance mismatch for shader_sha256" in blockers
    assert "helper provenance capability set is not covered by the release manifest" in blockers


def test_dotnet_texture_channels_seed_existing_source_texture_before_preview_overrides(tmp_path: Path) -> None:
    texture = tmp_path / "body.dds"
    texture.write_bytes(b"real-dds")
    source = SimpleNamespace(texture=str(texture), preview_material_texture_inputs=())

    channels = mesh_dotnet_experiment._dotnet_resolved_texture_channels(source)

    assert {channels[key] for key in ("base", "albedo", "diffuse")} == {str(texture)}
    packaged = mesh_dotnet_experiment._copy_dotnet_texture_channel_resources(channels, tmp_path / "package", {})
    assert packaged["base"] == packaged["albedo"] == packaged["diffuse"]
    assert (tmp_path / "package" / packaged["base"]).read_bytes() == b"real-dds"

    preview = tmp_path / "body_preview.png"
    preview.write_bytes(b"preview")
    source.preview_texture_path = str(preview)
    channels = mesh_dotnet_experiment._dotnet_resolved_texture_channels(source)
    assert {channels[key] for key in ("base", "albedo", "diffuse")} == {str(preview)}


def test_dotnet_experiment_editor_finder_prefers_env_path(tmp_path: Path, monkeypatch) -> None:
    exe_path = tmp_path / MESH_DOTNET_EXPERIMENT_BINARY_NAME
    exe_path.write_text("fake", encoding="utf-8")
    monkeypatch.setenv("CDMW_MESH_DOTNET_EXPERIMENT_EXE", str(exe_path))

    assert find_mesh_dotnet_experiment_editor() == exe_path


def test_dotnet_experiment_editor_finder_prefers_source_build_before_stale_publish(
    tmp_path: Path,
    monkeypatch,
) -> None:
    tools_exe = tmp_path / "tools" / "dotnet_mesh_editor_experiment" / "bin" / "Release" / "net10.0-windows" / MESH_DOTNET_EXPERIMENT_BINARY_NAME
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


def test_dotnet_experiment_editor_finder_finds_onedir_internal_native_helper(
    tmp_path: Path,
    monkeypatch,
) -> None:
    exe_root = tmp_path / "CTF"
    exe_path = exe_root / "_internal" / "native" / MESH_DOTNET_EXPERIMENT_BINARY_NAME
    exe_path.parent.mkdir(parents=True)
    exe_path.write_text("bundled", encoding="utf-8")
    monkeypatch.delenv("CDMW_MESH_DOTNET_EXPERIMENT_EXE", raising=False)
    monkeypatch.setattr(mesh_dotnet_experiment.sys, "frozen", True, raising=False)
    monkeypatch.setattr(mesh_dotnet_experiment.sys, "executable", str(exe_root / "CrimsonDesertModWorkbench.exe"))
    monkeypatch.setattr(mesh_dotnet_experiment, "_repo_root", lambda: tmp_path / "repo")

    assert find_mesh_dotnet_experiment_editor() == exe_path


def test_dotnet_experiment_editor_resolver_ignores_stale_configured_path(
    tmp_path: Path,
    monkeypatch,
) -> None:
    exe_path = tmp_path / "tools" / "dotnet_mesh_editor_experiment" / "bin" / "Release" / "net10.0-windows" / MESH_DOTNET_EXPERIMENT_BINARY_NAME
    exe_path.parent.mkdir(parents=True)
    exe_path.write_text("dev build", encoding="utf-8")
    monkeypatch.delenv("CDMW_MESH_DOTNET_EXPERIMENT_EXE", raising=False)
    monkeypatch.setattr(mesh_dotnet_experiment.sys, "frozen", False, raising=False)
    monkeypatch.setattr(mesh_dotnet_experiment.sys, "_MEIPASS", "", raising=False)
    monkeypatch.setattr(mesh_dotnet_experiment, "_repo_root", lambda: tmp_path)

    resolution = mesh_dotnet_experiment.resolve_mesh_dotnet_experiment_editor(tmp_path / "missing.exe")

    assert Path(resolution.resolved_path) == exe_path
    assert resolution.source == "source_release"
    assert resolution.is_file is True


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
    assert "Invoke-NativeHelperPreparation" in build_script
    assert "Invoke-DotNetMeshEditorBuild -Configuration $Configuration -Required:$RequireDotNet" in build_script
    assert "dotnet_mesh_editor_experiment\\Cdmw.MeshEditorExperiment.csproj" in build_script
    assert "--headless-gpu-sparse-soak" in build_script
    assert 'backend -ne "d3d11_vortice_shader"' in build_script
    assert 'Invoke-DotNetMeshEditorGpuSmoke -ExecutablePath $packagedDotNetHelper -Context "packaged onedir"' in build_script
    assert "native\\cdmw_mesh_dotnet_editor\\build\\$Configuration" in build_script
    assert (root / "schemas" / "mesh" / "mesh.cdmeta.schema.json").is_file()
    assert '_add_data_tree_if_exists(datas, "schemas", "schemas", suffixes={".json"})' in spec_source
    assert "_add_native_binary_tree" in spec_source
    assert 'NATIVE_CONFIGURATION = "Debug" if PROFILE == "debug" else "Release"' in spec_source
    assert "native/cdmw_mesh_dotnet_editor/build/{NATIVE_CONFIGURATION}" in spec_source
    assert "native/cdmw_mesh_dotnet_editor/build/{NATIVE_CONFIGURATION}/D3D11MaterialShaders.hlsl" in spec_source
    assert "native/cd_texture_dx/build/{NATIVE_CONFIGURATION}/cd-texture-dx.exe" in spec_source
    assert ("tex" + "conv.exe") not in spec_source.lower()
    assert 'if PROFILE != "release":' not in spec_source
    assert "suffixes={\".exe\", \".dll\", \".json\"}" in spec_source
    # Release bundles must not carry .NET debug symbols.
    assert ".pdb" not in spec_source


def test_dotnet_embedded_shader_fallback_is_bom_free() -> None:
    source = Path("tools/dotnet_mesh_editor_experiment/D3D11MaterialViewport.cs").read_text(encoding="utf-8")
    assert "File.WriteAllBytes(outputPath, shaderBytes)" in source
    assert "File.WriteAllText(outputPath, shaderText, Encoding.UTF8)" not in source


def test_dotnet_resident_material_resources_are_incremental() -> None:
    root = Path("tools/dotnet_mesh_editor_experiment")
    source = "\n".join(path.read_text(encoding="utf-8") for path in sorted(root.glob("D3D11MaterialViewport*.cs")))

    assert "reference.CacheKey" in source
    assert "PruneTextureCacheToActiveBindings" in source
    assert "CacheKeys" in source
    refresh_source = source.split("public void RefreshTextures()", maxsplit=1)[1].split("private void RebuildMaterialResourcesIfDirty", maxsplit=1)[0]
    assert "ClearTextureCache" not in refresh_source
    assert "texture_srv_reuses" in source
    assert "affected_material_batch_rebinds" in source




def test_dotnet_experiment_package_reuses_obj_sidecar_contract(tmp_path: Path, monkeypatch) -> None:
    export_names: list[str] = []

    def fake_export_obj(mesh: ParsedMesh, output_dir: str, name: str = "", **_kwargs: object) -> list[str]:
        export_names.append(name)
        root = Path(output_dir)
        obj = root / f"{name}.obj"
        mtl = root / f"{name}.mtl"
        sidecar = root / f"{name}.obj.meta.json"
        obj.write_text(f"mtllib {name}.mtl\no body\nv 0 0 0\nv 1 0 0\nv 0 1 0\nf 1 2 3\n", encoding="utf-8")
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
    mesh.submeshes[0].preview_material_texture_inputs = (
        {"semantic_type": "emissive", "source_dds_path": str(emissive_png)},
    )
    package = build_mesh_dotnet_experiment_package(mesh, output_root=tmp_path)

    assert export_names == ["mesh"]
    assert package.mesh_path.name == "mesh.obj"
    assert package.scene_mesh_path is not None
    assert "mtllib scene.mtl" in package.scene_mesh_path.read_text(encoding="utf-8")
    scene_sidecar = json.loads((package.package_dir / "scene.obj.meta.json").read_text(encoding="utf-8"))
    assert scene_sidecar["export_path"] == "scene.obj"
    assert scene_sidecar["companion_filename"] == "scene.mtl"
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
    assert launch["input"]["material_signature"] == package.material_signature
    material_payload = json.loads((package.package_dir / "net_materials.json").read_text(encoding="utf-8"))
    assert material_payload["format"] == "cdmw_mesh_dotnet_materials_v1"
    assert material_payload["renderer_authority"] == "dotnet_mesh_editor"
    assert material_payload["material_signature"] == package.material_signature
    assert package.material_signature == mesh_dotnet_material_input_signature(mesh)
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
    assert packaged_base == material_payload["submeshes"][0]["packaged_channels"]["albedo"]
    assert packaged_base == material_payload["submeshes"][0]["packaged_channels"]["diffuse"]
    assert (package.package_dir / packaged_base).is_file()
    assert (package.package_dir / packaged_normal).is_file()
    assert (package.package_dir / packaged_emissive).is_file()
    assert material_payload["submeshes"][0]["packaged_texture_count"] >= 3
    assert "emissive" in material_payload["texture_channels"]
    assert len(tuple((package.package_dir / "textures").iterdir())) == 3

    geometry_package = build_mesh_dotnet_experiment_package(
        mesh,
        output_root=tmp_path,
        include_material_resources=False,
    )
    geometry_materials = json.loads(
        (geometry_package.package_dir / "net_materials.json").read_text(encoding="utf-8")
    )
    assert geometry_materials["resources"] == []
    assert geometry_materials["submeshes"][0]["resolved_channels"] == {}
    assert geometry_materials["submeshes"][0]["packaged_channels"] == {}
    assert geometry_materials["submeshes"][0]["resource_channels"] == {}
    assert geometry_materials["submeshes"][0]["material_synthesis"]["reason"] == "textures_on_demand"
    assert not (geometry_package.package_dir / "textures").exists()
    assert not (geometry_package.package_dir / "material_synthesis").exists()

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


def test_dotnet_obj_export_retries_native_service_failure_without_python_fallback(
    tmp_path: Path,
    monkeypatch,
) -> None:
    attempts: list[str] = []
    shutdowns: list[bool] = []

    def flaky_export(_mesh: ParsedMesh, _output_dir: str, name: str = "") -> list[str]:
        attempts.append(name)
        if len(attempts) == 1:
            raise RuntimeError("native OBJ export failed and Python export fallback was blocked")
        return [str(tmp_path / f"{name}.obj")]

    monkeypatch.setattr(mesh_dotnet_experiment, "export_obj", flaky_export)
    monkeypatch.setattr(mesh_dotnet_experiment, "_shutdown_dotnet_native_export_service", lambda: shutdowns.append(True))

    exported = mesh_dotnet_experiment._export_dotnet_obj_paths(_mesh(), tmp_path, "mesh")

    assert exported == (tmp_path / "mesh.obj",)
    assert attempts == ["mesh", "mesh"]
    assert shutdowns == [True]


def test_dotnet_package_carries_resident_editable_and_original_scene(tmp_path: Path) -> None:
    editable = _mesh()
    reference = _mesh()
    reference.path = "character/original_body.pac"

    package = build_mesh_dotnet_experiment_package(
        editable,
        output_root=tmp_path,
        reference_mesh=reference,
        comparison_mode="side_by_side",
        interaction_mode="placement",
    )

    assert package.scene_mesh_path is not None and package.scene_mesh_path.is_file()
    assert package.scene_manifest_path is not None and package.scene_manifest_path.is_file()
    assert package.editable_submesh_count == 1
    assert package.reference_submesh_count == 1
    scene = json.loads(package.scene_manifest_path.read_text(encoding="utf-8"))
    assert scene["format"] == "cdmw_resident_scene_frame_v2"
    assert scene["protocol_version"] == 2
    assert scene["roles"]["replacement"] == [0]
    assert scene["roles"]["original_reference"] == [1]
    assert len(scene["roles"]["editable"]["model_matrix"]) == 16
    assert scene["roles"]["editable"]["world_bounds"]["min"] == [0.0, 0.0, 0.0]
    assert scene["roles"]["reference"]["model_matrix"] == [
        1.0, 0.0, 0.0, 0.0,
        0.0, 1.0, 0.0, 0.0,
        0.0, 0.0, 1.0, 0.0,
        0.0, 0.0, 0.0, 1.0,
    ]
    assert scene["comparison_mode"] == "side_by_side"
    assert scene["interaction_mode"] == "placement"
    assert scene["grid"]["visible"] is True
    assert scene["gizmo"]["tool"] == "move"
    assert scene["coordinate_contract"] == {
        "matrix_layout": "row_major",
        "vector_convention": "row_vector",
        "handedness": "right_handed",
        "units": "source_mesh_units",
        "multiplication_order": "source_point_then_automatic_alignment_then_manual_delta",
    }
    materials = json.loads((package.package_dir / "net_materials.json").read_text(encoding="utf-8"))
    assert len(materials["submeshes"]) == 2
    _program, args = mesh_dotnet_experiment_command("C:/tools/MeshEditorExperiment.exe", package)
    assert args[args.index("--mesh") + 1] == str(package.scene_mesh_path)
    assert package.mesh_path != package.scene_mesh_path


def _prefab_reference_batch(normal: Path, material: Path) -> dict[str, object]:
    return {
        "index": 1,
        "material_name": "CD_PHW_00_UW_00_0001",
        "vertex_file": "geometry/batch_001.bin",
        "vertex_count": 3,
        "editor_identity": {
            "source_submesh_index": 1,
            "source_local_submesh_index": 0,
            "source_component_index": 1,
            "source_component_label": "underwear.pac",
            "prefab_component": True,
            "identity_file": "geometry/batch_001_identity.bin",
        },
        "base_color": [0.90, 0.83, 0.71],
        "base_tint_only_fallback": True,
        "roughness": 0.48,
        "metalness": 0.0,
        "specular": 0.28,
        "material_category": "cloth",
        "shader_family": "SkinnedMeshCloth_Ver2",
        "normal_y_policy": "shader_invert_legacy_compat",
        "alpha_mode": "opaque",
        "two_sided": False,
        "dds_textures": {
            "normal": {
                "slot": "normal",
                "source_path": str(normal),
                "semantic_type": "normal",
                "shader_family": "SkinnedMeshCloth_Ver2",
            },
            "material": {
                "slot": "material",
                "source_path": str(material),
                "semantic_type": "packed_material",
                "semantic_subtype": "material_mask",
                "packed_channels": "r=occlusion,g=roughness,b=metalness,a=specular_response",
                "shader_family": "SkinnedMeshCloth_Ver2",
            },
            "material_inputs": [
                {
                    "slot": "normal",
                    "source_path": str(normal),
                    "semantic_type": "normal",
                    "shader_family": "SkinnedMeshCloth_Ver2",
                },
                {
                    "slot": "material",
                    "source_path": str(material),
                    "semantic_type": "packed_material",
                    "semantic_subtype": "material_mask",
                    "packed_channels": "r=occlusion,g=roughness,b=metalness,a=specular_response",
                    "shader_family": "SkinnedMeshCloth_Ver2",
                },
            ],
        },
    }


def _write_native_reference_composite_fixture(tmp_path: Path) -> Path:
    package_dir = tmp_path / "native_reference"
    geometry_dir = package_dir / "geometry"
    geometry_dir.mkdir(parents=True)
    center = (10.0, 20.0, 30.0)
    scale = 2.0
    source_positions = ((11.0, 20.0, 30.0), (10.0, 21.0, 30.0), (10.0, 20.0, 31.0))
    records = []
    for corner, position in enumerate(source_positions):
        normalized = tuple((position[axis] - center[axis]) * scale for axis in range(3))
        barycentric = tuple(1.0 if axis == corner else 0.0 for axis in range(3))
        records.append(
            struct.pack(
                "<23f",
                *normalized,
                0.0,
                0.0,
                1.0,
                0.64,
                0.64,
                0.56,
                float(corner == 1),
                float(corner == 2),
                1.0,
                0.0,
                0.0,
                0.0,
                1.0,
                0.0,
                0.0,
                0.0,
                1.0,
                *barycentric,
            )
        )
    (geometry_dir / "batch_001.bin").write_bytes(b"".join(records))
    (geometry_dir / "batch_000.bin").write_bytes(b"".join(records))
    (geometry_dir / "batch_001_identity.bin").write_bytes(
        b"".join(struct.pack("<2i", 1, source_vertex) for source_vertex in (7, 8, 9))
    )
    (geometry_dir / "batch_000_identity.bin").write_bytes(
        b"".join(struct.pack("<2i", 0, source_vertex) for source_vertex in (0, 1, 2))
    )
    (geometry_dir / "batch_001_cloth_particles.bin").write_bytes(
        b"".join(struct.pack("<3f", *tuple((position[axis] - center[axis]) * scale for axis in range(3))) for position in source_positions)
    )
    (geometry_dir / "batch_001_cloth_pins.bin").write_bytes(
        b"".join(struct.pack("<f", value) for value in (1.0, 0.0, 0.0))
    )
    (geometry_dir / "batch_001_cloth_constraints.bin").write_bytes(
        struct.pack("<2i2f", 0, 1, 1.0, 0.8) + struct.pack("<2i2f", 1, 2, 1.0, 0.8)
    )
    normal = tmp_path / "underwear_n.dds"
    material = tmp_path / "underwear_ma.dds"
    skin_base = tmp_path / "skin_base.dds"
    normal.write_bytes(b"normal")
    material.write_bytes(b"material")
    skin_base.write_bytes(b"skin")
    (package_dir / "manifest.json").write_text(
        json.dumps(
            {
                "normalization_center": list(center),
                "normalization_scale": scale,
                "batches": [
                    {
                        "index": 0,
                        "material_name": "material",
                        "vertex_file": "geometry/batch_000.bin",
                        "vertex_count": 3,
                        "editor_identity": {
                            "source_submesh_index": 0,
                            "source_local_submesh_index": 0,
                            "source_component_index": 0,
                            "prefab_component": False,
                            "identity_file": "geometry/batch_000_identity.bin",
                        },
                        "base_color": [0.78, 0.62, 0.44],
                        "base_tint_only_fallback": False,
                        "roughness": 0.56,
                        "metalness": 0.0,
                        "specular": 0.28,
                        "material_category": "skin",
                        "shader_family": "SkinnedMeshSkin",
                        "normal_y_policy": "shader_invert_legacy_compat",
                        "alpha_mode": "opaque",
                        "two_sided": False,
                        "dds_textures": {
                            "base": {
                                "slot": "base",
                                "source_path": str(skin_base),
                                "semantic_type": "albedo",
                                "shader_family": "SkinnedMeshSkin",
                            },
                            "material_inputs": [
                                {
                                    "slot": "base",
                                    "source_path": str(skin_base),
                                    "semantic_type": "albedo",
                                    "shader_family": "SkinnedMeshSkin",
                                }
                            ],
                        },
                    },
                    {
                        **_prefab_reference_batch(normal, material),
                        "cloth_enabled": True,
                        "cloth_particle_file": "geometry/batch_001_cloth_particles.bin",
                        "cloth_pin_file": "geometry/batch_001_cloth_pins.bin",
                        "cloth_constraint_file": "geometry/batch_001_cloth_constraints.bin",
                        "cloth_particle_count": 3,
                        "cloth_constraint_count": 2,
                        "cloth_gravity": -9.8,
                        "cloth_damping": 0.7,
                        "cloth_air_resistance": 0.9,
                        "cloth_wind_response": 0.5,
                        "cloth_solver_iterations": 24,
                    },
                ],
            }
        ),
        encoding="utf-8",
    )
    return package_dir


def test_native_reference_direct_materials_use_native_identity_and_dds(tmp_path: Path) -> None:
    package_dir = _write_native_reference_composite_fixture(tmp_path)
    reference = _mesh()

    assert apply_dotnet_native_reference_materials(reference, package_dir) == 1
    direct = reference.submeshes[0]
    assert direct.preview_sidecar_shader_family == "SkinnedMeshSkin"
    assert direct.preview_texture_dds_path == str(tmp_path / "skin_base.dds")
    assert direct.preview_native_material_overrides["material_category"] == "skin"
    assert direct.preview_native_material_overrides["metalness"] == 0.0
    assert direct.preview_color == (0.78, 0.62, 0.44)

    package = build_mesh_dotnet_experiment_package(
        _mesh(),
        output_root=tmp_path / "direct-materials",
        reference_mesh=reference,
        comparison_mode="side_by_side",
    )
    materials = json.loads((package.package_dir / "net_materials.json").read_text(encoding="utf-8"))
    direct_material = materials["submeshes"][1]
    assert direct_material["shader_family"] == "skin"
    assert direct_material["parameters"]["roughness"] == 0.56
    assert direct_material["parameters"]["metalness"] == 0.0
    assert direct_material["parameters"]["base_tint_color"] == [0.78, 0.62, 0.44]
    assert direct_material["parameters"]["base_tint_strength"] == 0.0
    assert "base" in direct_material["resolved_channels"]


def test_native_reference_composite_keeps_prefab_separate_and_reference_only(tmp_path: Path) -> None:
    package_dir = _write_native_reference_composite_fixture(tmp_path)
    reference = _mesh()

    assert append_dotnet_native_reference_composite(reference, package_dir) == 1
    assert len(reference.submeshes) == 2
    prefab = reference.submeshes[1]
    assert prefab.vertices == [(11.0, 20.0, 30.0), (10.0, 21.0, 30.0), (10.0, 20.0, 31.0)]
    assert prefab.faces == [(0, 1, 2)]
    assert prefab.source_vertex_map == [7, 8, 9]
    assert prefab.material == "CD_PHW_00_UW_00_0001"
    assert prefab.preview_role == "original_reference_prefab"
    assert prefab.preview_color == (0.90, 0.83, 0.71)
    assert prefab.preview_sidecar_shader_family == "SkinnedMeshCloth_Ver2"
    assert prefab.preview_native_material_overrides["material_category"] == "cloth"
    assert prefab.preview_native_material_overrides["metalness"] == 0.0

    package = build_mesh_dotnet_experiment_package(
        _mesh(),
        output_root=tmp_path / "dotnet",
        reference_mesh=reference,
        comparison_mode="side_by_side",
    )
    assert package.reference_submesh_count == 2
    scene = json.loads(package.scene_manifest_path.read_text(encoding="utf-8"))
    assert scene["roles"]["original_reference"] == [1, 2]
    materials = json.loads((package.package_dir / "net_materials.json").read_text(encoding="utf-8"))
    prefab_material = materials["submeshes"][2]
    assert prefab_material["shader_family"] == "cloth_v2"
    assert prefab_material["normal_y_policy"] == "invert_green_for_directx"
    assert prefab_material["parameters"]["roughness_scale"] == 0.48
    assert prefab_material["parameters"]["metalness_scale"] == 0.0
    assert prefab_material["parameters"]["base_tint_color"] == [0.90, 0.83, 0.71]
    assert prefab_material["parameters"]["base_tint_strength"] == 0.0
    prefab_resources = [resource for resource in materials["resources"] if resource["submesh_index"] == 2]
    assert prefab_resources
    assert all(resource["role"] == "original_reference" for resource in prefab_resources)


def test_native_reference_composite_cancellation_publishes_no_partial_geometry(tmp_path: Path) -> None:
    package_dir = _write_native_reference_composite_fixture(tmp_path)
    reference = _mesh()
    checks = 0

    def cancelled() -> bool:
        nonlocal checks
        checks += 1
        return checks >= 2

    assert append_dotnet_native_reference_composite(
        reference,
        package_dir,
        cancelled=cancelled,
    ) == 0
    assert len(reference.submeshes) == 1
    assert reference.total_vertices == 3


def test_preview_core_batches_build_one_cached_canonical_dotnet_package(tmp_path: Path) -> None:
    source_package = _write_native_reference_composite_fixture(tmp_path)
    decoded = decode_dotnet_native_preview_package(source_package)

    assert decoded.total_vertices == 6
    assert len(decoded.submeshes) == 2
    assert decoded.submeshes[0].cdmw_native_source_component_index == 0
    assert decoded.submeshes[1].cdmw_native_prefab_component is True
    assert decoded.submeshes[1].source_vertex_map == [7, 8, 9]

    cache_root = tmp_path / "preview-cache"
    package = build_or_lookup_dotnet_preview_package(
        source_package,
        cache_root=cache_root,
        archive_identity="archive-entry-v1",
        sidecar_generation=7,
        cache_mode="balanced",
        max_bytes=64 * 1024 * 1024,
        target_bytes=48 * 1024 * 1024,
    )
    valid, missing = validate_dotnet_preview_package(package.package_dir)
    assert valid, missing
    scene = json.loads(package.scene_manifest_path.read_text(encoding="utf-8"))
    assert scene["renderer_authority"] == "dotnet_vortice_resident_scene"
    assert scene["part_identities"][1]["prefab_component"] is True
    assert scene["part_identities"][1]["source_component_label"] == "underwear.pac"
    assert scene["cloth_overlay"]["particles"] == [
        [11.0, 20.0, 30.0],
        [10.0, 21.0, 30.0],
        [10.0, 20.0, 31.0],
    ]
    assert scene["cloth_overlay"]["constraints"] == [[0, 1], [1, 2]]
    materials = json.loads((package.package_dir / "net_materials.json").read_text(encoding="utf-8"))
    assert len(materials["submeshes"]) == 2
    packaged_resources = [package.package_dir / resource["path"] for resource in materials["resources"]]
    assert packaged_resources
    assert {path.read_bytes() for path in packaged_resources}.issuperset(
        {(tmp_path / "skin_base.dds").read_bytes(), (tmp_path / "underwear_n.dds").read_bytes()}
    )

    warm = build_or_lookup_dotnet_preview_package(
        source_package,
        cache_root=cache_root,
        archive_identity="archive-entry-v1",
        sidecar_generation=7,
        cache_mode="balanced",
        max_bytes=64 * 1024 * 1024,
        target_bytes=48 * 1024 * 1024,
    )
    assert warm.package_dir == package.package_dir

    package.scene_manifest_path.write_text("corrupt", encoding="utf-8")
    rebuilt = build_or_lookup_dotnet_preview_package(
        source_package,
        cache_root=cache_root,
        archive_identity="archive-entry-v1",
        sidecar_generation=7,
        cache_mode="balanced",
        max_bytes=64 * 1024 * 1024,
        target_bytes=48 * 1024 * 1024,
    )
    assert rebuilt.package_dir == package.package_dir
    assert validate_dotnet_preview_package(rebuilt.package_dir)[0] is True


def test_schema8_native_package_is_adapted_directly_without_obj_or_png_conversion(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source_package = _write_native_reference_composite_fixture(tmp_path)
    manifest_path = source_package / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest.update({"schema_version": 8, "source_path": "character/helmet.pac", "use_textures": True})
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    geometry_fingerprints = {
        path.name: (path.stat().st_size, path.stat().st_mtime_ns, hashlib.sha256(path.read_bytes()).hexdigest())
        for path in (source_package / "geometry").glob("*.bin")
    }

    def reject_legacy_decode(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("schema-8 package must not enter the Python geometry decoder")

    monkeypatch.setattr(
        "cdmw.services.mesh_dotnet_preview_package.decode_dotnet_native_preview_package",
        reject_legacy_decode,
    )
    package = build_or_lookup_dotnet_preview_package(
        source_package,
        cache_root=tmp_path / "preview-cache",
        archive_identity="helmet-entry",
        cache_mode="balanced",
        max_bytes=64 * 1024 * 1024,
        target_bytes=48 * 1024 * 1024,
    )

    assert package.package_dir == source_package.resolve()
    assert package.mesh_path == manifest_path.resolve()
    assert package.scene_mesh_path == manifest_path.resolve()
    assert not (source_package / "mesh.obj").exists()
    assert not tuple(source_package.rglob("*.png"))
    assert validate_dotnet_preview_package(source_package) == (True, ())
    materials = json.loads((source_package / "net_materials.json").read_text(encoding="utf-8"))
    assert materials["adapter"] == "cdmw_native_dotnet_adapter_v1"
    assert {Path(resource["path"]).suffix.casefold() for resource in materials["resources"]} == {".dds"}
    assert len(materials["submeshes"]) == 2
    scene = json.loads((source_package / "dotnet_scene.json").read_text(encoding="utf-8"))
    assert scene["renderer_authority"] == "dotnet_vortice_resident_scene"
    assert scene["cloth_overlay"]["constraints"] == [[0, 1], [1, 2]]
    assert geometry_fingerprints == {
        path.name: (path.stat().st_size, path.stat().st_mtime_ns, hashlib.sha256(path.read_bytes()).hexdigest())
        for path in (source_package / "geometry").glob("*.bin")
    }


def test_schema8_corrupt_adapter_sidecar_is_rebuilt_without_touching_base_geometry(tmp_path: Path) -> None:
    source_package = _write_native_reference_composite_fixture(tmp_path)
    manifest_path = source_package / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["schema_version"] = 8
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    cache_root = tmp_path / "preview-cache"
    first = build_or_lookup_dotnet_preview_package(
        source_package,
        cache_root=cache_root,
        archive_identity="schema8-recovery",
    )
    geometry_hashes = {
        path.name: hashlib.sha256(path.read_bytes()).hexdigest()
        for path in (source_package / "geometry").glob("*.bin")
    }
    first.scene_manifest_path.write_text("corrupt", encoding="utf-8")

    rebuilt = build_or_lookup_dotnet_preview_package(
        source_package,
        cache_root=cache_root,
        archive_identity="schema8-recovery",
    )

    assert rebuilt.package_dir == source_package.resolve()
    assert validate_dotnet_preview_package(source_package) == (True, ())
    assert geometry_hashes == {
        path.name: hashlib.sha256(path.read_bytes()).hexdigest()
        for path in (source_package / "geometry").glob("*.bin")
    }


def test_schema8_adapter_validates_available_dds_even_when_not_upload_candidate(tmp_path: Path) -> None:
    source_package = _write_native_reference_composite_fixture(tmp_path)
    manifest_path = source_package / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["schema_version"] = 8
    manifest["batches"][0]["dds_textures"]["diagnostic"] = {
        "available": True,
        "direct_upload_candidate": False,
        "source_path": str(tmp_path / "missing-diagnostic.dds"),
    }
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(ValueError, match="missing"):
        build_or_lookup_dotnet_preview_package(
            source_package,
            cache_root=tmp_path / "preview-cache",
            archive_identity="schema8-dds-validation",
        )


def test_python_preview_model_uses_the_same_canonical_package_contract(tmp_path: Path) -> None:
    base = tmp_path / "python_base.dds"
    base.write_bytes(b"python-base-dds")
    preview_mesh = ModelPreviewMesh(
        material_name="skin",
        texture_name="skin.dds",
        positions=[(-1.0, -1.0, 0.0), (1.0, -1.0, 0.0), (-1.0, 1.0, 0.0)],
        texture_coordinates=[(0.0, 0.0), (1.0, 0.0), (0.0, 1.0)],
        normals=[(0.0, 0.0, 1.0)] * 3,
        indices=[0, 1, 2],
        source_submesh_index=4,
        source_vertex_indices=[10, 11, 12],
        preview_texture_dds_path=str(base),
        preview_sidecar_shader_family="SkinnedMeshSkin",
        preview_role="archive_model",
    )
    model = ModelPreviewData(
        path="archive/python-body.pac",
        format="pac",
        normalization_center=(10.0, 20.0, 30.0),
        normalization_scale=2.0,
        meshes=[preview_mesh],
    )

    package = build_or_lookup_dotnet_preview_package_from_model(
        model,
        cache_root=tmp_path / "cache",
        archive_identity="python-entry",
        sidecar_generation=2,
        cache_mode="balanced",
        max_bytes=64 * 1024 * 1024,
        target_bytes=48 * 1024 * 1024,
    )

    assert validate_dotnet_preview_package(package.package_dir)[0] is True
    scene = json.loads(package.scene_manifest_path.read_text(encoding="utf-8"))
    assert scene["part_identities"][0]["source_submesh_index"] == 4
    materials = json.loads((package.package_dir / "net_materials.json").read_text(encoding="utf-8"))
    assert materials["submeshes"][0]["shader_family"] == "skin"
    resource_paths = [package.package_dir / resource["path"] for resource in materials["resources"]]
    assert any(path.read_bytes() == b"python-base-dds" for path in resource_paths)


def test_procedural_prewarm_package_is_valid_geometry_only_and_reused(tmp_path: Path) -> None:
    first = build_dotnet_preview_prewarm_package(tmp_path / "cache")
    second = build_dotnet_preview_prewarm_package(tmp_path / "cache")

    assert validate_dotnet_preview_package(first.package_dir)[0] is True
    assert second.package_dir == first.package_dir
    assert first.material_signature == second.material_signature
    materials = json.loads((first.package_dir / "net_materials.json").read_text(encoding="utf-8"))
    assert materials.get("resources", []) == []
