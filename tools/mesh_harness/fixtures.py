from __future__ import annotations

from collections.abc import Mapping
from cdmw.domain.mesh import MeshEditSelection
from cdmw.modding.mesh_parser import ParsedMesh
from pathlib import Path
from collections.abc import Sequence
from cdmw.modding.mesh_parser import SubMesh
import math
import struct

from tools.mesh_harness.constants import (
    _SYNTHETIC_MESH_FORMATS,
)

def _read_i32_descriptor_values(descriptor: object) -> tuple[int, ...]:
    if not isinstance(descriptor, Mapping):
        return ()
    try:
        path = Path(str(descriptor.get("path") or ""))
        count = int(descriptor.get("count", 0) or 0)
        components = int(descriptor.get("components", 1) or 1)
    except (TypeError, ValueError):
        return ()
    if count <= 0 or components <= 0 or not path.is_file():
        return ()
    byte_count = count * components * 4
    try:
        raw = path.read_bytes()[:byte_count]
    except OSError:
        return ()
    finally:
        if bool(descriptor.get("delete_after")) and path.name.startswith("cdmw_mesh_preview_delta_"):
            path.unlink(missing_ok=True)
    if len(raw) < byte_count:
        return ()
    return tuple(int(value) for value in struct.unpack(f"<{count * components}i", raw))

def _selection_faces_from_group(group: Mapping[str, object]) -> tuple[int, ...]:
    faces: list[int] = []
    for raw_face in tuple(group.get("source_face_indices") or ()):
        try:
            faces.append(int(raw_face))
        except (TypeError, ValueError):
            continue
    faces.extend(_read_i32_descriptor_values(group.get("source_face_indices_binary")))
    try:
        raw_start = group.get("source_face_start", -1)
        raw_count = group.get("source_face_count", 0)
        start = int(raw_start if raw_start is not None else -1)
        count = int(raw_count if raw_count is not None else 0)
    except (TypeError, ValueError):
        start = -1
        count = 0
    if start >= 0 and count > 0:
        faces.extend(range(start, start + count))
    return tuple(faces)

def _selection_edges_from_group(group: Mapping[str, object]) -> tuple[tuple[int, int], ...]:
    edges: list[tuple[int, int]] = []
    for raw_edge in tuple(group.get("source_edges") or ()):
        if not isinstance(raw_edge, Sequence) or isinstance(raw_edge, (str, bytes)) or len(raw_edge) < 2:
            continue
        try:
            edges.append((int(raw_edge[0]), int(raw_edge[1])))
        except (TypeError, ValueError):
            continue
    values = _read_i32_descriptor_values(group.get("source_edges_binary"))
    for index in range(0, len(values) - 1, 2):
        edges.append((values[index], values[index + 1]))
    return tuple(edges)

def build_synthetic_mesh(mesh_format: str = "pac") -> ParsedMesh:
    mesh_format = str(mesh_format or "pac").strip().lower()
    if mesh_format not in _SYNTHETIC_MESH_FORMATS:
        raise ValueError(f"Unsupported synthetic mesh format: {mesh_format!r}")
    submesh = SubMesh(
        name="harness_quad",
        material="harness_material",
        texture="harness.dds",
        vertices=[
            (-0.75, -0.75, 0.0),
            (0.75, -0.75, 0.0),
            (-0.75, 0.75, 0.0),
            (0.75, 0.75, 0.0),
        ],
        uvs=[(0.0, 1.0), (1.0, 1.0), (0.0, 0.0), (1.0, 0.0)],
        normals=[(0.0, 0.0, 1.0)] * 4,
        faces=[(0, 1, 2), (1, 3, 2)],
        vertex_count=4,
        face_count=2,
    )
    return ParsedMesh(
        path=f"tools/harness_quad.{mesh_format}",
        format=mesh_format,
        bbox_min=(-0.75, -0.75, 0.0),
        bbox_max=(0.75, 0.75, 0.0),
        submeshes=[submesh],
        total_vertices=4,
        total_faces=2,
        has_uvs=True,
    )

def build_native_benchmark_mesh(rows: int = 317, columns: int = 318) -> ParsedMesh:
    row_count = max(2, int(rows))
    column_count = max(2, int(columns))
    vertices: list[tuple[float, float, float]] = []
    uvs: list[tuple[float, float]] = []
    for row in range(row_count):
        v = row / max(1, row_count - 1)
        for column in range(column_count):
            u = column / max(1, column_count - 1)
            vertices.append((float(column), float(row), math.sin(u * math.pi) * math.sin(v * math.pi) * 0.05))
            uvs.append((u, v))
    faces: list[tuple[int, int, int]] = []
    for row in range(row_count - 1):
        row_start = row * column_count
        next_row_start = (row + 1) * column_count
        for column in range(column_count - 1):
            a = row_start + column
            b = a + 1
            c = next_row_start + column
            d = c + 1
            faces.append((a, b, c))
            faces.append((b, d, c))
    vertex_count = len(vertices)
    face_count = len(faces)
    submesh = SubMesh(
        name="native_benchmark_grid",
        material="benchmark_material",
        texture="benchmark.dds",
        vertices=vertices,
        uvs=uvs,
        normals=[(0.0, 0.0, 1.0)] * vertex_count,
        faces=faces,
        vertex_count=vertex_count,
        face_count=face_count,
    )
    return ParsedMesh(
        path="tools/native_benchmark_grid.pac",
        format="pac",
        bbox_min=(0.0, 0.0, -0.05),
        bbox_max=(float(column_count - 1), float(row_count - 1), 0.05),
        submeshes=[submesh],
        total_vertices=vertex_count,
        total_faces=face_count,
        has_uvs=True,
    )

def _build_malformed_face_mesh(mesh_format: str = "pac") -> ParsedMesh:
    mesh = build_synthetic_mesh(mesh_format)
    submesh = mesh.submeshes[0]
    submesh.faces = [(0, "bad", 3), (0, 1, 2), (0, True, 2), (0, 1.9, 2)]  # type: ignore[list-item]
    submesh.face_count = len(submesh.faces)
    mesh.total_faces = len(submesh.faces)
    return mesh

def _build_loose_edge_mesh(mesh_format: str = "pac") -> ParsedMesh:
    mesh = build_synthetic_mesh(mesh_format)
    submesh = mesh.submeshes[0]
    submesh.faces = []
    submesh.face_count = 0
    mesh.total_faces = 0
    return mesh

def _build_two_part_synthetic_mesh(mesh_format: str = "pac") -> ParsedMesh:
    mesh = build_synthetic_mesh(mesh_format)
    source = mesh.submeshes[0]
    source.preview_native_material_overrides = {"roughness": 0.2, "metalness": 0.6}
    source.cdmw_material_authority_profile = "material_authority_detail_mask"
    source.cdmw_material_authority_contract = "true_source_authority_detail_mask"
    mesh.submeshes.append(
        SubMesh(
            name="harness_quad_b",
            material="harness_material_b",
            texture="harness_b.dds",
            vertices=list(source.vertices),
            uvs=list(source.uvs),
            normals=list(source.normals),
            faces=list(source.faces),
            vertex_count=len(source.vertices),
            face_count=len(source.faces),
        )
    )
    mesh.total_vertices = sum(len(submesh.vertices) for submesh in mesh.submeshes)
    mesh.total_faces = sum(len(submesh.faces) for submesh in mesh.submeshes)
    return mesh

def _build_long_edit_mesh() -> ParsedMesh:
    return ParsedMesh(
        path="long-edit.pac",
        format="pac",
        submeshes=[
            SubMesh(
                name="long_edit_patch",
                material="long_edit_material",
                texture="harness.dds",
                vertices=[
                    (-1.0, -1.0, 0.0),
                    (1.0, -1.0, 0.0),
                    (1.0, 1.0, 0.0),
                    (-1.0, 1.0, 0.0),
                    (0.0, 0.0, 0.6),
                ],
                uvs=[(0.0, 1.0), (1.0, 1.0), (1.0, 0.0), (0.0, 0.0), (0.5, 0.5)],
                normals=[(0.0, 0.0, 1.0)] * 5,
                faces=[(0, 1, 4), (1, 2, 4), (2, 3, 4), (3, 0, 4)],
                vertex_count=5,
                face_count=4,
            )
        ],
        total_vertices=5,
        total_faces=4,
        has_uvs=True,
    )

def _long_edit_vertex_selection() -> MeshEditSelection:
    return MeshEditSelection.from_maps(vertices_by_submesh={0: (0, 1, 2, 3, 4)})

def _long_edit_topology_selection(selection_kind: str) -> MeshEditSelection:
    if selection_kind == "edge":
        return MeshEditSelection.from_maps(edges_by_submesh={0: ((0, 1),)})
    if selection_kind == "vertex":
        return MeshEditSelection.from_maps(vertices_by_submesh={0: (4,)})
    return MeshEditSelection.from_maps(faces_by_submesh={0: (0,)})

def _long_edit_split_selection(selection_kind: str) -> MeshEditSelection:
    if selection_kind == "edge":
        return MeshEditSelection.from_maps(edges_by_submesh={0: ((0, 1),)})
    if selection_kind == "vertex":
        return MeshEditSelection.from_maps(vertices_by_submesh={0: (0,)})
    return MeshEditSelection.from_maps(faces_by_submesh={0: (0,)})
