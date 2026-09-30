"""Authored channels and safe source identity across mesh interchange."""

from __future__ import annotations

import copy
import json
import struct
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image

from cdmw.modding.mesh_exporter import export_fbx, export_obj
from cdmw.modding.mesh_glb_interchange import _attach_glb_sidecar, _load_glb_roundtrip_sidecar, export_glb, import_glb_with_sidecar
from cdmw.modding.mesh_obj_importer import import_obj, _load_obj_roundtrip_sidecar
from cdmw.modding.mesh_parser import ParsedMesh, SubMesh
from cdmw.modding.scene_gltf_import import import_gltf
from cdmw.modding.scene_geometry_utils import _identity_matrix


def authored_mesh(root: Path) -> ParsedMesh:
    root.mkdir(parents=True, exist_ok=True)
    textures = {}
    for name, color in (("baseColorTexture", (200, 120, 60, 180)), ("normalTexture", (128, 128, 255, 255)),
                        ("metallicRoughnessTexture", (180, 100, 220, 255)), ("emissiveTexture", (40, 80, 120, 255))):
        image = root / f"{name}.png"
        Image.new("RGBA", (4, 4), color).save(image)
        textures[name] = {"path": str(image), "texCoord": 0}
    textures["normalTexture"]["scale"] = 0.7
    part = SubMesh(name="Body", material="BodyMat", vertices=[(0, 0, 0), (1, 0, 0), (0, 1, 0)],
                   normals=[(0, 0, 1)] * 3, uvs=[(0.1, 0.2), (0.9, 0.2), (0.1, 0.8)], faces=[(0, 1, 2)],
                   vertex_count=3, face_count=1, vertex_colors=[(1, 0.2, 0.3, 0.8), (0.4, 1, 0.5, 1), (0.6, 0.7, 1, 1)],
                   bone_indices=[(0, 1)] * 3, bone_weights=[(1, 0), (0.25, 0.75), (0, 1)],
                   morph_targets={"Smile": [(0, 0, 0), (1, 0.125, 0), (0, 1.125, 0)]}, morph_weights={"Smile": 0.25})
    part.uv_sets = {0: list(part.uvs), 1: [(0.2, 0.3), (0.7, 0.3), (0.2, 0.6)]}
    part.interchange_material = {"pbrMetallicRoughness": {"baseColorFactor": [0.6, 0.7, 0.8, 0.42],
                                                       "metallicFactor": 0.72, "roughnessFactor": 0.17},
                                 "emissiveFactor": [0.2, 0.3, 0.4], "alphaMode": "BLEND", "doubleSided": True,
                                 "extensions": {"KHR_materials_emissive_strength": {"emissiveStrength": 2.5}}, "textures": textures}
    nodes = [{"name": "Root", "children": [1]}, {"name": "Child", "translation": [0, 1, 0]}, {"name": "Body"}]
    inverse = list(_identity_matrix())
    inverse[13] = -1.0
    part.interchange_skin = {"name": "Rig", "nodes": nodes, "joints": [0, 1],
                             "inverse_bind_matrices": [list(_identity_matrix()), inverse]}
    part.interchange_node_index = 2
    mesh = ParsedMesh(path=str(root / "source.gltf"), format="gltf", submeshes=[part], total_vertices=3, total_faces=1,
                      has_bones=True, has_uvs=True)
    mesh.interchange_nodes = nodes
    mesh.interchange_animations = [{"name": "MovePart", "channels": [{"sampler": 0, "target": {"node": 2, "path": "translation"}}],
                                    "samplers": [{"input": [(0,), (1,)], "output": [(0, 0, 0), (0.2, 0, 0)],
                                                  "type": "VEC3", "interpolation": "LINEAR"}]}]
    return mesh


def glb_document(path):
    raw = Path(path).read_bytes()
    length, kind = struct.unpack_from("<II", raw, 12)
    assert kind == 0x4E4F534A
    return json.loads(raw[20:20 + length])


def test_glb_contains_and_reads_all_authored_channels(tmp_path):
    mesh = authored_mesh(tmp_path / "source")
    files = export_glb(mesh, tmp_path / "out")
    document = glb_document(files[0])
    attrs = document["meshes"][0]["primitives"][0]["attributes"]
    assert {"POSITION", "NORMAL", "TEXCOORD_0", "TEXCOORD_1", "COLOR_0", "JOINTS_0", "WEIGHTS_0", "_CDMW_VERTEX_ID"} <= attrs.keys()
    assert len(document["images"]) == 4
    assert len(document["skins"]) == 1
    assert document["animations"][0]["name"] == "MovePart"
    restored = import_glb_with_sidecar(files[0])
    part = restored.submeshes[0]
    for rows, expected in ((part.vertices, mesh.submeshes[0].vertices), (part.uv_sets[1], mesh.submeshes[0].uv_sets[1]),
                           (part.vertex_colors, mesh.submeshes[0].vertex_colors),
                           (part.morph_targets["Smile"], mesh.submeshes[0].morph_targets["Smile"])):
        for row, source in zip(rows, expected, strict=True):
            assert row == pytest.approx(source)
    assert part.morph_weights["Smile"] == pytest.approx(0.25)
    assert part.interchange_material["pbrMetallicRoughness"]["metallicFactor"] == 0.72
    assert all(Path(info["path"]).is_file() for info in part.interchange_material["textures"].values())
    again = export_glb(restored, tmp_path / "again")
    assert glb_document(again[0])["animations"][0]["channels"] == document["animations"][0]["channels"]


def test_glb_retains_morph_normals_tangents_and_unbaked_uv_bindings(tmp_path):
    mesh = authored_mesh(tmp_path / "source")
    part = mesh.submeshes[0]
    part.tangents = [(1, 0, 0)] * 3
    part.morph_normals = {"Smile": [(0.125, 0, 1)] * 3}
    part.morph_tangents = {"Smile": [(1, 0.125, 0)] * 3}
    info = part.interchange_material["textures"]["baseColorTexture"]
    info["texCoord"] = 1
    info["extensions"] = {"KHR_texture_transform": {"offset": [0.1, 0.2], "scale": [2, 3]}}
    path = export_glb(mesh, tmp_path / "out")[0]
    restored = import_glb_with_sidecar(path).submeshes[0]
    for attr in ("uvs", "tangents"):
        for actual, expected in zip(getattr(restored, attr), getattr(part, attr), strict=True):
            assert actual == pytest.approx(expected)
    assert restored.morph_normals == part.morph_normals
    assert restored.morph_tangents == part.morph_tangents
    binding = restored.interchange_material["textures"]["baseColorTexture"]
    assert binding["texCoord"] == 1
    assert binding["extensions"] == info["extensions"]


def test_glb_retains_scaled_bind_matrices_and_fbx_reports_normalization(tmp_path):
    mesh = authored_mesh(tmp_path / "source")
    skin = mesh.submeshes[0].interchange_skin
    mesh.interchange_nodes[0]["scale"] = [2, 3, 4]
    inverse_root = list(_identity_matrix())
    inverse_root[0], inverse_root[5], inverse_root[10] = 0.5, 1 / 3, 0.25
    inverse_child = list(inverse_root)
    inverse_child[13] = -1
    skin["inverse_bind_matrices"] = [inverse_root, inverse_child]
    path = export_glb(mesh, tmp_path / "glb")[0]
    restored = import_glb_with_sidecar(path)
    assert restored.interchange_nodes[0]["scale"] == [2, 3, 4]
    for actual, expected in zip(restored.submeshes[0].interchange_skin["inverse_bind_matrices"], skin["inverse_bind_matrices"]):
        assert actual == pytest.approx(expected)
    fbx = export_fbx(mesh, str(tmp_path / "fbx"), "mesh")
    report = json.loads(Path(f"{fbx}.meta.json").read_text())["interchange_report"]
    assert any("bone bind scale/shear" in row for row in report["omitted_from_interchange"])


def test_preview_obj_decodes_dds_and_includes_material_support_maps(tmp_path):
    from cdmw.core.model_export import export_model_preview_to_obj
    from cdmw.models import ModelPreviewData, ModelPreviewMesh
    base = tmp_path / "base.dds"
    normal, emission = tmp_path / "normal.dds", tmp_path / "emission.dds"
    for path, color in ((base, (200, 120, 60, 255)), (normal, (128, 128, 255, 255)), (emission, (40, 80, 120, 255))):
        Image.new("RGBA", (4, 4), color).save(path)
    part = ModelPreviewMesh(material_name="Body", positions=[(0, 0, 0), (1, 0, 0), (0, 1, 0)], indices=[0, 1, 2],
                            texture_coordinates=[(0, 0), (1, 0), (0, 1)], preview_texture_path=str(base),
                            preview_normal_texture_path=str(normal), preview_emissive_texture_path=str(emission))
    path = export_model_preview_to_obj(ModelPreviewData(meshes=[part]), tmp_path / "out/mesh.obj")
    mtl = path.with_suffix(".mtl").read_text()
    for command in ("map_Kd", "map_Bump", "map_Ke"):
        reference = next(line.split()[-1] for line in mtl.splitlines() if line.startswith(command + " "))
        with Image.open(path.parent / reference) as image:
            assert image.format == "PNG" and image.size == (4, 4)
    assert base.read_bytes().startswith(b"DDS ")


@pytest.mark.parametrize("format_name", ["obj", "fbx", "glb"])
def test_moved_package_retains_portable_protected_texture_sources(tmp_path, format_name):
    mesh = authored_mesh(tmp_path / "source")
    files = {"obj": export_obj, "fbx": export_fbx, "glb": export_glb}[format_name](mesh, str(tmp_path / "out"), "mesh")
    exported = Path(files if isinstance(files, str) else files[0])
    moved = tmp_path / "moved"
    exported.parent.rename(moved)
    for source in (tmp_path / "source").glob("*.png"):
        source.unlink()
    path = moved / exported.name
    payload = (_load_glb_roundtrip_sidecar(path) if format_name != "obj"
               else _load_obj_roundtrip_sidecar(str(path)))
    for entry in payload["lods"][0]["submeshes"]:
        for info in entry["interchange_material"]["textures"].values():
            assert Path(info["path"]).is_file()
            assert Path(info["path"]).is_relative_to(moved)


def test_game_glb_reexport_retains_source_palette_and_coordinate_frame(tmp_path):
    from tests.test_static_skin_weight_export import _skinned_pac
    from cdmw.modding.skeleton_parser import Bone, Skeleton
    raw, mesh = _skinned_pac()
    mesh._cdmw_original_data = raw
    rig = Skeleton(path="Rig", bones=[Bone(index=0, name="Root", parent_index=-1),
                                     Bone(index=1, name="Child", parent_index=0),
                                     Bone(index=2, name="Tip", parent_index=1)], bone_count=3)
    path = export_glb(mesh, tmp_path / "out", skeleton=rig, bone_palette=[2, 0, 1])[0]
    restored = import_glb_with_sidecar(path)
    assert restored.submeshes[0].bone_indices == mesh.submeshes[0].bone_indices
    again = export_glb(restored, tmp_path / "again")[0]
    reread = import_glb_with_sidecar(again)
    assert reread.submeshes[0].bone_indices == mesh.submeshes[0].bone_indices
    assert reread.submeshes[0].vertices == mesh.submeshes[0].vertices


def test_geometry_edits_keep_additional_vertex_channels_aligned(tmp_path):
    from cdmw.modding.mesh_deformer import _remap_interchange_vertex_channels, _subdivide_interchange_vertex_channels
    mesh = authored_mesh(tmp_path / "source")
    part = mesh.submeshes[0]
    before_color, before_uv = list(part.vertex_colors), list(part.uv_sets[1])
    midpoint = tuple((a + b) / 2 for a, b in zip(part.vertices[0], part.vertices[1]))
    _subdivide_interchange_vertex_channels(part, {(0, 1): 3}, 3, [*part.vertices, midpoint])
    assert part.vertex_colors[3] == tuple((a + b) / 2 for a, b in zip(before_color[0], before_color[1]))
    assert part.uv_sets[1][3] == tuple((a + b) / 2 for a, b in zip(before_uv[0], before_uv[1]))
    _remap_interchange_vertex_channels(part, {1: 0, 3: 1}, 4)
    assert len(part.vertex_colors) == len(part.uv_sets[1]) == len(part.morph_targets["Smile"]) == 2


def test_glb_reorders_vertex_identity_and_joint_order_safely(tmp_path):
    mesh = authored_mesh(tmp_path / "source")
    path = export_glb(mesh, tmp_path / "out")[0]
    edited = import_gltf(path, preserve_authoring=True).mesh
    part = edited.submeshes[0]
    order = [2, 0, 1]
    for attr in ("vertices", "normals", "uvs", "vertex_colors", "bone_indices", "bone_weights", "interchange_vertex_ids"):
        setattr(part, attr, [getattr(part, attr)[i] for i in order])
    part.faces = [(1, 2, 0)]
    part.interchange_skin["joints"] = [1, 0]
    part.interchange_skin["inverse_bind_matrices"].reverse()
    part.bone_indices = [tuple(1 - i for i in row) for row in part.bone_indices]
    _attach_glb_sidecar(edited, _load_glb_roundtrip_sidecar(Path(path)), "edited.glb")
    assert part.source_vertex_map == order
    assert part.bone_indices == [(0, 1)] * 3
    assert part.bone_weights == [(0, 1), (1, 0), (0.25, 0.75)]
    assert part._cdmw_verified_skin_mapping


def test_glb_refuses_identity_guess_after_losing_vertex_attribute(tmp_path):
    mesh = authored_mesh(tmp_path / "source")
    path = export_glb(mesh, tmp_path / "out")[0]
    edited = import_gltf(path, preserve_authoring=True).mesh
    del edited.submeshes[0].interchange_vertex_ids
    edited.submeshes[0].vertices[0] = (0.4, 0, 0)
    with pytest.raises(ValueError, match="prove edited vertex identity"):
        _attach_glb_sidecar(edited, _load_glb_roundtrip_sidecar(Path(path)), "edited.glb")


def test_glb_refuses_inconsistent_joint_bind_edits(tmp_path):
    mesh = authored_mesh(tmp_path / "source")
    path = export_glb(mesh, tmp_path / "out")[0]
    edited = import_gltf(path, preserve_authoring=True).mesh
    edited.submeshes[0].interchange_skin["nodes"][1]["translation"] = [0, 2, 0]
    with pytest.raises(ValueError, match="joint bind frames disagree"):
        _attach_glb_sidecar(edited, _load_glb_roundtrip_sidecar(Path(path)), "edited.glb")


@pytest.mark.parametrize("format_name", ["obj", "glb"])
def test_source_record_mapping_does_not_reorder_exported_protected_channels(tmp_path, format_name):
    mesh = authored_mesh(tmp_path / "source")
    part = mesh.submeshes[0]
    part.source_vertex_map = [2, 0, 1]
    path = {"obj": export_obj, "glb": export_glb}[format_name](mesh, str(tmp_path / "out"))[0]
    restored = {"obj": import_obj, "glb": import_glb_with_sidecar}[format_name](path).submeshes[0]
    assert restored.source_vertex_map == part.source_vertex_map
    for actual, expected in zip(restored.vertex_colors, part.vertex_colors, strict=True):
        assert actual == pytest.approx(expected)
    assert restored.bone_weights == part.bone_weights
    assert not getattr(restored, "_cdmw_skin_weights_changed", False)


def test_obj_material_maps_are_portable_and_limitations_explicit(tmp_path):
    mesh = authored_mesh(tmp_path / "source")
    files = export_obj(mesh, str(tmp_path / "out"), "mesh")
    mtl = (tmp_path / "out" / "mesh.mtl").read_text()
    assert float(next(line for line in mtl.splitlines() if line.startswith("Pm ")).split()[1]) == 1.0
    for directive in ("map_Kd", "map_Bump", "map_Pr", "map_Pm", "map_Ke"):
        line = next(line for line in mtl.splitlines() if line.startswith(directive + " "))
        assert (tmp_path / "out" / line.split()[-1]).is_file()
    payload = json.loads(Path(files[0] + ".meta.json").read_text())
    assert "morph targets" in payload["interchange_report"]["omitted_from_interchange"]
    restored = import_obj(files[0])
    assert restored.submeshes[0].vertex_colors == mesh.submeshes[0].vertex_colors


@pytest.mark.parametrize("format_name", ["obj", "fbx", "glb"])
def test_missing_texture_is_reported_for_every_format(tmp_path, format_name):
    mesh = authored_mesh(tmp_path / "source")
    Path(mesh.submeshes[0].interchange_material["textures"]["normalTexture"]["path"]).unlink()
    export = {"obj": export_obj, "fbx": export_fbx, "glb": export_glb}[format_name]
    files = export(mesh, str(tmp_path / "out"), "mesh")
    path = files if isinstance(files, str) else files[0]
    report = json.loads(Path(path + ".meta.json").read_text())["interchange_report"]
    assert len(report["missing_textures"]) == 1
    assert "normalTexture" in report["missing_textures"][0]


def test_sidecar_no_uv_preserves_absence_in_static_import(tmp_path):
    from cdmw.modding.scene_importer import import_scene_mesh
    mesh = authored_mesh(tmp_path / "source")
    mesh.submeshes[0].uvs = []
    mesh.submeshes[0].uv_sets = {}
    path = export_obj(mesh, str(tmp_path / "out"), "mesh")[0]
    restored = import_scene_mesh(path)
    assert restored.submeshes[0].uvs == []


def test_glb_sparse_accessor_expands_and_rejects_truncation():
    from cdmw.modding.scene_gltf_geometry import _read_gltf_accessor
    document = {"accessors": [{"componentType": 5126, "count": 3, "type": "VEC3",
                              "sparse": {"count": 1, "indices": {"bufferView": 0, "componentType": 5121}, "values": {"bufferView": 1}}}],
                "bufferViews": [{"buffer": 0, "byteLength": 1}, {"buffer": 0, "byteOffset": 4, "byteLength": 12}]}
    payload = SimpleNamespace(document=document, buffers=[b"\x01\0\0\0" + struct.pack("<fff", 1, 2, 3)])
    assert _read_gltf_accessor(payload, 0, expected_components=3) == [(0, 0, 0), (1, 2, 3), (0, 0, 0)]
    payload.buffers[0] = payload.buffers[0][:-1]
    with pytest.raises(ValueError, match="buffer|bounds|truncat",):
        _read_gltf_accessor(payload, 0, expected_components=3)


def test_glb_pac_preserves_no_edit_bytes_and_applies_verified_weight_edit(tmp_path):
    from tests.test_static_skin_weight_export import _skinned_pac
    from cdmw.modding.skeleton_parser import Bone, Skeleton
    from cdmw.modding.mesh_importer import build_mesh
    from cdmw.modding.mesh_parser import parse_pac
    raw, mesh = _skinned_pac()
    mesh._cdmw_original_data = raw
    mesh.interchange_skeleton = Skeleton(bones=[Bone(index=i, name=f"Bone{i}", parent_index=i - 1, position=(0, i, 0)) for i in range(3)])
    path = export_glb(mesh, tmp_path)[0]
    restored = import_glb_with_sidecar(path)
    assert build_mesh(restored, raw) == raw
    edited = import_gltf(path, preserve_authoring=True).mesh
    edited.submeshes[0].bone_indices[0] = (0, 1)
    edited.submeshes[0].bone_weights[0] = (0.5, 0.5)
    _attach_glb_sidecar(edited, _load_glb_roundtrip_sidecar(Path(path)), "edited.glb")
    rebuilt = build_mesh(edited, raw)
    actual = parse_pac(rebuilt).submeshes[0]
    assert actual.bone_indices[0][:2] == (0, 1)
    assert actual.bone_weights[0][:2] == pytest.approx((0.5, 0.5), abs=1 / 255)
    for offset in mesh.submeshes[0].source_vertex_offsets[1:]:
        assert rebuilt[offset:offset + 40] == raw[offset:offset + 40]


def test_separate_scalar_and_opacity_maps_are_packed_for_glb(tmp_path):
    mesh = authored_mesh(tmp_path / "source")
    textures = mesh.submeshes[0].interchange_material["textures"]
    packed = textures.pop("metallicRoughnessTexture")
    textures["roughnessTexture"] = dict(packed)
    textures["metallicTexture"] = dict(packed)
    textures["opacityTexture"] = dict(packed)
    path = export_glb(mesh, tmp_path / "out")[0]
    material = import_gltf(path, preserve_authoring=True).mesh.submeshes[0].interchange_material
    assert {"baseColorTexture", "metallicRoughnessTexture"} <= material["textures"].keys()
    with Image.open(material["textures"]["baseColorTexture"]["path"]) as image:
        assert image.getpixel((0, 0))[3] == 180 * 180 // 255


def test_companion_recovers_only_missing_uv_sets_in_vertex_identity_order(tmp_path):
    mesh = authored_mesh(tmp_path / "source")
    path = export_glb(mesh, tmp_path / "out")[0]
    incoming = import_gltf(path, preserve_authoring=True).mesh
    part = incoming.submeshes[0]
    order = [2, 0, 1]
    part.vertices = [part.vertices[index] for index in order]
    part.interchange_vertex_ids = order
    edited_uvs = [(0.35, 0.45)] * 3
    part.uvs, part.uv_sets = edited_uvs, {0: edited_uvs}
    _attach_glb_sidecar(incoming, _load_glb_roundtrip_sidecar(Path(path)), "edited.glb")
    assert part.uvs == part.uv_sets[0] == edited_uvs
    assert part.uv_sets[1] == [mesh.submeshes[0].uv_sets[1][index] for index in order]


def test_companion_recovers_omitted_material_channels_without_overwriting_edits(tmp_path):
    mesh = authored_mesh(tmp_path / "source")
    path = export_glb(mesh, tmp_path / "out")[0]
    incoming = import_gltf(path, preserve_authoring=True).mesh
    part = incoming.submeshes[0]
    material = part.interchange_material
    material["textures"].pop("baseColorTexture")
    material["textures"]["normalTexture"] = {"path": "edited-normal.png", "texCoord": 1, "scale": 0.3}
    material["pbrMetallicRoughness"]["roughnessFactor"] = 0.4
    material.pop("extensions")
    _attach_glb_sidecar(incoming, _load_glb_roundtrip_sidecar(Path(path)), "edited.glb")
    restored = part.interchange_material
    with Image.open(restored["textures"]["baseColorTexture"]["path"]) as image:
        assert image.getpixel((0, 0)) == (200, 120, 60, 180)
    assert restored["textures"]["normalTexture"] == {"path": "edited-normal.png", "texCoord": 1, "scale": 0.3}
    assert restored["pbrMetallicRoughness"]["roughnessFactor"] == 0.4
    assert restored["extensions"] == mesh.submeshes[0].interchange_material["extensions"]
    assert part.preview_texture_path == restored["textures"]["baseColorTexture"]["path"]


@pytest.mark.parametrize("source_format", ["fbx", "glb"])
def test_obj_return_restores_static_coordinates_from_other_format_companion(tmp_path, source_format):
    mesh = authored_mesh(tmp_path / "source")
    part = mesh.submeshes[0]
    part.bone_indices, part.bone_weights, part.interchange_skin = [], [], {}
    part.interchange_transform = (1.5, 0, 0, 2, 0, 2, 0, 3, 0, 0, 0.75, 4, 0, 0, 0, 1)
    exported = {"fbx": export_fbx, "glb": export_glb}[source_format](mesh, str(tmp_path / "out"), "source")
    original = Path(exported if isinstance(exported, str) else exported[0])
    returned = Path(export_obj(mesh, str(original.parent), "returned")[0])
    Path(f"{returned}.meta.json").write_bytes(Path(f"{original}.meta.json").read_bytes())
    restored = import_obj(str(returned)).submeshes[0]
    for actual, expected in zip(restored.vertices, part.vertices, strict=True):
        assert actual == pytest.approx(expected)
    assert restored.interchange_transform == part.interchange_transform


def test_split_obj_keeps_scene_clips_source_and_selected_part_metadata(tmp_path):
    mesh = authored_mesh(tmp_path / "source")
    second = copy.deepcopy(mesh.submeshes[0])
    second.name, second.material = "Trim", "TrimMat"
    mesh.submeshes.append(second)
    mesh.lod_levels = [list(mesh.submeshes)]
    mesh._cdmw_original_data = b"owned original mesh bytes"
    mesh._cdmw_mesh_asset_lods = [{"name": "OriginalLOD", "metadata": {"protected": True}, "submeshes": [
        {"stable_id": "original-body", "material_slot_index": 3},
        {"stable_id": "original-trim", "material_slot_index": 7}]}]
    files = export_obj(mesh, str(tmp_path / "out"), "parts", split_submeshes=True,
                       extra_payload={"export_context": "selected parts"})
    for index, path in enumerate(Path(file) for file in files if Path(file).suffix == ".obj"):
        payload = json.loads(Path(f"{path}.meta.json").read_text())
        entry = payload["lods"][0]["submeshes"][0]
        assert len(payload["lods"]) == len(payload["lods"][0]["submeshes"]) == 1
        assert entry["stable_id"] == ("original-body", "original-trim")[index]
        assert entry["material_slot_index"] == (3, 7)[index]
        assert payload["source_asset_size"] == len(mesh._cdmw_original_data)
        assert payload["export_context"] == "selected parts"
        restored = import_obj(str(path))
        assert len(restored.submeshes) == 1
        assert restored.interchange_nodes == mesh.interchange_nodes
        assert json.dumps(restored.interchange_animations, sort_keys=True) == json.dumps(mesh.interchange_animations, sort_keys=True)
        assert restored.submeshes[0].interchange_skin == mesh.submeshes[index].interchange_skin
    assert len(mesh.submeshes) == len(mesh.lod_levels[0]) == 2


def test_obj_companion_matching_retains_identity_after_blender_name_suffix_and_reordering(tmp_path):
    from cdmw.modding.mesh_obj_importer import _match_obj_roundtrip_sidecar_submeshes
    mesh = authored_mesh(tmp_path / "source")
    trim = copy.deepcopy(mesh.submeshes[0])
    trim.name, trim.material = "Trim", "TrimMat"
    mesh.submeshes.append(trim)
    path = export_glb(mesh, tmp_path / "out")[0]
    payload = _load_glb_roundtrip_sidecar(Path(path))
    entries = _match_obj_roundtrip_sidecar_submeshes(payload, [
        {"name": "Trim", "material": "TrimMat"}, {"name": "Body.001", "material": "BodyMat"}],
        source_path="", source_format="")
    assert [entry["name"] for entry in entries] == ["Trim", "Body"]
    assert [entry["submesh_index"] for entry in entries] == [1, 0]


def test_obj_companion_summary_without_skin_does_not_override_authoritative_bind_coordinates(tmp_path):
    mesh = authored_mesh(tmp_path / "source")
    part = mesh.submeshes[0]
    part.interchange_transform = (2, 0, 0, 3, 0, 3, 0, 4, 0, 0, 1, 5, 0, 0, 0, 1)
    path = export_obj(mesh, str(tmp_path / "out"))[0]
    manifest = Path(f"{path}.meta.json")
    payload = json.loads(manifest.read_text())
    for entry in payload["submeshes"]:
        entry.pop("interchange_skin", None)
        entry.pop("interchange_bone_indices", None)
    manifest.write_text(json.dumps(payload))
    restored = import_obj(path).submeshes[0]
    assert restored.vertices == part.vertices
    assert tuple(restored.interchange_transform) == part.interchange_transform


def test_glb_companion_restores_part_order_and_metadata_after_blender_renames(tmp_path):
    mesh = authored_mesh(tmp_path / "source")
    trim = copy.deepcopy(mesh.submeshes[0])
    trim.name, trim.material = "Trim", "TrimMat"
    trim.morph_targets, trim.morph_weights = {}, {}
    mesh.submeshes.append(trim)
    path = export_glb(mesh, tmp_path / "out")[0]
    incoming = import_gltf(path, preserve_authoring=True).mesh
    incoming.submeshes.reverse()
    incoming.submeshes[1].name = "Body.001"
    incoming.submeshes[1].morph_targets = {}
    _attach_glb_sidecar(incoming, _load_glb_roundtrip_sidecar(Path(path)), "returned.glb")
    assert [part.material for part in incoming.submeshes] == ["BodyMat", "TrimMat"]
    assert incoming.submeshes[0].morph_targets == mesh.submeshes[0].morph_targets
    assert incoming.submeshes[1].morph_targets == {}


def test_scene_companion_recovery_updates_preview_files_and_material_binding_indices(tmp_path, monkeypatch):
    from dataclasses import replace
    from cdmw.modding.scene_importer import import_scene_mesh_with_report
    mesh = authored_mesh(tmp_path / "source")
    trim = copy.deepcopy(mesh.submeshes[0])
    trim.name, trim.material = "Trim", "TrimMat"
    mesh.submeshes.append(trim)
    path = export_glb(mesh, tmp_path / "out")[0]
    incoming = import_gltf(path, preserve_authoring=True)
    incoming.mesh.submeshes.reverse()
    incoming.material_bindings = tuple(replace(binding, submesh_index=index, texture_slots=())
                                      for index, binding in enumerate(reversed(incoming.material_bindings)))
    for part in incoming.mesh.submeshes:
        part.interchange_material["textures"].pop("baseColorTexture")
        del part.preview_texture_path
    monkeypatch.setattr("cdmw.modding.scene_importer.import_gltf", lambda *a, **k: incoming)
    result = import_scene_mesh_with_report(path, preserve_authoring=True)
    assert [binding.material_name for binding in result.material_bindings] == ["BodyMat", "TrimMat"]
    for binding in result.material_bindings:
        part = result.mesh.submeshes[binding.submesh_index]
        assert binding.material_name == part.material
        base = dict(binding.texture_slots)["base"]
        assert str(base) == part.preview_texture_path
        assert base.is_file() and base in result.discovered_texture_files


def test_glb_companion_restores_bounds_with_local_coordinates(tmp_path):
    from cdmw.modding.scene_geometry_utils import _bake_interchange_coordinates
    mesh = authored_mesh(tmp_path / "source")
    part = mesh.submeshes[0]
    part.bone_indices, part.bone_weights, part.interchange_skin = [], [], {}
    part.interchange_transform = (1, 0, 0, 3, 0, 1, 0, 4, 0, 0, 1, 5, 0, 0, 0, 1)
    mesh.interchange_nodes[2]["translation"] = [3, 4, 5]
    path = export_glb(mesh, tmp_path / "out")[0]
    incoming = import_gltf(path, preserve_authoring=True).mesh
    _bake_interchange_coordinates(incoming.submeshes[0])
    incoming.bbox_min, incoming.bbox_max = (3, 4, 5), (4, 5, 5)
    _attach_glb_sidecar(incoming, _load_glb_roundtrip_sidecar(Path(path)), "returned.glb")
    assert incoming.bbox_min == pytest.approx((0, 0, 0))
    assert incoming.bbox_max == pytest.approx((1, 1, 0))
