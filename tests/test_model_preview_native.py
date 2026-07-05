from __future__ import annotations

import json
import os
from pathlib import Path
import struct
import tempfile
import unittest
from unittest.mock import patch

from PySide6.QtCore import QUrl

from cdmw.models import (
    HkxPhysicsOverlayBone,
    HkxPhysicsOverlayData,
    ModelPreviewData,
    ModelPreviewMesh,
    ModelPreviewRenderSettings,
    PreparedModelPreviewBatch,
    PreparedModelPreviewData,
    PreviewMaterialParameterInput,
    PreviewMaterialTextureInput,
)
from cdmw.rendering.material_combiner import (
    MaterialPreviewCombinerSettings,
    _decode_mode_for_input,
    combine_preview_material,
    decode_material_sample,
)
from cdmw.rendering.native_preview_package import (
    _input_texture_kind,
    _skeleton_overlay_metadata,
    build_native_preview_payloads,
    write_isolated_d3d11_preview_package,
)
from cdmw.ui.model_preview_native import (
    ARCHIVE_MODEL_RENDERER_D3D11,
    ARCHIVE_MODEL_RENDERER_DEFAULT,
    normalize_archive_model_renderer_backend,
)
from cdmw.ui.widgets import NativePreviewPanel


def _vertex(
    x: float,
    y: float,
    z: float,
    *,
    color: tuple[float, float, float] = (0.25, 0.50, 0.75),
    uv: tuple[float, float] = (0.0, 0.0),
) -> bytes:
    return struct.pack(
        "<23f",
        x,
        y,
        z,
        0.0,
        0.0,
        1.0,
        color[0],
        color[1],
        color[2],
        uv[0],
        uv[1],
        1.0,
        0.0,
        0.0,
        0.0,
        1.0,
        0.0,
        0.0,
        0.0,
        1.0,
        1.0,
        0.0,
        0.0,
    )


class NativePreviewPayloadTests(unittest.TestCase):
    def test_direct_preview_identity_sparse_source_ids_use_native_sidecars(self) -> None:
        from cdmw.modding import mesh_native_core

        sidecar_paths: list[Path] = []

        def _fake_native_job(binary: object, command: str, payload: dict[str, object], **_kwargs: object) -> dict[str, object]:
            self.assertEqual("preview-identity-json", command)
            self.assertNotIn("source_vertex_indices", payload)
            self.assertNotIn("source_face_indices", payload)
            vertex_descriptor = payload["source_vertex_indices_binary"]
            face_descriptor = payload["source_face_indices_binary"]
            vertex_path = Path(str(vertex_descriptor["path"]))  # type: ignore[index]
            face_path = Path(str(face_descriptor["path"]))  # type: ignore[index]
            sidecar_paths.extend((vertex_path, face_path))
            self.assertEqual((10, 12, 11), struct.unpack("<3i", vertex_path.read_bytes()))
            self.assertEqual((20,), struct.unpack("<i", face_path.read_bytes()))
            Path(str(payload["output_path"])).write_bytes(b"\0" * (3 * 12))
            return {"status": "ok", "binary": str(binary)}

        with tempfile.TemporaryDirectory() as temp_dir:
            with patch("cdmw.modding.mesh_native_core.find_native_mesh_core_binary", return_value=Path("mesh-core.exe")):
                with patch("cdmw.modding.mesh_native_core._run_native_mesh_core_job", side_effect=_fake_native_job):
                    report = mesh_native_core.write_native_preview_identity_blob(
                        Path(temp_dir) / "identity.bin",
                        source_submesh_index=5,
                        vertex_count=3,
                        source_vertex_indices=(10, 12, 11),
                        source_face_indices=(20,),
                    )

        self.assertEqual("ok", report["status"])  # type: ignore[index]
        self.assertTrue(sidecar_paths)
        self.assertTrue(all(not path.exists() for path in sidecar_paths))

    def test_native_vertex_blob_forwards_source_ranges_without_python_lists(self) -> None:
        from cdmw.rendering.model_preview_prepare import _build_vertex_blob_native

        model = ModelPreviewData(
            meshes=[
                ModelPreviewMesh(
                    positions=[(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0)],
                    normals=[(0.0, 0.0, 1.0)] * 3,
                    texture_coordinates=[(0.0, 0.0), (1.0, 0.0), (0.0, 1.0)],
                    indices=[0, 1, 2],
                    source_submesh_index=7,
                    source_vertex_range_start=0,
                    source_vertex_range_count=3,
                    source_face_range_start=0,
                    source_face_range_count=1,
                )
            ]
        )

        def _fake_writer(output_path: object, *, meshes: object, identity_output_path: object = None, **_kwargs: object) -> dict[str, object]:
            payload = tuple(meshes)[0]  # type: ignore[arg-type]
            self.assertEqual(0, payload["source_vertex_start"])
            self.assertEqual(3, payload["source_vertex_count"])
            self.assertEqual(0, payload["source_face_start"])
            self.assertEqual(1, payload["source_face_count"])
            self.assertNotIn("source_vertex_indices", payload)
            self.assertNotIn("source_face_indices", payload)
            Path(str(output_path)).write_bytes(b"\0" * (3 * 23 * 4))
            if identity_output_path is not None:
                Path(str(identity_output_path)).write_bytes(b"\0" * (3 * 12))
            return {
                "status": "ok",
                "operation": "preview_geometry",
                "vertex_count": 3,
                "geometry_size": 3 * 23 * 4,
                "batches": [
                    {
                        "mesh_index": 0,
                        "first_vertex": 0,
                        "vertex_count": 3,
                        "identity_offset": 0,
                        "identity_size": 3 * 12,
                        "source_vertex_start": 0,
                        "source_vertex_count": 3,
                        "source_face_start": 0,
                        "source_face_count": 1,
                    }
                ],
            }

        with patch("cdmw.modding.mesh_native_core.write_native_preview_geometry_blob", side_effect=_fake_writer):
            result = _build_vertex_blob_native(model)

        self.assertIsNotNone(result)
        _blob, vertex_count, batches = result  # type: ignore[misc]
        self.assertEqual(3, vertex_count)
        self.assertEqual(0, batches[0].source_vertex_range_start)
        self.assertEqual(3, batches[0].source_vertex_range_count)
        self.assertEqual(0, batches[0].source_face_range_start)
        self.assertEqual(1, batches[0].source_face_range_count)

    def test_mesh_editor_native_preview_prefers_report_descriptors_before_json_ids(self) -> None:
        from cdmw.modding.mesh_parser import ParsedMesh, SubMesh
        from cdmw.ui.mesh_editor.native_preview_payloads import mesh_to_native_preview

        class IterationForbiddenList(list):
            def __iter__(self):  # type: ignore[override]
                raise AssertionError("descriptor-backed native preview report parsed JSON source ids")

        mesh = ParsedMesh(
            path="descriptor-preview.pac",
            format="pac",
            submeshes=[
                SubMesh(
                    vertices=[(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0)],
                    normals=[(0.0, 0.0, 1.0)] * 3,
                    uvs=[(0.0, 0.0), (1.0, 0.0), (0.0, 1.0)],
                    faces=[(0, 1, 2)],
                )
            ],
            total_vertices=3,
            total_faces=1,
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            source_vertices_path = temp_root / "source_vertices.bin"
            source_faces_path = temp_root / "source_faces.bin"
            source_vertices_path.write_bytes(struct.pack("<3i", 10, 12, 11))
            source_faces_path.write_bytes(struct.pack("<i", 20))
            vertex_descriptor = {"path": str(source_vertices_path), "count": 3, "components": 1, "type": "i32"}
            face_descriptor = {"path": str(source_faces_path), "count": 1, "components": 1, "type": "i32"}

            def _fake_writer(output_path: object, *, identity_output_path: object = None, **_kwargs: object) -> dict[str, object]:
                Path(str(output_path)).write_bytes(_vertex(0.0, 0.0, 0.0) * 3)
                if identity_output_path is not None:
                    Path(str(identity_output_path)).write_bytes(b"\0" * (3 * 12))
                return {
                    "status": "ok",
                    "vertex_count": 3,
                    "geometry_size": 3 * 23 * 4,
                    "batches": [
                        {
                            "mesh_index": 0,
                            "first_vertex": 0,
                            "vertex_count": 3,
                            "identity_offset": 0,
                            "identity_size": 3 * 12,
                            "source_vertex_indices": IterationForbiddenList([10, 12, 11]),
                            "source_face_indices": IterationForbiddenList([20]),
                            "source_vertex_indices_binary": vertex_descriptor,
                            "source_face_indices_binary": face_descriptor,
                        }
                    ],
                }

            with patch("cdmw.modding.mesh_native_core.find_native_mesh_core_binary", return_value=Path("mesh-core.exe")):
                with patch("cdmw.modding.mesh_native_core._ensure_native_mesh_session_submesh", return_value="session-0"):
                    with patch("cdmw.modding.mesh_native_core.write_native_preview_geometry_blob", side_effect=_fake_writer):
                        prepared = mesh_to_native_preview(mesh)

        batch = prepared.batches[0]
        self.assertEqual((), batch.source_vertex_indices)
        self.assertEqual((), batch.source_face_indices)
        self.assertEqual(3, batch.source_vertex_indices_binary["count"])
        self.assertEqual(1, batch.source_face_indices_binary["count"])
        for descriptor in (batch.source_vertex_indices_binary, batch.source_face_indices_binary):
            Path(str(descriptor["path"])).unlink(missing_ok=True)

    def test_mesh_editor_preview_updates_prefer_descriptors_before_json_ids(self) -> None:
        from cdmw.modding.mesh_parser import ParsedMesh, SubMesh
        from cdmw.ui.mesh_editor.native_preview_payloads import mesh_edit_triangle_groups, mesh_edit_vertex_update_groups

        class IterationForbiddenList(list):
            def __iter__(self):  # type: ignore[override]
                raise AssertionError("descriptor-backed preview group parsed JSON source ids")

        def descriptor(path: str, count: int, *, components: int = 1, kind: str = "i32") -> dict[str, object]:
            return {"path": path, "count": count, "components": components, "type": kind}

        submesh = SubMesh(
            name="Body",
            material="Mat",
            texture="Tex",
            vertices=[(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0)],
            normals=[(0.0, 0.0, 1.0)] * 3,
            uvs=[(0.0, 0.0), (1.0, 0.0), (0.0, 1.0)],
            faces=[(0, 1, 2)],
        )
        submesh.cdmw_native_preview_triangle_group = {
            "preview_backend": "cdmw_mesh_core",
            "source_submesh_index": 0,
            "source_vertex_indices": IterationForbiddenList([0, 1, 2]),
            "source_face_indices": IterationForbiddenList([0]),
            "indices": IterationForbiddenList([0, 1, 2]),
            "source_vertex_indices_binary": descriptor("tri-source-vertices.bin", 3),
            "source_face_indices_binary": descriptor("tri-source-faces.bin", 1),
            "positions_binary": descriptor("tri-positions.bin", 3, components=3, kind="f64"),
            "normals_binary": descriptor("tri-normals.bin", 3, components=3, kind="f64"),
            "uvs_binary": descriptor("tri-uvs.bin", 3, components=2, kind="f64"),
            "indices_binary": descriptor("tri-indices.bin", 3),
        }
        mesh = ParsedMesh(submeshes=[submesh], total_vertices=3, total_faces=1)

        triangle_group = mesh_edit_triangle_groups(mesh, (0,))[0]
        self.assertIn("source_vertex_indices_binary", triangle_group)
        self.assertIn("source_face_indices_binary", triangle_group)
        self.assertIn("indices_binary", triangle_group)
        self.assertNotIn("source_vertex_indices", triangle_group)
        self.assertNotIn("source_face_indices", triangle_group)
        self.assertNotIn("indices", triangle_group)

        submesh.cdmw_native_preview_vertex_update_group = {
            "preview_backend": "cdmw_mesh_core",
            "source_submesh_index": 0,
            "source_vertex_indices": IterationForbiddenList([0, 1]),
            "source_vertex_indices_binary": descriptor("update-source-vertices.bin", 2),
            "positions_binary": descriptor("update-positions.bin", 2, components=3, kind="f64"),
            "normals_binary": descriptor("update-normals.bin", 2, components=3, kind="f64"),
            "uvs_binary": descriptor("update-uvs.bin", 2, components=2, kind="f64"),
        }
        vertex_group = mesh_edit_vertex_update_groups(mesh, {0: {"source_vertex_indices_binary": descriptor("changed.bin", 2)}})[0]
        self.assertIn("source_vertex_indices_binary", vertex_group)
        self.assertNotIn("source_vertex_indices", vertex_group)

    def test_native_vertex_blob_sparse_source_ids_use_binary_descriptors(self) -> None:
        from cdmw.rendering.model_preview_prepare import _build_vertex_blob_native

        model = ModelPreviewData(
            meshes=[
                ModelPreviewMesh(
                    positions=[
                        (0.0, 0.0, 0.0),
                        (1.0, 0.0, 0.0),
                        (0.0, 1.0, 0.0),
                        (1.0, 1.0, 0.0),
                    ],
                    normals=[(0.0, 0.0, 1.0)] * 4,
                    texture_coordinates=[(0.0, 0.0), (1.0, 0.0), (0.0, 1.0), (1.0, 1.0)],
                    indices=[0, 1, 2, 1, 3, 2],
                    source_submesh_index=7,
                    source_vertex_indices=[10, 12, 11, 15],
                    source_face_indices=[20, 25],
                )
            ]
        )
        persisted_paths: list[Path] = []

        def _fake_writer(output_path: object, *, meshes: object, identity_output_path: object = None, **_kwargs: object) -> dict[str, object]:
            payload = tuple(meshes)[0]  # type: ignore[arg-type]
            self.assertNotIn("source_vertex_indices", payload)
            self.assertNotIn("source_face_indices", payload)
            vertex_descriptor = payload["source_vertex_indices_binary"]
            face_descriptor = payload["source_face_indices_binary"]
            vertex_path = Path(str(vertex_descriptor["path"]))  # type: ignore[index]
            face_path = Path(str(face_descriptor["path"]))  # type: ignore[index]
            self.assertEqual((10, 12, 11, 15), struct.unpack("<4i", vertex_path.read_bytes()))
            self.assertEqual((20, 25), struct.unpack("<2i", face_path.read_bytes()))
            Path(str(output_path)).write_bytes(b"\0" * (6 * 23 * 4))
            if identity_output_path is not None:
                Path(str(identity_output_path)).write_bytes(b"\0" * (6 * 12))
            return {
                "status": "ok",
                "operation": "preview_geometry",
                "vertex_count": 6,
                "geometry_size": 6 * 23 * 4,
                "batches": [
                    {
                        "mesh_index": 0,
                        "first_vertex": 0,
                        "vertex_count": 6,
                        "identity_offset": 0,
                        "identity_size": 6 * 12,
                        "source_vertex_indices_binary": vertex_descriptor,
                        "source_face_indices_binary": face_descriptor,
                    }
                ],
            }

        with patch("cdmw.modding.mesh_native_core.write_native_preview_geometry_blob", side_effect=_fake_writer):
            result = _build_vertex_blob_native(model)

        self.assertIsNotNone(result)
        _blob, vertex_count, batches = result  # type: ignore[misc]
        self.assertEqual(6, vertex_count)
        self.assertEqual((), batches[0].source_vertex_indices)
        self.assertEqual((), batches[0].source_face_indices)
        for descriptor in (batches[0].source_vertex_indices_binary, batches[0].source_face_indices_binary):
            path = Path(str(descriptor["path"]))
            persisted_paths.append(path)
            self.assertTrue(path.is_file())
            self.assertTrue(descriptor.get("delete_after"))
        for path in persisted_paths:
            path.unlink(missing_ok=True)

    def test_prepare_model_preview_uses_compact_identity_ranges_for_missing_source_ids(self) -> None:
        from cdmw.rendering import model_preview_prepare as prepare

        model = ModelPreviewData(
            path="identity-range.pam",
            meshes=[
                ModelPreviewMesh(
                    positions=[(0.0, 0.0, 0.0)],
                    indices=[0, 0, 0],
                    source_submesh_index=4,
                )
            ],
        )
        batch = prepare.ModelPreviewDrawBatch(
            mesh_index=0,
            material_name="mat",
            texture_name="tex",
            first_vertex=0,
            vertex_count=6,
        )
        vertex_blob = b"\0" * (6 * 23 * 4)

        with patch.object(prepare, "build_vertex_blob", return_value=(vertex_blob, 6, [batch])):
            _model, prepared = prepare.prepare_model_preview(model, enable_material_combiner=False)

        self.assertIsNotNone(prepared)
        prepared_batch = prepared.batches[0]  # type: ignore[union-attr]
        self.assertEqual((), prepared_batch.source_vertex_indices)
        self.assertEqual((), prepared_batch.source_face_indices)
        self.assertEqual(0, prepared_batch.source_vertex_range_start)
        self.assertEqual(6, prepared_batch.source_vertex_range_count)
        self.assertEqual(0, prepared_batch.source_face_range_start)
        self.assertEqual(2, prepared_batch.source_face_range_count)

    def test_editor_identity_range_descriptors_skip_legacy_source_iterables(self) -> None:
        from cdmw.rendering.native_preview_package_writer import _editor_identity_blob, _editor_identity_metadata

        class ExplodingIterable:
            def __iter__(self) -> object:
                raise AssertionError("legacy source ids should not be iterated when compact range descriptors exist")

        batch = PreparedModelPreviewBatch(
            vertex_blob=_vertex(0.0, 0.0, 0.0) * 3,
            index_count=3,
            source_submesh_index=5,
            source_vertex_indices=ExplodingIterable(),  # type: ignore[arg-type]
            source_face_indices=ExplodingIterable(),  # type: ignore[arg-type]
            source_vertex_range_start=10,
            source_vertex_range_count=3,
            source_face_range_start=20,
            source_face_range_count=1,
        )

        metadata = _editor_identity_metadata(batch, 3, 0)
        blob_metadata, identity_blob = _editor_identity_blob(batch, 3)

        self.assertEqual(13, metadata["source_vertex_count"])
        self.assertEqual(21, metadata["source_face_count"])
        self.assertEqual(3 * 12, blob_metadata["identity_size"])
        self.assertEqual(3 * 12, len(identity_blob))

    def test_editor_identity_sparse_source_sequences_avoid_tuple_copy(self) -> None:
        from cdmw.rendering.native_preview_package_writer import _editor_identity_blob, _editor_identity_metadata

        class IndexOnlySourceIds:
            def __init__(self, values: tuple[int, ...]) -> None:
                self._values = values

            def __len__(self) -> int:
                return len(self._values)

            def __getitem__(self, index: int) -> int:
                return self._values[index]

            def __iter__(self) -> object:
                raise AssertionError("source ids should be indexed without tuple-copy iteration")

        batch = PreparedModelPreviewBatch(
            vertex_blob=_vertex(0.0, 0.0, 0.0) * 3,
            index_count=3,
            source_submesh_index=5,
            source_vertex_indices=IndexOnlySourceIds((10, 12, 11)),  # type: ignore[arg-type]
            source_face_indices=IndexOnlySourceIds((20,)),  # type: ignore[arg-type]
        )

        metadata = _editor_identity_metadata(batch, 3, 0)
        blob_metadata, identity_blob = _editor_identity_blob(batch, 3)
        identity_rows = tuple(struct.iter_unpack("<iii", identity_blob))

        self.assertEqual(13, metadata["source_vertex_count"])
        self.assertEqual(21, metadata["source_face_count"])
        self.assertEqual(3 * 12, blob_metadata["identity_size"])
        self.assertEqual(((5, 10, 20), (5, 12, 20), (5, 11, 20)), identity_rows)

    def test_preview_package_blocks_descriptor_backed_identity_python_fallback(self) -> None:
        blob = b"".join(
            (
                _vertex(0.0, 0.0, 0.0),
                _vertex(1.0, 0.0, 0.0),
                _vertex(0.0, 1.0, 0.0),
            )
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            temp = Path(temp_dir)
            source_vertices = temp / "source_vertices.bin"
            source_faces = temp / "source_faces.bin"
            source_vertices.write_bytes(struct.pack("<3i", 10, 11, 12))
            source_faces.write_bytes(struct.pack("<i", 20))
            prepared = PreparedModelPreviewData(
                source_path=str(temp / "scene.pam"),
                format="pam",
                batches=(
                    PreparedModelPreviewBatch(
                        vertex_blob=blob,
                        index_count=3,
                        source_submesh_index=5,
                        source_vertex_indices_binary={
                            "path": str(source_vertices),
                            "count": 3,
                            "components": 1,
                            "type": "i32",
                        },
                        source_face_indices_binary={
                            "path": str(source_faces),
                            "count": 1,
                            "components": 1,
                            "type": "i32",
                        },
                    ),
                ),
            )

            with patch("cdmw.rendering.native_preview_package_writer._write_editor_identity_blob_native", return_value=None):
                with self.assertRaisesRegex(RuntimeError, "descriptor-backed source ids"):
                    write_isolated_d3d11_preview_package(
                        ModelPreviewData(path=str(temp / "scene.pam")),
                        prepared,
                        output_root=temp / "package",
                    )

    def test_editor_identity_sparse_source_ids_use_native_sidecars(self) -> None:
        from cdmw.rendering.native_preview_package_writer import _write_editor_identity_blob_native

        batch = PreparedModelPreviewBatch(
            vertex_blob=_vertex(0.0, 0.0, 0.0) * 3,
            index_count=3,
            source_submesh_index=5,
            source_vertex_indices=(10, 11, 12),
            source_face_indices=(20,),
        )
        captured: dict[str, object] = {}
        sidecar_paths: list[Path] = []

        def _fake_identity_writer(output_path: object, **kwargs: object) -> dict[str, object]:
            captured.update(kwargs)
            vertex_descriptor = kwargs.get("source_vertex_indices_binary")
            face_descriptor = kwargs.get("source_face_indices_binary")
            self.assertIsInstance(vertex_descriptor, dict)
            self.assertIsInstance(face_descriptor, dict)
            vertex_path = Path(str(vertex_descriptor["path"]))  # type: ignore[index]
            face_path = Path(str(face_descriptor["path"]))  # type: ignore[index]
            sidecar_paths.extend((vertex_path, face_path))
            self.assertEqual((10, 11, 12), struct.unpack("<3i", vertex_path.read_bytes()))
            self.assertEqual((20,), struct.unpack("<i", face_path.read_bytes()))
            Path(str(output_path)).write_bytes(b"\0" * (3 * 12))
            return {
                "source_submesh_index": 5,
                "source_vertex_count": 13,
                "source_face_count": 21,
                "identity_stride_bytes": 12,
                "identity_size": 3 * 12,
                "role": "",
                "part_name": "",
                "editable": True,
            }

        with tempfile.TemporaryDirectory() as temp_dir:
            identity_path = Path(temp_dir) / "identity.bin"
            with patch("cdmw.rendering.native_preview_package_writer.write_native_preview_identity_blob", side_effect=_fake_identity_writer):
                metadata = _write_editor_identity_blob_native(identity_path, batch, 3)

        self.assertEqual((), captured["source_vertex_indices"])
        self.assertEqual((), captured["source_face_indices"])
        self.assertEqual(13, metadata["source_vertex_count"])  # type: ignore[index]
        self.assertEqual(21, metadata["source_face_count"])  # type: ignore[index]
        self.assertTrue(sidecar_paths)
        self.assertTrue(all(not path.exists() for path in sidecar_paths))

    def test_skeleton_overlay_manifest_includes_bone_positions(self) -> None:
        model = ModelPreviewData(
            path="body.pac",
            physics_overlay=HkxPhysicsOverlayData(
                bones=(
                    HkxPhysicsOverlayBone(index=0, name="Root", position=(0.0, 0.0, 0.0)),
                    HkxPhysicsOverlayBone(
                        index=1,
                        name="Spine",
                        parent_index=0,
                        parent_name="Root",
                        position=(0.0, 1.0, 0.0),
                        parent_position=(0.0, 0.0, 0.0),
                    ),
                ),
                skeleton_selected_bone_index=1,
            ),
        )

        metadata = _skeleton_overlay_metadata(model)

        self.assertTrue(metadata["enabled"])
        self.assertEqual([0.0, 1.0, 0.0], metadata["bones"][1]["position"])
        self.assertEqual([0.0, 0.0, 0.0], metadata["bones"][1]["parent_position"])
        self.assertEqual(1, metadata["selected_bone_index"])

    def test_legacy_material_combiner_cache_key_includes_synthesized_texture_paths(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            base_a = root / "base_a.png"
            base_b = root / "base_b.png"
            material = root / "material_ma.png"
            base_a.write_bytes(b"base-a")
            base_b.write_bytes(b"base-b")
            material.write_bytes(b"material")
            model_a = ModelPreviewData(
                path="weapon.pac",
                meshes=(
                    ModelPreviewMesh(
                        material_name="Blade",
                        texture_name="Blade",
                        preview_texture_path=str(base_a),
                        preview_material_texture_path=str(material),
                        preview_material_texture_name="material_ma.png",
                        preview_material_texture_subtype="packed_mask",
                    ),
                ),
            )
            model_b = ModelPreviewData(
                path="weapon.pac",
                meshes=(
                    ModelPreviewMesh(
                        material_name="Blade",
                        texture_name="Blade",
                        preview_texture_path=str(base_b),
                        preview_material_texture_path=str(material),
                        preview_material_texture_name="material_ma.png",
                        preview_material_texture_subtype="packed_mask",
                    ),
                ),
            )

            self.assertNotEqual(
                NativePreviewPanel._material_combiner_cache_dir(model_a),
                NativePreviewPanel._material_combiner_cache_dir(model_b),
            )

    def test_gltf_metallic_roughness_decodes_without_occlusion_channel(self) -> None:
        texture_input = PreviewMaterialTextureInput(
            slot_kind="material",
            parameter_name="_metallicRoughnessTexture",
            semantic_type="material",
            semantic_subtype="metallic_roughness",
            packed_channels=("roughness", "metallic"),
        )

        self.assertEqual("metallic_roughness", _decode_mode_for_input(texture_input))
        ao, roughness, metalness, _specular = decode_material_sample(0.1, 0.35, 0.8, 1.0, "metallic_roughness")

        self.assertAlmostEqual(1.0, ao)
        self.assertAlmostEqual(0.35, roughness)
        self.assertAlmostEqual(0.8, metalness)

    def test_gltf_specular_glossiness_decodes_alpha_as_glossiness(self) -> None:
        texture_input = PreviewMaterialTextureInput(
            slot_kind="material",
            parameter_name="_specularGlossinessTexture",
            semantic_type="specular",
            semantic_subtype="specular_glossiness",
            packed_channels=("specular", "glossiness"),
            texture_name="blade_specularGlossiness.png",
        )

        self.assertEqual("specular_glossiness", _decode_mode_for_input(texture_input))
        self.assertEqual("specular_glossiness", _input_texture_kind(texture_input))
        ao, roughness, metalness, specular = decode_material_sample(0.8, 0.5, 0.25, 0.75, "specular_glossiness")

        self.assertAlmostEqual(1.0, ao)
        self.assertAlmostEqual(0.25, roughness)
        self.assertAlmostEqual(0.0, metalness)
        self.assertAlmostEqual(0.8, specular)

    def test_gltf_specular_glossiness_synthesizes_visible_preview_albedo(self) -> None:
        from PySide6.QtGui import QColor, QImage

        with tempfile.TemporaryDirectory() as temp_dir:
            temp = Path(temp_dir)
            base_path = temp / "axe_diffuse.png"
            base_image = QImage(2, 2, QImage.Format_RGBA8888)
            base_image.fill(QColor(12, 10, 8, 255))
            self.assertTrue(base_image.save(str(base_path), "PNG"))
            spec_gloss_path = temp / "axe_specularGlossiness.png"
            spec_gloss_image = QImage(2, 2, QImage.Format_RGBA8888)
            spec_gloss_image.fill(QColor(210, 164, 96, 220))
            self.assertTrue(spec_gloss_image.save(str(spec_gloss_path), "PNG"))

            combined = combine_preview_material(
                type(
                    "Payload",
                    (),
                    {
                        "texture_flip_vertical": False,
                        "tangents_usable": False,
                        "normal_texture_strength": 0.0,
                        "material_texture_inputs": (
                            PreviewMaterialTextureInput(
                                slot_kind="base",
                                parameter_name="_diffuseTexture",
                                source_texture_path=str(base_path),
                                preview_texture_path=str(base_path),
                                semantic_type="color",
                                semantic_subtype="albedo",
                                material_name="Axe",
                                confidence="gltf",
                            ),
                            PreviewMaterialTextureInput(
                                slot_kind="material",
                                parameter_name="_specularGlossinessTexture",
                                source_texture_path=str(spec_gloss_path),
                                preview_texture_path=str(spec_gloss_path),
                                semantic_type="specular",
                                semantic_subtype="specular_glossiness",
                                packed_channels=("specular", "glossiness"),
                                material_name="Axe",
                                confidence="gltf",
                                material_parameters=(
                                    PreviewMaterialParameterInput(
                                        parameter_kind="color",
                                        parameter_name="_specularFactor",
                                        color_value=(1.0, 1.0, 1.0),
                                    ),
                                ),
                            ),
                        ),
                    },
                )(),
                temp / "combined",
                0,
                settings=MaterialPreviewCombinerSettings(support_map_max_dimension=128),
            )

            self.assertTrue(combined.base_source)
            self.assertIn("specular-glossiness", combined.base_note)
            preview_base = QImage(QUrl(combined.base_source).toLocalFile())
            self.assertFalse(preview_base.isNull())
            color = preview_base.pixelColor(0, 0)
            self.assertGreater(color.red(), 120)
            self.assertGreater(color.green(), 90)
            self.assertGreater(color.blue(), 45)

    def test_d3d11_package_splits_specular_glossiness_when_combiner_disabled(self) -> None:
        from PySide6.QtGui import QColor, QImage

        blob = b"".join(
            (
                _vertex(0.0, 0.0, 0.0),
                _vertex(1.0, 0.0, 0.0),
                _vertex(0.0, 1.0, 0.0),
            )
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            temp = Path(temp_dir)
            base_path = temp / "blade_diffuse.png"
            base_image = QImage(2, 2, QImage.Format_RGBA8888)
            base_image.fill(QColor(160, 120, 80, 255))
            self.assertTrue(base_image.save(str(base_path), "PNG"))
            spec_gloss_path = temp / "blade_specularGlossiness.png"
            spec_gloss_image = QImage(2, 2, QImage.Format_RGBA8888)
            spec_gloss_image.fill(QColor(204, 128, 64, 64))
            self.assertTrue(spec_gloss_image.save(str(spec_gloss_path), "PNG"))
            texture_input = PreviewMaterialTextureInput(
                slot_kind="material",
                parameter_name="_specularGlossinessTexture",
                source_texture_path=str(spec_gloss_path),
                texture_name=spec_gloss_path.name,
                preview_texture_path=str(spec_gloss_path),
                semantic_type="specular",
                semantic_subtype="specular_glossiness",
                packed_channels=("specular", "glossiness"),
            )
            prepared = PreparedModelPreviewData(
                source_path=str(temp / "scene.gltf"),
                format="gltf",
                batches=(
                    PreparedModelPreviewBatch(
                        vertex_blob=blob,
                        index_count=3,
                        preview_texture_path=str(base_path),
                        preview_material_texture_path=str(spec_gloss_path),
                        preview_material_texture_subtype="specular_glossiness",
                        preview_material_texture_packed_channels=("specular", "glossiness"),
                        preview_material_texture_inputs=(texture_input,),
                        has_texture_coordinates=True,
                    ),
                ),
            )

            package_dir = write_isolated_d3d11_preview_package(
                ModelPreviewData(path=str(temp / "scene.gltf")),
                prepared,
                output_root=temp / "package",
                enable_material_combiner=False,
                prefer_direct_dds=True,
            )
            manifest = json.loads((package_dir / "manifest.json").read_text(encoding="utf-8"))
            batch = manifest["batches"][0]
            textures = batch["textures"]

            self.assertTrue(textures["roughness"])
            self.assertTrue(textures["specular"])
            self.assertEqual("", textures["metalness"])
            self.assertIn("specular_glossiness", batch["material_combiner_decode_modes"])
            roughness_image = QImage(str(package_dir / textures["roughness"]))
            specular_image = QImage(str(package_dir / textures["specular"]))
            self.assertFalse(roughness_image.isNull())
            self.assertFalse(specular_image.isNull())
            self.assertEqual(191, roughness_image.pixelColor(0, 0).red())
            self.assertEqual(204, specular_image.pixelColor(0, 0).red())

    def test_d3d11_package_routes_occlusion_and_inverts_glossiness_when_combiner_disabled(self) -> None:
        from PySide6.QtGui import QColor, QImage

        blob = b"".join(
            (
                _vertex(0.0, 0.0, 0.0),
                _vertex(1.0, 0.0, 0.0),
                _vertex(0.0, 1.0, 0.0),
            )
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            temp = Path(temp_dir)
            base_path = temp / "body_base.png"
            base_image = QImage(2, 2, QImage.Format_RGBA8888)
            base_image.fill(QColor(160, 120, 80, 255))
            self.assertTrue(base_image.save(str(base_path), "PNG"))
            ao_path = temp / "body_ao.png"
            ao_image = QImage(2, 2, QImage.Format_RGBA8888)
            ao_image.fill(QColor(64, 64, 64, 255))
            self.assertTrue(ao_image.save(str(ao_path), "PNG"))
            gloss_path = temp / "body_glossiness.png"
            gloss_image = QImage(2, 2, QImage.Format_RGBA8888)
            gloss_image.fill(QColor(64, 64, 64, 255))
            self.assertTrue(gloss_image.save(str(gloss_path), "PNG"))
            prepared = PreparedModelPreviewData(
                source_path=str(temp / "scene.gltf"),
                format="gltf",
                batches=(
                    PreparedModelPreviewBatch(
                        vertex_blob=blob,
                        index_count=3,
                        preview_texture_path=str(base_path),
                        preview_material_texture_inputs=(
                            PreviewMaterialTextureInput(
                                slot_kind="occlusion",
                                parameter_name="_occlusionTexture",
                                source_texture_path=str(ao_path),
                                texture_name=ao_path.name,
                                preview_texture_path=str(ao_path),
                                semantic_type="ao",
                                semantic_subtype="ao",
                                packed_channels=("ao",),
                            ),
                            PreviewMaterialTextureInput(
                                slot_kind="glossiness",
                                parameter_name="_glossinessTexture",
                                source_texture_path=str(gloss_path),
                                texture_name=gloss_path.name,
                                preview_texture_path=str(gloss_path),
                                semantic_type="roughness",
                                semantic_subtype="glossiness",
                                packed_channels=("glossiness",),
                            ),
                        ),
                        has_texture_coordinates=True,
                    ),
                ),
            )

            package_dir = write_isolated_d3d11_preview_package(
                ModelPreviewData(path=str(temp / "scene.gltf")),
                prepared,
                output_root=temp / "package",
                enable_material_combiner=False,
                prefer_direct_dds=True,
            )
            manifest = json.loads((package_dir / "manifest.json").read_text(encoding="utf-8"))
            textures = manifest["batches"][0]["textures"]

            self.assertTrue(textures["occlusion"])
            self.assertTrue(textures["roughness"])
            self.assertEqual("", textures["metalness"])
            roughness_image = QImage(str(package_dir / textures["roughness"]))
            self.assertFalse(roughness_image.isNull())
            self.assertEqual(191, roughness_image.pixelColor(0, 0).red())

    def test_preview_package_treats_gltf_metallic_roughness_as_packed_material(self) -> None:
        texture_input = PreviewMaterialTextureInput(
            slot_kind="material",
            parameter_name="_metallicRoughnessTexture",
            semantic_type="material",
            semantic_subtype="metallic_roughness",
            packed_channels=("roughness", "metallic"),
            texture_name="lambert1_metallicRoughness.png",
        )

        self.assertEqual("packed_material", _input_texture_kind(texture_input))

    def test_normalizes_renderer_backend(self) -> None:
        self.assertEqual(ARCHIVE_MODEL_RENDERER_D3D11, normalize_archive_model_renderer_backend("d3d11"))
        self.assertEqual(ARCHIVE_MODEL_RENDERER_D3D11, normalize_archive_model_renderer_backend("direct3d11"))
        self.assertEqual(ARCHIVE_MODEL_RENDERER_D3D11, normalize_archive_model_renderer_backend("native_d3d11"))
        self.assertEqual(ARCHIVE_MODEL_RENDERER_D3D11, normalize_archive_model_renderer_backend("old_removed_renderer"))
        self.assertEqual(ARCHIVE_MODEL_RENDERER_DEFAULT, normalize_archive_model_renderer_backend("unknown"))

    def test_native_d3d11_mesh_edit_vertex_updates_keep_group_sequence(self) -> None:
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PySide6.QtWidgets import QApplication

        from cdmw.ui.native_d3d11_preview_host import NativeD3D11PreviewHostFrame

        app = QApplication.instance() or QApplication([])
        commands: list[dict[str, object]] = []
        host = NativeD3D11PreviewHostFrame()
        host._send_host_json_command = lambda payload: commands.append(payload) or True  # type: ignore[method-assign]
        groups = (
            {
                "source_submesh_index": 0,
                "source_vertex_start": 1,
                "source_vertex_count": 2,
                "positions_binary": {"path": "positions.bin", "count": 2, "components": 3, "type": "f64"},
            },
        )
        try:
            self.assertTrue(host.update_mesh_edit_vertices(groups))
            self.assertIs(groups, commands[-1]["groups"])
        finally:
            host.close()
            host.deleteLater()
            app.processEvents()

    def test_native_d3d11_mesh_edit_vertex_updates_use_file_for_large_payloads(self) -> None:
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PySide6.QtWidgets import QApplication

        from cdmw.ui.native_d3d11_preview_host import NativeD3D11PreviewHostFrame

        app = QApplication.instance() or QApplication([])
        commands: list[dict[str, object]] = []
        host = NativeD3D11PreviewHostFrame()
        host._MESH_EDIT_VERTEX_FILE_THRESHOLD = 1
        host._send_host_json_command = lambda payload: commands.append(dict(payload)) or True  # type: ignore[method-assign]
        payload_path: Path | None = None
        try:
            self.assertTrue(
                host.update_mesh_edit_vertices(
                    (
                        {
                            "source_submesh_index": 0,
                            "source_vertex_start": 0,
                            "source_vertex_count": 2,
                            "positions": [(0.0, 0.0, 0.0), (1.0, 0.0, 0.0)],
                        },
                    )
                )
            )
            self.assertEqual("update_mesh_edit_vertices_file", commands[-1]["command"])
            payload_path = Path(str(commands[-1]["payload_file"]))
            payload = json.loads(payload_path.read_text(encoding="utf-8"))
            self.assertEqual("update_mesh_edit_vertices", payload["command"])
            self.assertEqual(1, len(payload["groups"]))
        finally:
            if payload_path is not None:
                payload_path.unlink(missing_ok=True)
            host.close()
            host.deleteLater()
            app.processEvents()

    def test_native_d3d11_mesh_edit_triangle_replace_keeps_group_sequence(self) -> None:
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PySide6.QtWidgets import QApplication

        from cdmw.ui.native_d3d11_preview_host import NativeD3D11PreviewHostFrame

        app = QApplication.instance() or QApplication([])
        commands: list[dict[str, object]] = []
        host = NativeD3D11PreviewHostFrame()
        host._send_host_json_command = lambda payload: commands.append(payload) or True  # type: ignore[method-assign]
        groups = (
            {
                "source_submesh_index": 0,
                "source_vertex_start": 0,
                "source_vertex_count": 3,
                "source_face_start": 0,
                "source_face_count": 1,
                "indices_binary": {"path": "indices.bin", "count": 3, "components": 1, "type": "i32"},
            },
        )
        try:
            self.assertTrue(host.replace_mesh_edit_triangles(groups, source_submesh_indices=(0,)))
            self.assertIs(groups, commands[-1]["groups"])
        finally:
            host.close()
            host.deleteLater()
            app.processEvents()

    def test_native_d3d11_highlight_commands_select_individual_parts(self) -> None:
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PySide6.QtWidgets import QApplication

        from cdmw.ui.native_d3d11_preview_host import NativeD3D11PreviewHostFrame

        app = QApplication.instance() or QApplication([])
        commands: list[dict[str, object]] = []
        host = NativeD3D11PreviewHostFrame()
        host._send_host_json_command = lambda payload: commands.append(dict(payload)) or True  # type: ignore[method-assign]
        try:
            self.assertTrue(host.set_highlighted_source_submeshes([4, -1, 2, 4]))
            self.assertEqual(
                {
                    "command": "set_highlights",
                    "source_submesh_indices": [2, 4],
                },
                commands[-1],
            )

            self.assertTrue(
                host.set_highlighted_alignment_submeshes(
                    replacement_submesh_indices=[8, 3, 8],
                    original_submesh_indices=[1, -1],
                )
            )
            self.assertEqual(
                {
                    "command": "set_highlights",
                    "source_submesh_indices": [1, 3, 8],
                    "replacement_submesh_indices": [3, 8],
                    "original_submesh_indices": [1],
                },
                commands[-1],
            )
        finally:
            host.close()
            host.deleteLater()
            app.processEvents()

    def test_native_d3d11_vertex_selection_uses_binary_descriptor(self) -> None:
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PySide6.QtWidgets import QApplication

        from cdmw.ui.native_d3d11_preview_host import NativeD3D11PreviewHostFrame

        app = QApplication.instance() or QApplication([])
        commands: list[dict[str, object]] = []
        host = NativeD3D11PreviewHostFrame()
        host._send_host_json_command = lambda payload: commands.append(dict(payload)) or True  # type: ignore[method-assign]
        try:
            self.assertTrue(host.set_mesh_edit_vertex_selection({2: [5, 1, 5, -1]}))
            group = commands[-1]["groups"][0]  # type: ignore[index]
            self.assertEqual("set_mesh_edit_selection", commands[-1]["command"])
            self.assertEqual(2, group["source_submesh_index"])
            self.assertNotIn("source_vertex_indices", group)
            descriptor = group["source_vertex_indices_binary"]
            path = Path(str(descriptor["path"]))
            try:
                self.assertEqual({"count": 2, "components": 1, "type": "i32", "delete_after": True}, {key: descriptor[key] for key in ("count", "components", "type", "delete_after")})
                data = path.read_bytes()
                self.assertEqual([1, 5], list(struct.unpack("<ii", data)))
            finally:
                path.unlink(missing_ok=True)
        finally:
            host.close()
            host.deleteLater()
            app.processEvents()

    def test_native_d3d11_vertex_selection_forwards_compact_ranges(self) -> None:
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PySide6.QtWidgets import QApplication

        from cdmw.ui.native_d3d11_preview_host import NativeD3D11PreviewHostFrame

        app = QApplication.instance() or QApplication([])
        commands: list[dict[str, object]] = []
        host = NativeD3D11PreviewHostFrame()
        host._send_host_json_command = lambda payload: commands.append(dict(payload)) or True  # type: ignore[method-assign]
        try:
            self.assertTrue(host.set_mesh_edit_vertex_selection({2: range(3, 6)}))
            group = commands[-1]["groups"][0]  # type: ignore[index]
            self.assertEqual("set_mesh_edit_selection", commands[-1]["command"])
            self.assertEqual(2, group["source_submesh_index"])
            self.assertEqual(3, group["source_vertex_start"])
            self.assertEqual(3, group["source_vertex_count"])
            self.assertNotIn("source_vertex_indices", group)
            self.assertNotIn("source_vertex_indices_binary", group)
        finally:
            host.close()
            host.deleteLater()
            app.processEvents()

    def test_native_d3d11_selection_groups_compact_contiguous_indices(self) -> None:
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PySide6.QtWidgets import QApplication

        from cdmw.ui.native_d3d11_preview_host import NativeD3D11PreviewHostFrame

        app = QApplication.instance() or QApplication([])
        commands: list[dict[str, object]] = []
        host = NativeD3D11PreviewHostFrame()
        host._send_host_json_command = lambda payload: commands.append(dict(payload)) or True  # type: ignore[method-assign]
        try:
            self.assertTrue(
                host.set_mesh_edit_selection_groups(
                    [
                        {
                            "source_submesh_index": 2,
                            "source_selected": True,
                            "source_vertex_indices": [3, 4, 5],
                            "source_face_indices": [7, 8],
                        },
                        {
                            "source_submesh_index": 3,
                            "source_vertex_indices": [1, 5],
                            "source_face_indices": [9, 12],
                        },
                    ]
                )
            )
            first = commands[-1]["groups"][0]  # type: ignore[index]
            self.assertIs(True, first["source_selected"])
            self.assertEqual(3, first["source_vertex_start"])
            self.assertEqual(3, first["source_vertex_count"])
            self.assertEqual(7, first["source_face_start"])
            self.assertEqual(2, first["source_face_count"])
            self.assertNotIn("source_vertex_indices", first)
            self.assertNotIn("source_face_indices", first)

            second = commands[-1]["groups"][1]  # type: ignore[index]
            self.assertNotIn("source_vertex_indices", second)
            self.assertNotIn("source_vertex_start", second)
            descriptor = second["source_vertex_indices_binary"]
            path = Path(str(descriptor["path"]))
            try:
                self.assertEqual({"count": 2, "components": 1, "type": "i32", "delete_after": True}, {key: descriptor[key] for key in ("count", "components", "type", "delete_after")})
                self.assertEqual([1, 5], list(struct.unpack("<ii", path.read_bytes())))
            finally:
                path.unlink(missing_ok=True)
            face_descriptor = second["source_face_indices_binary"]
            face_path = Path(str(face_descriptor["path"]))
            try:
                self.assertEqual({"count": 2, "components": 1, "type": "i32", "delete_after": True}, {key: face_descriptor[key] for key in ("count", "components", "type", "delete_after")})
                self.assertEqual([9, 12], list(struct.unpack("<ii", face_path.read_bytes())))
            finally:
                face_path.unlink(missing_ok=True)
        finally:
            host.close()
            host.deleteLater()
            app.processEvents()

    def test_builds_batch_payload_bounds_color_and_texture(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            texture_path = Path(temp_dir) / "base.png"
            texture_path.write_bytes(b"not a real image but an existing path is enough for URL conversion")
            normal_path = Path(temp_dir) / "normal.png"
            normal_path.write_bytes(b"existing normal")
            material_path = Path(temp_dir) / "material.png"
            material_path.write_bytes(b"existing material")
            height_path = Path(temp_dir) / "height.png"
            height_path.write_bytes(b"existing height")
            blob = b"".join(
                (
                    _vertex(-1.0, -0.5, 0.25, uv=(0.0, 0.0)),
                    _vertex(0.5, 2.0, -0.25, uv=(0.5, 0.5)),
                    _vertex(1.5, 0.25, 0.75, uv=(1.0, 1.0)),
                )
            )
            prepared = PreparedModelPreviewData(
                batches=(
                    PreparedModelPreviewBatch(
                        material_name="mat",
                        texture_name="base.dds",
                        vertex_blob=blob,
                        index_count=3,
                        preview_texture_path=str(texture_path),
                        preview_texture_flip_vertical=True,
                        preview_normal_texture_path=str(normal_path),
                        preview_normal_texture_strength=0.7,
                        preview_material_texture_path=str(material_path),
                        preview_material_texture_subtype="orm",
                        preview_material_texture_packed_channels=("ao", "roughness", "metallic"),
                        preview_height_texture_path=str(height_path),
                        has_texture_coordinates=True,
                    ),
                )
            )

            payloads = build_native_preview_payloads(prepared)

        self.assertEqual(1, len(payloads))
        payload = payloads[0]
        self.assertEqual("mat", payload.material_name)
        self.assertEqual(3, payload.vertex_count)
        self.assertEqual((-1.0, -0.5, -0.25), payload.bounds_min)
        self.assertEqual((1.5, 2.0, 0.75), payload.bounds_max)
        self.assertEqual((0.25, 0.5, 0.75), payload.base_color)
        self.assertTrue(payload.texture_source.startswith("file:///"))
        self.assertTrue(payload.normal_texture_source.startswith("file:///"))
        self.assertTrue(payload.material_texture_source.startswith("file:///"))
        self.assertTrue(payload.height_texture_source.startswith("file:///"))
        self.assertEqual(0.7, payload.normal_texture_strength)
        self.assertEqual(("ao", "roughness", "metallic"), payload.material_texture_packed_channels)
        self.assertEqual(("occlusion", "roughness", "metalness"), payload.material_texture_slots)
        self.assertEqual({"base", "normal", "material", "height"}, {item.slot_kind for item in payload.material_texture_inputs})
        self.assertTrue(payload.texture_flip_vertical)
        self.assertTrue(payload.has_texture_coordinates)
        self.assertTrue(payload.tangents_usable)

    def test_skips_empty_batches_and_ignores_invalid_texture_paths(self) -> None:
        blob = b"".join(
            (
                _vertex(0.0, 0.0, 0.0),
                _vertex(1.0, 0.0, 0.0),
                _vertex(0.0, 1.0, 0.0),
            )
        )
        prepared = PreparedModelPreviewData(
            batches=(
                PreparedModelPreviewBatch(vertex_blob=b"", index_count=0),
                PreparedModelPreviewBatch(
                    vertex_blob=blob,
                    index_count=3,
                    preview_texture_path="missing/not_here.png",
                    has_texture_coordinates=True,
                ),
            )
        )

        payloads = build_native_preview_payloads(prepared)

        self.assertEqual(1, len(payloads))
        self.assertEqual("", payloads[0].texture_source)
        self.assertEqual((), payloads[0].material_texture_slots)
        self.assertFalse(payloads[0].texture_flip_vertical)

    def test_scene_format_payload_defaults_to_unflipped_texture_v_and_flip_override_toggles(self) -> None:
        blob = b"".join(
            (
                _vertex(0.0, 0.0, 0.0),
                _vertex(1.0, 0.0, 0.0),
                _vertex(0.0, 1.0, 0.0),
            )
        )
        prepared = PreparedModelPreviewData(
            source_path="triangle.glb",
            format="glb",
            batches=(
                PreparedModelPreviewBatch(
                    vertex_blob=blob,
                    index_count=3,
                    preview_texture_flip_vertical=None,
                    has_texture_coordinates=True,
                ),
            ),
        )

        payloads = build_native_preview_payloads(prepared)
        flipped_payloads = build_native_preview_payloads(
            prepared,
            render_settings=ModelPreviewRenderSettings(flip_texture_v=True),
        )

        self.assertFalse(payloads[0].texture_flip_vertical)
        self.assertTrue(flipped_payloads[0].texture_flip_vertical)

    def test_material_mask_slots_avoid_opacity_and_generic_blackout_sources(self) -> None:
        blob = b"".join(
            (
                _vertex(0.0, 0.0, 0.0),
                _vertex(1.0, 0.0, 0.0),
                _vertex(0.0, 1.0, 0.0),
            )
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            material_path = Path(temp_dir) / "mask.png"
            material_path.write_bytes(b"existing material mask")
            prepared = PreparedModelPreviewData(
                batches=(
                    PreparedModelPreviewBatch(
                        vertex_blob=blob,
                        index_count=3,
                        preview_material_texture_path=str(material_path),
                        preview_material_texture_subtype="material_mask",
                        preview_material_texture_packed_channels=("r", "g", "b", "alpha"),
                        has_texture_coordinates=True,
                    ),
                    PreparedModelPreviewBatch(
                        vertex_blob=blob,
                        index_count=3,
                        preview_material_texture_path=str(material_path),
                        preview_material_texture_subtype="opacity_mask",
                        preview_material_texture_packed_channels=("alpha",),
                        has_texture_coordinates=True,
                    ),
                )
            )

            payloads = build_native_preview_payloads(prepared)

        self.assertEqual(("roughness", "specular"), payloads[0].material_texture_slots)
        self.assertNotIn("opacity", payloads[0].material_texture_slots)
        self.assertEqual((), payloads[1].material_texture_slots)

    def test_qml_material_uses_opaque_safe_preview_defaults(self) -> None:
        source = Path("cdmw/ui/model_preview_native.py").read_text(encoding="utf-8")

        self.assertIn("ARCHIVE_MODEL_RENDERER_D3D11", source)
        self.assertNotIn("ExperimentalNativeD3D11PreviewPanel", source)
        self.assertNotIn("prepare_model_preview(model)", source)
        self.assertNotIn("Q" + "Quick", source)
        self.assertNotIn("PrincipledMaterial", source)

    def test_material_combiner_decodes_orm_and_rejects_technical_base(self) -> None:
        from PySide6.QtCore import QUrl
        from PySide6.QtGui import QColor, QImage

        with tempfile.TemporaryDirectory() as temp_dir:
            temp = Path(temp_dir)
            technical_base = temp / "blade_ma.png"
            base_image = QImage(2, 2, QImage.Format_RGBA8888)
            base_image.fill(QColor(210, 170, 80, 255))
            self.assertTrue(base_image.save(str(technical_base), "PNG"))
            material_path = temp / "blade_orm.png"
            material_image = QImage(2, 2, QImage.Format_RGBA8888)
            material_image.fill(QColor(64, 128, 255, 255))
            self.assertTrue(material_image.save(str(material_path), "PNG"))

            prepared = PreparedModelPreviewData(
                batches=(
                    PreparedModelPreviewBatch(
                        vertex_blob=b"".join((_vertex(0, 0, 0), _vertex(1, 0, 0), _vertex(0, 1, 0))),
                        index_count=3,
                        preview_texture_path=str(technical_base),
                        preview_material_texture_path=str(material_path),
                        preview_material_texture_subtype="orm",
                        preview_material_texture_packed_channels=("ao", "roughness", "metallic"),
                        has_texture_coordinates=True,
                    ),
                )
            )
            payload = build_native_preview_payloads(prepared)[0]
            combined = combine_preview_material(
                payload,
                temp / "out",
                0,
                settings=MaterialPreviewCombinerSettings(),
            )

            self.assertEqual("", combined.base_source)
            self.assertIn("technical base rejected", "; ".join(combined.notes))
            self.assertIn("no reliable base DDS", "; ".join(combined.notes))
            self.assertEqual(("orm",), combined.decode_modes)
            self.assertIn("roughness", combined.material_slots)
            self.assertIn("metalness", combined.material_slots)
            roughness_path = Path(QUrl(combined.roughness_source).toLocalFile())
            metalness_path = Path(QUrl(combined.metalness_source).toLocalFile())
            self.assertTrue(roughness_path.is_file())
            self.assertTrue(metalness_path.is_file())

    def test_material_combiner_generates_legacy_pbr_map_from_shader_family_inputs(self) -> None:
        from PySide6.QtCore import QUrl
        from PySide6.QtGui import QColor, QImage

        with tempfile.TemporaryDirectory() as temp_dir:
            temp = Path(temp_dir)
            mask_path = temp / "blade_ma.png"
            mask_image = QImage(3, 3, QImage.Format_RGBA8888)
            mask_image.fill(QColor(42, 112, 210, 190))
            self.assertTrue(mask_image.save(str(mask_path), "PNG"))
            spec_path = temp / "blade_sp.png"
            spec_image = QImage(3, 3, QImage.Format_RGBA8888)
            spec_image.fill(QColor(190, 180, 170, 220))
            self.assertTrue(spec_image.save(str(spec_path), "PNG"))
            payload = type(
                "Payload",
                (),
                {
                    "material_name": "CD_PHM_02_Blade_0014",
                    "texture_name": "CD_PHM_02_Blade_0014",
                    "texture_flip_vertical": False,
                    "tangents_usable": True,
                    "normal_texture_strength": 0.8,
                    "material_texture_inputs": (
                        PreviewMaterialTextureInput(
                            slot_kind="material",
                            parameter_name="_colorBlendingMaskTexture",
                            source_texture_path="cd_phm_02_blade_0014_ma.dds",
                            texture_name="cd_phm_02_blade_0014_ma.dds",
                            preview_texture_path=str(mask_path),
                            semantic_type="mask",
                            semantic_subtype="material_mask",
                            material_name="CD_PHM_02_Blade_0014",
                            shader_family="SkinnedMeshStandard_Ver2",
                            material_parameters=(
                                PreviewMaterialParameterInput(
                                    parameter_kind="byte4",
                                    parameter_name="_scratchMetallic",
                                    value="16777215",
                                ),
                            ),
                        ),
                        PreviewMaterialTextureInput(
                            slot_kind="material",
                            parameter_name="_materialTexture",
                            source_texture_path="cd_phm_02_blade_0014_sp.dds",
                            texture_name="cd_phm_02_blade_0014_sp.dds",
                            preview_texture_path=str(spec_path),
                            semantic_type="specular",
                            semantic_subtype="specular",
                            material_name="CD_PHM_02_Blade_0014",
                            shader_family="SkinnedMeshStandard_Ver2",
                            material_parameters=(
                                PreviewMaterialParameterInput(
                                    parameter_kind="byte4",
                                    parameter_name="_scratchMetallic",
                                    value="16777215",
                                ),
                            ),
                        ),
                    ),
                },
            )()

            combined = combine_preview_material(
                payload,
                temp / "out",
                0,
                settings=MaterialPreviewCombinerSettings(support_map_max_dimension=96),
            )

            self.assertIn("standard_v2_mask", combined.decode_modes)
            self.assertIn("standard_v2_specular", combined.decode_modes)
            self.assertIn("roughness", combined.material_slots)
            self.assertIn("specular", combined.material_slots)
            self.assertNotIn("metalness", combined.material_slots)
            self.assertTrue(Path(QUrl(combined.legacy_material_source).toLocalFile()).is_file())
            self.assertEqual("pbr_combined", combined.legacy_material_decode_mode)
            self.assertIn("shader rule:standard_v2", "; ".join(combined.notes))
            self.assertIn("sidecar material hints:metallic", "; ".join(combined.notes))

    def test_material_combiner_synthesizes_albedo_from_standard_v2_visible_layers(self) -> None:
        from PySide6.QtCore import QUrl
        from PySide6.QtGui import QColor, QImage

        with tempfile.TemporaryDirectory() as temp_dir:
            temp = Path(temp_dir)
            low_authority_base = temp / "cd_common_default_overlay_old.png"
            base_image = QImage(4, 4, QImage.Format_RGBA8888)
            base_image.fill(QColor(24, 24, 24, 255))
            self.assertTrue(base_image.save(str(low_authority_base), "PNG"))
            detail_diffuse = temp / "cd_texturelayer_003_0016.png"
            detail_image = QImage(4, 4, QImage.Format_RGBA8888)
            detail_image.fill(QColor(220, 48, 32, 255))
            self.assertTrue(detail_image.save(str(detail_diffuse), "PNG"))
            detail_mask = temp / "blade_mg.png"
            mask_image = QImage(4, 4, QImage.Format_RGBA8888)
            mask_image.fill(QColor(255, 0, 0, 255))
            self.assertTrue(mask_image.save(str(detail_mask), "PNG"))
            material_mask = temp / "blade_ma.png"
            material_image = QImage(4, 4, QImage.Format_RGBA8888)
            material_image.fill(QColor(70, 170, 210, 255))
            self.assertTrue(material_image.save(str(material_mask), "PNG"))
            payload = type(
                "Payload",
                (),
                {
                    "material_name": "CD_PHM_02_Blade_0014",
                    "texture_name": "CD_PHM_02_Blade_0014",
                    "texture_flip_vertical": False,
                    "tangents_usable": True,
                    "normal_texture_strength": 0.8,
                    "material_texture_inputs": (
                        PreviewMaterialTextureInput(
                            slot_kind="base",
                            parameter_name="_overlayColorTexture",
                            source_texture_path="character/texture/cd_common_default_overlay_old.dds",
                            texture_name="cd_common_default_overlay_old.dds",
                            preview_texture_path=str(low_authority_base),
                            semantic_type="color",
                            semantic_subtype="albedo",
                            material_name="CD_PHM_02_Blade_0014",
                            shader_family="SkinnedMeshStandard_Ver2",
                            confidence="pac_xml",
                            visualized=True,
                        ),
                        PreviewMaterialTextureInput(
                            slot_kind="material",
                            parameter_name="_detailDiffuseMaskR",
                            source_texture_path="character/texture/cd_texturelayer_003_0016.dds",
                            texture_name="cd_texturelayer_003_0016.dds",
                            preview_texture_path=str(detail_diffuse),
                            semantic_type="color",
                            semantic_subtype="detail_diffuse",
                            material_name="CD_PHM_02_Blade_0014",
                            shader_family="SkinnedMeshStandard_Ver2",
                            material_parameters=(
                                PreviewMaterialParameterInput(
                                    parameter_kind="byte4",
                                    parameter_name="_dyeingGlobalOpacity",
                                    value="255",
                                ),
                            ),
                            visualized=True,
                        ),
                        PreviewMaterialTextureInput(
                            slot_kind="material",
                            parameter_name="_detailMaskTexture",
                            source_texture_path="character/texture/cd_phm_02_blade_0014_mg.dds",
                            texture_name="cd_phm_02_blade_0014_mg.dds",
                            preview_texture_path=str(detail_mask),
                            semantic_type="mask",
                            semantic_subtype="detail_mask",
                            material_name="CD_PHM_02_Blade_0014",
                            shader_family="SkinnedMeshStandard_Ver2",
                            visualized=True,
                        ),
                        PreviewMaterialTextureInput(
                            slot_kind="material",
                            parameter_name="_colorBlendingMaskTexture",
                            source_texture_path="character/texture/cd_phm_02_blade_0014_ma.dds",
                            texture_name="cd_phm_02_blade_0014_ma.dds",
                            preview_texture_path=str(material_mask),
                            semantic_type="mask",
                            semantic_subtype="material_mask",
                            material_name="CD_PHM_02_Blade_0014",
                            shader_family="SkinnedMeshStandard_Ver2",
                            visualized=True,
                        ),
                    ),
                },
            )()

            combined = combine_preview_material(
                payload,
                temp / "out",
                0,
                settings=MaterialPreviewCombinerSettings(support_map_max_dimension=96),
            )

            self.assertTrue(combined.base_source)
            self.assertIn("standard_v2_mask", combined.decode_modes)
            self.assertIn("standard_v2_detail", combined.decode_modes)
            self.assertNotIn("visible_color", combined.decode_modes)
            self.assertIn("albedo synthesized:detail:r", "; ".join(combined.notes))
            self.assertIn("registry:standard_v2", "; ".join(combined.notes))
            albedo = QImage(QUrl(combined.base_source).toLocalFile())
            self.assertFalse(albedo.isNull())
            color = albedo.pixelColor(0, 0)
            self.assertGreater(color.red(), color.green())
            self.assertGreater(color.red(), 80)

    def test_material_combiner_does_not_decode_visible_detail_diffuse_as_pbr_mask(self) -> None:
        from PySide6.QtCore import QUrl
        from PySide6.QtGui import QColor, QImage

        with tempfile.TemporaryDirectory() as temp_dir:
            temp = Path(temp_dir)
            detail_diffuse = temp / "cd_texturelayer_001_0001.png"
            detail_image = QImage(2, 2, QImage.Format_RGBA8888)
            detail_image.fill(QColor(80, 130, 190, 255))
            self.assertTrue(detail_image.save(str(detail_diffuse), "PNG"))
            payload = type(
                "Payload",
                (),
                {
                    "material_name": "CD_PHM_00_LB_0018",
                    "texture_name": "CD_PHM_00_LB_0018",
                    "texture_flip_vertical": False,
                    "tangents_usable": True,
                    "normal_texture_strength": 0.8,
                    "material_texture_inputs": (
                        PreviewMaterialTextureInput(
                            slot_kind="material",
                            parameter_name="_detailDiffuseMaskR",
                            source_texture_path="character/texture/cd_texturelayer_001_0001.dds",
                            texture_name="cd_texturelayer_001_0001.dds",
                            preview_texture_path=str(detail_diffuse),
                            semantic_type="color",
                            semantic_subtype="detail_diffuse",
                            material_name="CD_PHM_00_LB_0018",
                            shader_family="SkinnedMeshStandard_Ver2",
                            visualized=True,
                        ),
                    ),
                },
            )()

            combined = combine_preview_material(
                payload,
                temp / "out",
                0,
                settings=MaterialPreviewCombinerSettings(),
            )

            self.assertTrue(combined.base_source)
            self.assertEqual((), combined.decode_modes)
            self.assertEqual((), combined.material_slots)
            self.assertEqual("", combined.legacy_material_source)
            self.assertIn("no reliable base DDS", "; ".join(combined.notes))
            albedo = QImage(QUrl(combined.base_source).toLocalFile())
            self.assertFalse(albedo.isNull())
            self.assertEqual(80, albedo.pixelColor(0, 0).red())

    def test_material_combiner_gates_standard_v2_detail_material_by_detail_mask(self) -> None:
        from PySide6.QtGui import QColor, QImage

        with tempfile.TemporaryDirectory() as temp_dir:
            temp = Path(temp_dir)
            detail_mask = temp / "blade_mg.png"
            mask_image = QImage(3, 3, QImage.Format_RGBA8888)
            mask_image.fill(QColor(0, 0, 0, 255))
            self.assertTrue(mask_image.save(str(detail_mask), "PNG"))
            detail_material = temp / "blade_detail_sp.png"
            material_image = QImage(3, 3, QImage.Format_RGBA8888)
            material_image.fill(QColor(240, 240, 240, 255))
            self.assertTrue(material_image.save(str(detail_material), "PNG"))
            payload = type(
                "Payload",
                (),
                {
                    "material_name": "CD_PHM_02_Blade_0014",
                    "texture_name": "CD_PHM_02_Blade_0014",
                    "texture_flip_vertical": False,
                    "tangents_usable": True,
                    "normal_texture_strength": 0.8,
                    "material_texture_inputs": (
                        PreviewMaterialTextureInput(
                            slot_kind="material",
                            parameter_name="_detailMaskTexture",
                            source_texture_path="cd_phm_02_blade_0014_mg.dds",
                            texture_name="cd_phm_02_blade_0014_mg.dds",
                            preview_texture_path=str(detail_mask),
                            semantic_type="mask",
                            semantic_subtype="detail_mask",
                            material_name="CD_PHM_02_Blade_0014",
                            shader_family="SkinnedMeshStandard_Ver2",
                        ),
                        PreviewMaterialTextureInput(
                            slot_kind="material",
                            parameter_name="_detailMaterialMaskR",
                            source_texture_path="cd_texturelayer_003_0016_sp.dds",
                            texture_name="cd_texturelayer_003_0016_sp.dds",
                            preview_texture_path=str(detail_material),
                            semantic_type="material",
                            semantic_subtype="material_response",
                            material_name="CD_PHM_02_Blade_0014",
                            shader_family="SkinnedMeshStandard_Ver2",
                        ),
                    ),
                },
            )()

            combined = combine_preview_material(
                payload,
                temp / "out",
                0,
                settings=MaterialPreviewCombinerSettings(support_map_max_dimension=96),
            )

            self.assertIn("standard_v2_detail", combined.decode_modes)
            self.assertIn("standard_v2_material", combined.decode_modes)
            self.assertEqual((), combined.material_slots)
            self.assertEqual("", combined.legacy_material_source)
            self.assertIn("material layer mask applied:detail:r", "; ".join(combined.notes))

    def test_material_combiner_gates_standard_v2_channel_with_color_blending_flag(self) -> None:
        from PySide6.QtGui import QColor, QImage

        with tempfile.TemporaryDirectory() as temp_dir:
            temp = Path(temp_dir)
            detail_mask = temp / "blade_mg.png"
            mask_image = QImage(3, 3, QImage.Format_RGBA8888)
            mask_image.fill(QColor(255, 255, 255, 255))
            self.assertTrue(mask_image.save(str(detail_mask), "PNG"))
            detail_material = temp / "blade_detail_sp.png"
            material_image = QImage(3, 3, QImage.Format_RGBA8888)
            material_image.fill(QColor(255, 255, 255, 255))
            self.assertTrue(material_image.save(str(detail_material), "PNG"))
            parameters = (
                PreviewMaterialParameterInput(
                    parameter_kind="bitflag",
                    parameter_name="_colorBlendingFlag",
                    value="2",
                    index=1,
                ),
                PreviewMaterialParameterInput(
                    parameter_kind="texture",
                    parameter_name="_detailMaterialMaskR",
                    texture_path="cd_texturelayer_003_0016_sp.dds",
                    index=2,
                ),
            )
            payload = type(
                "Payload",
                (),
                {
                    "material_name": "CD_PHM_02_Blade_0014",
                    "texture_name": "CD_PHM_02_Blade_0014",
                    "texture_flip_vertical": False,
                    "tangents_usable": True,
                    "normal_texture_strength": 0.8,
                    "material_texture_inputs": (
                        PreviewMaterialTextureInput(
                            slot_kind="material",
                            parameter_name="_detailMaskTexture",
                            source_texture_path="cd_phm_02_blade_0014_mg.dds",
                            texture_name="cd_phm_02_blade_0014_mg.dds",
                            preview_texture_path=str(detail_mask),
                            semantic_type="mask",
                            semantic_subtype="detail_mask",
                            material_name="CD_PHM_02_Blade_0014",
                            shader_family="SkinnedMeshStandard_Ver2",
                            material_parameters=parameters,
                        ),
                        PreviewMaterialTextureInput(
                            slot_kind="material",
                            parameter_name="_detailMaterialMaskR",
                            source_texture_path="cd_texturelayer_003_0016_sp.dds",
                            texture_name="cd_texturelayer_003_0016_sp.dds",
                            preview_texture_path=str(detail_material),
                            semantic_type="material",
                            semantic_subtype="material_response",
                            material_name="CD_PHM_02_Blade_0014",
                            shader_family="SkinnedMeshStandard_Ver2",
                            material_parameters=parameters,
                        ),
                    ),
                },
            )()

            combined = combine_preview_material(
                payload,
                temp / "out",
                0,
                settings=MaterialPreviewCombinerSettings(support_map_max_dimension=96),
            )

            self.assertIn("standard_v2_material", combined.decode_modes)
            self.assertEqual((), combined.material_slots)
            self.assertIn("material layer disabled by colorBlendingFlag:detail:r", "; ".join(combined.notes))

    def test_material_combiner_uses_standard_v2_channel_specific_scratch_hints(self) -> None:
        from PySide6.QtGui import QColor, QImage

        with tempfile.TemporaryDirectory() as temp_dir:
            temp = Path(temp_dir)
            detail_mask = temp / "blade_mg.png"
            mask_image = QImage(3, 3, QImage.Format_RGBA8888)
            mask_image.fill(QColor(255, 255, 255, 255))
            self.assertTrue(mask_image.save(str(detail_mask), "PNG"))
            detail_material = temp / "blade_detail_sp.png"
            material_image = QImage(3, 3, QImage.Format_RGBA8888)
            material_image.fill(QColor(0, 0, 0, 255))
            self.assertTrue(material_image.save(str(detail_material), "PNG"))
            payload = type(
                "Payload",
                (),
                {
                    "material_name": "CD_PHM_02_Blade_0014",
                    "texture_name": "CD_PHM_02_Blade_0014",
                    "texture_flip_vertical": False,
                    "tangents_usable": True,
                    "normal_texture_strength": 0.8,
                    "material_texture_inputs": (
                        PreviewMaterialTextureInput(
                            slot_kind="material",
                            parameter_name="_detailMaskTexture",
                            source_texture_path="cd_phm_02_blade_0014_mg.dds",
                            texture_name="cd_phm_02_blade_0014_mg.dds",
                            preview_texture_path=str(detail_mask),
                            semantic_type="mask",
                            semantic_subtype="detail_mask",
                            material_name="CD_PHM_02_Blade_0014",
                            shader_family="SkinnedMeshStandard_Ver2",
                        ),
                        PreviewMaterialTextureInput(
                            slot_kind="material",
                            parameter_name="_detailMaterialMaskR",
                            source_texture_path="cd_texturelayer_003_0016_sp.dds",
                            texture_name="cd_texturelayer_003_0016_sp.dds",
                            preview_texture_path=str(detail_material),
                            semantic_type="material",
                            semantic_subtype="material_response",
                            material_name="CD_PHM_02_Blade_0014",
                            shader_family="SkinnedMeshStandard_Ver2",
                            material_parameters=(
                                PreviewMaterialParameterInput(
                                    parameter_kind="byte4",
                                    parameter_name="_scratchMetallic",
                                    value=str(0x00FF0000),
                                ),
                            ),
                        ),
                    ),
                },
            )()

            combined = combine_preview_material(
                payload,
                temp / "out",
                0,
                settings=MaterialPreviewCombinerSettings(support_map_max_dimension=96),
            )

            self.assertIn("standard_v2_material", combined.decode_modes)
            self.assertIn("roughness", combined.material_slots)
            self.assertIn("specular", combined.material_slots)
            self.assertNotIn("metalness", combined.material_slots)
            self.assertNotIn("sidecar material hints:metallic", "; ".join(combined.notes))

    def test_legacy_combiner_cache_key_includes_sidecar_parameter_values(self) -> None:
        from cdmw.ui.widgets import NativePreviewPanel

        def model_with_parameter(value: str) -> ModelPreviewData:
            return ModelPreviewData(
                path="character/model/example.pac",
                meshes=[
                    ModelPreviewMesh(
                        material_name="blade",
                        preview_material_texture_inputs=(
                            PreviewMaterialTextureInput(
                                slot_kind="material",
                                parameter_name="_materialTexture",
                                preview_texture_path="blade_sp.png",
                                source_texture_path="blade_sp.dds",
                                shader_family="SkinnedMeshStandard_Ver2",
                                material_parameters=(
                                    PreviewMaterialParameterInput(
                                        parameter_kind="byte4",
                                        parameter_name="_scratchMetallic",
                                        value=value,
                                    ),
                                ),
                            ),
                        ),
                    )
                ],
            )

        first = NativePreviewPanel._material_combiner_cache_dir(model_with_parameter("0"))
        second = NativePreviewPanel._material_combiner_cache_dir(model_with_parameter("16777215"))

        self.assertNotEqual(first, second)

    def test_legacy_combiner_cache_key_includes_input_packed_channels(self) -> None:
        def model_with_channels(channels: tuple[str, ...]) -> ModelPreviewData:
            return ModelPreviewData(
                path="character/model/example.gltf",
                meshes=[
                    ModelPreviewMesh(
                        material_name="blade",
                        preview_material_texture_inputs=(
                            PreviewMaterialTextureInput(
                                slot_kind="material",
                                parameter_name="_materialTexture",
                                preview_texture_path="shared.png",
                                source_texture_path="shared.png",
                                semantic_type="material",
                                semantic_subtype="metallic_roughness",
                                packed_channels=channels,
                            ),
                        ),
                    )
                ],
            )

        first = NativePreviewPanel._material_combiner_cache_dir(model_with_channels(("roughness", "metallic")))
        second = NativePreviewPanel._material_combiner_cache_dir(model_with_channels(("specular", "glossiness")))

        self.assertNotEqual(first, second)

    def test_legacy_combiner_cache_key_includes_numeric_parameter_values(self) -> None:
        def model_with_numeric(value: float) -> ModelPreviewData:
            return ModelPreviewData(
                path="character/model/example.gltf",
                meshes=[
                    ModelPreviewMesh(
                        material_name="blade",
                        preview_material_texture_inputs=(
                            PreviewMaterialTextureInput(
                                slot_kind="material",
                                parameter_name="_metallicRoughnessTexture",
                                preview_texture_path="blade_mr.png",
                                source_texture_path="blade_mr.png",
                                semantic_type="material",
                                semantic_subtype="metallic_roughness",
                                packed_channels=("roughness", "metallic"),
                                material_parameters=(
                                    PreviewMaterialParameterInput(
                                        parameter_kind="float",
                                        parameter_name="_roughnessFactor",
                                        numeric_value=value,
                                    ),
                                ),
                            ),
                        ),
                    )
                ],
            )

        first = NativePreviewPanel._material_combiner_cache_dir(model_with_numeric(0.2))
        second = NativePreviewPanel._material_combiner_cache_dir(model_with_numeric(0.8))

        self.assertNotEqual(first, second)

    def test_material_combiner_uses_pami_multitextured_layer_base_as_albedo_layer(self) -> None:
        from PySide6.QtCore import QUrl
        from PySide6.QtGui import QColor, QImage

        with tempfile.TemporaryDirectory() as temp_dir:
            temp = Path(temp_dir)
            base_path = temp / "cd_wall_mud_12.png"
            base_image = QImage(4, 4, QImage.Format_RGBA8888)
            base_image.fill(QColor(80, 55, 40, 255))
            self.assertTrue(base_image.save(str(base_path), "PNG"))
            layer_path = temp / "cd_wall_rough_03.png"
            layer_image = QImage(4, 4, QImage.Format_RGBA8888)
            layer_image.fill(QColor(160, 150, 140, 255))
            self.assertTrue(layer_image.save(str(layer_path), "PNG"))
            layer_mask_path = temp / "cd_wall_01_mix.png"
            mask_image = QImage(4, 4, QImage.Format_RGBA8888)
            mask_image.fill(QColor(255, 255, 255, 255))
            self.assertTrue(mask_image.save(str(layer_mask_path), "PNG"))
            layer_spec_path = temp / "cd_wall_rough_03_sp.png"
            spec_image = QImage(4, 4, QImage.Format_RGBA8888)
            spec_image.fill(QColor(190, 190, 190, 255))
            self.assertTrue(spec_image.save(str(layer_spec_path), "PNG"))
            material_parameters = (
                PreviewMaterialParameterInput(
                    parameter_kind="float",
                    parameter_name="_alphaHeightIntensityX",
                    numeric_value=0.6,
                    value="0.600000",
                ),
                PreviewMaterialParameterInput(
                    parameter_kind="color",
                    parameter_name="_baseHeightTintColor",
                    color_value=(1.0, 0.75, 0.64),
                    value="1.000000 0.750000 0.640000",
                ),
            )
            payload = type(
                "Payload",
                (),
                {
                    "material_name": "cd_wall_mud_12",
                    "texture_name": "cd_wall_mud_12",
                    "texture_flip_vertical": False,
                    "tangents_usable": True,
                    "normal_texture_strength": 0.8,
                    "material_texture_inputs": (
                        PreviewMaterialTextureInput(
                            slot_kind="base",
                            parameter_name="_baseColorTexture",
                            source_texture_path="object/texture/cd_wall_mud_12.dds",
                            texture_name="cd_wall_mud_12.dds",
                            preview_texture_path=str(base_path),
                            semantic_type="color",
                            semantic_subtype="albedo",
                            shader_family="MultiTextured",
                            material_parameters=material_parameters,
                            visualized=True,
                        ),
                        PreviewMaterialTextureInput(
                            slot_kind="material",
                            parameter_name="_layerBaseColorTexture",
                            source_texture_path="object/texture/cd_wall_rough_03.dds",
                            texture_name="cd_wall_rough_03.dds",
                            preview_texture_path=str(layer_path),
                            semantic_type="color",
                            semantic_subtype="detail_diffuse",
                            shader_family="MultiTextured",
                            material_parameters=material_parameters,
                            visualized=True,
                        ),
                        PreviewMaterialTextureInput(
                            slot_kind="material",
                            parameter_name="_layerMaskTexture",
                            source_texture_path="object/texture/cd_wall_01_mix.dds",
                            texture_name="cd_wall_01_mix.dds",
                            preview_texture_path=str(layer_mask_path),
                            semantic_type="mask",
                            semantic_subtype="mask",
                            shader_family="MultiTextured",
                            material_parameters=material_parameters,
                            visualized=True,
                        ),
                        PreviewMaterialTextureInput(
                            slot_kind="material",
                            parameter_name="_layerSpecularTexture",
                            source_texture_path="object/texture/cd_wall_rough_03_sp.dds",
                            texture_name="cd_wall_rough_03_sp.dds",
                            preview_texture_path=str(layer_spec_path),
                            semantic_type="mask",
                            semantic_subtype="specular",
                            shader_family="MultiTextured",
                            material_parameters=material_parameters,
                            visualized=True,
                        ),
                    ),
                },
            )()

            combined = combine_preview_material(
                payload,
                temp / "out",
                0,
                settings=MaterialPreviewCombinerSettings(),
            )

            self.assertIn("shader rule:static_multitextured", "; ".join(combined.notes))
            self.assertIn("albedo synthesized:layer", "; ".join(combined.notes))
            self.assertIn("specular", combined.material_slots)
            albedo = QImage(QUrl(combined.base_source).toLocalFile())
            self.assertFalse(albedo.isNull())
            color = albedo.pixelColor(0, 0)
            self.assertGreater(color.red(), 100)
            self.assertGreater(color.green(), 70)

    def test_material_combiner_uses_pami_rgb_mask_for_static_multitextured_color_layers(self) -> None:
        from PySide6.QtCore import QUrl
        from PySide6.QtGui import QColor, QImage

        with tempfile.TemporaryDirectory() as temp_dir:
            temp = Path(temp_dir)
            base_path = temp / "cd_stone_base.png"
            base_image = QImage(4, 4, QImage.Format_RGBA8888)
            base_image.fill(QColor(48, 44, 42, 255))
            self.assertTrue(base_image.save(str(base_path), "PNG"))
            layer_path = temp / "cd_stone_moss.png"
            layer_image = QImage(4, 4, QImage.Format_RGBA8888)
            layer_image.fill(QColor(120, 190, 95, 255))
            self.assertTrue(layer_image.save(str(layer_path), "PNG"))
            rgb_mask_path = temp / "cd_stone_rgb.png"
            mask_image = QImage(4, 4, QImage.Format_RGBA8888)
            mask_image.fill(QColor(0, 255, 0, 255))
            self.assertTrue(mask_image.save(str(rgb_mask_path), "PNG"))
            material_path = temp / "cd_stone_moss_m.png"
            material_image = QImage(4, 4, QImage.Format_RGBA8888)
            material_image.fill(QColor(35, 70, 220, 255))
            self.assertTrue(material_image.save(str(material_path), "PNG"))
            material_parameters = (
                PreviewMaterialParameterInput(
                    parameter_kind="float",
                    parameter_name="_alphaHeightIntensityX",
                    numeric_value=0.7,
                    value="0.700000",
                ),
                PreviewMaterialParameterInput(
                    parameter_kind="color",
                    parameter_name="_tintColorG",
                    color_value=(0.80, 1.00, 0.70),
                    value="0.800000 1.000000 0.700000",
                ),
            )
            payload = type(
                "Payload",
                (),
                {
                    "material_name": "cd_static_moss",
                    "texture_name": "cd_static_moss",
                    "texture_flip_vertical": False,
                    "tangents_usable": True,
                    "normal_texture_strength": 0.8,
                    "material_texture_inputs": (
                        PreviewMaterialTextureInput(
                            slot_kind="base",
                            parameter_name="_baseColorTexture",
                            source_texture_path="object/texture/cd_stone_base.dds",
                            texture_name="cd_stone_base.dds",
                            preview_texture_path=str(base_path),
                            semantic_type="color",
                            semantic_subtype="albedo",
                            shader_family="MultiTextured",
                            material_parameters=material_parameters,
                            visualized=True,
                        ),
                        PreviewMaterialTextureInput(
                            slot_kind="material",
                            parameter_name="_colorTextureG",
                            source_texture_path="object/texture/cd_stone_moss.dds",
                            texture_name="cd_stone_moss.dds",
                            preview_texture_path=str(layer_path),
                            semantic_type="color",
                            semantic_subtype="detail_diffuse",
                            shader_family="MultiTextured",
                            material_parameters=material_parameters,
                            visualized=True,
                        ),
                        PreviewMaterialTextureInput(
                            slot_kind="material",
                            parameter_name="_rgbTexture",
                            source_texture_path="object/texture/cd_stone_rgb.dds",
                            texture_name="cd_stone_rgb.dds",
                            preview_texture_path=str(rgb_mask_path),
                            semantic_type="mask",
                            semantic_subtype="mask",
                            shader_family="MultiTextured",
                            material_parameters=material_parameters,
                            visualized=True,
                        ),
                        PreviewMaterialTextureInput(
                            slot_kind="material",
                            parameter_name="_materialTextureG",
                            source_texture_path="object/texture/cd_stone_moss_m.dds",
                            texture_name="cd_stone_moss_m.dds",
                            preview_texture_path=str(material_path),
                            semantic_type="material",
                            semantic_subtype="material_response",
                            shader_family="MultiTextured",
                            material_parameters=material_parameters,
                            visualized=True,
                        ),
                    ),
                },
            )()

            combined = combine_preview_material(
                payload,
                temp / "out",
                0,
                settings=MaterialPreviewCombinerSettings(),
            )

            notes = "; ".join(combined.notes)
            self.assertIn("shader rule:static_multitextured", notes)
            self.assertIn("albedo synthesized:layer:g", notes)
            self.assertEqual(("static_multitextured_material",), combined.decode_modes)
            self.assertIn("roughness", combined.material_slots)
            self.assertIn("specular", combined.material_slots)
            albedo = QImage(QUrl(combined.base_source).toLocalFile())
            self.assertFalse(albedo.isNull())
            color = albedo.pixelColor(0, 0)
            self.assertGreater(color.green(), 120)
            self.assertGreater(color.red(), 80)

    def test_material_combiner_recognizes_emissive_v2_as_standard_v2_family(self) -> None:
        from PySide6.QtCore import QUrl
        from PySide6.QtGui import QColor, QImage

        with tempfile.TemporaryDirectory() as temp_dir:
            temp = Path(temp_dir)
            emissive_path = temp / "emi.png"
            emissive_image = QImage(4, 4, QImage.Format_RGBA8888)
            emissive_image.fill(QColor(180, 96, 32, 255))
            self.assertTrue(emissive_image.save(str(emissive_path), "PNG"))
            mask_path = temp / "emi_ma.png"
            mask_image = QImage(4, 4, QImage.Format_RGBA8888)
            mask_image.fill(QColor(42, 150, 215, 255))
            self.assertTrue(mask_image.save(str(mask_path), "PNG"))
            prepared = PreparedModelPreviewData(
                batches=(
                    PreparedModelPreviewBatch(
                        vertex_blob=b"".join((_vertex(0, 0, 0), _vertex(1, 0, 0), _vertex(0, 1, 0))),
                        index_count=3,
                        preview_material_texture_inputs=(
                            PreviewMaterialTextureInput(
                                slot_kind="base",
                                parameter_name="_emissiveIntensityTexture",
                                texture_name="cd_fx_sword_emi.dds",
                                source_texture_path="cd_fx_sword_emi.dds",
                                preview_texture_path=str(emissive_path),
                                semantic_type="emissive",
                                semantic_subtype="emissive",
                                shader_family="SkinnedMeshEmissive_Ver2",
                                visualized=True,
                            ),
                            PreviewMaterialTextureInput(
                                slot_kind="material",
                                parameter_name="_colorBlendingMaskTexture",
                                texture_name="cd_fx_sword_ma.dds",
                                source_texture_path="cd_fx_sword_ma.dds",
                                preview_texture_path=str(mask_path),
                                semantic_type="mask",
                                semantic_subtype="material_mask",
                                shader_family="SkinnedMeshEmissive_Ver2",
                                visualized=True,
                            ),
                        ),
                        has_texture_coordinates=True,
                    ),
                )
            )
            payload = build_native_preview_payloads(prepared)[0]
            combined = combine_preview_material(
                payload,
                temp / "out",
                0,
                settings=MaterialPreviewCombinerSettings(),
            )

            self.assertIn("shader rule:emissive_v2", "; ".join(combined.notes))
            self.assertEqual(("standard_v2_mask",), combined.decode_modes)
            self.assertEqual((), combined.material_slots)
            self.assertEqual("", combined.legacy_material_source)
            albedo = QImage(QUrl(combined.base_source).toLocalFile())
            self.assertFalse(albedo.isNull())
            self.assertGreater(albedo.pixelColor(0, 0).red(), albedo.pixelColor(0, 0).blue())

    def test_material_combiner_treats_sp_as_specular_and_caps_support_maps(self) -> None:
        from PySide6.QtCore import QUrl
        from PySide6.QtGui import QColor, QImage

        with tempfile.TemporaryDirectory() as temp_dir:
            temp = Path(temp_dir)
            specular_path = temp / "skin_sp.png"
            specular_image = QImage(256, 64, QImage.Format_RGBA8888)
            specular_image.fill(QColor(72, 164, 210, 255))
            self.assertTrue(specular_image.save(str(specular_path), "PNG"))
            prepared = PreparedModelPreviewData(
                batches=(
                    PreparedModelPreviewBatch(
                        vertex_blob=b"".join((_vertex(0, 0, 0), _vertex(1, 0, 0), _vertex(0, 1, 0))),
                        index_count=3,
                        preview_material_texture_inputs=(
                            PreviewMaterialTextureInput(
                                slot_kind="material",
                                texture_name="cd_phw_00_nude_00_0001_sp.dds",
                                source_texture_path="cd_phw_00_nude_00_0001_sp.dds",
                                preview_texture_path=str(specular_path),
                                semantic_type="material",
                                semantic_subtype="material_mask",
                                visualized=True,
                            ),
                        ),
                        has_texture_coordinates=True,
                    ),
                )
            )
            payload = build_native_preview_payloads(prepared)[0]
            combined = combine_preview_material(
                payload,
                temp / "out",
                0,
                settings=MaterialPreviewCombinerSettings(support_map_max_dimension=128),
            )

            self.assertEqual(("specular",), combined.decode_modes)
            self.assertEqual(("specular",), combined.material_slots)
            self.assertEqual("", combined.occlusion_source)
            self.assertEqual("", combined.roughness_source)
            self.assertEqual("", combined.metalness_source)
            specular_image = QImage(QUrl(combined.specular_source).toLocalFile())
            self.assertFalse(specular_image.isNull())
            self.assertLessEqual(max(specular_image.width(), specular_image.height()), 128)

    def test_material_combiner_uses_sidecar_parameter_context_for_skin_sp_maps(self) -> None:
        from PySide6.QtCore import QUrl
        from PySide6.QtGui import QColor, QImage

        with tempfile.TemporaryDirectory() as temp_dir:
            temp = Path(temp_dir)
            skin_material_path = temp / "skin_sp.png"
            skin_material_image = QImage(4, 4, QImage.Format_RGBA8888)
            skin_material_image.fill(QColor(72, 164, 210, 255))
            self.assertTrue(skin_material_image.save(str(skin_material_path), "PNG"))
            prepared = PreparedModelPreviewData(
                batches=(
                    PreparedModelPreviewBatch(
                        vertex_blob=b"".join((_vertex(0, 0, 0), _vertex(1, 0, 0), _vertex(0, 1, 0))),
                        index_count=3,
                        preview_material_texture_inputs=(
                            PreviewMaterialTextureInput(
                                slot_kind="material",
                                parameter_name="_materialTexture",
                                texture_name="cd_phw_00_nude_00_0001_sp.dds",
                                source_texture_path="cd_phw_00_nude_00_0001_sp.dds",
                                preview_texture_path=str(skin_material_path),
                                semantic_type="material",
                                semantic_subtype="material_mask",
                                shader_family="SkinnedMeshSkin",
                                visualized=True,
                            ),
                        ),
                        has_texture_coordinates=True,
                    ),
                )
            )
            payload = build_native_preview_payloads(prepared)[0]
            combined = combine_preview_material(
                payload,
                temp / "out",
                0,
                settings=MaterialPreviewCombinerSettings(),
            )

            self.assertEqual(("skin_material",), combined.decode_modes)
            self.assertEqual(("roughness", "specular"), combined.material_slots)
            self.assertEqual("", combined.metalness_source)
            roughness_image = QImage(QUrl(combined.roughness_source).toLocalFile())
            specular_image = QImage(QUrl(combined.specular_source).toLocalFile())
            self.assertFalse(roughness_image.isNull())
            self.assertFalse(specular_image.isNull())
            self.assertLess(specular_image.pixelColor(0, 0).red(), 120)

    def test_material_combiner_caps_nonmetal_surface_material_response(self) -> None:
        from PySide6.QtCore import QUrl
        from PySide6.QtGui import QColor, QImage

        cases = (
            ("CD_PHM_00_Cloak_0054", "cloth"),
            ("CD_PHM_02_Handle_0015", "leather"),
            ("CD_PHM_01_Stick_0001", "wood"),
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            temp = Path(temp_dir)
            for index, (material_name, category) in enumerate(cases):
                material_path = temp / f"{category}_ma.png"
                material_image = QImage(4, 4, QImage.Format_RGBA8888)
                material_image.fill(QColor(32, 20, 255, 255))
                self.assertTrue(material_image.save(str(material_path), "PNG"))
                prepared = PreparedModelPreviewData(
                    batches=(
                        PreparedModelPreviewBatch(
                            material_name=material_name,
                            texture_name=material_name,
                            vertex_blob=b"".join((_vertex(0, 0, 0), _vertex(1, 0, 0), _vertex(0, 1, 0))),
                            index_count=3,
                            preview_material_texture_inputs=(
                                PreviewMaterialTextureInput(
                                    slot_kind="material",
                                    parameter_name="_materialTexture",
                                    texture_name=f"{material_name.lower()}_ma.dds",
                                    source_texture_path=f"{material_name.lower()}_ma.dds",
                                    preview_texture_path=str(material_path),
                                    semantic_type="mask",
                                    semantic_subtype="material_mask",
                                    material_name=material_name,
                                    shader_family="SkinnedMeshStandardVer2",
                                    visualized=True,
                                ),
                            ),
                            has_texture_coordinates=True,
                        ),
                    )
                )
                payload = build_native_preview_payloads(prepared)[0]
                combined = combine_preview_material(
                    payload,
                    temp / f"out_{index}",
                    0,
                    settings=MaterialPreviewCombinerSettings(),
                )

                self.assertIn("standard_v2_material", combined.decode_modes)
                self.assertEqual("", combined.metalness_source)
                self.assertIn("roughness", combined.material_slots)
                self.assertIn("specular", combined.material_slots)
                self.assertIn(f"nonmetal material response clamp:{category}", "; ".join(combined.notes))
                specular_image = QImage(QUrl(combined.specular_source).toLocalFile())
                self.assertFalse(specular_image.isNull())
                self.assertLessEqual(specular_image.pixelColor(0, 0).red(), 118)

    def test_material_combiner_keeps_metallic_response_for_blade(self) -> None:
        from PySide6.QtCore import QUrl
        from PySide6.QtGui import QColor, QImage

        with tempfile.TemporaryDirectory() as temp_dir:
            temp = Path(temp_dir)
            material_path = temp / "blade_ma.png"
            material_image = QImage(4, 4, QImage.Format_RGBA8888)
            material_image.fill(QColor(32, 20, 255, 255))
            self.assertTrue(material_image.save(str(material_path), "PNG"))
            prepared = PreparedModelPreviewData(
                batches=(
                    PreparedModelPreviewBatch(
                        material_name="CD_PHM_02_Blade_0015",
                        texture_name="CD_PHM_02_Blade_0015",
                        vertex_blob=b"".join((_vertex(0, 0, 0), _vertex(1, 0, 0), _vertex(0, 1, 0))),
                        index_count=3,
                        preview_material_texture_inputs=(
                            PreviewMaterialTextureInput(
                                slot_kind="material",
                                parameter_name="_materialTexture",
                                texture_name="cd_phm_02_blade_0015_ma.dds",
                                source_texture_path="cd_phm_02_blade_0015_ma.dds",
                                preview_texture_path=str(material_path),
                                semantic_type="mask",
                                semantic_subtype="material_mask",
                                material_name="CD_PHM_02_Blade_0015",
                                shader_family="SkinnedMeshStandardVer2",
                                visualized=True,
                            ),
                        ),
                        has_texture_coordinates=True,
                    ),
                )
            )
            payload = build_native_preview_payloads(prepared)[0]
            combined = combine_preview_material(
                payload,
                temp / "out",
                0,
                settings=MaterialPreviewCombinerSettings(),
            )

            self.assertIn("metalness", combined.material_slots)
            metalness_image = QImage(QUrl(combined.metalness_source).toLocalFile())
            self.assertFalse(metalness_image.isNull())
            self.assertGreater(metalness_image.pixelColor(0, 0).red(), 90)
            self.assertNotIn("nonmetal material response clamp", "; ".join(combined.notes))

    def test_material_combiner_combines_mask_and_specular_by_slot(self) -> None:
        from PySide6.QtCore import QUrl
        from PySide6.QtGui import QColor, QImage

        with tempfile.TemporaryDirectory() as temp_dir:
            temp = Path(temp_dir)
            mask_path = temp / "blade_ma.png"
            mask_image = QImage(4, 4, QImage.Format_RGBA8888)
            mask_image.fill(QColor(64, 180, 230, 255))
            self.assertTrue(mask_image.save(str(mask_path), "PNG"))
            specular_path = temp / "blade_sp.png"
            specular_image = QImage(4, 4, QImage.Format_RGBA8888)
            specular_image.fill(QColor(250, 250, 250, 255))
            self.assertTrue(specular_image.save(str(specular_path), "PNG"))
            prepared = PreparedModelPreviewData(
                batches=(
                    PreparedModelPreviewBatch(
                        material_name="CD_PHM_01_Blade_0059",
                        texture_name="CD_PHM_01_Blade_0059",
                        vertex_blob=b"".join((_vertex(0, 0, 0), _vertex(1, 0, 0), _vertex(0, 1, 0))),
                        index_count=3,
                        preview_material_texture_inputs=(
                            PreviewMaterialTextureInput(
                                slot_kind="material",
                                texture_name="cd_phw_00_head_00_0001_01_sp.dds",
                                source_texture_path="cd_phw_00_head_00_0001_01_sp.dds",
                                preview_texture_path=str(specular_path),
                                semantic_type="mask",
                                semantic_subtype="specular",
                                visualized=True,
                            ),
                            PreviewMaterialTextureInput(
                                slot_kind="material",
                                texture_name="cd_phm_01_blade_0059_00_01_01_ma.dds",
                                source_texture_path="cd_phm_01_blade_0059_00_01_01_ma.dds",
                                preview_texture_path=str(mask_path),
                                semantic_type="mask",
                                semantic_subtype="material_mask",
                                visualized=True,
                            ),
                            PreviewMaterialTextureInput(
                                slot_kind="material",
                                texture_name="cd_phm_01_blade_0059_00_01_01_sp.dds",
                                source_texture_path="cd_phm_01_blade_0059_00_01_01_sp.dds",
                                preview_texture_path=str(specular_path),
                                semantic_type="mask",
                                semantic_subtype="specular",
                                visualized=True,
                            ),
                            PreviewMaterialTextureInput(
                                slot_kind="material",
                                texture_name="cd_texturelayer_skin_0001_sp.dds",
                                source_texture_path="cd_texturelayer_skin_0001_sp.dds",
                                preview_texture_path=str(specular_path),
                                semantic_type="mask",
                                semantic_subtype="packed_mask",
                                visualized=True,
                            ),
                        ),
                        has_texture_coordinates=True,
                    ),
                )
            )
            payload = build_native_preview_payloads(prepared)[0]
            combined = combine_preview_material(
                payload,
                temp / "out",
                0,
                settings=MaterialPreviewCombinerSettings(),
            )

            self.assertEqual(("material_mask", "specular"), combined.decode_modes)
            self.assertEqual(("occlusion", "roughness", "metalness", "specular"), combined.material_slots)
            self.assertIn("material inputs combined", "; ".join(combined.notes))
            self.assertIn("material slots blended", "; ".join(combined.notes))
            self.assertIn("material inputs culled:4->2", "; ".join(combined.notes))
            specular_image = QImage(QUrl(combined.specular_source).toLocalFile())
            metalness_image = QImage(QUrl(combined.metalness_source).toLocalFile())
            self.assertFalse(specular_image.isNull())
            self.assertFalse(metalness_image.isNull())
            self.assertGreater(specular_image.pixelColor(0, 0).red(), 230)
            self.assertGreater(metalness_image.pixelColor(0, 0).red(), 40)

    def test_material_combiner_selects_highest_contrast_height_input(self) -> None:
        from PySide6.QtCore import QUrl
        from PySide6.QtGui import QColor, QImage

        with tempfile.TemporaryDirectory() as temp_dir:
            temp = Path(temp_dir)
            flat_path = temp / "blade_flat_disp.png"
            flat_image = QImage(2, 2, QImage.Format_RGBA8888)
            flat_image.fill(QColor(128, 128, 128, 255))
            self.assertTrue(flat_image.save(str(flat_path), "PNG"))
            relief_path = temp / "blade_detail_disp.png"
            relief_image = QImage(2, 2, QImage.Format_RGBA8888)
            relief_image.setPixelColor(0, 0, QColor(20, 20, 20, 255))
            relief_image.setPixelColor(1, 0, QColor(230, 230, 230, 255))
            relief_image.setPixelColor(0, 1, QColor(80, 80, 80, 255))
            relief_image.setPixelColor(1, 1, QColor(180, 180, 180, 255))
            self.assertTrue(relief_image.save(str(relief_path), "PNG"))
            prepared = PreparedModelPreviewData(
                batches=(
                    PreparedModelPreviewBatch(
                        vertex_blob=b"".join((_vertex(0, 0, 0), _vertex(1, 0, 0), _vertex(0, 1, 0))),
                        index_count=3,
                        preview_material_texture_inputs=(
                            PreviewMaterialTextureInput(
                                slot_kind="height",
                                texture_name="blade_flat_disp.dds",
                                source_texture_path="blade_flat_disp.dds",
                                preview_texture_path=str(flat_path),
                                semantic_type="height",
                                semantic_subtype="displacement",
                                visualized=True,
                            ),
                            PreviewMaterialTextureInput(
                                slot_kind="height",
                                texture_name="blade_detail_disp.dds",
                                source_texture_path="blade_detail_disp.dds",
                                preview_texture_path=str(relief_path),
                                semantic_type="height",
                                semantic_subtype="displacement",
                                visualized=True,
                            ),
                        ),
                        has_texture_coordinates=True,
                    ),
                )
            )
            payload = build_native_preview_payloads(prepared)[0]
            combined = combine_preview_material(
                payload,
                temp / "out",
                0,
                settings=MaterialPreviewCombinerSettings(height_amount=0.12),
            )

            self.assertTrue(combined.height_source)
            self.assertGreater(combined.height_amount, 0.0)
            self.assertLessEqual(combined.height_amount, 0.12)
            self.assertIn("height selected:1", "; ".join(combined.notes))
            height_image = QImage(QUrl(combined.height_source).toLocalFile())
            self.assertFalse(height_image.isNull())

    def test_material_combiner_scales_height_from_sidecar_displacement_parameter(self) -> None:
        from PySide6.QtGui import QColor, QImage

        with tempfile.TemporaryDirectory() as temp_dir:
            temp = Path(temp_dir)
            height_path = temp / "blade_disp.png"
            height_image = QImage(2, 2, QImage.Format_RGBA8888)
            height_image.setPixelColor(0, 0, QColor(0, 0, 0, 255))
            height_image.setPixelColor(1, 0, QColor(255, 255, 255, 255))
            height_image.setPixelColor(0, 1, QColor(64, 64, 64, 255))
            height_image.setPixelColor(1, 1, QColor(192, 192, 192, 255))
            self.assertTrue(height_image.save(str(height_path), "PNG"))
            prepared = PreparedModelPreviewData(
                batches=(
                    PreparedModelPreviewBatch(
                        vertex_blob=b"".join((_vertex(0, 0, 0), _vertex(1, 0, 0), _vertex(0, 1, 0))),
                        index_count=3,
                        preview_material_texture_inputs=(
                            PreviewMaterialTextureInput(
                                slot_kind="height",
                                texture_name="blade_disp.dds",
                                source_texture_path="blade_disp.dds",
                                preview_texture_path=str(height_path),
                                semantic_type="height",
                                semantic_subtype="displacement",
                                material_parameters=(
                                    PreviewMaterialParameterInput(
                                        parameter_kind="float",
                                        parameter_name="_screenSpaceDisplacementScale",
                                        numeric_value=0.025,
                                        value="0.025000",
                                    ),
                                ),
                                visualized=True,
                            ),
                        ),
                        has_texture_coordinates=True,
                    ),
                )
            )
            payload = build_native_preview_payloads(prepared)[0]
            combined = combine_preview_material(
                payload,
                temp / "out",
                0,
                settings=MaterialPreviewCombinerSettings(height_amount=0.12),
            )

            self.assertTrue(combined.height_source)
            self.assertGreater(combined.height_amount, 0.0)
            self.assertLess(combined.height_amount, 0.04)
            self.assertIn("height scale:0.20 from _screenSpaceDisplacementScale", "; ".join(combined.notes))

    def test_material_combiner_inverts_normal_green_and_skips_flat_height(self) -> None:
        from PySide6.QtCore import QUrl
        from PySide6.QtGui import QColor, QImage

        with tempfile.TemporaryDirectory() as temp_dir:
            temp = Path(temp_dir)
            base_path = temp / "body_o.png"
            base_image = QImage(2, 2, QImage.Format_RGBA8888)
            base_image.fill(QColor(100, 80, 70, 18))
            self.assertTrue(base_image.save(str(base_path), "PNG"))
            normal_path = temp / "body_n.png"
            normal_image = QImage(1, 1, QImage.Format_RGBA8888)
            normal_image.setPixelColor(0, 0, QColor(128, 64, 255, 255))
            self.assertTrue(normal_image.save(str(normal_path), "PNG"))
            height_path = temp / "body_disp.png"
            height_image = QImage(2, 2, QImage.Format_RGBA8888)
            height_image.fill(QColor(128, 128, 128, 255))
            self.assertTrue(height_image.save(str(height_path), "PNG"))
            prepared = PreparedModelPreviewData(
                batches=(
                    PreparedModelPreviewBatch(
                        vertex_blob=b"".join((_vertex(0, 0, 0), _vertex(1, 0, 0), _vertex(0, 1, 0))),
                        index_count=3,
                        preview_texture_path=str(base_path),
                        preview_normal_texture_path=str(normal_path),
                        preview_height_texture_path=str(height_path),
                        has_texture_coordinates=True,
                    ),
                )
            )
            payload = build_native_preview_payloads(prepared)[0]
            combined = combine_preview_material(
                payload,
                temp / "out",
                0,
                settings=MaterialPreviewCombinerSettings(),
            )

            self.assertTrue(combined.base_source)
            prepared_base = QImage(QUrl(combined.base_source).toLocalFile())
            self.assertEqual(255, prepared_base.pixelColor(0, 0).alpha())
            prepared_normal = QImage(QUrl(combined.normal_source).toLocalFile())
            self.assertFalse(prepared_normal.isNull())
            self.assertEqual(191, prepared_normal.pixelColor(0, 0).green())
            self.assertEqual("", combined.height_source)
            self.assertIn("height flat", "; ".join(combined.notes))

    def test_decode_material_sample_matches_channel_order_modes(self) -> None:
        orm = decode_material_sample(0.25, 0.50, 1.0, 1.0, "orm")
        rma = decode_material_sample(0.25, 0.50, 1.0, 1.0, "rma")
        mra = decode_material_sample(0.25, 0.50, 1.0, 1.0, "mra")

        self.assertAlmostEqual(0.50, orm[1], places=2)
        self.assertAlmostEqual(1.00, orm[2], places=2)
        self.assertAlmostEqual(0.25, rma[1], places=2)
        self.assertAlmostEqual(0.50, rma[2], places=2)
        self.assertAlmostEqual(0.25, mra[2], places=2)


class NativePreviewWidgetRuntimeTests(unittest.TestCase):
    def test_native_preview_panel_keeps_alignment_view_state_api(self) -> None:
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PySide6.QtWidgets import QApplication

        app = QApplication.instance() or QApplication([])
        widget = NativePreviewPanel("test", theme_key="dark")
        widget.resize(120, 90)
        widget.show()
        app.processEvents()
        widget.set_view(yaw=12.0, pitch=-8.0, zoom_factor=2.0, fit_to_view=False, pan=(1.0, 2.0, 3.0))

        state = widget.view_state_snapshot()
        self.assertEqual((12.0, -8.0, False, 2.0), state[:4])
        self.assertEqual((1.0, 2.0, 3.0), state[5])
        widget.reset_view()
        widget.restore_view_state(state)
        self.assertEqual(state, widget.view_state_snapshot())
        self.assertFalse(widget.grab().isNull())

        widget.close()
        widget.deleteLater()
        app.processEvents()

    def test_native_preview_panel_selection_fallback_emits_compact_ranges(self) -> None:
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PySide6.QtWidgets import QApplication

        app = QApplication.instance() or QApplication([])
        widget = NativePreviewPanel("test", theme_key="dark")
        payloads: list[dict[str, object]] = []
        widget.mesh_edit_selection_changed.connect(lambda payload: payloads.append(dict(payload)))
        try:
            widget.set_mesh_edit_vertex_selection({2: [3, 5, 4, 3, -1]})
            group = payloads[-1]["groups"][0]  # type: ignore[index]
            self.assertEqual(2, group["source_submesh_index"])
            self.assertEqual(3, group["source_vertex_start"])
            self.assertEqual(3, group["source_vertex_count"])
            self.assertNotIn("source_vertex_indices", group)
            self.assertEqual(3, payloads[-1]["selected_vertex_count"])

            widget.set_mesh_edit_vertex_selection({2: [5, 1, 5, -1]})
            group = payloads[-1]["groups"][0]  # type: ignore[index]
            self.assertEqual([1, 5], group["source_vertex_indices"])
            self.assertNotIn("source_vertex_start", group)
            self.assertEqual(2, payloads[-1]["selected_vertex_count"])
        finally:
            widget.close()
            widget.deleteLater()
            app.processEvents()

    def test_repeated_payload_replacement_does_not_delete_live_geometry(self) -> None:
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PySide6.QtWidgets import QApplication

        app = QApplication.instance() or QApplication([])
        widget = NativePreviewPanel("test", theme_key="dark")
        model = ModelPreviewData(
            path="test.pam",
            summary="test model",
            meshes=[ModelPreviewMesh(positions=[(0.0, 0.0, 0.0)], indices=[0, 0, 0])],
        )
        prepared = PreparedModelPreviewData(
            batches=(
                PreparedModelPreviewBatch(
                    vertex_blob=b"".join(
                        (
                            _vertex(0.0, 1.0, 0.0),
                            _vertex(-1.0, -1.0, 0.0),
                            _vertex(1.0, -1.0, 0.0),
                        )
                    ),
                    index_count=3,
                    has_texture_coordinates=True,
                ),
            )
        )

        for _attempt in range(3):
            widget.set_prepared_model(model, prepared)
            app.processEvents()
            widget.clear_model("reload")
            app.processEvents()
        widget.set_prepared_model(model, prepared)
        app.processEvents()

        self.assertTrue(widget.is_available(), widget.failure_reason())
        self.assertIn("1 batch", widget.debug_details_text())
        self.assertEqual(getattr(widget, "_vertex_count", 0), 3)
        widget.close()
        widget.deleteLater()
        app.processEvents()

    def test_textured_batches_use_white_material_color_and_disable_support_pbr_by_default(self) -> None:
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PySide6.QtCore import QUrl
        from PySide6.QtGui import QColor, QImage
        from PySide6.QtWidgets import QApplication

        app = QApplication.instance() or QApplication([])
        with tempfile.TemporaryDirectory() as temp_dir:
            texture_path = Path(temp_dir) / "base.png"
            texture_image = QImage(2, 2, QImage.Format_RGBA8888)
            texture_image.setPixelColor(0, 0, QColor(255, 0, 0, 12))
            texture_image.setPixelColor(1, 0, QColor(255, 0, 0, 12))
            texture_image.setPixelColor(0, 1, QColor(0, 0, 255, 48))
            texture_image.setPixelColor(1, 1, QColor(0, 0, 255, 48))
            self.assertTrue(texture_image.save(str(texture_path), "PNG"))
            normal_path = Path(temp_dir) / "normal.png"
            normal_path.write_bytes(b"existing normal")
            widget = NativePreviewPanel("test", theme_key="dark")
            model = ModelPreviewData(
                path="test.pam",
                summary="test model",
                meshes=[ModelPreviewMesh(positions=[(0.0, 0.0, 0.0)], indices=[0, 0, 0])],
            )
            prepared = PreparedModelPreviewData(
                batches=(
                    PreparedModelPreviewBatch(
                        vertex_blob=b"".join(
                            (
                                _vertex(0.0, 1.0, 0.0),
                                _vertex(-1.0, -1.0, 0.0),
                                _vertex(1.0, -1.0, 0.0),
                            )
                        ),
                        index_count=3,
                        preview_texture_path=str(texture_path),
                        preview_normal_texture_path=str(normal_path),
                        has_texture_coordinates=True,
                    ),
                )
            )

            widget.set_prepared_model(model, prepared)
            widget.set_use_textures(True)
            app.processEvents()

            details = widget.debug_details_text()
            self.assertIn("Native D3D11 preview data ready", details)
            payload = build_native_preview_payloads(prepared)[0]
            self.assertFalse(payload.texture_flip_vertical)
            prepared_path = Path(QUrl(payload.texture_source).toLocalFile())
            self.assertTrue(prepared_path.is_file())
            prepared_image = QImage(str(prepared_path))
            self.assertFalse(prepared_image.isNull())
            self.assertEqual(12, prepared_image.pixelColor(0, 0).alpha())
            widget.close()
            widget.deleteLater()
            app.processEvents()


if __name__ == "__main__":
    unittest.main()
