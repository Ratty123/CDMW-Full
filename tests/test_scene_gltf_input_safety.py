from __future__ import annotations

import base64
import json
import struct
from pathlib import Path
from unittest.mock import patch

import pytest
from PIL import Image

from cdmw.core.atomic_file import atomic_write_bytes
from cdmw.modding.scene_gltf_uv import (
    _validate_gltf_image_payload,
    build_gltf_material_uv_plan,
    build_gltf_uv_bake_report,
)
from cdmw.modding.scene_importer import import_scene_mesh_with_report
from tests.scene_gltf_test_support import valid_image_bytes


def _write_textured_triangle(root: Path, document_edit=None) -> Path:
    positions = struct.pack("<9f", 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0, 0.0)
    uvs = struct.pack("<6f", 0.0, 0.0, 1.0, 0.0, 0.0, 1.0)
    indices = struct.pack("<3H", 0, 1, 2)
    payload = positions + uvs + indices
    document = {
        "asset": {"version": "2.0"},
        "buffers": [{"uri": "mesh.bin", "byteLength": len(payload)}],
        "bufferViews": [
            {"buffer": 0, "byteOffset": 0, "byteLength": len(positions)},
            {"buffer": 0, "byteOffset": len(positions), "byteLength": len(uvs)},
            {"buffer": 0, "byteOffset": len(positions) + len(uvs), "byteLength": len(indices)},
        ],
        "accessors": [
            {"bufferView": 0, "componentType": 5126, "count": 3, "type": "VEC3"},
            {"bufferView": 1, "componentType": 5126, "count": 3, "type": "VEC2"},
            {"bufferView": 2, "componentType": 5123, "count": 3, "type": "SCALAR"},
        ],
        "materials": [{
            "name": "Safe",
            "pbrMetallicRoughness": {"baseColorTexture": {
                "index": 0,
                "extensions": {"KHR_texture_transform": {"offset": [0.25, 0.0]}},
            }},
        }],
        "textures": [{"source": 0}],
        "images": [{"uri": "base.png"}],
        "meshes": [{"primitives": [{
            "attributes": {"POSITION": 0, "TEXCOORD_0": 1},
            "indices": 2,
            "material": 0,
        }]}],
        "nodes": [{"mesh": 0}],
        "scenes": [{"nodes": [0]}],
        "scene": 0,
    }
    if document_edit is not None:
        document_edit(document)
    (root / "mesh.bin").write_bytes(payload)
    path = root / "mesh.gltf"
    path.write_text(json.dumps(document), encoding="utf-8")
    return path


@pytest.mark.parametrize(
    ("case", "message"),
    [
        ("texture_index", "invalid texture index 9"),
        ("texture_source", "invalid texture source index"),
        ("image_index", "invalid image index 9"),
        ("image_location", "neither URI nor bufferView"),
        ("buffer_view_index", "invalid bufferView 99"),
        ("basisu", "unsupported texture extension source KHR_texture_basisu"),
        ("extension_source", "unsupported texture extension source EXT_texture_webp"),
        ("texture_metadata", "invalid texture metadata"),
    ],
)
def test_invalid_referenced_texture_graph_fails_closed(
    tmp_path: Path, case: str, message: str
) -> None:
    def break_reference(document: dict) -> None:
        texture_info = document["materials"][0]["pbrMetallicRoughness"]
        if case == "texture_index":
            texture_info["baseColorTexture"]["index"] = 9
        elif case == "texture_source":
            document["textures"][0].pop("source")
        elif case == "image_index":
            document["textures"][0]["source"] = 9
        elif case == "image_location":
            document["images"][0] = {}
        elif case == "buffer_view_index":
            document["images"][0] = {"bufferView": 99, "mimeType": "image/png"}
        elif case == "basisu":
            document["textures"][0]["extensions"] = {"KHR_texture_basisu": {"source": 0}}
        elif case == "extension_source":
            document["textures"][0]["extensions"] = {"EXT_texture_webp": {"source": 0}}
        else:
            texture_info["baseColorTexture"] = "texture-zero"

    path = _write_textured_triangle(tmp_path, break_reference)
    (tmp_path / "base.png").write_bytes(valid_image_bytes())

    with pytest.raises(ValueError, match=message):
        import_scene_mesh_with_report(path, include_external_audit=False)


@pytest.mark.parametrize(("payload", "message"), [(None, "is missing at"), (b"not-an-image", "invalid image payload")])
def test_shared_transform_path_requires_present_decodable_external_image(
    tmp_path: Path, payload: bytes | None, message: str
) -> None:
    path = _write_textured_triangle(tmp_path)
    if payload is not None:
        (tmp_path / "base.png").write_bytes(payload)

    with pytest.raises(ValueError, match=message):
        import_scene_mesh_with_report(path, include_external_audit=False)


def test_invalid_data_uri_and_buffer_view_payloads_fail_closed(tmp_path: Path) -> None:
    invalid_data = base64.b64encode(b"not-an-image").decode("ascii")
    data_uri_path = _write_textured_triangle(
        tmp_path,
        lambda document: document["images"].__setitem__(0, {"uri": f"data:image/png;base64,{invalid_data}"}),
    )
    with pytest.raises(ValueError, match="invalid image payload"):
        import_scene_mesh_with_report(data_uri_path, include_external_audit=False)

    bounded_root = tmp_path / "bounded"
    bounded_root.mkdir()

    def use_invalid_view(document: dict) -> None:
        document["images"][0] = {"bufferView": 2, "mimeType": "image/png"}
        document["bufferViews"][2]["byteLength"] = 999

    view_path = _write_textured_triangle(bounded_root, use_invalid_view)
    with pytest.raises(ValueError, match="invalid bufferView 2 bounds"):
        import_scene_mesh_with_report(view_path, include_external_audit=False)


def test_image_payload_validation_enforces_byte_and_dimension_ceilings() -> None:
    payload = valid_image_bytes()
    with (
        patch("cdmw.modding.scene_gltf_uv._GLTF_IMAGE_MAX_SOURCE_BYTES", len(payload) - 1),
        pytest.raises(ValueError, match="maximum is"),
    ):
        _validate_gltf_image_payload(payload, 0, ".png")
    with (
        patch("cdmw.modding.scene_gltf_uv._GLTF_IMAGE_MAX_DIMENSION", 0),
        pytest.raises(ValueError, match="dimensions 1x1 exceed"),
    ):
        _validate_gltf_image_payload(payload, 0, ".png")


@pytest.mark.parametrize("bomb", [Image.DecompressionBombWarning("warning"), Image.DecompressionBombError("error")])
def test_image_payload_validation_blocks_pillow_decompression_bombs(bomb: Exception) -> None:
    with (
        patch("PIL.Image.open", side_effect=bomb),
        pytest.raises(ValueError, match="exceeds safe decode dimensions"),
    ):
        _validate_gltf_image_payload(valid_image_bytes(), 0, ".png")


def test_embedded_image_publication_is_atomic(tmp_path: Path) -> None:
    encoded = base64.b64encode(valid_image_bytes()).decode("ascii")
    path = _write_textured_triangle(
        tmp_path,
        lambda document: document["images"].__setitem__(0, {"uri": f"data:image/png;base64,{encoded}"}),
    )
    with patch("cdmw.modding.scene_gltf_embedded_images.atomic_write_bytes", wraps=atomic_write_bytes) as write:
        result = import_scene_mesh_with_report(path, include_external_audit=False)

    assert write.call_count == 1
    assert result.extracted_embedded_files[0].read_bytes() == valid_image_bytes()


def test_planned_texture_slot_cannot_disappear_during_material_resolution(tmp_path: Path) -> None:
    path = _write_textured_triangle(tmp_path)
    (tmp_path / "base.png").write_bytes(valid_image_bytes())

    with (
        patch("cdmw.modding.scene_gltf_import._gltf_scene_material_slot", return_value=None),
        pytest.raises(ValueError, match="failed material-slot resolution for base"),
    ):
        import_scene_mesh_with_report(path, include_external_audit=False)


def test_uv_plan_and_report_permutation_golden() -> None:
    document = {
        "textures": [{"source": 0}, {"source": 1}],
        "images": [{"uri": "normal.png"}, {"uri": "base.png"}],
    }
    base = (
        "base",
        "base",
        {"index": 1, "texCoord": 2, "extensions": {"KHR_texture_transform": {"offset": [0.25, 0.0]}}},
        "_baseColorTexture",
    )
    normal = ("normal", "normal", {"index": 0, "texCoord": 0}, "_normalTexture")
    forward = build_gltf_material_uv_plan(document, 0, "Mixed", (normal, base))
    reverse = build_gltf_material_uv_plan(document, 0, "Mixed", (base, normal))
    assert forward == reverse
    assert forward.source_texcoord == 0
    assert forward.transform == (0.0, 0.0, 1.0, 1.0, 0.0)
    single = build_gltf_material_uv_plan(document, 1, "Single", (normal,))

    general_forward = {
        "generated_texture_hashes": {"normal": "n", "base": "b"},
        "output_dimensions": {"normal": [2, 2], "base": [1, 1]},
        "generated_slots": [{"slot_key": "normal"}, {"slot_key": "base"}],
        "warnings": ["z-warning", "a-warning"],
        "review_required": True,
        "mode": "xatlas_raster_bake",
    }
    general_reverse = dict(reversed(tuple(general_forward.items())))
    report_forward = build_gltf_uv_bake_report((single, forward), {0: general_forward})
    report_reverse = build_gltf_uv_bake_report((reverse, single), {0: general_reverse})
    assert json.dumps(report_forward, separators=(",", ":")) == json.dumps(report_reverse, separators=(",", ":"))

    row = report_forward["materials"][0]
    assert {
        "material_indices": [material["material_index"] for material in report_forward["materials"]],
        "slot_keys": [slot["slot_key"] for slot in row["slots"]],
        "source_uv_sets": row["source_uv_sets"],
        "source_transforms": row["source_transforms"],
        "has_representative_transform": "source_transform" in row,
        "generated_slots": [slot["slot_key"] for slot in row["generated_slots"]],
        "generated_hash_keys": list(row["generated_texture_hashes"]),
        "warnings": row["warnings"],
    } == {
        "material_indices": [0, 1],
        "slot_keys": ["base", "normal"],
        "source_uv_sets": ["TEXCOORD_0", "TEXCOORD_2"],
        "source_transforms": [[0.0, 0.0, 1.0, 1.0, 0.0], [0.25, 0.0, 1.0, 1.0, 0.0]],
        "has_representative_transform": False,
        "generated_slots": ["base", "normal"],
        "generated_hash_keys": ["base", "normal"],
        "warnings": ["a-warning", "z-warning"],
    }
