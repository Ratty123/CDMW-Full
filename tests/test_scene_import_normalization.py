from __future__ import annotations

import json
import math
import struct
from pathlib import Path

import pytest

from cdmw.modding.scene_importer import (
    import_scene_mesh,
    import_scene_mesh_with_report,
    reduce_scene_import_result_quality,
)
from tests.scene_gltf_test_support import write_valid_image


def _write_gltf(
    root: Path,
    *,
    positions: list[tuple[float, float, float]],
    indices: list[int],
    mode: int = 4,
    normals: list[tuple[float, float, float]] | None = None,
    uvs: list[tuple[float, float]] | None = None,
    uv1: list[tuple[float, float]] | None = None,
    tangents: list[tuple[float, float, float, float]] | None = None,
    weights: list[tuple[float, float, float, float]] | None = None,
    scale: list[float] | None = None,
    material: dict[str, object] | None = None,
) -> Path:
    chunks: list[bytes] = []
    views: list[dict[str, int]] = []
    accessors: list[dict[str, int | str]] = []

    def add_accessor(rows: list[tuple[float, ...]], type_name: str) -> int:
        raw = struct.pack(f"<{sum(len(row) for row in rows)}f", *(value for row in rows for value in row))
        offset = sum(len(chunk) for chunk in chunks)
        chunks.append(raw + b"\0" * ((-len(raw)) % 4))
        views.append({"buffer": 0, "byteOffset": offset, "byteLength": len(raw)})
        accessors.append({"bufferView": len(views) - 1, "componentType": 5126, "count": len(rows), "type": type_name})
        return len(accessors) - 1

    def add_joint_accessor(count: int) -> int:
        raw = struct.pack(f"<{count * 4}H", *([0] * count * 4))
        offset = sum(len(chunk) for chunk in chunks)
        chunks.append(raw + b"\0" * ((-len(raw)) % 4))
        views.append({"buffer": 0, "byteOffset": offset, "byteLength": len(raw)})
        accessors.append({"bufferView": len(views) - 1, "componentType": 5123, "count": count, "type": "VEC4"})
        return len(accessors) - 1

    attributes = {"POSITION": add_accessor(positions, "VEC3")}
    if normals is not None:
        attributes["NORMAL"] = add_accessor(normals, "VEC3")
    if uvs is not None:
        attributes["TEXCOORD_0"] = add_accessor(uvs, "VEC2")
    if uv1 is not None:
        attributes["TEXCOORD_1"] = add_accessor(uv1, "VEC2")
    if tangents is not None:
        attributes["TANGENT"] = add_accessor(tangents, "VEC4")
    if weights is not None:
        attributes["JOINTS_0"] = add_joint_accessor(len(positions))
        attributes["WEIGHTS_0"] = add_accessor(weights, "VEC4")
    index_raw = struct.pack(f"<{len(indices)}H", *indices)
    index_offset = sum(len(chunk) for chunk in chunks)
    chunks.append(index_raw + b"\0" * ((-len(index_raw)) % 4))
    views.append({"buffer": 0, "byteOffset": index_offset, "byteLength": len(index_raw)})
    accessors.append({"bufferView": len(views) - 1, "componentType": 5123, "count": len(indices), "type": "SCALAR"})

    node: dict[str, object] = {"mesh": 0}
    if scale is not None:
        node["scale"] = scale
    if weights is not None:
        node["skin"] = 0
    nodes: list[dict[str, object]] = [node]
    scene_nodes = [0]
    if weights is not None:
        nodes.append({"translation": [0.0, 1.0, 0.0]})
        scene_nodes.append(1)
    primitive: dict[str, object] = {"attributes": attributes, "indices": len(accessors) - 1, "mode": mode}
    payload: dict[str, object] = {
        "asset": {"version": "2.0"},
        "buffers": [{"uri": "mesh.bin", "byteLength": sum(len(chunk) for chunk in chunks)}],
        "bufferViews": views,
        "accessors": accessors,
        "meshes": [{"primitives": [primitive]}],
        "nodes": nodes,
        "scenes": [{"nodes": scene_nodes}],
        "scene": 0,
    }
    if weights is not None:
        payload["skins"] = [{"joints": [1]}]
    if material is not None:
        primitive["material"] = 0
        payload["materials"] = [material]
        payload["textures"] = [{"source": 0}]
        payload["images"] = [{"uri": "texture.png"}]
        write_valid_image(root / "texture.png")
    (root / "mesh.bin").write_bytes(b"".join(chunks))
    path = root / "mesh.gltf"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


@pytest.mark.parametrize(
    ("mode", "expected_faces"),
    [
        (5, [(0, 1, 2), (2, 1, 3)]),
        (6, [(0, 1, 2), (0, 2, 3)]),
    ],
)
def test_gltf_triangle_strip_and_fan_are_triangulated(
    tmp_path: Path,
    mode: int,
    expected_faces: list[tuple[int, int, int]],
) -> None:
    path = _write_gltf(
        tmp_path,
        positions=[(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (1.0, 1.0, 0.0)],
        indices=[0, 1, 2, 3],
        mode=mode,
        uvs=[(0.0, 0.0), (1.0, 0.0), (0.0, 1.0), (1.0, 1.0)],
    )

    mesh = import_scene_mesh(path)

    assert mesh.submeshes[0].faces == expected_faces


def test_gltf_mirror_uses_inverse_transpose_and_preserves_tangents(tmp_path: Path) -> None:
    diagonal = math.sqrt(0.5)
    path = _write_gltf(
        tmp_path,
        positions=[(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0)],
        indices=[0, 1, 2],
        normals=[(diagonal, diagonal, 0.0)] * 3,
        tangents=[(diagonal, -diagonal, 0.0, -1.0)] * 3,
        uvs=[(0.0, 0.0), (1.0, 0.0), (0.0, 1.0)],
        scale=[-2.0, 1.0, 1.0],
    )

    submesh = import_scene_mesh(path).submeshes[0]

    assert submesh.faces == [(0, 2, 1)]
    assert all(row == pytest.approx((-0.4472136, 0.8944272, 0.0)) for row in submesh.normals)
    assert all(row == pytest.approx((-0.8944272, -0.4472136, 0.0)) for row in submesh.tangents)
    assert getattr(submesh, "tangent_signs") == [1.0, 1.0, 1.0]


def test_gltf_generates_absent_uvs_with_review_diagnostic(tmp_path: Path) -> None:
    path = _write_gltf(
        tmp_path,
        positions=[(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0)],
        indices=[0, 1, 2],
    )

    result = import_scene_mesh_with_report(path, include_external_audit=False)
    mesh = result.mesh
    submesh = mesh.submeshes[0]

    assert len(submesh.uvs) == len(submesh.vertices)
    assert mesh.has_uvs is True
    assert "Review required" in " ".join(result.diagnostics)
    assert all(row == pytest.approx((0.0, 0.0, 1.0)) for row in submesh.normals)


def test_identity_khr_texture_transform_allows_texcoord_override(tmp_path: Path) -> None:
    uv1 = [(0.2, 0.3), (0.8, 0.3), (0.2, 0.9)]
    path = _write_gltf(
        tmp_path,
        positions=[(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0)],
        indices=[0, 1, 2],
        uvs=[(0.0, 0.0), (1.0, 0.0), (0.0, 1.0)],
        uv1=uv1,
        material={
            "name": "Override",
            "pbrMetallicRoughness": {
                "baseColorTexture": {
                    "index": 0,
                    "texCoord": 0,
                    "extensions": {"KHR_texture_transform": {"texCoord": 1, "scale": [1.0, 1.0]}},
                }
            },
        },
    )

    result = import_scene_mesh_with_report(path, include_external_audit=False)
    submesh = result.mesh.submeshes[0]

    expected_uvs = [(u, 1.0 - v) for u, v in uv1]
    assert all(actual == pytest.approx(expected) for actual, expected in zip(submesh.uvs, expected_uvs, strict=True))
    base_input = next(item for item in submesh.preview_material_texture_inputs if item.slot_kind == "base")
    assert "texcoord:1" not in base_input.blend_flags
    assert "texture_transform" not in base_input.blend_flags
    material_report = result.uv_bake_report["materials"][0]
    assert material_report["source_uv_sets"] == ["TEXCOORD_1"]
    assert material_report["output_uv_set"] == "TEXCOORD_0"
    assert material_report["slots"][0]["texcoord"] == 1

    reduced, _reduction = reduce_scene_import_result_quality(result)
    assert reduced.uv_bake_report == result.uv_bake_report
    assert reduced.uv_bake_report is not result.uv_bake_report


def test_shared_khr_affine_transform_bakes_before_internal_v_flip_with_provenance(tmp_path: Path) -> None:
    rotation = math.pi / 2.0
    transform = {"offset": [0.25, -0.5], "scale": [2.0, 3.0], "rotation": rotation, "texCoord": 1}
    uv1 = [(0.2, 0.3), (0.8, 0.3), (0.2, 0.9)]
    tangents = [(1.0, 0.0, 0.0, -1.0)] * 3
    path = _write_gltf(
        tmp_path,
        positions=[(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0)],
        indices=[0, 1, 2],
        uvs=[(0.0, 0.0), (1.0, 0.0), (0.0, 1.0)],
        uv1=uv1,
        tangents=tangents,
        material={
            "name": "SharedTransform",
            "pbrMetallicRoughness": {
                "baseColorTexture": {"index": 0, "extensions": {"KHR_texture_transform": transform}}
            },
            "normalTexture": {"index": 0, "extensions": {"KHR_texture_transform": transform}},
        },
    )
    document = json.loads(path.read_text(encoding="utf-8"))
    document["samplers"] = [{"wrapS": 33071, "wrapT": 33648, "minFilter": 9987, "magFilter": 9729}]
    document["textures"][0]["sampler"] = 0
    path.write_text(json.dumps(document), encoding="utf-8")

    result = import_scene_mesh_with_report(path, include_external_audit=False)
    submesh = result.mesh.submeshes[0]

    expected_uvs = []
    for u, v in uv1:
        transformed_u = 0.25 + math.cos(rotation) * (u * 2.0) - math.sin(rotation) * (v * 3.0)
        transformed_v = -0.5 + math.sin(rotation) * (u * 2.0) + math.cos(rotation) * (v * 3.0)
        expected_uvs.append((transformed_u, 1.0 - transformed_v))
    assert all(actual == pytest.approx(expected) for actual, expected in zip(submesh.uvs, expected_uvs, strict=True))
    assert submesh.tangents == [(1.0, 0.0, 0.0)] * 3
    assert getattr(submesh, "tangent_signs") == [-1.0, -1.0, -1.0]
    assert all("texcoord:1" not in item.blend_flags for item in submesh.preview_material_texture_inputs)
    assert all("texture_transform" not in item.blend_flags for item in submesh.preview_material_texture_inputs)
    report = result.uv_bake_report
    assert report["schema"] == "cdmw_gltf_uv_bake_report_v1"
    assert report["schema_version"] == 1
    assert report["status"] == "baked"
    material_report = report["materials"][0]
    assert material_report["source_transform"] == pytest.approx([0.25, -0.5, 2.0, 3.0, rotation])
    assert material_report["output_transform"] == [0.0, 0.0, 1.0, 1.0, 0.0]
    assert len(material_report["slots"]) == 2
    assert material_report["slots"][0]["sampler"] == {
        "wrap_s": 33071,
        "wrap_t": 33648,
        "min_filter": 9987,
        "mag_filter": 9729,
    }


def test_gltf_blocks_missing_referenced_texcoord_without_fallback(tmp_path: Path) -> None:
    path = _write_gltf(
        tmp_path,
        positions=[(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0)],
        indices=[0, 1, 2],
        uvs=[(0.0, 0.0), (1.0, 0.0), (0.0, 1.0)],
        material={
            "name": "MissingUv1",
            "pbrMetallicRoughness": {"baseColorTexture": {"index": 0, "texCoord": 1}},
        },
    )

    with pytest.raises(ValueError, match="references TEXCOORD_1, but the primitive does not provide it") as exc_info:
        import_scene_mesh_with_report(path, include_external_audit=False)

    assert "complete, non-sparse VEC2 accessor" in str(exc_info.value)


def test_gltf_blocks_sparse_referenced_texcoord(tmp_path: Path) -> None:
    path = _write_gltf(
        tmp_path,
        positions=[(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0)],
        indices=[0, 1, 2],
        uvs=[(0.0, 0.0), (1.0, 0.0), (0.0, 1.0)],
        uv1=[(0.2, 0.3), (0.8, 0.3), (0.2, 0.9)],
        material={
            "name": "SparseUv1",
            "pbrMetallicRoughness": {"baseColorTexture": {"index": 0, "texCoord": 1}},
        },
    )
    document = json.loads(path.read_text(encoding="utf-8"))
    accessor_index = document["meshes"][0]["primitives"][0]["attributes"]["TEXCOORD_1"]
    document["accessors"][accessor_index]["sparse"] = {"count": 1}
    path.write_text(json.dumps(document), encoding="utf-8")

    with pytest.raises(ValueError, match="references sparse TEXCOORD_1 accessor") as exc_info:
        import_scene_mesh_with_report(path, include_external_audit=False)

    assert "cannot safely expand" in str(exc_info.value)


def test_gltf_rejects_zero_sum_skin_rows_instead_of_reporting_a_bake(tmp_path: Path) -> None:
    path = _write_gltf(
        tmp_path,
        positions=[(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0)],
        indices=[0, 1, 2],
        weights=[(0.0, 0.0, 0.0, 0.0)] * 3,
    )

    with pytest.raises(ValueError, match="WEIGHTS_0 contains an invalid zero-sum skin row at vertex 0"):
        import_scene_mesh(path)


def test_obj_generates_absent_uvs_and_preserves_normals(tmp_path: Path) -> None:
    path = tmp_path / "mesh.obj"
    path.write_text(
        "\n".join(("o Triangle", "v 0 0 0", "v 1 0 0", "v 0 1 0", "f 1 2 3")),
        encoding="utf-8",
    )

    result = import_scene_mesh_with_report(path, include_external_audit=False)
    mesh = result.mesh
    submesh = mesh.submeshes[0]

    assert len(submesh.uvs) == len(submesh.vertices)
    assert mesh.has_uvs is True
    assert "Review required" in " ".join(result.diagnostics)
    assert all(row == pytest.approx((0.0, 0.0, 1.0)) for row in submesh.normals)


def test_dae_applies_asset_hierarchy_and_generates_missing_uvs(tmp_path: Path) -> None:
    path = tmp_path / "mesh.dae"
    path.write_text(
        """<?xml version="1.0" encoding="utf-8"?>
<COLLADA xmlns="http://www.collada.org/2005/11/COLLADASchema" version="1.4.1">
  <asset><unit meter="0.01"/><up_axis>Z_UP</up_axis></asset>
  <library_geometries><geometry id="geo" name="Triangle"><mesh>
    <source id="positions"><float_array id="positions-array" count="9">0 0 0 100 0 0 0 100 0</float_array><technique_common><accessor source="#positions-array" count="3" stride="3"/></technique_common></source>
    <vertices id="vertices"><input semantic="POSITION" source="#positions"/></vertices>
    <triangles count="1"><input semantic="VERTEX" source="#vertices" offset="0"/><p>0 1 2</p></triangles>
  </mesh></geometry></library_geometries>
  <library_visual_scenes><visual_scene id="Scene">
    <node id="parent"><translate>100 0 0</translate><node id="child"><translate>0 100 0</translate><rotate>0 0 1 90</rotate><instance_geometry url="#geo"/></node></node>
  </visual_scene></library_visual_scenes>
  <scene><instance_visual_scene url="#Scene"/></scene>
</COLLADA>
""",
        encoding="utf-8",
    )

    result = import_scene_mesh_with_report(path, include_external_audit=False)
    mesh = result.mesh
    submesh = mesh.submeshes[0]

    expected_vertices = [(1.0, 0.0, -1.0), (1.0, 0.0, -2.0), (0.0, 0.0, -1.0)]
    assert all(actual == pytest.approx(expected) for actual, expected in zip(submesh.vertices, expected_vertices, strict=True))
    assert mesh.bbox_min == pytest.approx((0.0, 0.0, -2.0))
    assert mesh.bbox_max == pytest.approx((1.0, 0.0, -1.0))
    assert len(submesh.uvs) == len(submesh.vertices)
    assert mesh.has_uvs is True
    assert "Review required" in " ".join(result.diagnostics)
    assert all(row == pytest.approx((0.0, 1.0, 0.0)) for row in submesh.normals)
