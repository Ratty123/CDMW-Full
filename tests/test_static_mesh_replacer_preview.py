import copy
import struct
import unittest
from array import array
from pathlib import Path
from unittest.mock import patch

import pytest

from cdmw.modding.mesh_deformer import apply_brush_deformation, delete_faces_touching_vertices
from cdmw.modding.mesh_parser import ParsedMesh, SubMesh, _parse_par_sections, parse_pac
from cdmw.modding.static_mesh_replacer import (
    StaticIndependentPart,
    StaticMaterialAtlasRect,
    StaticMeshReplacementOptions,
    StaticOutputDrawSection,
    StaticReplacementTransform,
    StaticSourcePartAdjustment,
    StaticSubmeshMapping,
    StaticTextureUvTransform,
    _build_mapped_replacement_mesh,
    _transformed_replacement_sources,
    analyze_static_replacement,
    build_static_mesh_replacement,
    build_static_replacement_preview_mesh,
    plan_static_output_draw_sections,
    source_affine_for_transformed_preview,
    source_delta_for_transformed_delta,
    source_distance_for_transformed_distance,
    source_normal_transform_for_transformed_preview,
    source_point_for_transformed_point,
    suggest_static_submesh_mappings,
)


def _mesh(path: str, submeshes: list[SubMesh]) -> ParsedMesh:
    return ParsedMesh(
        path=path,
        format="pac",
        submeshes=submeshes,
        total_vertices=sum(len(submesh.vertices) for submesh in submeshes),
        total_faces=sum(len(submesh.faces) for submesh in submeshes),
        has_uvs=any(bool(submesh.uvs) for submesh in submeshes),
    )


def _large_part(name: str, vertex_count: int) -> SubMesh:
    return SubMesh(
        name=name,
        material=name,
        vertices=[(float(index), float(index % 13), float(index % 7)) for index in range(vertex_count)],
        faces=[(0, 1, 2)] if vertex_count >= 3 else [],
    )


def _write_f64_values(path: object, values: list[float]) -> None:
    data = array("d", values)
    with Path(str(path)).open("wb") as handle:
        data.tofile(handle)


def _read_f64_values(path: object) -> list[float]:
    data = array("d")
    data.frombytes(Path(str(path)).read_bytes())
    return [float(value) for value in data]


def _write_i32_values(path: object, values: list[int]) -> None:
    data = array("i", values)
    with Path(str(path)).open("wb") as handle:
        data.tofile(handle)


class _CountingSequence:
    def __init__(self, values: list[object]) -> None:
        self._values = list(values)
        self.iterations = 0

    def __bool__(self) -> bool:
        return bool(self._values)

    def __iter__(self):
        self.iterations += 1
        return iter(self._values)

    def __len__(self) -> int:
        return len(self._values)

    def __getitem__(self, index: int) -> object:
        return self._values[index]


def test_native_merge_submeshes_bridge_uses_mesh_core_binary_payloads() -> None:
    from cdmw.modding.mesh_native_core import merge_native_mesh_submeshes

    source_a = SubMesh(
        vertices=[(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0)],
        faces=[(0, 1, 2)],
        uvs=[(0.0, 0.0), (1.0, 0.0), (0.0, 1.0)],
    )
    source_b = SubMesh(
        vertices=[(2.0, 0.0, 0.0), (3.0, 0.0, 0.0), (2.0, 1.0, 0.0)],
        faces=[(0, 1, 2)],
    )

    def native_job(_binary: Path, command: str, payload: object, *, timeout_seconds: float) -> dict[str, object]:
        assert command == "merge-submeshes-json"
        assert isinstance(payload, dict)
        submesh_payloads = payload["submeshes"]
        assert len(submesh_payloads) == 2
        for submesh_payload in submesh_payloads:
            assert "vertices_binary" in submesh_payload
            assert "faces_binary" in submesh_payload
            assert "vertices" not in submesh_payload
            assert "faces" not in submesh_payload
        vertices_path = payload["vertices_output_path"]
        faces_path = payload["faces_output_path"]
        normals_path = payload["normals_output_path"]
        uvs_path = payload["uvs_output_path"]
        _write_f64_values(vertices_path, [0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 2.0, 0.0, 0.0, 3.0, 0.0, 0.0, 2.0, 1.0, 0.0])
        _write_i32_values(faces_path, [0, 1, 2, 3, 4, 5])
        _write_f64_values(normals_path, [0.0, 0.0, 1.0] * 6)
        _write_f64_values(uvs_path, [0.0, 0.0] * 6)
        return {
            "status": "ok",
            "backend": "cdmw_mesh_core_0.1",
            "operation": "merge_submeshes",
            "vertex_count": 6,
            "face_count": 2,
            "vertices_binary": {"path": str(vertices_path), "count": 6, "components": 3, "type": "f64"},
            "faces_binary": {"path": str(faces_path), "count": 2, "components": 3, "type": "i32"},
            "normals_binary": {"path": str(normals_path), "count": 6, "components": 3, "type": "f64"},
            "uvs_binary": {"path": str(uvs_path), "count": 6, "components": 2, "type": "f64"},
        }

    with (
        patch("cdmw.modding.mesh_native_core.find_native_mesh_core_binary", return_value=Path("native.exe")),
        patch("cdmw.modding.mesh_native_core._run_native_mesh_core_job", side_effect=native_job),
    ):
        merged = merge_native_mesh_submeshes([source_a, source_b])

    assert merged is not None
    assert merged.vertices[3] == (2.0, 0.0, 0.0)
    assert merged.faces == [(0, 1, 2), (3, 4, 5)]
    assert len(merged.normals) == 6
    assert len(merged.uvs) == 6


def test_native_merge_submeshes_bridge_streams_vertex_sidecars_without_tuple_copy() -> None:
    from cdmw.modding.mesh_native_core import merge_native_mesh_submeshes

    vertices = _CountingSequence([(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0)])
    faces = _CountingSequence([(0, 1, 2)])
    source = SubMesh(vertices=vertices, faces=faces)  # type: ignore[arg-type]

    def native_job(_binary: Path, command: str, payload: object, *, timeout_seconds: float) -> dict[str, object]:
        assert command == "merge-submeshes-json"
        assert isinstance(payload, dict)
        item = payload["submeshes"][0]
        assert item["vertices_binary"]["count"] == 3
        assert item["faces_binary"]["count"] == 1
        vertices_path = payload["vertices_output_path"]
        faces_path = payload["faces_output_path"]
        _write_f64_values(vertices_path, [0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0, 0.0])
        _write_i32_values(faces_path, [0, 1, 2])
        return {
            "status": "ok",
            "backend": "cdmw_mesh_core_0.1",
            "operation": "merge_submeshes",
            "vertex_count": 3,
            "face_count": 1,
            "vertices_binary": {"path": str(vertices_path), "count": 3, "components": 3, "type": "f64"},
            "faces_binary": {"path": str(faces_path), "count": 1, "components": 3, "type": "i32"},
        }

    with (
        patch("cdmw.modding.mesh_native_core.find_native_mesh_core_binary", return_value=Path("native.exe")),
        patch("cdmw.modding.mesh_native_core._run_native_mesh_core_job", side_effect=native_job),
    ):
        merged = merge_native_mesh_submeshes([source])

    assert merged is not None
    assert vertices.iterations == 1
    assert faces.iterations == 1


def test_native_static_donor_bridge_streams_vertex_sidecars_without_tuple_copy() -> None:
    from cdmw.modding.mesh_native_core import build_native_static_donor_indices

    original_vertices = _CountingSequence([(0.0, 0.0, 0.0), (1.0, 0.0, 0.0)])
    new_vertices = _CountingSequence([(0.0, 0.0, 0.0), (1.1, 0.0, 0.0)])
    original = SubMesh(vertices=original_vertices)  # type: ignore[arg-type]
    new = SubMesh(vertices=new_vertices)  # type: ignore[arg-type]

    def native_job(_binary: Path, command: str, payload: object, *, timeout_seconds: float) -> dict[str, object]:
        assert command == "static-donor-indices-json"
        assert isinstance(payload, dict)
        item = payload["submeshes"][0]
        assert item["original_vertices_binary"]["count"] == 2
        assert item["new_vertices_binary"]["count"] == 2
        donor_indices_path = Path(str(item["donor_indices_output_path"]))
        _write_i32_values(donor_indices_path, [0, 1])
        return {
            "status": "ok",
            "backend": "cdmw_mesh_core_0.1",
            "operation": "static_donor_indices",
            "submeshes": [
                {
                    "index": 0,
                    "new_vertex_count": 2,
                    "donor_indices_binary": {"path": str(donor_indices_path), "count": 2, "components": 1, "type": "i32"},
                }
            ],
        }

    with (
        patch("cdmw.modding.mesh_native_core.find_native_mesh_core_binary", return_value=Path("native.exe")),
        patch("cdmw.modding.mesh_native_core._run_native_mesh_core_job", side_effect=native_job),
    ):
        donor_indices = build_native_static_donor_indices(original, new)

    assert donor_indices == [0, 1]
    assert original_vertices.iterations == 1
    assert new_vertices.iterations == 1


def test_native_preview_decimation_bridge_uses_mesh_core_binary_payloads() -> None:
    from cdmw.modding.mesh_native_core import decimate_native_mesh_preview_submeshes

    submesh = SubMesh(
        name="dense",
        material="mat",
        texture="tex",
        vertices=[(float(index), 0.0, 0.0) for index in range(12)],
        uvs=[(float(index) / 10.0, float(index) / 20.0) for index in range(12)],
        normals=[(0.0, 0.0, 1.0)] * 12,
        faces=[(0, 1, 2), (3, 4, 5), (6, 7, 8), (9, 10, 11)],
        bone_indices=[(index,) for index in range(12)],
        bone_weights=[(1.0,) for _index in range(12)],
        source_vertex_map=[100 + index for index in range(12)],
        source_vertex_offsets=[index * 12 for index in range(12)],
    )
    submeshes = [submesh]

    def native_job(_binary: Path, command: str, payload: object, *, timeout_seconds: float) -> dict[str, object]:
        assert command == "preview-decimate-json"
        assert isinstance(payload, dict)
        assert payload["operation"] == "preview_decimate"
        item = payload["submeshes"][0]
        assert item["max_faces"] == 2
        assert "vertices_binary" in item
        assert "faces_binary" in item
        assert "uvs_binary" in item
        assert "normals_binary" in item
        assert "bone_counts_binary" in item
        assert item["source_vertex_map_start"] == 100
        assert item["source_vertex_map_count"] == 12
        assert "vertices" not in item
        assert "faces" not in item
        vertices_path = item["vertices_output_path"]
        faces_path = item["faces_output_path"]
        uvs_path = item["uvs_output_path"]
        normals_path = item["normals_output_path"]
        bone_counts_path = item["bone_counts_output_path"]
        bone_indices_path = item["bone_indices_output_path"]
        bone_weights_path = item["bone_weights_output_path"]
        source_map_path = item["source_vertex_map_output_path"]
        _write_f64_values(vertices_path, [0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 2.0, 0.0, 0.0, 6.0, 0.0, 0.0, 7.0, 0.0, 0.0, 8.0, 0.0, 0.0])
        _write_i32_values(faces_path, [0, 1, 2, 3, 4, 5])
        _write_f64_values(uvs_path, [0.0, 0.0, 0.1, 0.05, 0.2, 0.1, 0.6, 0.3, 0.7, 0.35, 0.8, 0.4])
        _write_f64_values(normals_path, [0.0, 0.0, 1.0] * 6)
        _write_i32_values(bone_counts_path, [1, 1, 1, 1, 1, 1])
        _write_i32_values(bone_indices_path, [0, 1, 2, 6, 7, 8])
        _write_f64_values(bone_weights_path, [1.0] * 6)
        _write_i32_values(source_map_path, [100, 101, 102, 106, 107, 108])
        return {
            "status": "ok",
            "backend": "cdmw_mesh_core_0.1",
            "operation": "preview_decimate",
            "submeshes": [
                {
                    "index": 0,
                    "vertex_count": 6,
                    "face_count": 2,
                    "vertices_binary": {"path": str(vertices_path), "count": 6, "components": 3, "type": "f64"},
                    "faces_binary": {"path": str(faces_path), "count": 2, "components": 3, "type": "i32"},
                    "uvs_binary": {"path": str(uvs_path), "count": 6, "components": 2, "type": "f64"},
                    "normals_binary": {"path": str(normals_path), "count": 6, "components": 3, "type": "f64"},
                    "bone_counts_binary": {"path": str(bone_counts_path), "count": 6, "components": 1, "type": "i32"},
                    "bone_indices_binary": {"path": str(bone_indices_path), "count": 6, "components": 1, "type": "i32"},
                    "bone_weights_binary": {"path": str(bone_weights_path), "count": 6, "components": 1, "type": "f64"},
                    "source_vertex_map_binary": {"path": str(source_map_path), "count": 6, "components": 1, "type": "i32"},
                }
            ],
        }

    with (
        patch("cdmw.modding.mesh_native_core.find_native_mesh_core_binary", return_value=Path("native.exe")),
        patch("cdmw.modding.mesh_native_core._run_native_mesh_core_job", side_effect=native_job),
    ):
        changed = decimate_native_mesh_preview_submeshes(submeshes, 2)

    assert changed == {0}
    preview = submeshes[0]
    assert preview is not submesh
    assert preview.name == "dense"
    assert preview.material == "mat"
    assert preview.texture == "tex"
    assert preview.vertices == [(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (2.0, 0.0, 0.0), (6.0, 0.0, 0.0), (7.0, 0.0, 0.0), (8.0, 0.0, 0.0)]
    assert preview.faces == [(0, 1, 2), (3, 4, 5)]
    assert preview.uvs == [(0.0, 0.0), (0.1, 0.05), (0.2, 0.1), (0.6, 0.3), (0.7, 0.35), (0.8, 0.4)]
    assert preview.normals == [(0.0, 0.0, 1.0)] * 6
    assert preview.bone_indices == [(0,), (1,), (2,), (6,), (7,), (8,)]
    assert preview.bone_weights == [(1.0,), (1.0,), (1.0,), (1.0,), (1.0,), (1.0,)]
    assert preview.source_vertex_map == [100, 101, 102, 106, 107, 108]
    assert preview.source_vertex_offsets == []
    assert preview.source_index_offset == -1
    assert preview.source_index_count == 6


def test_native_preview_decimation_bridge_streams_vertex_sidecars_without_tuple_copy() -> None:
    from cdmw.modding.mesh_native_core import decimate_native_mesh_preview_submeshes

    vertices = _CountingSequence([(float(index), 0.0, 0.0) for index in range(6)])
    faces = _CountingSequence([(0, 1, 2), (3, 4, 5)])
    submesh = SubMesh(vertices=vertices, faces=faces)  # type: ignore[arg-type]

    def native_job(_binary: Path, command: str, payload: object, *, timeout_seconds: float) -> dict[str, object]:
        assert command == "preview-decimate-json"
        assert isinstance(payload, dict)
        item = payload["submeshes"][0]
        assert item["vertices_binary"]["count"] == 6
        assert item["faces_binary"]["count"] == 2
        assert vertices.iterations == 1
        assert faces.iterations == 1
        vertices_path = item["vertices_output_path"]
        faces_path = item["faces_output_path"]
        _write_f64_values(vertices_path, [0.0, 0.0, 0.0, 3.0, 0.0, 0.0, 5.0, 0.0, 0.0])
        _write_i32_values(faces_path, [0, 1, 2])
        return {
            "status": "ok",
            "backend": "cdmw_mesh_core_0.1",
            "operation": "preview_decimate",
            "submeshes": [
                {
                    "index": 0,
                    "vertex_count": 3,
                    "face_count": 1,
                    "vertices_binary": {"path": str(vertices_path), "count": 3, "components": 3, "type": "f64"},
                    "faces_binary": {"path": str(faces_path), "count": 1, "components": 3, "type": "i32"},
                }
            ],
        }

    with (
        patch("cdmw.modding.mesh_native_core.find_native_mesh_core_binary", return_value=Path("native.exe")),
        patch("cdmw.modding.mesh_native_core._run_native_mesh_core_job", side_effect=native_job),
    ):
        changed = decimate_native_mesh_preview_submeshes([submesh], 1)

    assert changed == {0}
    assert vertices.iterations == 2
    assert faces.iterations == 2


def test_native_mesh_metadata_bridge_uses_mesh_core_binary_payloads() -> None:
    from cdmw.modding.mesh_native_core import summarize_native_mesh_submesh_metadata

    submesh = SubMesh(
        vertices=[(-1.0, 2.0, 0.5), (4.0, -3.0, 2.0), (0.0, 1.0, -2.0)],
        faces=[(0, 1, 2)],
        uvs=[(0.0, 0.0), (1.0, 0.0), (0.0, 1.0)],
    )

    def native_job(_binary: Path, command: str, payload: object, *, timeout_seconds: float) -> dict[str, object]:
        assert command == "mesh-metadata-json"
        assert isinstance(payload, dict)
        assert payload["operation"] == "mesh_metadata"
        item = payload["submeshes"][0]
        assert item["vertex_count"] == 3
        assert item["face_count"] == 1
        assert item["uv_count"] == 3
        assert item["has_uvs"] is True
        assert "vertices_binary" in item
        assert "vertices" not in item
        assert "faces" not in item
        assert "faces_binary" not in item
        return {
            "status": "ok",
            "backend": "cdmw_mesh_core_0.1",
            "operation": "mesh_metadata",
            "submesh_count": 1,
            "total_vertices": 3,
            "total_faces": 1,
            "has_uvs": True,
            "has_bounds": True,
            "bbox_min": [-1.0, -3.0, -2.0],
            "bbox_max": [4.0, 2.0, 2.0],
            "submeshes": [
                {
                    "index": 0,
                    "vertex_count": 3,
                    "face_count": 1,
                    "has_uvs": True,
                    "has_bounds": True,
                    "bbox_min": [-1.0, -3.0, -2.0],
                    "bbox_max": [4.0, 2.0, 2.0],
                }
            ],
        }

    with (
        patch("cdmw.modding.mesh_native_core.find_native_mesh_core_binary", return_value=Path("native.exe")),
        patch("cdmw.modding.mesh_native_core._run_native_mesh_core_job", side_effect=native_job),
    ):
        report = summarize_native_mesh_submesh_metadata([submesh])

    assert report is not None
    assert report["total_vertices"] == 3
    assert report["bbox_min"] == [-1.0, -3.0, -2.0]


def test_native_mesh_metadata_bridge_streams_vertex_sidecars_without_tuple_copy() -> None:
    from cdmw.modding.mesh_native_core import summarize_native_mesh_submesh_metadata

    vertices = _CountingSequence([(-1.0, 2.0, 0.5), (4.0, -3.0, 2.0), (0.0, 1.0, -2.0)])
    submesh = SubMesh(vertices=vertices, faces=[(0, 1, 2)])  # type: ignore[arg-type]

    def native_job(_binary: Path, command: str, payload: object, *, timeout_seconds: float) -> dict[str, object]:
        assert command == "mesh-metadata-json"
        assert isinstance(payload, dict)
        assert payload["submeshes"][0]["vertices_binary"]["count"] == 3
        return {
            "status": "ok",
            "backend": "cdmw_mesh_core_0.1",
            "operation": "mesh_metadata",
            "submesh_count": 1,
            "total_vertices": 3,
            "total_faces": 1,
            "has_uvs": False,
            "has_bounds": True,
            "bbox_min": [-1.0, -3.0, -2.0],
            "bbox_max": [4.0, 2.0, 2.0],
            "submeshes": [],
        }

    with (
        patch("cdmw.modding.mesh_native_core.find_native_mesh_core_binary", return_value=Path("native.exe")),
        patch("cdmw.modding.mesh_native_core._run_native_mesh_core_job", side_effect=native_job),
    ):
        report = summarize_native_mesh_submesh_metadata([submesh])

    assert report is not None
    assert vertices.iterations == 1


def test_runtime_mesh_metadata_helper_uses_native_before_python_bbox() -> None:
    from cdmw.modding.static_mesh_runtime_builder import _mesh_metadata_for_submeshes

    submesh = SubMesh(
        vertices=[(-1.0, 2.0, 0.5), (4.0, -3.0, 2.0), (0.0, 1.0, -2.0)],
        faces=[(0, 1, 2)],
    )
    native_report = {
        "status": "ok",
        "backend": "cdmw_mesh_core_0.1",
        "operation": "mesh_metadata",
        "total_vertices": 3,
        "total_faces": 1,
        "has_uvs": False,
        "has_bounds": True,
        "bbox_min": [-1.0, -3.0, -2.0],
        "bbox_max": [4.0, 2.0, 2.0],
    }

    with (
        patch("cdmw.modding.mesh_native_core.summarize_native_mesh_submesh_metadata", return_value=native_report) as native_summary,
        patch("cdmw.modding.static_mesh_runtime_builder._bbox", side_effect=AssertionError("python bbox scan")),
    ):
        metadata = _mesh_metadata_for_submeshes([submesh])

    native_summary.assert_called_once()
    assert metadata == ((-1.0, -3.0, -2.0), (4.0, 2.0, 2.0), 3, 1, False)


def test_mapped_replacement_uses_native_merge_for_multi_source_runtime_slot() -> None:
    original = _mesh(
        "original.pac",
        [SubMesh(name="target", material="target", vertices=[(0.0, 0.0, 0.0)], faces=[])],
    )
    replacement = _mesh(
        "replacement.pac",
        [
            SubMesh(name="a", material="a", vertices=[(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0)], faces=[(0, 1, 2)]),
            SubMesh(name="b", material="b", vertices=[(2.0, 0.0, 0.0), (3.0, 0.0, 0.0), (2.0, 1.0, 0.0)], faces=[(0, 1, 2)]),
        ],
    )
    mapping = StaticSubmeshMapping(0, "target", [0, 1], 0)
    native_merged = SubMesh(
        vertices=[(9.0, 0.0, 0.0), (10.0, 0.0, 0.0), (9.0, 1.0, 0.0)],
        faces=[(0, 1, 2)],
        normals=[(0.0, 0.0, 1.0)] * 3,
        uvs=[(0.0, 0.0)] * 3,
    )

    with (
        patch("cdmw.modding.mesh_native_core.merge_native_mesh_submeshes", return_value=native_merged) as native_merge,
        patch("cdmw.modding.static_mesh_runtime_builder._compute_smooth_normals", side_effect=AssertionError("python normal merge")),
    ):
        mapped = _build_mapped_replacement_mesh(original, replacement, [mapping], StaticMeshReplacementOptions())

    native_merge.assert_called_once()
    assert mapped.submeshes[0].vertices == native_merged.vertices
    assert mapped.submeshes[0].faces == native_merged.faces
    assert mapped.submeshes[0].material == "target"


def test_native_affine_transform_bridge_uses_mesh_core_binary_payloads() -> None:
    from cdmw.modding.mesh_native_core import apply_native_mesh_affine_transform_submeshes

    submesh = SubMesh(
        vertices=[(1.0, 2.0, 3.0), (2.0, 3.0, 4.0)],
        normals=[(0.0, 0.0, 1.0), (0.0, 1.0, 0.0)],
    )
    position_matrix = (1.0, 0.0, 0.0, 5.0, 0.0, 1.0, 0.0, -2.0, 0.0, 0.0, 1.0, 0.5)
    normal_matrix = (1.0, 0.0, 0.0, 0.0, 0.0, -1.0, 0.0, 1.0, 0.0)

    def native_job(_binary: Path, command: str, payload: object, *, timeout_seconds: float) -> dict[str, object]:
        assert command == "affine-transform-json"
        assert isinstance(payload, dict)
        item = payload["submeshes"][0]
        assert item["position_matrix"] == list(position_matrix)
        assert item["normal_matrix"] == list(normal_matrix)
        assert "vertices_binary" in item
        assert "normals_binary" in item
        assert "vertices" not in item
        vertices_path = item["vertices_output_path"]
        normals_path = item["normals_output_path"]
        _write_f64_values(vertices_path, [6.0, 0.0, 3.5, 7.0, 1.0, 4.5])
        _write_f64_values(normals_path, [0.0, -1.0, 0.0, 0.0, 0.0, 1.0])
        return {
            "status": "ok",
            "backend": "cdmw_mesh_core_0.1",
            "operation": "affine_transform",
            "submeshes": [
                {
                    "index": 0,
                    "vertex_count": 2,
                    "vertices_binary": {"path": str(vertices_path), "count": 2, "components": 3, "type": "f64"},
                    "normals_binary": {"path": str(normals_path), "count": 2, "components": 3, "type": "f64"},
                }
            ],
        }

    with (
        patch("cdmw.modding.mesh_native_core.find_native_mesh_core_binary", return_value=Path("native.exe")),
        patch("cdmw.modding.mesh_native_core._run_native_mesh_core_job", side_effect=native_job),
    ):
        changed = apply_native_mesh_affine_transform_submeshes(
            [submesh],
            position_matrices_by_index={0: position_matrix},
            normal_matrices_by_index={0: normal_matrix},
        )

    assert changed == {0}
    assert submesh.vertices == [(6.0, 0.0, 3.5), (7.0, 1.0, 4.5)]
    assert submesh.normals == [(0.0, -1.0, 0.0), (0.0, 0.0, 1.0)]


def test_native_affine_transform_bridge_can_reverse_face_winding() -> None:
    from cdmw.modding.mesh_native_core import apply_native_mesh_affine_transform_submeshes

    submesh = SubMesh(
        vertices=[(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0)],
        faces=[(0, 1, 2)],
    )
    position_matrix = (1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0)

    def native_job(_binary: Path, command: str, payload: object, *, timeout_seconds: float) -> dict[str, object]:
        assert command == "affine-transform-json"
        assert isinstance(payload, dict)
        item = payload["submeshes"][0]
        assert item["reverse_face_winding"] is True
        assert "faces_binary" in item
        assert "faces" not in item
        vertices_path = item["vertices_output_path"]
        faces_path = item["faces_output_path"]
        _write_f64_values(vertices_path, [0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0, 0.0])
        _write_i32_values(faces_path, [0, 2, 1])
        return {
            "status": "ok",
            "backend": "cdmw_mesh_core_0.1",
            "operation": "affine_transform",
            "submeshes": [
                {
                    "index": 0,
                    "vertex_count": 3,
                    "face_count": 1,
                    "vertices_binary": {"path": str(vertices_path), "count": 3, "components": 3, "type": "f64"},
                    "faces_binary": {"path": str(faces_path), "count": 1, "components": 3, "type": "i32"},
                }
            ],
        }

    with (
        patch("cdmw.modding.mesh_native_core.find_native_mesh_core_binary", return_value=Path("native.exe")),
        patch("cdmw.modding.mesh_native_core._run_native_mesh_core_job", side_effect=native_job),
    ):
        changed = apply_native_mesh_affine_transform_submeshes(
            [submesh],
            position_matrices_by_index={0: position_matrix},
            reverse_face_winding_by_index={0: True},
        )

    assert changed == {0}
    assert submesh.faces == [(0, 2, 1)]
    assert submesh.face_count == 1


def test_native_affine_transform_bridge_can_send_source_part_adjustment() -> None:
    from cdmw.modding.mesh_native_core import apply_native_mesh_affine_transform_submeshes

    submesh = SubMesh(
        vertices=[(0.0, 0.0, 0.0), (2.0, 0.0, 0.0)],
        normals=[(1.0, 0.0, 0.0), (0.0, 1.0, 0.0)],
    )

    def native_job(_binary: Path, command: str, payload: object, *, timeout_seconds: float) -> dict[str, object]:
        assert command == "affine-transform-json"
        assert isinstance(payload, dict)
        item = payload["submeshes"][0]
        assert "position_matrix" not in item
        assert item["source_part_adjustment"] == {
            "scale_xyz": [2.0, 1.0, 1.0],
            "uniform_scale": 1.0,
            "offset_xyz": [1.0, 0.0, 0.0],
            "rotate_xyz_degrees": [0.0, 0.0, 0.0],
        }
        assert "normals_binary" in item
        vertices_path = item["vertices_output_path"]
        normals_path = item["normals_output_path"]
        _write_f64_values(vertices_path, [0.0, 0.0, 0.0, 4.0, 0.0, 0.0])
        _write_f64_values(normals_path, [1.0, 0.0, 0.0, 0.0, 1.0, 0.0])
        return {
            "status": "ok",
            "backend": "cdmw_mesh_core_0.1",
            "operation": "affine_transform",
            "submeshes": [
                {
                    "index": 0,
                    "vertex_count": 2,
                    "vertices_binary": {"path": str(vertices_path), "count": 2, "components": 3, "type": "f64"},
                    "normals_binary": {"path": str(normals_path), "count": 2, "components": 3, "type": "f64"},
                }
            ],
        }

    with (
        patch("cdmw.modding.mesh_native_core.find_native_mesh_core_binary", return_value=Path("native.exe")),
        patch("cdmw.modding.mesh_native_core._run_native_mesh_core_job", side_effect=native_job),
    ):
        changed = apply_native_mesh_affine_transform_submeshes(
            [submesh],
            source_part_adjustments_by_index={
                0: {
                    "scale_xyz": (2.0, 1.0, 1.0),
                    "uniform_scale": 1.0,
                    "offset_xyz": (1.0, 0.0, 0.0),
                    "rotate_xyz_degrees": (0.0, 0.0, 0.0),
                }
            },
        )

    assert changed == {0}
    assert submesh.vertices == [(0.0, 0.0, 0.0), (4.0, 0.0, 0.0)]
    assert submesh.normals == [(1.0, 0.0, 0.0), (0.0, 1.0, 0.0)]


def test_native_affine_clone_can_mirror_source_part_without_python_preclone() -> None:
    from cdmw.modding.mesh_native_core import clone_native_mesh_affine_transformed_submesh

    submesh = SubMesh(
        name="source",
        material="mat",
        texture="tex",
        vertices=[(0.0, 0.0, 0.0), (2.0, 0.0, 0.0), (1.0, 1.0, 0.0)],
        normals=[(1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0)],
        uvs=[(0.0, 0.0), (1.0, 0.0), (0.5, 1.0)],
        faces=[(0, 1, 2)],
    )

    def native_job(_binary: Path, command: str, payload: object, *, timeout_seconds: float) -> dict[str, object]:
        assert command == "affine-transform-json"
        assert isinstance(payload, dict)
        item = payload["submeshes"][0]
        assert item["mirror_x_around_bounds_center"] is True
        assert "faces_binary" in item
        vertices_path = item["vertices_output_path"]
        normals_path = item["normals_output_path"]
        faces_path = item["faces_output_path"]
        _write_f64_values(vertices_path, [3.0, 0.0, 0.0, 1.0, 0.0, 0.0, 2.0, 1.0, 0.0])
        _write_f64_values(normals_path, [-1.0, 0.0, 0.0, -0.0, 1.0, 0.0, -0.0, 0.0, 1.0])
        _write_i32_values(faces_path, [0, 2, 1])
        return {
            "status": "ok",
            "backend": "cdmw_mesh_core_0.1",
            "operation": "affine_transform",
            "submeshes": [
                {
                    "index": 0,
                    "vertex_count": 3,
                    "face_count": 1,
                    "vertices_binary": {"path": str(vertices_path), "count": 3, "components": 3, "type": "f64"},
                    "normals_binary": {"path": str(normals_path), "count": 3, "components": 3, "type": "f64"},
                    "faces_binary": {"path": str(faces_path), "count": 1, "components": 3, "type": "i32"},
                }
            ],
        }

    with (
        patch("cdmw.modding.mesh_native_core.find_native_mesh_core_binary", return_value=Path("native.exe")),
        patch("cdmw.modding.mesh_native_core._run_native_mesh_core_job", side_effect=native_job),
    ):
        cloned = clone_native_mesh_affine_transformed_submesh(
            submesh,
            source_part_adjustment={
                "scale_xyz": (1.0, 1.0, 1.0),
                "uniform_scale": 1.0,
                "offset_xyz": (1.0, 0.0, 0.0),
                "rotate_xyz_degrees": (0.0, 0.0, 0.0),
            },
            mirror_x_around_bounds_center=True,
        )

    assert cloned is not None
    assert cloned is not submesh
    assert cloned.name == "source"
    assert cloned.material == "mat"
    assert cloned.texture == "tex"
    assert cloned.vertices == [(3.0, 0.0, 0.0), (1.0, 0.0, 0.0), (2.0, 1.0, 0.0)]
    assert cloned.normals == [(-1.0, 0.0, 0.0), (-0.0, 1.0, 0.0), (-0.0, 0.0, 1.0)]
    assert cloned.faces == [(0, 2, 1)]
    assert cloned.uvs == submesh.uvs


def test_mirror_submesh_x_uses_native_clone_before_python_deepcopy() -> None:
    from cdmw.ui.archive_browser.static_replacement_geometry_math import mirror_submesh_x

    submesh = SubMesh(
        name="source",
        material="mat",
        texture="tex",
        vertices=[(0.0, 0.0, 0.0), (2.0, 0.0, 0.0), (1.0, 1.0, 0.0)],
        normals=[(1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0)],
        faces=[(0, 1, 2)],
    )

    def native_job(_binary: Path, command: str, payload: object, *, timeout_seconds: float) -> dict[str, object]:
        assert command == "affine-transform-json"
        assert isinstance(payload, dict)
        item = payload["submeshes"][0]
        assert item["position_matrix"] == [-1.0, 0.0, 0.0, 4.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0]
        assert item["normal_matrix"] == [-1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0]
        assert item["reverse_face_winding"] is True
        assert "source_part_adjustment" not in item
        vertices_path = item["vertices_output_path"]
        normals_path = item["normals_output_path"]
        faces_path = item["faces_output_path"]
        _write_f64_values(vertices_path, [4.0, 0.0, 0.0, 2.0, 0.0, 0.0, 3.0, 1.0, 0.0])
        _write_f64_values(normals_path, [-1.0, 0.0, 0.0, -0.0, 1.0, 0.0, -0.0, 0.0, 1.0])
        _write_i32_values(faces_path, [0, 2, 1])
        return {
            "status": "ok",
            "backend": "cdmw_mesh_core_0.1",
            "operation": "affine_transform",
            "submeshes": [
                {
                    "index": 0,
                    "vertex_count": 3,
                    "face_count": 1,
                    "vertices_binary": {"path": str(vertices_path), "count": 3, "components": 3, "type": "f64"},
                    "normals_binary": {"path": str(normals_path), "count": 3, "components": 3, "type": "f64"},
                    "faces_binary": {"path": str(faces_path), "count": 1, "components": 3, "type": "i32"},
                }
            ],
        }

    with (
        patch("cdmw.modding.mesh_native_core.find_native_mesh_core_binary", return_value=Path("native.exe")),
        patch("cdmw.modding.mesh_native_core._run_native_mesh_core_job", side_effect=native_job),
        patch(
            "cdmw.ui.archive_browser.static_replacement_geometry_math.copy.deepcopy",
            side_effect=AssertionError("Python mirror deepcopy should not run"),
        ),
    ):
        mirrored = mirror_submesh_x(submesh, 2.0, normalize_vector=lambda vector: tuple(vector))  # type: ignore[arg-type]

    assert mirrored is not submesh
    assert mirrored.vertices == [(4.0, 0.0, 0.0), (2.0, 0.0, 0.0), (3.0, 1.0, 0.0)]
    assert mirrored.faces == [(0, 2, 1)]
    assert submesh.vertices == [(0.0, 0.0, 0.0), (2.0, 0.0, 0.0), (1.0, 1.0, 0.0)]


def test_native_affine_transform_bridge_writes_source_part_pivot_vertices_binary() -> None:
    from cdmw.modding.mesh_native_core import apply_native_mesh_affine_transform_submeshes

    submesh = SubMesh(vertices=[(10.0, 0.0, 0.0), (12.0, 0.0, 0.0)])

    def native_job(_binary: Path, command: str, payload: object, *, timeout_seconds: float) -> dict[str, object]:
        assert command == "affine-transform-json"
        assert isinstance(payload, dict)
        item = payload["submeshes"][0]
        adjustment = item["source_part_adjustment"]
        assert "pivot_vertices" not in adjustment
        pivot_descriptor = adjustment["pivot_vertices_binary"]
        assert pivot_descriptor["count"] == 2
        pivot_values = _read_f64_values(Path(pivot_descriptor["path"]))
        assert pivot_values == [0.0, 0.0, 0.0, 2.0, 0.0, 0.0]
        vertices_path = item["vertices_output_path"]
        _write_f64_values(vertices_path, [11.0, 0.0, 0.0, 13.0, 0.0, 0.0])
        return {
            "status": "ok",
            "backend": "cdmw_mesh_core_0.1",
            "operation": "affine_transform",
            "submeshes": [
                {
                    "index": 0,
                    "vertex_count": 2,
                    "vertices_binary": {"path": str(vertices_path), "count": 2, "components": 3, "type": "f64"},
                }
            ],
        }

    with (
        patch("cdmw.modding.mesh_native_core.find_native_mesh_core_binary", return_value=Path("native.exe")),
        patch("cdmw.modding.mesh_native_core._run_native_mesh_core_job", side_effect=native_job),
    ):
        changed = apply_native_mesh_affine_transform_submeshes(
            [submesh],
            source_part_adjustments_by_index={
                0: {
                    "scale_xyz": (1.0, 1.0, 1.0),
                    "uniform_scale": 1.0,
                    "offset_xyz": (1.0, 0.0, 0.0),
                    "rotate_xyz_degrees": (0.0, 0.0, 0.0),
                    "pivot_vertices": ((0.0, 0.0, 0.0), (2.0, 0.0, 0.0)),
                }
            },
        )

    assert changed == {0}
    assert submesh.vertices == [(11.0, 0.0, 0.0), (13.0, 0.0, 0.0)]


def test_native_uv_transform_submesh_bridge_uses_selected_all_descriptor() -> None:
    from cdmw.modding.mesh_native_core import apply_native_mesh_uv_transform_submeshes

    submesh = SubMesh(
        vertices=[(0.0, 0.0, 0.0), (1.0, 0.0, 0.0)],
        uvs=[(0.0, 0.0), (1.0, 0.0)],
    )
    uv_transform = {
        "offset": (0.25, -0.5),
        "scale": (2.0, 1.0),
        "rotate": 0.0,
        "flip_u": False,
        "flip_v": True,
        "pivot": (0.5, 0.5),
    }

    def native_job(_binary: Path, command: str, payload: object, *, timeout_seconds: float) -> dict[str, object]:
        assert command == "uv-transform-json"
        assert isinstance(payload, dict)
        item = payload["submeshes"][0]
        assert item["selected_all_vertices"] is True
        assert item["uv_transform"] == {
            "offset": [0.25, -0.5],
            "scale": [2.0, 1.0],
            "rotate": 0.0,
            "flip_u": False,
            "flip_v": True,
            "pivot": [0.5, 0.5],
        }
        assert "selected_vertices" not in item
        assert "selected_vertices_binary" not in item
        assert "uvs_binary" in item
        uvs_path = item["uvs_output_path"]
        changed_path = item["changed_vertices_output_path"]
        _write_f64_values(uvs_path, [-0.25, 0.0, 1.75, 0.0])
        _write_i32_values(changed_path, [0, 1])
        return {
            "status": "ok",
            "backend": "cdmw_mesh_core_0.1",
            "operation": "uv_transform",
            "submeshes": [
                {
                    "index": 0,
                    "changed_vertices_binary": {"path": str(changed_path), "count": 2, "components": 1, "type": "i32"},
                    "uvs_binary": {"path": str(uvs_path), "count": 2, "components": 2, "type": "f64"},
                }
            ],
        }

    with (
        patch("cdmw.modding.mesh_native_core.find_native_mesh_core_binary", return_value=Path("native.exe")),
        patch("cdmw.modding.mesh_native_core._run_native_mesh_core_job", side_effect=native_job),
    ):
        processed = apply_native_mesh_uv_transform_submeshes([submesh], {0: uv_transform})

    assert processed == {0}
    assert submesh.uvs == [(-0.25, 0.0), (1.75, 0.0)]


def test_native_uv_atlas_submesh_bridge_uses_bounds_and_clamp() -> None:
    from cdmw.modding.mesh_native_core import apply_native_mesh_uv_atlas_submesh

    submesh = SubMesh(
        vertices=[(0.0, 0.0, 0.0), (1.0, 0.0, 0.0)],
        uvs=[(-0.00005, 0.25), (1.00005, 1.0)],
    )

    def native_job(_binary: Path, command: str, payload: object, *, timeout_seconds: float) -> dict[str, object]:
        assert command == "uv-transform-json"
        assert isinstance(payload, dict)
        item = payload["submeshes"][0]
        assert item["selected_all_vertices"] is True
        assert item["uv_transform"] == {
            "offset": [0.25, 0.5],
            "scale": [0.5, 0.25],
            "rotate": 0.0,
            "flip_u": False,
            "flip_v": False,
            "pivot": [0.0, 0.0],
            "input_bounds_min": [-0.0001, -0.0001],
            "input_bounds_max": [1.0001, 1.0001],
            "input_clamp_min": [0.0, 0.0],
            "input_clamp_max": [1.0, 1.0],
            "clamp_input_uv": True,
        }
        uvs_path = item["uvs_output_path"]
        changed_path = item["changed_vertices_output_path"]
        _write_f64_values(uvs_path, [0.25, 0.5625, 0.75, 0.75])
        _write_i32_values(changed_path, [0, 1])
        return {
            "status": "ok",
            "backend": "cdmw_mesh_core_0.1",
            "operation": "uv_transform",
            "submeshes": [
                {
                    "index": 0,
                    "changed_vertices_binary": {"path": str(changed_path), "count": 2, "components": 1, "type": "i32"},
                    "uvs_binary": {"path": str(uvs_path), "count": 2, "components": 2, "type": "f64"},
                }
            ],
        }

    with (
        patch("cdmw.modding.mesh_native_core.find_native_mesh_core_binary", return_value=Path("native.exe")),
        patch("cdmw.modding.mesh_native_core._run_native_mesh_core_job", side_effect=native_job),
    ):
        processed = apply_native_mesh_uv_atlas_submesh(submesh, offset=(0.25, 0.5), scale=(0.5, 0.25))

    assert processed is True
    assert submesh.uvs == [(0.25, 0.5625), (0.75, 0.75)]


def test_native_uv_atlas_submesh_bridge_surfaces_bounds_error() -> None:
    from cdmw.modding.mesh_native_core import apply_native_mesh_uv_atlas_submesh

    submesh = SubMesh(
        vertices=[(0.0, 0.0, 0.0)],
        uvs=[(1.5, 0.25)],
    )

    def native_job(_binary: Path, command: str, payload: object, *, timeout_seconds: float) -> dict[str, object]:
        assert command == "uv-transform-json"
        return {
            "status": "ok",
            "backend": "cdmw_mesh_core_0.1",
            "operation": "uv_transform",
            "submeshes": [
                {
                    "index": 0,
                    "status": "uv_out_of_bounds",
                    "error": "input UV outside allowed bounds",
                    "invalid_vertex_index": 0,
                    "invalid_uv": [1.5, 0.25],
                }
            ],
        }

    with (
        patch("cdmw.modding.mesh_native_core.find_native_mesh_core_binary", return_value=Path("native.exe")),
        patch("cdmw.modding.mesh_native_core._run_native_mesh_core_job", side_effect=native_job),
    ):
        with pytest.raises(ValueError) as exc:
            apply_native_mesh_uv_atlas_submesh(submesh, offset=(0.25, 0.5), scale=(0.5, 0.25))

    assert exc.value.args[1] == (1.5, 0.25)


def test_material_atlas_uv_rewrite_routes_through_native_first() -> None:
    from cdmw.modding import static_mesh_runtime_builder as runtime_builder

    submesh = SubMesh(
        vertices=[(0.0, 0.0, 0.0), (1.0, 0.0, 0.0)],
        uvs=[(0.0, 0.0), (1.0, 1.0)],
    )
    rect = StaticMaterialAtlasRect("mat", (0,), x=0.25, y=0.5, width=0.5, height=0.25)

    def native_atlas(target: SubMesh, *, offset, scale, timeout_seconds: float = 5.0) -> bool:
        assert target is submesh
        assert offset == (0.25, 0.5)
        assert scale == (0.5, 0.25)
        target.uvs = [(9.0, 9.0), (8.0, 8.0)]
        return True

    with patch("cdmw.modding.mesh_native_core.apply_native_mesh_uv_atlas_submesh", side_effect=native_atlas):
        runtime_builder._rewrite_submesh_uvs_for_material_atlas(
            submesh,
            rect,
            target_name="target",
            source_index=0,
            source_material_name="mat",
        )

    assert submesh.uvs == [(9.0, 9.0), (8.0, 8.0)]


def test_preview_decimation_routes_through_native_first() -> None:
    from cdmw.modding import static_mesh_runtime_builder as runtime_builder

    original = _mesh(
        "target.pac",
        [SubMesh(name="target", material="target", vertices=[(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0)], faces=[(0, 1, 2)])],
    )
    replacement = _mesh(
        "dense.obj",
        [
            SubMesh(
                name="dense",
                material="dense",
                vertices=[(float(index), 0.0, 0.0) for index in range(12)],
                faces=[(0, 1, 2), (3, 4, 5), (6, 7, 8), (9, 10, 11)],
            )
        ],
    )
    native_vertices = [(9.0, 0.0, 0.0), (10.0, 0.0, 0.0), (9.0, 1.0, 0.0)]

    def native_decimate(sources: list[SubMesh], max_faces: int, *, timeout_seconds: float = 5.0) -> set[int]:
        assert max_faces == 2
        sources[0] = SubMesh(
            name=sources[0].name,
            material=sources[0].material,
            vertices=native_vertices,
            faces=[(0, 1, 2)],
            vertex_count=3,
            face_count=1,
        )
        return {0}

    with (
        patch("cdmw.modding.mesh_native_core.decimate_native_mesh_preview_submeshes", side_effect=native_decimate) as native_decimate_call,
        patch("cdmw.modding.mesh_native_core.apply_native_mesh_affine_transform_submeshes", return_value=set()),
        patch("cdmw.modding.static_mesh_runtime_builder._decimate_submesh_for_preview", side_effect=AssertionError("python decimation")),
    ):
        sources = runtime_builder._transformed_replacement_sources(
            original,
            replacement,
            StaticReplacementTransform(alignment_mode="manual", scale_to_original_length=False),
            max_source_faces_per_submesh=2,
        )

    native_decimate_call.assert_called_once()
    assert sources[0].vertices == native_vertices
    assert sources[0].faces == [(0, 1, 2)]


def test_transformed_sources_use_native_affine_for_final_global_transform() -> None:
    from cdmw.modding import static_mesh_runtime_builder as runtime_builder

    original = _mesh(
        "original.pac",
        [SubMesh(name="target", material="target", vertices=[(0.0, 0.0, 0.0), (4.0, 0.0, 0.0), (0.0, 4.0, 0.0)], faces=[(0, 1, 2)])],
    )
    replacement = _mesh(
        "replacement.pac",
        [SubMesh(name="source", material="source", vertices=[(1.0, 2.0, 3.0), (2.0, 3.0, 4.0)], normals=[(0.0, 0.0, 1.0)] * 2)],
    )
    transform = StaticReplacementTransform(
        alignment_mode="manual",
        scale_xyz=(2.0, 3.0, 4.0),
        offset_xyz=(10.0, 20.0, 30.0),
    )

    def native_transform(submeshes, *, position_matrices_by_index, normal_matrices_by_index=None, timeout_seconds=5.0):
        matrix = position_matrices_by_index[0]
        submesh = submeshes[0]
        submesh.vertices = [
            (
                matrix[0] * vertex[0] + matrix[1] * vertex[1] + matrix[2] * vertex[2] + matrix[3],
                matrix[4] * vertex[0] + matrix[5] * vertex[1] + matrix[6] * vertex[2] + matrix[7],
                matrix[8] * vertex[0] + matrix[9] * vertex[1] + matrix[10] * vertex[2] + matrix[11],
            )
            for vertex in submesh.vertices
        ]
        return {0}

    with (
        patch("cdmw.modding.mesh_native_core.apply_native_mesh_affine_transform_submeshes", side_effect=native_transform) as native_affine,
        patch("cdmw.modding.static_mesh_runtime_builder._apply_transform", wraps=runtime_builder._apply_transform) as apply_transform,
    ):
        sources = _transformed_replacement_sources(original, replacement, transform)

    native_affine.assert_called_once()
    assert apply_transform.call_count == 1
    assert sources[0].vertices == [(12.0, 26.0, 42.0), (14.0, 29.0, 46.0)]


def test_transformed_sources_skip_python_fallback_bbox_when_native_affine_handles_all() -> None:
    from cdmw.modding import static_mesh_runtime_builder as runtime_builder

    original = _mesh(
        "original.pac",
        [SubMesh(name="target", material="target", vertices=[(0.0, 0.0, 0.0), (4.0, 0.0, 0.0), (0.0, 4.0, 0.0)], faces=[(0, 1, 2)])],
    )
    replacement = _mesh(
        "replacement.pac",
        [SubMesh(name="source", material="source", vertices=[(1.0, 2.0, 3.0), (2.0, 3.0, 4.0)])],
    )
    transform = StaticReplacementTransform(
        alignment_mode="manual",
        scale_xyz=(2.0, 3.0, 4.0),
        offset_xyz=(10.0, 20.0, 30.0),
        fit_to_original_bbox=False,
    )

    def native_transform(submeshes, *, position_matrices_by_index, normal_matrices_by_index=None, timeout_seconds=5.0):
        matrix = position_matrices_by_index[0]
        submesh = submeshes[0]
        submesh.vertices = [
            (
                matrix[0] * vertex[0] + matrix[1] * vertex[1] + matrix[2] * vertex[2] + matrix[3],
                matrix[4] * vertex[0] + matrix[5] * vertex[1] + matrix[6] * vertex[2] + matrix[7],
                matrix[8] * vertex[0] + matrix[9] * vertex[1] + matrix[10] * vertex[2] + matrix[11],
            )
            for vertex in submesh.vertices
        ]
        return {0}

    with (
        patch("cdmw.modding.mesh_native_core.apply_native_mesh_affine_transform_submeshes", side_effect=native_transform) as native_affine,
        patch("cdmw.modding.static_mesh_runtime_builder._bbox", side_effect=AssertionError("python fallback bbox")),
    ):
        sources = runtime_builder._transformed_replacement_sources(original, replacement, transform)

    native_affine.assert_called_once()
    assert sources[0].vertices == [(12.0, 26.0, 42.0), (14.0, 29.0, 46.0)]


def test_transformed_sources_use_native_uv_for_texture_uv_transform() -> None:
    original = _mesh(
        "original.pac",
        [SubMesh(name="target", material="target", vertices=[(0.0, 0.0, 0.0)], faces=[])],
    )
    replacement = _mesh(
        "replacement.pac",
        [
            SubMesh(
                name="source",
                material="source",
                vertices=[(0.0, 0.0, 0.0), (1.0, 0.0, 0.0)],
                uvs=[(0.0, 0.0), (1.0, 0.0)],
            )
        ],
    )
    uv_transform = StaticTextureUvTransform(
        source_material_name="source",
        rotate_degrees=90,
        flip_u=True,
        offset_uv=(0.1, -0.2),
    )

    def native_uv_transform(submeshes, transforms_by_index, *, timeout_seconds=5.0):
        assert transforms_by_index == {
            0: {
                "offset": (0.1, -0.2),
                "scale": (1.0, 1.0),
                "rotate": 90.0,
                "flip_u": True,
                "flip_v": False,
                "pivot": (0.5, 0.5),
            }
        }
        submeshes[0].uvs = [(1.1, 0.8), (1.1, -0.2)]
        return {0}

    with (
        patch("cdmw.modding.mesh_native_core.apply_native_mesh_uv_transform_submeshes", side_effect=native_uv_transform) as native_uv,
        patch("cdmw.modding.static_mesh_runtime_builder._apply_texture_uv_transform", side_effect=AssertionError("python uv transform")),
    ):
        sources = _transformed_replacement_sources(
            original,
            replacement,
            StaticReplacementTransform(),
            texture_uv_transforms=[uv_transform],
            global_transform_exempt_indices={0},
        )

    native_uv.assert_called_once()
    assert sources[0].uvs == [(1.1, 0.8), (1.1, -0.2)]


def test_transformed_sources_use_native_affine_for_source_part_adjustment() -> None:
    original = _mesh(
        "original.pac",
        [SubMesh(name="target", material="target", vertices=[(0.0, 0.0, 0.0)], faces=[])],
    )
    replacement = _mesh(
        "replacement.pac",
        [
            SubMesh(
                name="source",
                material="source",
                vertices=[(1.0, 2.0, 0.0), (2.0, 2.0, 0.0)],
                normals=[(1.0, 0.0, 0.0), (0.0, 1.0, 0.0)],
            )
        ],
    )
    adjustment = StaticSourcePartAdjustment(
        source_submesh_index=0,
        scale_xyz=(2.0, 1.0, 1.0),
        rotate_xyz_degrees=(0.0, 0.0, 90.0),
        offset_xyz=(10.0, 20.0, 30.0),
    )

    def native_transform(submeshes, *, source_part_adjustments_by_index=None, timeout_seconds=5.0, **kwargs):
        assert not kwargs.get("position_matrices_by_index")
        native_adjustment = dict(source_part_adjustments_by_index or {})[0]
        assert native_adjustment["scale_xyz"] == (2.0, 1.0, 1.0)
        assert native_adjustment["offset_xyz"] == (10.0, 20.0, 30.0)
        assert native_adjustment["rotate_xyz_degrees"] == (0.0, 0.0, 90.0)
        assert native_adjustment["pivot_vertices"] == ((1.0, 2.0, 0.0), (2.0, 2.0, 0.0))
        submesh = submeshes[0]
        submesh.vertices = [(11.5, 21.0, 30.0), (11.5, 23.0, 30.0)]
        submesh.normals = [(0.0, 1.0, 0.0), (-1.0, 0.0, 0.0)]
        return {0}

    with (
        patch("cdmw.modding.mesh_native_core.apply_native_mesh_affine_transform_submeshes", side_effect=native_transform) as native_affine,
        patch("cdmw.modding.static_mesh_runtime_builder._apply_source_part_adjustment", side_effect=AssertionError("python source part adjustment")),
    ):
        sources = _transformed_replacement_sources(
            original,
            replacement,
            StaticReplacementTransform(),
            source_part_adjustments=[adjustment],
            global_transform_exempt_indices={0},
        )

    native_affine.assert_called_once()
    assert [tuple(round(component, 7) for component in vertex) for vertex in sources[0].vertices] == [
        (11.5, 21.0, 30.0),
        (11.5, 23.0, 30.0),
    ]
    assert tuple(round(component, 7) for component in sources[0].normals[0]) == (0.0, 1.0, 0.0)
    assert round(sources[0].normals[1][0], 7) == -1.0
    assert round(sources[0].normals[1][1], 7) == 0.0


def test_transformed_sources_can_freeze_alignment_basis_for_live_mesh_edits() -> None:
    original = _mesh(
        "original.pac",
        [
            SubMesh(
                name="target",
                material="target",
                vertices=[(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0)],
                faces=[(0, 1, 2)],
            )
        ],
    )
    base = copy.deepcopy(original)
    edited = _mesh(
        "edited.pac",
        [
            SubMesh(
                name="target",
                material="target",
                vertices=[(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 2.0, 0.0)],
                faces=[(0, 1, 2)],
            )
        ],
    )
    transform = StaticReplacementTransform(
        fit_to_original_bbox=True,
        preserve_aspect_ratio=False,
        scale_to_original_length=False,
    )

    base_vertices = _transformed_replacement_sources(original, base, transform)[0].vertices
    edited_vertices = _transformed_replacement_sources(
        original,
        edited,
        transform,
        alignment_basis_mesh=base,
    )[0].vertices

    assert base_vertices[0] == edited_vertices[0]
    assert base_vertices[1] == edited_vertices[1]
    assert base_vertices[2] != edited_vertices[2]


def test_source_delta_for_transformed_delta_inverts_live_mesh_edit_transform() -> None:
    original = _mesh(
        "original.pac",
        [
            SubMesh(
                name="target",
                material="target",
                vertices=[
                    (0.0, 0.0, 0.0),
                    (4.0, 0.0, 0.0),
                    (0.0, 9.0, 0.0),
                    (0.0, 0.0, 2.0),
                ],
                faces=[(0, 1, 2), (0, 1, 3), (0, 2, 3), (1, 2, 3)],
            )
        ],
    )
    replacement = _mesh(
        "replacement.pac",
        [
            SubMesh(
                name="source",
                material="source",
                vertices=[
                    (-1.0, -1.5, -2.5),
                    (1.0, -1.5, -2.5),
                    (-1.0, 1.5, -2.5),
                    (-1.0, -1.5, 2.5),
                ],
                faces=[(0, 1, 2), (0, 1, 3), (0, 2, 3), (1, 2, 3)],
            )
        ],
    )
    transform = StaticReplacementTransform(
        alignment_mode="manual",
        source_anchor=(0.0, 0.0, 0.0),
        target_anchor=(0.0, 0.0, 0.0),
        source_axis=(0.0, 0.0, 1.0),
        target_axis=(0.0, 0.0, 1.0),
        rotate_xyz_degrees=(0.0, 0.0, 90.0),
        scale_xyz=(1.5, 0.75, 2.0),
        offset_xyz=(5.0, -2.0, 1.0),
        fit_to_original_bbox=True,
        preserve_aspect_ratio=False,
        scale_to_original_length=False,
    )
    adjustments = [
        StaticSourcePartAdjustment(
            source_submesh_index=0,
            rotate_xyz_degrees=(0.0, 35.0, 0.0),
            scale_xyz=(2.0, 0.5, 1.25),
            uniform_scale=0.8,
        )
    ]
    displayed_delta = (0.35, -0.20, 0.45)

    source_delta = source_delta_for_transformed_delta(
        original,
        replacement,
        transform,
        0,
        displayed_delta,
        source_part_adjustments=adjustments,
        global_transform_source_indices={0},
        alignment_basis_mesh=replacement,
    )
    before = _transformed_replacement_sources(
        original,
        replacement,
        transform,
        adjustments,
        global_transform_source_indices={0},
        alignment_basis_mesh=replacement,
    )[0].vertices[0]
    edited = copy.deepcopy(replacement)
    edited.submeshes[0].vertices[0] = tuple(
        float(edited.submeshes[0].vertices[0][axis]) + source_delta[axis]
        for axis in range(3)
    )
    after = _transformed_replacement_sources(
        original,
        edited,
        transform,
        adjustments,
        global_transform_source_indices={0},
        alignment_basis_mesh=replacement,
    )[0].vertices[0]

    actual_delta = tuple(after[axis] - before[axis] for axis in range(3))
    for axis in range(3):
        assert abs(actual_delta[axis] - displayed_delta[axis]) <= 1e-6


def test_source_point_for_transformed_point_inverts_live_mesh_edit_transform() -> None:
    original = _mesh(
        "original.pac",
        [
            SubMesh(
                name="target",
                material="target",
                vertices=[
                    (0.0, 0.0, 0.0),
                    (4.0, 0.0, 0.0),
                    (0.0, 9.0, 0.0),
                    (0.0, 0.0, 2.0),
                ],
                faces=[(0, 1, 2), (0, 1, 3), (0, 2, 3), (1, 2, 3)],
            )
        ],
    )
    replacement = _mesh(
        "replacement.pac",
        [
            SubMesh(
                name="source",
                material="source",
                vertices=[
                    (-1.0, -1.5, -2.5),
                    (1.0, -1.5, -2.5),
                    (-1.0, 1.5, -2.5),
                    (-1.0, -1.5, 2.5),
                ],
                faces=[(0, 1, 2), (0, 1, 3), (0, 2, 3), (1, 2, 3)],
            )
        ],
    )
    transform = StaticReplacementTransform(
        alignment_mode="manual",
        source_anchor=(0.0, 0.0, 0.0),
        target_anchor=(0.0, 0.0, 0.0),
        source_axis=(0.0, 0.0, 1.0),
        target_axis=(0.0, 0.0, 1.0),
        rotate_xyz_degrees=(0.0, 0.0, 90.0),
        scale_xyz=(1.5, 0.75, 2.0),
        offset_xyz=(5.0, -2.0, 1.0),
        fit_to_original_bbox=True,
        preserve_aspect_ratio=False,
        scale_to_original_length=False,
    )
    adjustments = [
        StaticSourcePartAdjustment(
            source_submesh_index=0,
            offset_xyz=(0.25, -0.5, 0.75),
            rotate_xyz_degrees=(0.0, 35.0, 0.0),
            scale_xyz=(2.0, 0.5, 1.25),
            uniform_scale=0.8,
        )
    ]
    displayed_point = _transformed_replacement_sources(
        original,
        replacement,
        transform,
        adjustments,
        global_transform_source_indices={0},
        alignment_basis_mesh=replacement,
    )[0].vertices[2]

    source_point = source_point_for_transformed_point(
        original,
        replacement,
        transform,
        0,
        displayed_point,
        source_part_adjustments=adjustments,
        global_transform_source_indices={0},
        alignment_basis_mesh=replacement,
    )

    for axis in range(3):
        assert abs(source_point[axis] - replacement.submeshes[0].vertices[2][axis]) <= 1e-6


def test_source_affine_for_transformed_preview_matches_live_preview_transform() -> None:
    original = _mesh(
        "original.pac",
        [
            SubMesh(
                name="target",
                material="target",
                vertices=[
                    (0.0, 0.0, 0.0),
                    (4.0, 0.0, 0.0),
                    (0.0, 9.0, 0.0),
                    (0.0, 0.0, 2.0),
                ],
                faces=[(0, 1, 2), (0, 1, 3), (0, 2, 3), (1, 2, 3)],
            )
        ],
    )
    replacement = _mesh(
        "replacement.pac",
        [
            SubMesh(
                name="source",
                material="source",
                vertices=[
                    (-1.0, -1.5, -2.5),
                    (1.0, -1.5, -2.5),
                    (-1.0, 1.5, -2.5),
                    (-1.0, -1.5, 2.5),
                ],
                faces=[(0, 1, 2), (0, 1, 3), (0, 2, 3), (1, 2, 3)],
            )
        ],
    )
    transform = StaticReplacementTransform(
        alignment_mode="manual",
        source_anchor=(0.0, 0.0, 0.0),
        target_anchor=(0.0, 0.0, 0.0),
        source_axis=(0.0, 0.0, 1.0),
        target_axis=(0.0, 0.0, 1.0),
        rotate_xyz_degrees=(0.0, 0.0, 90.0),
        scale_xyz=(1.5, 0.75, 2.0),
        offset_xyz=(5.0, -2.0, 1.0),
        fit_to_original_bbox=True,
        preserve_aspect_ratio=False,
        scale_to_original_length=False,
    )
    adjustments = [
        StaticSourcePartAdjustment(
            source_submesh_index=0,
            offset_xyz=(0.25, -0.5, 0.75),
            rotate_xyz_degrees=(0.0, 35.0, 0.0),
            scale_xyz=(2.0, 0.5, 1.25),
            uniform_scale=0.8,
        )
    ]
    center = (1.0, -2.0, 0.5)
    scale = 3.0

    affine = source_affine_for_transformed_preview(
        original,
        replacement,
        transform,
        0,
        normalization_center=center,
        normalization_scale=scale,
        source_part_adjustments=adjustments,
        global_transform_source_indices={0},
        alignment_basis_mesh=replacement,
    )

    assert affine is not None
    source = replacement.submeshes[0].vertices[2]
    actual = (
        affine[0] * source[0] + affine[1] * source[1] + affine[2] * source[2] + affine[3],
        affine[4] * source[0] + affine[5] * source[1] + affine[6] * source[2] + affine[7],
        affine[8] * source[0] + affine[9] * source[1] + affine[10] * source[2] + affine[11],
    )
    displayed = _transformed_replacement_sources(
        original,
        replacement,
        transform,
        adjustments,
        global_transform_source_indices={0},
        alignment_basis_mesh=replacement,
    )[0].vertices[2]
    expected = tuple((displayed[axis] - center[axis]) * scale for axis in range(3))

    for axis in range(3):
        assert abs(actual[axis] - expected[axis]) <= 1e-6


def test_source_normal_transform_for_transformed_preview_matches_live_preview_normals() -> None:
    original = _mesh(
        "original.pac",
        [
            SubMesh(
                name="target",
                material="target",
                vertices=[
                    (0.0, 0.0, 0.0),
                    (4.0, 0.0, 0.0),
                    (0.0, 9.0, 0.0),
                    (0.0, 0.0, 2.0),
                ],
                faces=[(0, 1, 2), (0, 1, 3), (0, 2, 3), (1, 2, 3)],
            )
        ],
    )
    source_normal = (0.2, 0.6, 0.77)
    replacement = _mesh(
        "replacement.pac",
        [
            SubMesh(
                name="source",
                material="source",
                vertices=[
                    (-1.0, -1.5, -2.5),
                    (1.0, -1.5, -2.5),
                    (-1.0, 1.5, -2.5),
                    (-1.0, -1.5, 2.5),
                ],
                normals=[source_normal] * 4,
                faces=[(0, 1, 2), (0, 1, 3), (0, 2, 3), (1, 2, 3)],
            )
        ],
    )
    transform = StaticReplacementTransform(
        alignment_mode="manual",
        source_anchor=(0.0, 0.0, 0.0),
        target_anchor=(0.0, 0.0, 0.0),
        source_axis=(0.0, 0.0, 1.0),
        target_axis=(0.0, 1.0, 0.0),
        rotate_xyz_degrees=(30.0, -20.0, 70.0),
        scale_xyz=(5.0, 0.25, 2.0),
        fit_to_original_bbox=True,
        preserve_aspect_ratio=False,
        scale_to_original_length=False,
    )
    adjustments = [
        StaticSourcePartAdjustment(
            source_submesh_index=0,
            rotate_xyz_degrees=(15.0, 35.0, -10.0),
            scale_xyz=(0.2, 4.0, 1.5),
            uniform_scale=2.0,
        )
    ]

    normal_transform = source_normal_transform_for_transformed_preview(
        original,
        replacement,
        transform,
        0,
        source_part_adjustments=adjustments,
        global_transform_source_indices={0},
        alignment_basis_mesh=replacement,
    )

    assert normal_transform is not None
    actual = (
        normal_transform[0] * source_normal[0] + normal_transform[1] * source_normal[1] + normal_transform[2] * source_normal[2],
        normal_transform[3] * source_normal[0] + normal_transform[4] * source_normal[1] + normal_transform[5] * source_normal[2],
        normal_transform[6] * source_normal[0] + normal_transform[7] * source_normal[1] + normal_transform[8] * source_normal[2],
    )
    actual_length = sum(component * component for component in actual) ** 0.5
    actual = tuple(component / actual_length for component in actual)
    expected = _transformed_replacement_sources(
        original,
        replacement,
        transform,
        adjustments,
        global_transform_source_indices={0},
        alignment_basis_mesh=replacement,
    )[0].normals[0]

    for axis in range(3):
        assert abs(actual[axis] - expected[axis]) <= 1e-6


def test_source_distance_for_transformed_distance_uses_uniform_live_edit_scale() -> None:
    original = _mesh(
        "original.pac",
        [
            SubMesh(
                name="target",
                material="target",
                vertices=[(0.0, 0.0, 0.0), (10.0, 0.0, 0.0), (0.0, 10.0, 0.0)],
                faces=[(0, 1, 2)],
            )
        ],
    )
    replacement = _mesh(
        "replacement.pac",
        [
            SubMesh(
                name="source",
                material="source",
                vertices=[(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0)],
                faces=[(0, 1, 2)],
            )
        ],
    )
    transform = StaticReplacementTransform(
        alignment_mode="manual",
        source_anchor=(0.0, 0.0, 0.0),
        target_anchor=(0.0, 0.0, 0.0),
        scale_xyz=(4.0, 4.0, 4.0),
        scale_to_original_length=False,
    )

    source_distance = source_distance_for_transformed_distance(
        original,
        replacement,
        transform,
        0,
        8.0,
        global_transform_source_indices={0},
        alignment_basis_mesh=replacement,
    )

    assert abs(source_distance - 2.0) <= 1e-6


def test_display_space_push_pull_delta_round_trips_to_source_mesh() -> None:
    original = _mesh(
        "original.pac",
        [
            SubMesh(
                name="target",
                material="target",
                vertices=[
                    (0.0, 0.0, 0.0),
                    (6.0, 0.0, 0.0),
                    (0.0, 4.0, 0.0),
                    (0.0, 0.0, 5.0),
                ],
                faces=[(0, 1, 2), (0, 1, 3), (0, 2, 3), (1, 2, 3)],
            )
        ],
    )
    replacement = _mesh(
        "replacement.pac",
        [
            SubMesh(
                name="source",
                material="source",
                vertices=[
                    (-0.5, -0.5, 0.0),
                    (0.5, -0.5, 0.0),
                    (-0.5, 0.5, 0.0),
                    (-0.5, -0.5, 0.5),
                ],
                normals=[(0.0, 0.0, 1.0)] * 4,
                faces=[(0, 1, 2), (0, 1, 3), (0, 2, 3), (1, 2, 3)],
            )
        ],
    )
    transform = StaticReplacementTransform(
        alignment_mode="manual",
        source_anchor=(0.0, 0.0, 0.0),
        target_anchor=(0.0, 0.0, 0.0),
        rotate_xyz_degrees=(12.0, -30.0, 45.0),
        scale_xyz=(8.0, 0.5, 3.0),
        fit_to_original_bbox=True,
        preserve_aspect_ratio=False,
        scale_to_original_length=False,
    )
    adjustments = [
        StaticSourcePartAdjustment(
            source_submesh_index=0,
            rotate_xyz_degrees=(0.0, 25.0, 10.0),
            scale_xyz=(0.4, 2.5, 1.2),
            uniform_scale=1.5,
        )
    ]
    displayed_before = _transformed_replacement_sources(
        original,
        replacement,
        transform,
        adjustments,
        global_transform_source_indices={0},
        alignment_basis_mesh=replacement,
    )[0]
    displayed_edit = copy.deepcopy(displayed_before)
    changed = apply_brush_deformation(
        displayed_edit,
        tool="inflate",
        center=displayed_before.vertices[0],
        radius=1.0,
        strength=1.0,
        amount=0.25,
        vertex_indices=[0],
        vertex_weights={0: 1.0},
        recompute_normals=False,
    )
    assert changed == [0]
    displayed_delta = tuple(
        displayed_edit.vertices[0][axis] - displayed_before.vertices[0][axis]
        for axis in range(3)
    )
    source_delta = source_delta_for_transformed_delta(
        original,
        replacement,
        transform,
        0,
        displayed_delta,
        source_part_adjustments=adjustments,
        global_transform_source_indices={0},
        alignment_basis_mesh=replacement,
    )
    edited = copy.deepcopy(replacement)
    edited.submeshes[0].vertices[0] = tuple(
        edited.submeshes[0].vertices[0][axis] + source_delta[axis]
        for axis in range(3)
    )
    displayed_after = _transformed_replacement_sources(
        original,
        edited,
        transform,
        adjustments,
        global_transform_source_indices={0},
        alignment_basis_mesh=replacement,
    )[0]

    for axis in range(3):
        assert abs(displayed_after.vertices[0][axis] - displayed_edit.vertices[0][axis]) <= 1e-6


def _minimal_pac_original() -> tuple[bytes, ParsedMesh]:
    n_lods = 4
    vertex_records = bytearray(3 * 40)
    positions = [(0, 0, 0), (32767, 0, 0), (0, 32767, 0)]
    for index, position in enumerate(positions):
        struct.pack_into("<HHH", vertex_records, index * 40, *position)
        struct.pack_into("<I", vertex_records, index * 40 + 16, 0)
    indices = struct.pack("<HHH", 0, 1, 2)
    lod_section = bytes(vertex_records + indices)

    sec0 = bytearray(5 + n_lods * 8)
    sec0[4] = n_lods
    sec0.extend(bytes([6]) + b"target")
    sec0.extend(bytes([6]) + b"target")
    desc_start = len(sec0)
    desc = bytearray(64)
    desc[0] = 0x01
    struct.pack_into("<8f", desc, 3, 0.0, 0.0, 0.0, 0.0, 0.0, 1.0, 1.0, 1.0)
    desc[35:40] = bytes([0x04, 0x00, 0x01, 0x02, 0x03])
    for lod_index in range(n_lods):
        struct.pack_into("<H", desc, 40 + lod_index * 2, 3)
        struct.pack_into("<I", desc, 48 + lod_index * 4, 3)
    sec0.extend(desc)

    header = bytearray(0x50)
    header[:4] = b"PAR "
    sections = [bytes(sec0)] + [lod_section] * n_lods
    for index, payload in enumerate(sections):
        struct.pack_into("<I", header, 0x10 + index * 8, 0)
        struct.pack_into("<I", header, 0x10 + index * 8 + 4, len(payload))
    offsets = []
    cursor = len(header)
    for payload in sections:
        offsets.append(cursor)
        cursor += len(payload)
    for lod_index in range(n_lods):
        section_index = n_lods - lod_index
        struct.pack_into("<I", sec0, 5 + lod_index * 4, offsets[section_index])
        struct.pack_into("<I", sec0, 5 + n_lods * 4 + lod_index * 4, offsets[section_index] + len(vertex_records))
    sections[0] = bytes(sec0)
    data = bytes(header) + b"".join(sections)
    lod0_offset = offsets[4]
    original = _mesh(
        "target.pac",
        [
            SubMesh(
                name="target",
                material="target",
                vertices=[(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0)],
                faces=[(0, 1, 2)],
                source_vertex_offsets=[lod0_offset + index * 40 for index in range(3)],
                source_vertex_stride=40,
                source_descriptor_offset=offsets[0] + desc_start,
                source_lod_count=n_lods,
            )
        ],
    )
    return data, original


def _minimal_two_part_pac_original() -> tuple[bytes, ParsedMesh]:
    n_lods = 4
    part_count = 2
    vertices_per_part = 3
    vertex_records = bytearray(part_count * vertices_per_part * 40)
    positions = [
        (0, 0, 0),
        (32767, 0, 0),
        (0, 32767, 0),
        (0, 0, 0),
        (0, 32767, 0),
        (0, 0, 32767),
    ]
    for index, position in enumerate(positions):
        struct.pack_into("<HHH", vertex_records, index * 40, *position)
        struct.pack_into("<I", vertex_records, index * 40 + 16, 0)
    indices = struct.pack("<HHH", 0, 1, 2) + struct.pack("<HHH", 0, 1, 2)
    lod_section = bytes(vertex_records + indices)

    sec0 = bytearray(5 + n_lods * 8)
    sec0[4] = n_lods
    descriptor_starts: list[int] = []
    for part_index in range(part_count):
        name = f"target{part_index}".encode("ascii")
        sec0.extend(bytes([len(name)]) + name)
        sec0.extend(bytes([len(name)]) + name)
        descriptor_starts.append(len(sec0))
        desc = bytearray(64)
        desc[0] = 0x01
        struct.pack_into(
            "<8f",
            desc,
            3,
            0.0,
            0.0,
            0.0,
            0.0,
            0.0,
            1.0,
            1.0,
            1.0,
        )
        desc[35:40] = bytes([0x04, 0x00, 0x01, 0x02, 0x03])
        for lod_index in range(n_lods):
            struct.pack_into("<H", desc, 40 + lod_index * 2, vertices_per_part)
            struct.pack_into("<I", desc, 48 + lod_index * 4, 3)
        sec0.extend(desc)

    header = bytearray(0x50)
    header[:4] = b"PAR "
    sections = [bytes(sec0)] + [lod_section] * n_lods
    for index, payload in enumerate(sections):
        struct.pack_into("<I", header, 0x10 + index * 8, 0)
        struct.pack_into("<I", header, 0x10 + index * 8 + 4, len(payload))
    offsets = []
    cursor = len(header)
    for payload in sections:
        offsets.append(cursor)
        cursor += len(payload)
    for lod_index in range(n_lods):
        section_index = n_lods - lod_index
        struct.pack_into("<I", sec0, 5 + lod_index * 4, offsets[section_index])
        struct.pack_into("<I", sec0, 5 + n_lods * 4 + lod_index * 4, offsets[section_index] + len(vertex_records))
    sections[0] = bytes(sec0)
    data = bytes(header) + b"".join(sections)
    lod0_offset = offsets[4]
    original = _mesh(
        "target.pac",
        [
            SubMesh(
                name=f"target{part_index}",
                material=f"target{part_index}",
                vertices=[
                    (float(part_index), 0.0, 0.0),
                    (float(part_index) + 1.0, 0.0, 0.0),
                    (float(part_index), 1.0, 0.0),
                ],
                faces=[(0, 1, 2)],
                source_vertex_offsets=[
                    lod0_offset + (part_index * vertices_per_part + vertex_index) * 40
                    for vertex_index in range(vertices_per_part)
                ],
                source_vertex_stride=40,
                source_descriptor_offset=offsets[0] + descriptor_starts[part_index],
                source_lod_count=n_lods,
            )
            for part_index in range(part_count)
        ],
    )
    return data, original


class StaticMeshReplacementPreviewTests(unittest.TestCase):
    def test_static_mapping_avoids_flag_runtime_slot_for_generic_source(self) -> None:
        vertices = [(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0)]
        faces = [(0, 1, 2)]
        original = _mesh(
            "cd_phm_02_sword_0015.pac",
            [
                SubMesh(name="CD_PHM_02_Sword_Flag_0015", material="CD_PHM_02_Flag_0001", vertices=vertices, faces=faces),
                SubMesh(name="CD_PHM_02_Blade_0015", material="CD_PHM_02_Blade_0015", vertices=vertices, faces=faces),
            ],
        )
        replacement = _mesh(
            "verdict_axe.gltf",
            [
                SubMesh(name="polySurface265_lambert1_0", material="lambert1", vertices=vertices, faces=faces),
            ],
        )

        mappings = suggest_static_submesh_mappings(original, replacement)

        self.assertEqual([], mappings[0].source_submesh_indices)
        self.assertEqual([0], mappings[1].source_submesh_indices)

    def test_static_mapping_allows_real_flag_source_to_flag_runtime_slot(self) -> None:
        vertices = [(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0)]
        faces = [(0, 1, 2)]
        original = _mesh(
            "target.pac",
            [
                SubMesh(name="CD_PHM_02_Sword_Flag_0015", material="CD_PHM_02_Flag_0001", vertices=vertices, faces=faces),
                SubMesh(name="CD_PHM_02_Blade_0015", material="CD_PHM_02_Blade_0015", vertices=vertices, faces=faces),
            ],
        )
        replacement = _mesh(
            "source.gltf",
            [
                SubMesh(name="cloth_flag_panel", material="flag_cloth", vertices=vertices, faces=faces),
            ],
        )

        mappings = suggest_static_submesh_mappings(original, replacement)

        self.assertEqual([0], mappings[0].source_submesh_indices)
        self.assertEqual([], mappings[1].source_submesh_indices)

    def test_complete_source_owned_blocks_generic_source_in_flag_runtime_slot(self) -> None:
        vertices = [(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0)]
        faces = [(0, 1, 2)]
        original = _mesh(
            "cd_phm_02_sword_0015.pac",
            [
                SubMesh(name="CD_PHM_02_Sword_Flag_0015", material="CD_PHM_02_Flag_0001", vertices=vertices, faces=faces),
                SubMesh(name="CD_PHM_02_Blade_0015", material="CD_PHM_02_Blade_0015", vertices=vertices, faces=faces),
            ],
        )
        replacement = _mesh(
            "verdict_axe.gltf",
            [
                SubMesh(name="polySurface265_lambert1_0", material="lambert1", vertices=vertices, faces=faces),
            ],
        )
        options = StaticMeshReplacementOptions(
            complete_external_swap=True,
            submesh_mappings=[
                StaticSubmeshMapping(0, "CD_PHM_02_Flag_0001", [0], 0),
                StaticSubmeshMapping(1, "CD_PHM_02_Blade_0015", [], 1),
            ],
        )

        report = analyze_static_replacement(original, replacement, options)

        self.assertTrue(any("Unsafe runtime draw-slot mapping" in error for error in report.errors))

    def test_manual_alignment_does_not_apply_hidden_axis_rotation(self) -> None:
        original = _mesh(
            "target.pac",
            [
                SubMesh(
                    name="target",
                    material="target",
                    vertices=[(0.0, 0.0, 0.0), (0.0, 3.0, 0.0), (0.0, 0.0, 1.0)],
                    faces=[(0, 1, 2)],
                )
            ],
        )
        replacement = _mesh(
            "replacement.obj",
            [
                SubMesh(
                    name="replacement",
                    material="replacement",
                    vertices=[(0.0, 0.0, 0.0), (2.0, 0.0, 0.0), (0.0, 0.0, 1.0)],
                    faces=[(0, 1, 2)],
                )
            ],
        )
        mapping = StaticSubmeshMapping(
            target_submesh_index=0,
            target_submesh_name="target",
            source_submesh_indices=[0],
            target_material_slot_index=0,
        )
        preview = build_static_replacement_preview_mesh(
            original,
            replacement,
            StaticMeshReplacementOptions(
                transform=StaticReplacementTransform(alignment_mode="manual", scale_to_original_length=False),
                submesh_mappings=[mapping],
            ),
        )

        self.assertEqual(preview.submeshes[0].vertices[1], (2.0, 0.0, 0.0))

    def test_static_replacement_export_uses_face_deleted_edited_source_mesh(self) -> None:
        original_data, original = _minimal_pac_original()
        replacement = _mesh(
            "cut_source.obj",
            [
                SubMesh(
                    name="replacement",
                    material="replacement",
                    vertices=[
                        (-1.0, 0.0, 0.0),
                        (1.0, 0.0, 0.0),
                        (-1.0, 1.0, 0.0),
                        (1.0, 1.0, 0.0),
                    ],
                    uvs=[(0.0, 0.0), (1.0, 0.0), (0.0, 1.0), (1.0, 1.0)],
                    faces=[(0, 1, 2), (1, 3, 2)],
                )
            ],
        )
        edited = copy.deepcopy(replacement)
        result = delete_faces_touching_vertices(edited, {0: [0]})
        mapping = StaticSubmeshMapping(
            target_submesh_index=0,
            target_submesh_name="target",
            source_submesh_indices=[0],
            target_material_slot_index=0,
        )
        options = StaticMeshReplacementOptions(
            transform=StaticReplacementTransform(alignment_mode="manual", scale_to_original_length=False),
            submesh_mappings=[mapping],
            edited_source_mesh=edited,
        )

        rebuilt, report = build_static_mesh_replacement(original_data, original, replacement, options)
        parsed = parse_pac(rebuilt, "rebuilt.pac")

        self.assertEqual(1, result.removed_face_count)
        self.assertFalse(report.errors)
        self.assertEqual(1, report.replacement_face_count)
        self.assertEqual(1, len(parsed.submeshes[0].faces))
        self.assertEqual(3, len(parsed.submeshes[0].vertices))

    def test_static_replacement_disabled_part_exports_runtime_safe_placeholder(self) -> None:
        original_data, original = _minimal_two_part_pac_original()
        replacement = _mesh(
            "two_part_source.obj",
            [
                SubMesh(
                    name="visible",
                    material="visible",
                    vertices=[(0.0, 0.0, 0.0), (1.5, 0.0, 0.0), (0.0, 1.5, 0.0)],
                    faces=[(0, 1, 2)],
                ),
                SubMesh(
                    name="disabled",
                    material="disabled",
                    vertices=[(5.0, 0.0, 0.0), (6.0, 0.0, 0.0), (5.0, 1.0, 0.0)],
                    faces=[(0, 1, 2)],
                ),
            ],
        )
        options = StaticMeshReplacementOptions(
            transform=StaticReplacementTransform(alignment_mode="manual", scale_to_original_length=False),
            submesh_mappings=[
                StaticSubmeshMapping(0, "target0", [0], 0),
                StaticSubmeshMapping(1, "target1", [1], 1),
            ],
            source_part_adjustments=[
                StaticSourcePartAdjustment(source_submesh_index=1, enabled=False),
            ],
        )

        rebuilt, report = build_static_mesh_replacement(original_data, original, replacement, options)
        parsed = parse_pac(rebuilt, "rebuilt.pac")

        self.assertFalse(report.errors)
        self.assertEqual(2, len(parsed.submeshes))
        self.assertEqual(3, len(parsed.submeshes[1].vertices))
        self.assertEqual(1, len(parsed.submeshes[1].faces))
        xs = [vertex[0] for vertex in parsed.submeshes[1].vertices]
        ys = [vertex[1] for vertex in parsed.submeshes[1].vertices]
        zs = [vertex[2] for vertex in parsed.submeshes[1].vertices]
        self.assertLess(max(xs) - min(xs), 0.001)
        self.assertLess(max(ys) - min(ys), 0.001)
        self.assertLess(max(zs) - min(zs), 0.001)

    def test_auto_flat_original_rolls_replacement_to_original_plane(self) -> None:
        original = _mesh(
            "flat_target.pac",
            [
                SubMesh(
                    name="target blade",
                    material="target blade",
                    vertices=[(0.0, 0.0, 0.0), (2.0, 0.0, 0.0), (0.0, 0.0, 1.0)],
                    faces=[(0, 1, 2)],
                )
            ],
        )
        replacement = _mesh(
            "upright_replacement.obj",
            [
                SubMesh(
                    name="replacement blade",
                    material="replacement blade",
                    vertices=[(0.0, 0.0, 0.0), (2.0, 0.0, 0.0), (0.0, 1.0, 0.0)],
                    faces=[(0, 1, 2)],
                )
            ],
        )
        mapping = StaticSubmeshMapping(
            target_submesh_index=0,
            target_submesh_name="target blade",
            source_submesh_indices=[0],
            target_material_slot_index=0,
        )

        preview = build_static_replacement_preview_mesh(
            original,
            replacement,
            StaticMeshReplacementOptions(
                transform=StaticReplacementTransform(alignment_mode="auto_flat_original", scale_to_original_length=False),
                submesh_mappings=[mapping],
            ),
        )

        first, _tip, width = preview.submeshes[0].vertices
        width_delta = (
            width[0] - first[0],
            width[1] - first[1],
            width[2] - first[2],
        )
        self.assertAlmostEqual(0.0, width_delta[1], places=6)
        self.assertGreater(abs(width_delta[2]), 0.9)

    def test_grid_flat_forces_replacement_to_preview_grid(self) -> None:
        original = _mesh(
            "upright_target.pac",
            [
                SubMesh(
                    name="target blade",
                    material="target blade",
                    vertices=[(0.0, 0.0, 0.0), (10.0, 0.0, 0.0), (0.0, 2.0, 0.0)],
                    faces=[(0, 1, 2)],
                )
            ],
        )
        replacement = _mesh(
            "upright_replacement.obj",
            [
                SubMesh(
                    name="replacement blade",
                    material="replacement blade",
                    vertices=[(0.0, 0.0, 0.0), (10.0, 0.0, 0.0), (0.0, 2.0, 0.0)],
                    faces=[(0, 1, 2)],
                )
            ],
        )
        mapping = StaticSubmeshMapping(
            target_submesh_index=0,
            target_submesh_name="target blade",
            source_submesh_indices=[0],
            target_material_slot_index=0,
        )

        preview = build_static_replacement_preview_mesh(
            original,
            replacement,
            StaticMeshReplacementOptions(
                transform=StaticReplacementTransform(alignment_mode="grid_flat", scale_to_original_length=False),
                submesh_mappings=[mapping],
            ),
        )

        vertices = preview.submeshes[0].vertices
        min_y = min(vertex[1] for vertex in vertices)
        y_span = max(vertex[1] for vertex in vertices) - min(vertex[1] for vertex in vertices)
        z_span = max(vertex[2] for vertex in vertices) - min(vertex[2] for vertex in vertices)
        self.assertAlmostEqual(0.0, min_y, places=6)
        self.assertLess(y_span, 1e-6)
        self.assertGreater(z_span, 1.9)

    def test_grid_flat_does_not_follow_upright_target_axis_off_grid(self) -> None:
        original = _mesh(
            "upright_target.pac",
            [
                SubMesh(
                    name="target blade",
                    material="target blade",
                    vertices=[(0.0, 0.0, 0.0), (0.0, 10.0, 0.0), (2.0, 0.0, 0.0)],
                    faces=[(0, 1, 2)],
                )
            ],
        )
        replacement = _mesh(
            "upright_replacement.obj",
            [
                SubMesh(
                    name="replacement blade",
                    material="replacement blade",
                    vertices=[(0.0, 0.0, 0.0), (10.0, 0.0, 0.0), (0.0, 2.0, 0.0)],
                    faces=[(0, 1, 2)],
                )
            ],
        )
        mapping = StaticSubmeshMapping(
            target_submesh_index=0,
            target_submesh_name="target blade",
            source_submesh_indices=[0],
            target_material_slot_index=0,
        )

        preview = build_static_replacement_preview_mesh(
            original,
            replacement,
            StaticMeshReplacementOptions(
                transform=StaticReplacementTransform(alignment_mode="grid_flat", scale_to_original_length=False),
                submesh_mappings=[mapping],
            ),
        )

        vertices = preview.submeshes[0].vertices
        min_y = min(vertex[1] for vertex in vertices)
        y_span = max(vertex[1] for vertex in vertices) - min(vertex[1] for vertex in vertices)
        z_span = max(vertex[2] for vertex in vertices) - min(vertex[2] for vertex in vertices)
        self.assertAlmostEqual(0.0, min_y, places=6)
        self.assertLess(y_span, 1e-6)
        self.assertGreater(z_span, 1.9)

    def test_grid_flat_projects_sloped_target_axis_to_grid(self) -> None:
        original = _mesh(
            "sloped_target.pac",
            [
                SubMesh(
                    name="target blade",
                    material="target blade",
                    vertices=[(0.0, 0.0, 0.0), (8.0, 6.0, 0.0), (0.0, 0.0, 2.0)],
                    faces=[(0, 1, 2)],
                )
            ],
        )
        replacement = _mesh(
            "upright_replacement.obj",
            [
                SubMesh(
                    name="replacement blade",
                    material="replacement blade",
                    vertices=[(0.0, 0.0, 0.0), (10.0, 0.0, 0.0), (0.0, 2.0, 0.0)],
                    faces=[(0, 1, 2)],
                )
            ],
        )
        mapping = StaticSubmeshMapping(
            target_submesh_index=0,
            target_submesh_name="target blade",
            source_submesh_indices=[0],
            target_material_slot_index=0,
        )

        preview = build_static_replacement_preview_mesh(
            original,
            replacement,
            StaticMeshReplacementOptions(
                transform=StaticReplacementTransform(alignment_mode="grid_flat", scale_to_original_length=False),
                submesh_mappings=[mapping],
            ),
        )

        vertices = preview.submeshes[0].vertices
        self.assertAlmostEqual(0.0, min(vertex[1] for vertex in vertices), places=6)
        self.assertLess(max(vertex[1] for vertex in vertices) - min(vertex[1] for vertex in vertices), 1e-6)

    def test_grid_flat_lowers_elevated_replacement_to_preview_grid(self) -> None:
        original = _mesh(
            "flat_target.pac",
            [
                SubMesh(
                    name="target blade",
                    material="target blade",
                    vertices=[(0.0, 0.0, 0.0), (10.0, 0.0, 0.0), (0.0, 2.0, 0.0)],
                    faces=[(0, 1, 2)],
                )
            ],
        )
        replacement = _mesh(
            "elevated_replacement.obj",
            [
                SubMesh(
                    name="replacement blade",
                    material="replacement blade",
                    vertices=[(0.0, 5.0, 0.0), (10.0, 5.0, 0.0), (0.0, 7.0, 0.0)],
                    faces=[(0, 1, 2)],
                )
            ],
        )
        mapping = StaticSubmeshMapping(
            target_submesh_index=0,
            target_submesh_name="target blade",
            source_submesh_indices=[0],
            target_material_slot_index=0,
        )

        preview = build_static_replacement_preview_mesh(
            original,
            replacement,
            StaticMeshReplacementOptions(
                transform=StaticReplacementTransform(alignment_mode="grid_flat", scale_to_original_length=False),
                submesh_mappings=[mapping],
            ),
        )

        vertices = preview.submeshes[0].vertices
        self.assertAlmostEqual(0.0, min(vertex[1] for vertex in vertices), places=6)
        self.assertLess(max(vertex[1] for vertex in vertices) - min(vertex[1] for vertex in vertices), 1e-6)

    def test_source_affine_for_grid_flat_includes_preview_grid_floor(self) -> None:
        original = _mesh(
            "flat_target.pac",
            [
                SubMesh(
                    name="target",
                    material="target",
                    vertices=[(0.0, 0.0, 0.0), (10.0, 0.0, 0.0), (0.0, 2.0, 0.0)],
                    faces=[(0, 1, 2)],
                )
            ],
        )
        replacement = _mesh(
            "raised_source.obj",
            [
                SubMesh(
                    name="source",
                    material="source",
                    vertices=[(0.0, 5.0, 0.0), (10.0, 5.0, 0.0), (0.0, 7.0, 0.0)],
                    faces=[(0, 1, 2)],
                )
            ],
        )
        transform = StaticReplacementTransform(alignment_mode="grid_flat", scale_to_original_length=False)
        affine = source_affine_for_transformed_preview(
            original,
            replacement,
            transform,
            0,
            global_transform_source_indices={0},
            alignment_basis_mesh=replacement,
        )

        self.assertIsNotNone(affine)
        assert affine is not None
        source = replacement.submeshes[0].vertices[0]
        displayed_y = affine[4] * source[0] + affine[5] * source[1] + affine[6] * source[2] + affine[7]
        self.assertAlmostEqual(0.0, displayed_y, places=6)

    def test_preview_allows_large_mapped_target_that_export_rejects(self) -> None:
        original = _mesh(
            "helmet.pac",
            [
                SubMesh(
                    name="helmet",
                    material="helmet",
                    vertices=[(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0)],
                    faces=[(0, 1, 2)],
                )
            ],
        )
        replacement = _mesh(
            "large.obj",
            [
                SubMesh(
                    name="large helmet",
                    material="large helmet",
                    vertices=[(float(index), 0.0, 0.0) for index in range(70_000)],
                    faces=[(0, 1, 2)],
                )
            ],
        )
        mapping = StaticSubmeshMapping(
            target_submesh_index=0,
            target_submesh_name="helmet",
            source_submesh_indices=[0],
            target_material_slot_index=0,
        )
        options = StaticMeshReplacementOptions(
            transform=StaticReplacementTransform(
                alignment_mode="manual",
                scale_to_original_length=False,
                offset_xyz=(1.0, 2.0, 3.0),
            ),
            submesh_mappings=[mapping],
        )

        preview = build_static_replacement_preview_mesh(original, replacement, options)

        self.assertEqual(len(preview.submeshes[0].vertices), 70_000)
        self.assertEqual(preview.submeshes[0].vertices[0], (1.0, 2.0, 3.0))
        with self.assertRaisesRegex(ValueError, "65,535"):
            _build_mapped_replacement_mesh(original, replacement, [mapping], options)

    def test_dense_output_plan_preserves_under_limit_parts_as_cloned_sections(self) -> None:
        original = _mesh(
            "target.pac",
            [
                SubMesh(
                    name="target",
                    material="target",
                    vertices=[(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0)],
                    faces=[(0, 1, 2)],
                )
            ],
        )
        replacement = _mesh(
            "dense.gltf",
            [_large_part(f"part_{index}", 22_000) for index in range(4)],
        )
        mapping = StaticSubmeshMapping(
            target_submesh_index=0,
            target_submesh_name="target",
            source_submesh_indices=[0, 1, 2, 3],
            target_material_slot_index=0,
        )
        options = StaticMeshReplacementOptions(submesh_mappings=[mapping])

        sections, warnings, errors = plan_static_output_draw_sections(original, replacement, [mapping], options)

        self.assertFalse(errors)
        self.assertTrue(warnings)
        self.assertEqual(2, len(sections))
        self.assertFalse(sections[0].is_cloned_section)
        self.assertTrue(sections[1].is_cloned_section)
        self.assertEqual([0, 1], sections[0].source_submesh_indices)
        self.assertEqual([2, 3], sections[1].source_submesh_indices)
        self.assertLessEqual(sections[0].vertex_count, 65_535)
        self.assertLessEqual(sections[1].vertex_count, 65_535)

    def test_dense_output_plan_blocks_single_oversized_source_part(self) -> None:
        original = _mesh(
            "target.pac",
            [
                SubMesh(
                    name="target",
                    material="target",
                    vertices=[(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0)],
                    faces=[(0, 1, 2)],
                )
            ],
        )
        replacement = _mesh("dense.gltf", [_large_part("too_big", 65_536)])
        mapping = StaticSubmeshMapping(
            target_submesh_index=0,
            target_submesh_name="target",
            source_submesh_indices=[0],
            target_material_slot_index=0,
        )

        _sections, _warnings, errors = plan_static_output_draw_sections(
            original,
            replacement,
            [mapping],
            StaticMeshReplacementOptions(submesh_mappings=[mapping]),
        )

        self.assertEqual(1, len(errors))
        self.assertIn("65,536 vertices", errors[0])
        self.assertIn("65,535", errors[0])

    def test_pac_dense_rebuild_clones_draw_section_descriptors(self) -> None:
        original_data, original = _minimal_pac_original()
        replacement = _mesh(
            "dense.gltf",
            [_large_part(f"part_{index}", 22_000) for index in range(4)],
        )
        mapping = StaticSubmeshMapping(
            target_submesh_index=0,
            target_submesh_name="target",
            source_submesh_indices=[0, 1, 2, 3],
            target_material_slot_index=0,
        )
        options = StaticMeshReplacementOptions(
            transform=StaticReplacementTransform(alignment_mode="manual", scale_to_original_length=False),
            submesh_mappings=[mapping],
        )

        rebuilt, report = build_static_mesh_replacement(original_data, original, replacement, options)
        parsed = parse_pac(rebuilt, "rebuilt.pac")

        self.assertEqual(2, len(report.output_draw_sections))
        self.assertEqual(1, sum(1 for section in report.output_draw_sections if section.is_cloned_section))
        self.assertEqual(2, len(parsed.submeshes))
        self.assertTrue(all(len(submesh.vertices) <= 65_535 for submesh in parsed.submeshes))
        self.assertEqual(88_000, sum(len(submesh.vertices) for submesh in parsed.submeshes))

    def test_complete_source_owned_blocks_more_source_materials_than_runtime_slots(self) -> None:
        original_data, original = _minimal_pac_original()
        replacement = _mesh(
            "wolf_sword.gltf",
            [
                SubMesh(
                    name="Broken_sword_Gem_inside_0",
                    material="Gem_inside",
                    vertices=[(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0)],
                    faces=[(0, 1, 2)],
                ),
                SubMesh(
                    name="Broken_sword_Gem_outside_0",
                    material="Gem_outside",
                    vertices=[(0.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0)],
                    faces=[(0, 1, 2)],
                ),
            ],
        )
        mapping = StaticSubmeshMapping(
            target_submesh_index=0,
            target_submesh_name="CD_PHM_02_Handle_0015",
            source_submesh_indices=[0, 1],
            target_material_slot_index=0,
        )
        options = StaticMeshReplacementOptions(
            transform=StaticReplacementTransform(alignment_mode="manual", scale_to_original_length=False),
            submesh_mappings=[mapping],
            complete_external_swap=True,
            complete_swap_atlas_mode="block",
        )

        with self.assertRaisesRegex(ValueError, "PAC runtime ABI has only 1 safe draw slot"):
            build_static_mesh_replacement(original_data, original, replacement, options)

    def test_complete_source_owned_auto_atlas_merges_overflow_material_groups(self) -> None:
        original_data, original = _minimal_pac_original()
        replacement = _mesh(
            "wolf_sword.gltf",
            [
                SubMesh(
                    name="Broken_sword_Gem_inside_0",
                    material="Gem_inside",
                    vertices=[(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0)],
                    uvs=[(0.0, 0.0), (1.0, 0.0), (0.0, 1.0)],
                    faces=[(0, 1, 2)],
                ),
                SubMesh(
                    name="Broken_sword_Gem_outside_0",
                    material="Gem_outside",
                    vertices=[(0.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0)],
                    uvs=[(0.0, 0.0), (1.0, 0.0), (0.0, 1.0)],
                    faces=[(0, 1, 2)],
                ),
            ],
        )
        mapping = StaticSubmeshMapping(
            target_submesh_index=0,
            target_submesh_name="CD_PHM_02_Handle_0015",
            source_submesh_indices=[0, 1],
            target_material_slot_index=0,
        )
        options = StaticMeshReplacementOptions(
            transform=StaticReplacementTransform(alignment_mode="manual", scale_to_original_length=False),
            submesh_mappings=[mapping],
            complete_external_swap=True,
        )

        rebuilt, report = build_static_mesh_replacement(original_data, original, replacement, options)
        parsed = parse_pac(rebuilt, "rebuilt.pac")

        self.assertFalse(report.errors)
        self.assertEqual(1, len(report.output_draw_sections))
        section = report.output_draw_sections[0]
        self.assertEqual(("Gem_inside", "Gem_outside"), section.atlas_source_material_names)
        self.assertEqual(2, len(section.atlas_rects))
        self.assertEqual(1, len(parsed.submeshes))
        self.assertEqual(6, len(parsed.submeshes[0].uvs))
        first_group_u = [uv[0] for uv in parsed.submeshes[0].uvs[:3]]
        second_group_u = [uv[0] for uv in parsed.submeshes[0].uvs[3:]]
        self.assertLessEqual(max(first_group_u), 0.5)
        self.assertGreaterEqual(min(second_group_u), 0.5)

    def test_complete_source_owned_auto_atlas_handles_two_slot_three_material_sword_shape(self) -> None:
        original = _mesh(
            "cd_phm_02_sword_0042.pac",
            [
                SubMesh(name="slot0", material="CD_PHM_02_Sword_0042", vertices=[(0.0, 0.0, 0.0)], faces=[]),
                SubMesh(name="slot1", material="cd_phm_02_sword_handle_0042", vertices=[(0.0, 0.0, 0.0)], faces=[]),
            ],
        )
        replacement = _mesh(
            "wolf_sword.gltf",
            [
                SubMesh(name="blade", material="lambert1", vertices=[(0.0, 0.0, 0.0)], faces=[]),
                SubMesh(name="gem_outside", material="Gem_outside", vertices=[(0.0, 0.0, 0.0)], faces=[]),
                SubMesh(name="gem_inside", material="Gem_inside", vertices=[(0.0, 0.0, 0.0)], faces=[]),
            ],
        )

        sections, warnings, errors = plan_static_output_draw_sections(
            original,
            replacement,
            [
                StaticSubmeshMapping(0, "CD_PHM_02_Sword_0042", [1], 0),
                StaticSubmeshMapping(1, "cd_phm_02_sword_handle_0042", [0, 2], 1),
            ],
            StaticMeshReplacementOptions(complete_external_swap=True),
        )

        self.assertFalse(errors)
        self.assertEqual(2, len(sections))
        self.assertEqual([1], sections[0].source_submesh_indices)
        self.assertEqual([0, 2], sections[1].source_submesh_indices)
        self.assertEqual(("lambert1", "Gem_inside"), sections[1].atlas_source_material_names)
        self.assertTrue(any("atlas/bake lambert1, Gem_inside" in warning for warning in warnings))

    def test_complete_source_owned_preserves_pac_section0_and_descriptor_names(self) -> None:
        original_data, original = _minimal_pac_original()
        replacement = _mesh(
            "wolf_sword.gltf",
            [
                SubMesh(
                    name="Broken_sword_Gem_inside_0",
                    material="Gem_inside",
                    vertices=[(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0)],
                    faces=[(0, 1, 2)],
                ),
            ],
        )
        mapping = StaticSubmeshMapping(
            target_submesh_index=0,
            target_submesh_name="runtime_target",
            source_submesh_indices=[0],
            target_material_slot_index=0,
        )

        rebuilt, report = build_static_mesh_replacement(
            original_data,
            original,
            replacement,
            StaticMeshReplacementOptions(
                transform=StaticReplacementTransform(alignment_mode="manual", scale_to_original_length=False),
                submesh_mappings=[mapping],
                complete_external_swap=True,
                source_owned_target_names=["runtime_target"],
            ),
        )
        original_sec0 = next(section for section in _parse_par_sections(original_data) if section["index"] == 0)
        rebuilt_sec0 = next(section for section in _parse_par_sections(rebuilt) if section["index"] == 0)
        parsed = parse_pac(rebuilt, "rebuilt.pac")

        self.assertEqual(original_sec0["size"], rebuilt_sec0["size"])
        self.assertEqual("target", parsed.submeshes[0].name)
        self.assertEqual("target", parsed.submeshes[0].material)
        self.assertEqual("runtime_target", report.output_draw_sections[0].target_submesh_name)
        self.assertTrue(report.output_draw_sections[0].section0_preserved)

    def test_complete_source_owned_preserves_original_runtime_slot_placeholders(self) -> None:
        original = _mesh(
            "target.pac",
            [
                SubMesh(name="original_handle", material="CD_Handle", vertices=[(0.0, 0.0, 0.0)], faces=[]),
                SubMesh(name="original_guard", material="CD_Guard", vertices=[(0.0, 0.0, 0.0)], faces=[]),
                SubMesh(name="original_blade", material="CD_Blade", vertices=[(0.0, 0.0, 0.0)], faces=[]),
                SubMesh(name="original_acc", material="CD_Acc", vertices=[(0.0, 0.0, 0.0)], faces=[]),
            ],
        )
        replacement = _mesh(
            "wolf_sword.gltf",
            [
                SubMesh(name="gem_inside", material="Gem_inside", vertices=[(0.0, 0.0, 0.0)], faces=[]),
                SubMesh(name="gem_outside", material="Gem_outside", vertices=[(0.0, 0.0, 0.0)], faces=[]),
                SubMesh(name="blade", material="lambert1", vertices=[(0.0, 0.0, 0.0)], faces=[]),
            ],
        )
        sections, warnings, errors = plan_static_output_draw_sections(
            original,
            replacement,
            [
                StaticSubmeshMapping(0, "CD_Handle", [0, 1], 0),
                StaticSubmeshMapping(2, "CD_Blade", [2], 2),
            ],
            StaticMeshReplacementOptions(
                complete_external_swap=True,
                source_owned_target_names=["runtime_handle_a", "runtime_handle_b", "runtime_blade", "runtime_acc"],
            ),
        )

        self.assertFalse(errors)
        self.assertTrue(any("runtime slot placeholder" in warning for warning in warnings))
        self.assertEqual(
            ["runtime_handle_a", "runtime_handle_b", "runtime_blade", "runtime_acc"],
            [section.target_submesh_name for section in sections],
        )
        self.assertEqual([False, False, False, False], [section.is_cloned_section for section in sections])
        self.assertEqual([0, 1, 2, 3], [section.target_submesh_index for section in sections])
        self.assertEqual(["original_handle", "original_guard", "original_blade", "original_acc"], [section.runtime_slot_name for section in sections])

    def test_complete_source_owned_empty_runtime_placeholder_emits_degenerate_draw(self) -> None:
        original = _mesh(
            "target.pac",
            [
                SubMesh(
                    name="original_handle",
                    material="CD_Handle",
                    vertices=[(3.0, 4.0, 5.0), (4.0, 4.0, 5.0), (3.0, 5.0, 5.0)],
                    faces=[(0, 1, 2)],
                    bone_weights=[(), (), ()],
                )
            ],
        )
        replacement = _mesh("wolf_sword.gltf", [])
        mapped = _build_mapped_replacement_mesh(
            original,
            replacement,
            [],
            StaticMeshReplacementOptions(complete_external_swap=True),
            output_draw_sections=[
                StaticOutputDrawSection(0, 0, "runtime_handle", [], 0, 0, "CD_Handle", 0, False)
            ],
        )

        self.assertEqual(1, len(mapped.submeshes))
        placeholder = mapped.submeshes[0]
        self.assertEqual("original_handle", placeholder.name)
        self.assertEqual("CD_Handle", placeholder.material)
        self.assertEqual(3, len(placeholder.vertices))
        self.assertEqual([(0, 1, 2)], placeholder.faces)
        self.assertEqual([0, 0, 0], placeholder.source_vertex_map)
        self.assertGreater(placeholder.vertices[1][0], placeholder.vertices[0][0])

    def test_complete_source_owned_uses_runtime_sidecar_slot_names_when_available(self) -> None:
        original_data, original = _minimal_pac_original()
        replacement = _mesh(
            "wolf_sword.gltf",
            [
                SubMesh(
                    name="Broken_sword_Gem_inside_0",
                    material="Gem_inside",
                    vertices=[(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0)],
                    faces=[(0, 1, 2)],
                ),
                SubMesh(
                    name="Broken_sword_Gem_outside_0",
                    material="Gem_outside",
                    vertices=[(0.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0)],
                    faces=[(0, 1, 2)],
                ),
            ],
        )
        mapping = StaticSubmeshMapping(
            target_submesh_index=0,
            target_submesh_name="CD_PHM_02_Handle_0015",
            source_submesh_indices=[0, 1],
            target_material_slot_index=0,
        )
        options = StaticMeshReplacementOptions(
            transform=StaticReplacementTransform(alignment_mode="manual", scale_to_original_length=False),
            submesh_mappings=[mapping],
            complete_external_swap=True,
            complete_swap_atlas_mode="block",
            source_owned_target_names=[
                "cd_phm_02_sword_handle_0015_03",
                "cd_phm_02_sword_handle_0015",
            ],
        )

        with self.assertRaisesRegex(ValueError, "PAC runtime ABI has only 1 safe draw slot"):
            build_static_mesh_replacement(original_data, original, replacement, options)

    def test_preview_decimation_keeps_transform_responsive(self) -> None:
        original = _mesh(
            "target.pac",
            [
                SubMesh(
                    name="target",
                    material="target",
                    vertices=[(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0)],
                    faces=[(0, 1, 2)],
                )
            ],
        )
        vertices = [(float(index), 0.0, 0.0) for index in range(270)]
        faces = [(index * 3, index * 3 + 1, index * 3 + 2) for index in range(90)]
        replacement = _mesh(
            "dense.obj",
            [
                SubMesh(
                    name="dense",
                    material="dense",
                    vertices=vertices,
                    faces=faces,
                )
            ],
        )
        options = StaticMeshReplacementOptions(
            transform=StaticReplacementTransform(
                alignment_mode="manual",
                scale_to_original_length=False,
                offset_xyz=(0.5, 0.0, 0.0),
            ),
            submesh_mappings=[
                StaticSubmeshMapping(
                    target_submesh_index=0,
                    target_submesh_name="target",
                    source_submesh_indices=[0],
                    target_material_slot_index=0,
                )
            ],
        )

        preview = build_static_replacement_preview_mesh(
            original,
            replacement,
            options,
            max_source_faces_per_submesh=10,
        )

        self.assertLessEqual(len(preview.submeshes[0].faces), 10)
        self.assertLessEqual(len(preview.submeshes[0].vertices), 30)
        self.assertEqual(preview.submeshes[0].vertices[0], (0.5, 0.0, 0.0))

    def test_texture_uv_transform_applies_to_preview_and_export_mesh(self) -> None:
        original = _mesh(
            "target.pac",
            [
                SubMesh(
                    name="target",
                    material="target",
                    vertices=[(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0)],
                    faces=[(0, 1, 2)],
                )
            ],
        )
        replacement = _mesh(
            "replacement.obj",
            [
                SubMesh(
                    name="helmet_geo",
                    material="UV_Samurai_Helmet",
                    vertices=[(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0)],
                    uvs=[(0.0, 0.0), (1.0, 0.5), (0.25, 1.0)],
                    faces=[(0, 1, 2)],
                )
            ],
        )
        mapping = StaticSubmeshMapping(
            target_submesh_index=0,
            target_submesh_name="target",
            source_submesh_indices=[0],
            target_material_slot_index=0,
        )
        options = StaticMeshReplacementOptions(
            transform=StaticReplacementTransform(
                alignment_mode="manual",
                scale_to_original_length=False,
            ),
            submesh_mappings=[mapping],
            texture_uv_transforms=[
                StaticTextureUvTransform(
                    source_material_name="UV_Samurai_Helmet",
                    rotate_degrees=90,
                    flip_u=True,
                    offset_uv=(0.1, -0.2),
                )
            ],
        )

        preview = build_static_replacement_preview_mesh(original, replacement, options)
        exported = _build_mapped_replacement_mesh(original, replacement, [mapping], options)

        self.assertEqual(preview.submeshes[0].uvs, exported.submeshes[0].uvs)
        self.assertAlmostEqual(preview.submeshes[0].uvs[0][0], 1.1)
        self.assertAlmostEqual(preview.submeshes[0].uvs[0][1], 0.8)
        self.assertAlmostEqual(preview.submeshes[0].uvs[1][0], 0.6)
        self.assertAlmostEqual(preview.submeshes[0].uvs[1][1], -0.2)

    def test_edited_source_mesh_override_feeds_preview(self) -> None:
        original = _mesh(
            "target.pac",
            [
                SubMesh(
                    name="target",
                    material="target",
                    vertices=[(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0)],
                    faces=[(0, 1, 2)],
                )
            ],
        )
        replacement = _mesh(
            "replacement.obj",
            [
                SubMesh(
                    name="source",
                    material="source",
                    vertices=[(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0)],
                    faces=[(0, 1, 2)],
                )
            ],
        )
        edited = _mesh(
            "replacement.obj",
            [
                SubMesh(
                    name="source",
                    material="source",
                    vertices=[(0.25, 0.0, 0.0), (1.25, 0.0, 0.0), (0.25, 1.0, 0.0)],
                    faces=[(0, 1, 2)],
                )
            ],
        )
        mapping = StaticSubmeshMapping(
            target_submesh_index=0,
            target_submesh_name="target",
            source_submesh_indices=[0],
            target_material_slot_index=0,
        )

        preview = build_static_replacement_preview_mesh(
            original,
            replacement,
            StaticMeshReplacementOptions(
                transform=StaticReplacementTransform(alignment_mode="manual", scale_to_original_length=False),
                submesh_mappings=[mapping],
                edited_source_mesh=edited,
            ),
        )

        self.assertEqual((0.25, 0.0, 0.0), preview.submeshes[0].vertices[0])

    def test_unmapped_appended_source_does_not_change_mapped_alignment(self) -> None:
        original = _mesh(
            "target.pac",
            [
                SubMesh(
                    name="helmet",
                    material="helmet",
                    vertices=[(0.0, 0.0, 0.0), (0.0, 2.0, 0.0), (0.0, 0.0, 1.0)],
                    faces=[(0, 1, 2)],
                )
            ],
        )
        mapped_source = SubMesh(
            name="helmet",
            material="helmet",
            vertices=[(0.0, 0.0, 0.0), (0.0, 2.0, 0.0), (0.0, 0.0, 1.0)],
            faces=[(0, 1, 2)],
        )
        far_unmapped_attachment = SubMesh(
            name="horns",
            material="horns",
            vertices=[(100.0, 0.0, 0.0), (101.0, 0.0, 0.0), (100.0, 1.0, 0.0)],
            faces=[(0, 1, 2)],
        )
        mapping = StaticSubmeshMapping(
            target_submesh_index=0,
            target_submesh_name="helmet",
            source_submesh_indices=[0],
            target_material_slot_index=0,
        )
        options = StaticMeshReplacementOptions(
            transform=StaticReplacementTransform(alignment_mode="auto_fit_original", scale_to_original_length=True),
            submesh_mappings=[mapping],
        )
        replacement_without_append = _mesh("replacement.obj", [mapped_source])
        replacement_with_append = _mesh(
            "replacement.obj",
            [
                SubMesh(**mapped_source.__dict__),
                far_unmapped_attachment,
            ],
        )

        preview_without_append = build_static_replacement_preview_mesh(original, replacement_without_append, options)
        preview_with_append = build_static_replacement_preview_mesh(original, replacement_with_append, options)

        self.assertEqual(preview_without_append.submeshes[0].vertices, preview_with_append.submeshes[0].vertices)

    def test_mapped_appended_source_can_be_exempt_from_global_alignment(self) -> None:
        original = _mesh(
            "target.pac",
            [
                SubMesh(
                    name="helmet",
                    material="helmet",
                    vertices=[(0.0, 0.0, 0.0), (0.0, 2.0, 0.0), (0.0, 0.0, 1.0)],
                    faces=[(0, 1, 2)],
                )
            ],
        )
        mapped_source = SubMesh(
            name="helmet",
            material="helmet",
            vertices=[(0.0, 0.0, 0.0), (0.0, 2.0, 0.0), (0.0, 0.0, 1.0)],
            faces=[(0, 1, 2)],
        )
        far_attachment = SubMesh(
            name="horns",
            material="horns",
            vertices=[(100.0, 0.0, 0.0), (101.0, 0.0, 0.0), (100.0, 1.0, 0.0)],
            faces=[(0, 1, 2)],
        )
        baseline_mapping = StaticSubmeshMapping(
            target_submesh_index=0,
            target_submesh_name="helmet",
            source_submesh_indices=[0],
            target_material_slot_index=0,
        )
        appended_mapping = StaticSubmeshMapping(
            target_submesh_index=0,
            target_submesh_name="helmet",
            source_submesh_indices=[0, 1],
            target_material_slot_index=0,
        )
        transform = StaticReplacementTransform(alignment_mode="auto_fit_original", scale_to_original_length=True)
        baseline = build_static_replacement_preview_mesh(
            original,
            _mesh("replacement.obj", [mapped_source]),
            StaticMeshReplacementOptions(transform=transform, submesh_mappings=[baseline_mapping]),
        )
        with_appended = build_static_replacement_preview_mesh(
            original,
            _mesh("replacement.obj", [SubMesh(**mapped_source.__dict__), far_attachment]),
            StaticMeshReplacementOptions(
                transform=transform,
                submesh_mappings=[appended_mapping],
                global_transform_exempt_source_indices=[1],
            ),
        )

        self.assertEqual(baseline.submeshes[0].vertices, with_appended.submeshes[0].vertices[:3])
        self.assertEqual(6, len(with_appended.submeshes[0].vertices))

    def test_auto_alignment_uses_projected_blade_frame_to_remove_twist(self) -> None:
        original = _mesh(
            "original_sword.pac",
            [
                SubMesh(
                    name="blade",
                    material="blade",
                    vertices=[
                        (0.0, -0.5, 0.0),
                        (0.0, 0.5, 0.0),
                        (10.0, -0.5, 0.0),
                        (10.0, 0.5, 0.0),
                    ],
                    faces=[(0, 1, 2), (1, 3, 2)],
                )
            ],
        )
        replacement = _mesh(
            "replacement_sword.obj",
            [
                SubMesh(
                    name="blade",
                    material="blade",
                    vertices=[
                        (-0.5, -0.5, 0.0),
                        (0.5, 0.5, 0.0),
                        (-0.5, -0.5, 10.0),
                        (0.5, 0.5, 10.0),
                    ],
                    faces=[(0, 1, 2), (1, 3, 2)],
                )
            ],
        )
        options = StaticMeshReplacementOptions(
            transform=StaticReplacementTransform(
                alignment_mode="auto_fit_original",
                scale_to_original_length=True,
            ),
            submesh_mappings=[
                StaticSubmeshMapping(
                    target_submesh_index=0,
                    target_submesh_name="blade",
                    source_submesh_indices=[0],
                    target_material_slot_index=0,
                )
            ],
        )

        preview = build_static_replacement_preview_mesh(original, replacement, options)
        vertices = preview.submeshes[0].vertices
        x_span = max(vertex[0] for vertex in vertices) - min(vertex[0] for vertex in vertices)
        y_span = max(vertex[1] for vertex in vertices) - min(vertex[1] for vertex in vertices)
        z_span = max(vertex[2] for vertex in vertices) - min(vertex[2] for vertex in vertices)

        self.assertAlmostEqual(10.0, x_span, places=6)
        self.assertGreater(y_span, 1.0)
        self.assertLess(z_span, 1e-6)

    def test_source_part_adjustment_does_not_recompute_auto_alignment_basis(self) -> None:
        original = _mesh(
            "target.pac",
            [
                SubMesh(
                    name="target",
                    material="target",
                    vertices=[(0.0, 0.0, 0.0), (0.0, 10.0, 0.0), (0.2, 0.0, 0.0)],
                    faces=[(0, 1, 2)],
                )
            ],
        )
        main_source = SubMesh(
            name="main",
            material="main",
            vertices=[(0.0, 0.0, 0.0), (0.0, 2.0, 0.0), (0.1, 0.0, 0.0)],
            faces=[(0, 1, 2)],
        )
        adjusted_source = SubMesh(
            name="attachment",
            material="attachment",
            vertices=[(0.0, 0.0, 0.0), (0.0, 0.2, 0.0), (0.1, 0.0, 0.0)],
            faces=[(0, 1, 2)],
        )
        mapping = StaticSubmeshMapping(
            target_submesh_index=0,
            target_submesh_name="target",
            source_submesh_indices=[0, 1],
            target_material_slot_index=0,
        )
        transform = StaticReplacementTransform(alignment_mode="auto_fit_original", scale_to_original_length=True)
        baseline = build_static_replacement_preview_mesh(
            original,
            _mesh("replacement.obj", [main_source, adjusted_source]),
            StaticMeshReplacementOptions(transform=transform, submesh_mappings=[mapping]),
        )
        adjusted = build_static_replacement_preview_mesh(
            original,
            _mesh("replacement.obj", [SubMesh(**main_source.__dict__), SubMesh(**adjusted_source.__dict__)]),
            StaticMeshReplacementOptions(
                transform=transform,
                submesh_mappings=[mapping],
                source_part_adjustments=[
                    StaticSourcePartAdjustment(
                        source_submesh_index=1,
                        offset_xyz=(100.0, 0.0, 0.0),
                        rotate_xyz_degrees=(0.0, 0.0, 90.0),
                    )
                ],
            ),
        )

        self.assertEqual(baseline.submeshes[0].vertices[:3], adjusted.submeshes[0].vertices[:3])

    def test_preview_decimation_keeps_source_part_adjustment_pivot_stable(self) -> None:
        original = _mesh(
            "target.pac",
            [
                SubMesh(
                    name="target",
                    material="target",
                    vertices=[(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0)],
                    faces=[(0, 1, 2)],
                )
            ],
        )
        attachment = SubMesh(
            name="horn",
            material="horn",
            vertices=[
                (0.0, 0.0, 0.0),
                (1.0, 0.0, 0.0),
                (0.0, 1.0, 0.0),
                (100.0, 0.0, 0.0),
                (101.0, 0.0, 0.0),
                (100.0, 1.0, 0.0),
            ],
            faces=[(0, 1, 2), (3, 4, 5)],
        )
        mapping = StaticSubmeshMapping(
            target_submesh_index=0,
            target_submesh_name="target",
            source_submesh_indices=[0],
            target_material_slot_index=0,
        )
        options = StaticMeshReplacementOptions(
            transform=StaticReplacementTransform(alignment_mode="manual", scale_to_original_length=False),
            submesh_mappings=[mapping],
            source_part_adjustments=[
                StaticSourcePartAdjustment(
                    source_submesh_index=0,
                    rotate_xyz_degrees=(0.0, 0.0, 180.0),
                )
            ],
            global_transform_exempt_source_indices=[0],
        )

        full_preview = build_static_replacement_preview_mesh(original, _mesh("horn.obj", [attachment]), options)
        decimated_preview = build_static_replacement_preview_mesh(
            original,
            _mesh("horn.obj", [attachment]),
            options,
            max_source_faces_per_submesh=1,
        )

        self.assertEqual(full_preview.submeshes[0].vertices[:3], decimated_preview.submeshes[0].vertices[:3])

    def test_independent_output_part_previews_without_target_mapping(self) -> None:
        original = _mesh(
            "helmet.pac",
            [
                SubMesh(
                    name="helmet",
                    material="helmet",
                    vertices=[(0.0, 0.0, 0.0), (0.0, 2.0, 0.0), (0.0, 0.0, 1.0)],
                    faces=[(0, 1, 2)],
                )
            ],
        )
        helmet_source = SubMesh(
            name="helmet",
            material="helmet",
            vertices=[(0.0, 0.0, 0.0), (0.0, 2.0, 0.0), (0.0, 0.0, 1.0)],
            faces=[(0, 1, 2)],
        )
        horns_source = SubMesh(
            name="horns",
            material="horns_source",
            vertices=[(10.0, 0.0, 0.0), (11.0, 0.0, 0.0), (10.0, 1.0, 0.0)],
            uvs=[(0.0, 0.0), (1.0, 0.0), (0.0, 1.0)],
            faces=[(0, 1, 2)],
        )
        replacement = _mesh("replacement.obj", [helmet_source, horns_source])
        mapping = StaticSubmeshMapping(
            target_submesh_index=0,
            target_submesh_name="helmet",
            source_submesh_indices=[0],
            target_material_slot_index=0,
        )
        options = StaticMeshReplacementOptions(
            transform=StaticReplacementTransform(alignment_mode="auto_fit_original", scale_to_original_length=True),
            submesh_mappings=[mapping],
            independent_output_parts=[
                StaticIndependentPart(
                    source_submesh_index=1,
                    label="horns attachment",
                    material_name="horns_custom",
                )
            ],
        )

        preview = build_static_replacement_preview_mesh(original, replacement, options)
        report = analyze_static_replacement(original, replacement, options)

        self.assertEqual(2, len(preview.submeshes))
        self.assertEqual("horns attachment", preview.submeshes[1].name)
        self.assertEqual("horns_custom", preview.submeshes[1].material)
        self.assertEqual([(10.0, 0.0, 0.0), (11.0, 0.0, 0.0), (10.0, 1.0, 0.0)], preview.submeshes[1].vertices)
        self.assertFalse(any("not used by mapping" in warning for warning in report.warnings))

    def test_final_build_blocks_independent_parts_until_draw_section_cloning_exists(self) -> None:
        original = _mesh(
            "helmet.pac",
            [
                SubMesh(
                    name="helmet",
                    material="helmet",
                    vertices=[(0.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0)],
                    faces=[(0, 1, 2)],
                )
            ],
        )
        replacement = _mesh(
            "replacement.obj",
            [
                SubMesh(
                    name="helmet",
                    material="helmet",
                    vertices=[(0.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0)],
                    faces=[(0, 1, 2)],
                ),
                SubMesh(
                    name="horns",
                    material="horns",
                    vertices=[(1.0, 0.0, 0.0), (2.0, 0.0, 0.0), (1.0, 1.0, 0.0)],
                    faces=[(0, 1, 2)],
                ),
            ],
        )
        options = StaticMeshReplacementOptions(
            transform=StaticReplacementTransform(alignment_mode="manual", scale_to_original_length=False),
            submesh_mappings=[
                StaticSubmeshMapping(
                    target_submesh_index=0,
                    target_submesh_name="helmet",
                    source_submesh_indices=[0],
                    target_material_slot_index=0,
                )
            ],
            independent_output_parts=[StaticIndependentPart(source_submesh_index=1, label="horns")],
        )

        with self.assertRaisesRegex(ValueError, "Independent added mesh parts cannot be written"):
            build_static_mesh_replacement(b"not a real par", original, replacement, options)


if __name__ == "__main__":
    unittest.main()
