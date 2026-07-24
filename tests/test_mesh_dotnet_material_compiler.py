from __future__ import annotations

from pathlib import Path

import pytest
from PIL import Image

from cdmw.domain.cancellation import RunCancelled
from cdmw.models import PreviewMaterialTextureInput
from cdmw.modding.mesh_parser import ParsedMesh, SubMesh
from cdmw.services import mesh_dotnet_material_compiler
from cdmw.services.mesh_dotnet_material_compiler import (
    MeshDotNetMaterialCompilationError,
    MeshDotNetMaterialCompileRequest,
    compile_mesh_dotnet_material_update,
    snapshot_mesh_dotnet_material_inputs,
)
from cdmw.services.mesh_dotnet_material_channels import _dotnet_material_input_channels
from cdmw.services.mesh_dotnet_material_package import (
    _source_has_usable_tangents,
    compile_mesh_dotnet_material_manifest,
)
from cdmw.services.mesh_dotnet_material_semantics import (
    mesh_dotnet_material_input_signature,
)
from cdmw.services.pac_material_graph import build_pac_material_graph_v1
from cdmw.workers.mesh_dotnet_material_update_worker import (
    MeshDotNetMaterialUpdateWorker,
)


def _image(path: Path, color: tuple[int, int, int, int]) -> Path:
    Image.new("RGBA", (8, 8), color).save(path)
    return path


def _mesh_with_layer_graph(tmp_path: Path) -> ParsedMesh:
    base = _image(tmp_path / "base.png", (48, 44, 40, 255))
    detail = _image(tmp_path / "detail.png", (210, 170, 64, 255))
    mask = _image(tmp_path / "mask.png", (255, 0, 0, 255))
    normal = _image(tmp_path / "normal.png", (128, 128, 255, 255))
    submesh = SubMesh(
        name="Blade",
        material="Blade",
        texture=str(base),
        vertices=[(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0)],
        uvs=[(0.0, 0.0), (1.0, 0.0), (0.0, 1.0)],
        faces=[],
    )
    submesh.submesh_index = 4
    submesh.material_slot_index = 3
    submesh.preview_normal_texture_path = str(normal)
    submesh.preview_sidecar_shader_family = "MultiTextured"
    submesh.preview_material_texture_inputs = (
        PreviewMaterialTextureInput(
            slot_kind="base",
            parameter_name="_overlayColorTexture",
            source_dds_path=str(base),
            preview_texture_path=str(base),
            semantic_type="base",
            shader_family="MultiTextured",
            sidecar_kind="pac_xml",
            owner_slot_index=3,
            owner_wrapper_item_id="100",
            binding_authority="authoritative",
            binding_disposition="promoted",
            source_kind="crimson_overlay_color",
        ),
        PreviewMaterialTextureInput(
            slot_kind="material",
            parameter_name="_colorTextureG",
            source_dds_path=str(detail),
            preview_texture_path=str(detail),
            semantic_type="color",
            shader_family="MultiTextured",
            sidecar_kind="pac_xml",
            layer_role="",
            layer_channel="g",
            owner_slot_index=3,
            owner_wrapper_item_id="100",
            binding_authority="authoritative",
            binding_disposition="layer_only",
            source_kind="crimson_layer_color",
        ),
        PreviewMaterialTextureInput(
            slot_kind="material",
            parameter_name="_rgbTexture",
            source_dds_path=str(mask),
            preview_texture_path=str(mask),
            semantic_type="mask",
            shader_family="MultiTextured",
            sidecar_kind="pac_xml",
            layer_role="mask",
            layer_channel="g",
            owner_slot_index=3,
            owner_wrapper_item_id="100",
            binding_authority="authoritative",
            binding_disposition="layer_only",
            source_kind="crimson_detail_mask",
        ),
        PreviewMaterialTextureInput(
            slot_kind="normal",
            parameter_name="normalTexture",
            source_dds_path=str(normal),
            preview_texture_path=str(normal),
            semantic_type="normal",
            semantic_subtype="normal",
            confidence="gltf",
            visualized=True,
        ),
    )
    return ParsedMesh(path="character/model/weapon/test.pac", format="pac", submeshes=[submesh])


def _request(mesh: ParsedMesh, root: Path, generation: int = 1) -> MeshDotNetMaterialCompileRequest:
    snapshot = snapshot_mesh_dotnet_material_inputs(mesh)
    return MeshDotNetMaterialCompileRequest(
        session_id="material-session",
        edit_revision=4,
        generation=generation,
        role="replacement",
        mesh_snapshot=snapshot,
        material_signature=mesh_dotnet_material_input_signature(snapshot),
        output_root=root,
    )


def test_initial_and_resident_paths_use_the_same_compiler_contract(tmp_path: Path) -> None:
    mesh = _mesh_with_layer_graph(tmp_path)
    snapshot = snapshot_mesh_dotnet_material_inputs(mesh)
    assert snapshot.submeshes[0].preview_tangents_usable is True
    assert _source_has_usable_tangents(snapshot.submeshes[0]) is True
    signature = mesh_dotnet_material_input_signature(snapshot)
    initial = compile_mesh_dotnet_material_manifest(
        mesh,
        package_dir=tmp_path / "initial",
        material_signature=signature,
        role="replacement",
    )
    resident = compile_mesh_dotnet_material_update(_request(mesh, tmp_path / "cache"))

    initial_submesh = initial["submeshes"][0]
    resident_submesh = resident["submeshes"][0]
    assert resident["schema"] == "cdmw_mesh_material_state_v3"
    assert resident["compiler"]["initial_resident_equivalent"] is True
    assert initial_submesh["submesh_index"] == resident_submesh["submesh_index"] == 4
    assert initial_submesh["material_slot_index"] == resident_submesh["material_slot_index"] == 3
    assert resident_submesh["source_contract"]["schema"] == "cdmw_pac_material_graph_v1"
    assert resident_submesh["source_contract"]["graph_hash"] == initial_submesh["source_contract"]["graph_hash"]
    assert resident_submesh["material_synthesis"]["generated_channels"] == initial_submesh["material_synthesis"]["generated_channels"]
    assert resident_submesh["resource_channels"] == initial_submesh["resource_channels"]
    assert resident_submesh["resolved_features"] == initial_submesh["resolved_features"]
    assert all(Path(resource["path"]).is_file() for resource in resident["resources"])


def test_resident_compiler_reuses_content_addressed_outputs(tmp_path: Path) -> None:
    mesh = _mesh_with_layer_graph(tmp_path)
    request = _request(mesh, tmp_path / "cache")

    first = compile_mesh_dotnet_material_update(request)
    second = compile_mesh_dotnet_material_update(request)

    assert first["compiler"]["cache_hit"] is False
    assert second["compiler"]["cache_hit"] is True
    assert first["compiler"]["cache_key"] == second["compiler"]["cache_key"]

    cache_dir = Path(first["compiler"]["cache_dir"])
    manifest_path = cache_dir / "net_materials.json"
    manifest_text = manifest_path.read_text(encoding="utf-8")
    assert ".tmp" not in manifest_text
    for submesh in first["submeshes"]:
        for raw_path in submesh["resolved_channels"].values():
            assert Path(raw_path).is_file()


def test_snapshot_separates_scene_slot_from_duplicate_pac_wrapper_owner(tmp_path: Path) -> None:
    second = SubMesh(name="Blade_B", material="Shared_Blade")
    second.preview_material_texture_inputs = (
        PreviewMaterialTextureInput(
            slot_kind="normal",
            parameter_name="_normalTexture",
            preview_texture_path="normal.dds",
            semantic_type="normal",
            owner_slot_index=1,
            owner_wrapper_item_id="wrapper-1",
            binding_authority="authoritative",
            binding_disposition="bound",
            sidecar_kind="pac_xml",
        ),
    )
    mesh = ParsedMesh(
        path="duplicate-material.pac",
        format="pac",
        submeshes=[
            SubMesh(name="Blade_A", material="Shared_Blade"),
            second,
            SubMesh(name="Tail", material="Tail_Material"),
        ],
    )
    # Imported OBJ-style parts may carry an explicit -1 sentinel. The snapshot
    # must restore deterministic source indices instead of transporting -1 into
    # every initial PAC graph while the resident original uses 0..N.
    for submesh in mesh.submeshes:
        submesh.submesh_index = -1
        submesh.material_slot_index = -1

    snapshot = snapshot_mesh_dotnet_material_inputs(mesh)
    exported_snapshot = snapshot_mesh_dotnet_material_inputs(
        mesh,
        scene_material_slot_indices=(0, 4, 2),
    )

    assert [row.material_slot_index for row in snapshot.submeshes] == [0, 0, 2]
    assert [row.source_submesh_index for row in snapshot.submeshes] == [0, 1, 2]
    assert [row.preview_pac_material_owner_slot_index for row in snapshot.submeshes] == [0, 1, 2]
    assert [row.material_slot_index for row in exported_snapshot.submeshes] == [0, 4, 2]
    assert [row.preview_pac_material_owner_slot_index for row in exported_snapshot.submeshes] == [0, 1, 2]
    assert mesh_dotnet_material_input_signature(mesh) == mesh_dotnet_material_input_signature(snapshot)
    initial = compile_mesh_dotnet_material_manifest(
        mesh,
        package_dir=tmp_path / "negative-index-initial",
        material_signature=mesh_dotnet_material_input_signature(mesh),
    )
    canonical = compile_mesh_dotnet_material_manifest(
        snapshot,
        package_dir=tmp_path / "negative-index-resident",
        material_signature=mesh_dotnet_material_input_signature(snapshot),
    )
    assert [
        row["source_contract"]["graph_hash"] for row in initial["submeshes"]
    ] == [
        row["source_contract"]["graph_hash"] for row in canonical["submeshes"]
    ]
    graph = build_pac_material_graph_v1(snapshot.submeshes[1])
    assert graph["source_submesh_index"] == 1
    assert graph["binding_conservation"]["cross_owner_bindings"] == []
    assert _dotnet_material_input_channels(snapshot.submeshes[1])["normal"] == "normal.dds"


def test_resident_compiler_cancels_before_publishing(tmp_path: Path) -> None:
    mesh = _mesh_with_layer_graph(tmp_path)
    root = tmp_path / "cancelled-cache"

    with pytest.raises(RunCancelled):
        compile_mesh_dotnet_material_update(
            _request(mesh, root),
            cancelled=lambda: True,
        )

    assert not root.exists()


def test_resident_compiler_blocks_cross_owner_bindings(tmp_path: Path) -> None:
    mesh = _mesh_with_layer_graph(tmp_path)
    mesh.submeshes[0].preview_material_texture_inputs[0].owner_slot_index = 1

    with pytest.raises(MeshDotNetMaterialCompilationError, match="cross_owner_bindings"):
        compile_mesh_dotnet_material_update(_request(mesh, tmp_path / "cache"))


def test_resident_compiler_blocks_unreadable_synthesis_inputs() -> None:
    blockers = mesh_dotnet_material_compiler._material_compile_blockers(
        {
            "submeshes": [
                {
                    "submesh_index": 4,
                    "material_synthesis": {
                        "attempted": True,
                        "succeeded": True,
                        "notes": [
                            "height unreadable:cd_texturelayer_012_0002_disp.png"
                        ],
                    },
                }
            ]
        }
    )

    assert blockers == [
        {
            "submesh_index": 4,
            "kind": "unreadable_material_inputs",
            "notes": ["height unreadable:cd_texturelayer_012_0002_disp.png"],
        }
    ]


def test_material_update_worker_publishes_request_and_payload(tmp_path: Path) -> None:
    mesh = _mesh_with_layer_graph(tmp_path)
    request = _request(mesh, tmp_path / "cache", generation=7)
    completed: list[tuple[object, object, float]] = []
    errors: list[tuple[object, str]] = []
    worker = MeshDotNetMaterialUpdateWorker(request)
    worker.completed.connect(lambda *args: completed.append(args))
    worker.error.connect(lambda *args: errors.append(args))

    worker.run()

    assert errors == []
    assert completed[0][0] is request
    assert completed[0][1]["generation"] == 7
