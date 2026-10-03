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
