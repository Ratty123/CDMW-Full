"""Real Blender interchange checks; set CDMW_TEST_BLENDER_EXE to run."""

from __future__ import annotations

import json
import os
import struct
import subprocess
from pathlib import Path

import pytest

from cdmw.modding.mesh_exporter import export_fbx, export_obj
from cdmw.modding.mesh_glb_interchange import export_glb, import_glb_with_sidecar
from cdmw.modding.scene_gltf_import import import_gltf
from cdmw.modding.scene_importer import import_fbx
from tests.test_mesh_interchange_authoring import authored_mesh, glb_document


_SCRIPT = r'''
import bpy, json, sys
from pathlib import Path
source, target, report = map(Path, sys.argv[sys.argv.index("--") + 1:])
bpy.ops.wm.read_factory_settings(use_empty=True)
if source.suffix == ".fbx":
    bpy.ops.import_scene.fbx(filepath=str(source))
elif source.suffix == ".obj":
    bpy.ops.wm.obj_import(filepath=str(source))
else:
    bpy.ops.import_scene.gltf(filepath=str(source))
facts = []
for obj in bpy.data.objects:
    if obj.type != "MESH":
        continue
    part = {"name": obj.name, "vertices": [list(v.co) for v in obj.data.vertices],
            "uv_names": [layer.name for layer in obj.data.uv_layers],
            "colors": [a.name for a in obj.data.color_attributes],
            "groups": [group.name for group in obj.vertex_groups],
            "morphs": [key.name for key in obj.data.shape_keys.key_blocks] if obj.data.shape_keys else [],
            "morph_weights": {key.name: key.value for key in obj.data.shape_keys.key_blocks} if obj.data.shape_keys else {},
            "materials": []}
    for slot in obj.material_slots:
        mat = slot.material
        if mat is None:
            continue
        shader = next(n for n in mat.node_tree.nodes if n.type == "BSDF_PRINCIPLED")
        part["materials"].append({"name": mat.name, "metallic": shader.inputs["Metallic"].default_value,
                                  "roughness": shader.inputs["Roughness"].default_value,
                                  "images": [n.image.name for n in mat.node_tree.nodes if n.type == "TEX_IMAGE" and n.image],
                                  "linked": [i.name for i in shader.inputs if i.is_linked]})
    facts.append(part)
report.write_text(json.dumps(facts, indent=2))
bpy.ops.export_scene.gltf(filepath=str(target), export_format="GLB", export_attributes=True,
                          export_skins=True, export_morph=True, export_animations=True)
'''


def blender_executable():
    executable = os.environ.get("CDMW_TEST_BLENDER_EXE", "")
    if not executable:
        pytest.skip("CDMW_TEST_BLENDER_EXE is not set")
    assert Path(executable).is_file()
    return executable


def _run_blender(root, source, returned):
    script = root / "roundtrip.py"
    script.write_text(_SCRIPT)
    report = root / "blender.json"
    run = subprocess.run([blender_executable(), "--background", "--factory-startup", "--python-exit-code", "31",
                          "--python", str(script), "--", str(source), str(returned), str(report)],
                         capture_output=True, text=True, timeout=60)
    (root / "blender.log").write_text(run.stdout + run.stderr)
    assert run.returncode == 0, (run.stdout + run.stderr)[-3000:]
    return json.loads(report.read_text())


@pytest.mark.parametrize("format_name", ["glb", "fbx", "obj"])
def test_blender_import_and_export_rich_channels(tmp_path, format_name):
    blender = blender_executable()
    mesh = authored_mesh(tmp_path / "source")
    files = {"glb": export_glb, "fbx": export_fbx, "obj": export_obj}[format_name](mesh, str(tmp_path / "out"), "mesh")
    source = Path(files if isinstance(files, str) else files[0])
    returned = source.with_name("edited.glb")
    part = _run_blender(tmp_path, source, returned)[0]
    assert len(part["vertices"]) == 3
    assert len(part["materials"][0]["images"]) >= 4
    returned_part = import_gltf(returned, preserve_authoring=True).mesh.submeshes[0]
    for actual, expected in zip(returned_part.uvs, mesh.submeshes[0].uvs, strict=True):
        assert actual == pytest.approx(expected, abs=2e-6)
    if format_name in {"glb", "fbx"}:
        assert len(part["uv_names"]) >= 2
        assert part["colors"]
        assert {"Root", "Child"} <= set(part["groups"])
        assert "Smile" in part["morphs"]
        assert part["morph_weights"]["Smile"] == pytest.approx(0.25)
    if format_name == "glb":
        Path(str(returned) + ".meta.json").write_bytes(Path(str(source) + ".meta.json").read_bytes())
        imported = import_glb_with_sidecar(returned)
        assert imported.submeshes[0].source_vertex_map == [0, 1, 2]
        assert imported.submeshes[0].morph_targets
        pbr = glb_document(returned)["materials"][0]["pbrMetallicRoughness"]
        assert pbr["metallicFactor"] == pytest.approx(0.72)
        assert pbr["roughnessFactor"] == pytest.approx(0.17)
        assert imported.interchange_animations
    if format_name == "fbx":
        imported = import_fbx(source, blender_path=blender)
        assert imported.submeshes[0].source_vertex_map == [0, 1, 2]
        assert imported.submeshes[0].bone_weights == mesh.submeshes[0].bone_weights
        assert set(imported.submeshes[0].uv_sets) == {0, 1}
    if format_name in {"obj", "fbx"}:
        from PIL import Image
        material = import_gltf(returned, preserve_authoring=True).mesh.submeshes[0].interchange_material
        pbr = material["pbrMetallicRoughness"]
        with Image.open(material["textures"]["metallicRoughnessTexture"]["path"]) as image:
            _, rough, metal = image.convert("RGB").getpixel((0, 0))
        assert metal / 255 * pbr.get("metallicFactor", 1) == pytest.approx(220 / 255 * 0.72, abs=1 / 255)
        assert rough / 255 * pbr.get("roughnessFactor", 1) == pytest.approx(100 / 255 * 0.17, abs=1 / 255)
        assert material["textures"]["normalTexture"].get("scale", 1) == pytest.approx(0.7)
    # The returned GLB also has to be readable by the application, not only Blender.
    assert import_gltf(returned, preserve_authoring=True).mesh.total_faces == 1


@pytest.mark.parametrize("source_format", ["pac", "pam", "pamlod"])
@pytest.mark.parametrize("exchange_format", ["obj", "fbx", "glb"])
def test_blender_no_edit_game_mesh_rebuild_is_byte_identical(tmp_path, source_format, exchange_format):
    blender_executable()
    from tests.test_static_skin_weight_export import _skinned_pac
    from tests.test_mesh_import_paired_lod import _static_payload
    from tests.test_archive_mesh_export_fidelity import _entry
    from cdmw.modding.mesh_parser import parse_mesh
    from cdmw.modding.mesh_pac_builder import _pack_pac_normal
    from cdmw.core.archive_mesh_import_preview import build_mesh_import_preview
    if source_format == "pac":
        raw, original = _skinned_pac()
        raw = bytearray(raw)
        for offset in original.submeshes[0].source_vertex_offsets:
            word = struct.unpack_from("<I", raw, offset + 16)[0]
            struct.pack_into("<I", raw, offset + 16, _pack_pac_normal((0, 0, 1), word))
        raw = bytes(raw)
    else:
        raw = _static_payload(lod=source_format == "pamlod")
    source_path = tmp_path / f"source.{source_format}"
    source_path.write_bytes(raw)
    mesh = parse_mesh(raw, str(source_path))
    mesh._cdmw_original_data = raw
    files = {"glb": export_glb, "fbx": export_fbx, "obj": export_obj}[exchange_format](mesh, str(tmp_path / "out"), "mesh")
    exported = Path(files if isinstance(files, str) else files[0])
    returned = exported.with_name("edited.glb")
    _run_blender(tmp_path, exported, returned)
    Path(str(returned) + ".meta.json").write_bytes(Path(str(exported) + ".meta.json").read_bytes())
    entry = _entry(tmp_path / "archive", f"object/source.{source_format}", raw)
    result = build_mesh_import_preview(entry, returned, import_mode="roundtrip")
    assert result.rebuilt_data == raw
    assert source_path.read_bytes() == raw


@pytest.mark.parametrize("exchange_format", ["fbx", "glb"])
def test_blender_position_and_weight_edits_change_only_owned_pac_bytes(tmp_path, exchange_format):
    from tests.test_static_skin_weight_export import _skinned_pac
    from tests.test_archive_mesh_export_fidelity import _entry
    from cdmw.modding.skeleton_parser import Bone, Skeleton
    from cdmw.modding.mesh_parser import parse_pac, PAC_SKIN_WEIGHT_OFFSET, PAC_SKIN_INFLUENCES, PAC_SKIN_SLOT_GROUPS
    from cdmw.modding.mesh_pac_builder import _pack_pac_normal
    from cdmw.core.archive_mesh_import_preview import build_mesh_import_preview

    raw, original = _skinned_pac()
    raw = bytearray(raw)
    for offset in original.submeshes[0].source_vertex_offsets:
        word = struct.unpack_from("<I", raw, offset + 16)[0]
        struct.pack_into("<I", raw, offset + 16, _pack_pac_normal((0, 0, 1), word))
    raw = bytes(raw)
    mesh = parse_pac(raw, "source.pac")
    mesh._cdmw_original_data = raw
    mesh.interchange_skeleton = Skeleton(bones=[Bone(index=i, name=f"Bone{i}", parent_index=i - 1,
                                                    position=(0, i, 0)) for i in range(3)])
    files = {"fbx": export_fbx, "glb": export_glb}[exchange_format](mesh, str(tmp_path / "out"), "mesh")
    exported = Path(files if isinstance(files, str) else files[0])
    returned = exported.with_name(f"edited.{exchange_format}")
    edit = '''
obj = next(o for o in bpy.data.objects if o.type == "MESH" and o.vertex_groups.get("Bone0"))
obj.data.vertices[0].co.x += 0.125
for group in obj.vertex_groups:
    group.remove([0])
obj.vertex_groups["Bone0"].add([0], 0.5, "REPLACE")
obj.vertex_groups["Bone1"].add([0], 0.5, "REPLACE")
'''
    script = _SCRIPT.replace("facts = []", edit + "\nfacts = []")
    if exchange_format == "fbx":
        script = script.replace('bpy.ops.export_scene.gltf(filepath=str(target), export_format="GLB", export_attributes=True,\n'
                                '                          export_skins=True, export_morph=True, export_animations=True)',
                                'bpy.ops.export_scene.fbx(filepath=str(target), add_leaf_bones=False, bake_anim=False)')
    path = tmp_path / "edit.py"
    path.write_text(script)
    run = subprocess.run([blender_executable(), "--background", "--factory-startup", "--python-exit-code", "31",
                          "--python", str(path), "--", str(exported), str(returned), str(tmp_path / "edit.json")],
                         capture_output=True, text=True, timeout=60)
    (tmp_path / "edit.log").write_text(run.stdout + run.stderr)
    assert run.returncode == 0, (run.stdout + run.stderr)[-3000:]
    Path(str(returned) + ".meta.json").write_bytes(Path(str(exported) + ".meta.json").read_bytes())
    entry = _entry(tmp_path / "archive", "object/source.pac", raw)
    result = build_mesh_import_preview(entry, returned, import_mode="roundtrip")
    (tmp_path / "rebuilt.pac").write_bytes(result.rebuilt_data)
    part = parse_pac(result.rebuilt_data).submeshes[0]
    assert part.vertices[0][0] == pytest.approx(mesh.submeshes[0].vertices[0][0] + 0.125, abs=1e-4)
    weights = {i: w for i, w in zip(part.bone_indices[0], part.bone_weights[0]) if w}
    assert weights == pytest.approx({0: 0.5, 1: 0.5}, abs=1 / 255)
    offset = mesh.submeshes[0].source_vertex_offsets[0]
    allowed = set(range(offset, offset + 6)) | set(range(offset + PAC_SKIN_WEIGHT_OFFSET, offset + PAC_SKIN_WEIGHT_OFFSET + PAC_SKIN_INFLUENCES))
    for slot_offset in PAC_SKIN_SLOT_GROUPS:
        allowed.update(range(offset + slot_offset, offset + slot_offset + 4))
    changed = {i for i, (before, after) in enumerate(zip(raw, result.rebuilt_data, strict=True)) if before != after}
    assert changed and changed <= allowed


@pytest.mark.parametrize("exchange_format", ["obj", "fbx", "glb"])
@pytest.mark.parametrize("mirrored", [False, True])
@pytest.mark.parametrize("skinned", [False, True])
def test_blender_transformed_scene_returns_to_original_local_coordinates(tmp_path, exchange_format, mirrored, skinned):
    from cdmw.modding.mesh_obj_importer import import_obj
    mesh = authored_mesh(tmp_path / "source")
    part = mesh.submeshes[0]
    if not skinned:
        part.bone_indices, part.bone_weights, part.interchange_skin = [], [], {}
    mesh.interchange_animations = []
    scale_x = -2 if mirrored else 2
    part.interchange_transform = (scale_x, 0, 0, 3, 0, 3, 0, 4, 0, 0, 1, 5, 0, 0, 0, 1)
    mesh.interchange_nodes[2].update(translation=[3, 4, 5], scale=[scale_x, 3, 1])
    files = {"obj": export_obj, "fbx": export_fbx, "glb": export_glb}[exchange_format](mesh, str(tmp_path / "out"), "mesh")
    exported = Path(files if isinstance(files, str) else files[0])
    returned = exported.with_name("returned.glb")
    _run_blender(tmp_path, exported, returned)
    Path(str(returned) + ".meta.json").write_bytes(Path(str(exported) + ".meta.json").read_bytes())
    restored = import_glb_with_sidecar(returned).submeshes[0]
    for vertex, expected in zip(restored.vertices, part.vertices, strict=True):
        assert vertex == pytest.approx(expected, abs=2e-6)
    assert restored.faces == part.faces
    assert restored.interchange_transform == part.interchange_transform
    if exchange_format == "obj":
        imported = import_obj(str(exported)).submeshes[0]
        for vertex, expected in zip(imported.vertices, part.vertices, strict=True):
            assert vertex == pytest.approx(expected, abs=2e-6)
