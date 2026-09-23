"""Exercise FBX material recovery through the New Item import entry point."""

import hashlib
import json
import struct
import threading
import zipfile
from pathlib import Path
from types import SimpleNamespace

import pytest

from cdmw.services.mesh_dotnet_material_state import mesh_dotnet_material_state_payload
from cdmw.services.mesh_rust_authoring import _mesh_material_presentations
from cdmw.services.new_item_materials import source_materials_from_import
from cdmw.ui.new_item.model_import import load_model_import_source
from tests.scene_gltf_test_support import valid_image_bytes
from tests.test_scene_importer_gltf import _triangle_payload


def _converted_glb(declared_channels: tuple[str, ...]) -> bytes:
    binary, document = _triangle_payload()
    pbr = {
        "baseColorFactor": [0.5, 0.5, 0.5, 1.0],
        "roughnessFactor": 0.55,
        "metallicFactor": 0.0,
    }
    document["materials"] = [
        {"name": "lambert1", "pbrMetallicRoughness": pbr},
        {"name": "Gem_outside", "pbrMetallicRoughness": {
            "baseColorFactor": [1.0, 1.0, 0.0, 1.0],
            "roughnessFactor": 0.75, "metallicFactor": 0.5,
        }},
    ]
    primitive = document["meshes"][0]["primitives"][0]
    document["meshes"][0]["primitives"].append({**primitive, "material": 1})
    for channel, property_name, filename in (
        ("base", "baseColorTexture", "lambert1_Base_Color.png"),
        ("material", "metallicRoughnessTexture", "lambert1_metallicRoughness.png"),
    ):
        if channel in declared_channels:
            index = len(document.setdefault("images", []))
            document["images"].append({"uri": f"textures/{filename}"})
            document.setdefault("textures", []).append({"source": index})
            pbr[property_name] = {"index": index}
    encoded = json.dumps(document).encode("utf-8")
    encoded += b" " * (-len(encoded) % 4)
    return (
        struct.pack("<4sII", b"glTF", 2, 28 + len(encoded) + len(binary))
        + struct.pack("<I4s", len(encoded), b"JSON") + encoded
        + struct.pack("<I4s", len(binary), b"BIN\x00") + binary
    )


def _import_source(tmp_path, monkeypatch, *, fbx=True, declared=(), metallic=True, packed=False):
    payload = _converted_glb(declared)
    names = ["lambert1_Base_Color.png", "lambert1_Normal_DirectX.png", "lambert1_Roughness.png"]
    if packed:
        names.remove("lambert1_Roughness.png")
    elif metallic:
        names.append("lambert1_Metallic.png")
    if "material" in declared or packed:
        names.append("lambert1_metallicRoughness.png")
    output = tmp_path / "import"
    if fbx:
        archive = tmp_path / "sword.zip"
        with zipfile.ZipFile(archive, "w") as package:
            package.writestr("source/sword.fbx", b"FBX conversion fixture")
            for name in names:
                package.writestr(f"textures/{name}", valid_image_bytes())
        before = hashlib.sha256(archive.read_bytes()).digest()

        cancellation = threading.Event()

        def convert(source, blender, *, output_dir, on_log, stop_event):
            assert stop_event is cancellation
            assert source.read_bytes() == b"FBX conversion fixture"
            path = output_dir / "sword.glb"
            path.write_bytes(payload)
            return SimpleNamespace(glb=path)

        monkeypatch.setattr("cdmw.ui.new_item.model_import.convert_fbx_to_glb", convert)
        result = load_model_import_source(archive, extract_root=output, stop_event=cancellation)
        assert hashlib.sha256(archive.read_bytes()).digest() == before
        return result
    textures = tmp_path / "textures"
    textures.mkdir()
    for name in names:
        (textures / name).write_bytes(valid_image_bytes())
    path = tmp_path / "sword.glb"
    path.write_bytes(payload)
    return load_model_import_source(path, extract_root=output)


def _material_rows(source):
    state = mesh_dotnet_material_state_payload(
        source.scene.mesh, session_id="fbx-import", edit_revision=0, generation=0,
    )
    return state["submeshes"]


def test_fbx_zip_recovers_surface_maps_and_keeps_yellow_gem(tmp_path, monkeypatch):
    source = _import_source(tmp_path, monkeypatch)
    blade, gem = _material_rows(source)
    assert {"base", "normal", "roughness", "metallic"} <= blade["channels"].keys()
    assert blade["normal_y_policy"] == "preserve"
    assert blade["parameters"]["texture_tint"] == [1.0, 1.0, 1.0]
    assert blade["parameters"]["roughness_scale"] == 1.0
    assert blade["parameters"]["metalness_scale"] == 1.0
    renderer_blade, renderer_gem = _mesh_material_presentations(source.scene.mesh)
    assert renderer_blade["roughness"] == renderer_blade["metalness"] == 1.0
    assert renderer_gem["texture_tint"] == [1.0, 1.0, 0.0]
    assert gem["channels"] == {}
    assert gem["parameters"]["roughness"] == 0.75
    assert gem["parameters"]["metalness"] == 0.5
    assert gem["alpha_mode"] == "opaque"
    section = SimpleNamespace(target_submesh_name="blade", source_material_name="lambert1")
    exported = source_materials_from_import(
        SimpleNamespace(source_owned_output_draw_sections=(section,)), source.scene,
    )["blade"]
    assert exported.normal.name == "lambert1_Normal_DirectX.png"
    assert exported.roughness.name == "lambert1_Roughness.png"
    assert exported.metallic.name == "lambert1_Metallic.png"
    assert exported.roughness_factor == exported.metallic_factor == 1.0
    assert exported.base_slot.base_color_factor in ((), (1.0, 1.0, 1.0))


def test_fbx_packed_map_retains_channel_layout_in_output(tmp_path, monkeypatch):
    source = _import_source(tmp_path, monkeypatch, packed=True)
    blade = _material_rows(source)[0]
    assert blade["channel_components"] == {"roughness": "g", "metallic": "b"}
    section = SimpleNamespace(target_submesh_name="blade", source_material_name="lambert1")
    exported = source_materials_from_import(
        SimpleNamespace(source_owned_output_draw_sections=(section,)), source.scene,
    )["blade"]
    assert exported.material.name == "lambert1_metallicRoughness.png"
    assert exported.roughness is exported.metallic is None
    assert exported.roughness_factor == exported.metallic_factor == 1.0


@pytest.mark.parametrize("declared", [("base",), ("material",), ("base", "material")])
def test_fbx_keeps_factors_for_explicitly_linked_channels(tmp_path, monkeypatch, declared):
    source = _import_source(tmp_path, monkeypatch, declared=declared)
    blade = _material_rows(source)[0]
    parameters = blade["parameters"]
    assert parameters["texture_tint"] == ([0.5] * 3 if "base" in declared else [1.0] * 3)
    assert parameters["roughness_scale"] == (0.55 if "material" in declared else 1.0)
    assert parameters["metalness_scale"] == (0.0 if "material" in declared else 1.0)
    if declared == ("base",):
        # The linked base keeps its tint, but its parameter snapshot must carry
        # the corrected factors for the newly recovered surface maps into baking.
        texture = source.scene.mesh.submeshes[0].preview_material_texture_inputs[0]
        snapshot = {p.parameter_name: p.numeric_value for p in texture.material_parameters}
        assert snapshot["_roughnessFactor"] == snapshot["_metallicFactor"] == 1.0


def test_gltf_loose_maps_keep_authored_material_factors(tmp_path, monkeypatch):
    source = _import_source(tmp_path, monkeypatch, fbx=False)
    parameters = _material_rows(source)[0]["parameters"]
    assert parameters["texture_tint"] == [0.5, 0.5, 0.5]
    assert parameters["roughness_scale"] == 0.55
    assert parameters["metalness_scale"] == 0.0


def test_fbx_keeps_scalar_when_no_corresponding_map_is_recovered(tmp_path, monkeypatch):
    source = _import_source(tmp_path, monkeypatch, metallic=False)
    blade = _material_rows(source)[0]
    assert "metallic" not in blade["channels"]
    assert blade["parameters"]["metalness"] == 0.0
    assert blade["parameters"]["roughness_scale"] == 1.0
