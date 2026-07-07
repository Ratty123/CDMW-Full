from __future__ import annotations

import struct
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from cdmw.models import ModelPreviewData, ModelPreviewMesh, PreparedModelPreviewBatch, PreparedModelPreviewData
from cdmw.rendering.model_preview_prepare import (
    build_vertex_blob,
    build_vertex_blob_python_reference,
)
from cdmw.rendering.native_preview_package import (
    ISOLATED_PREVIEW_VERTEX_STRIDE_BYTES,
    read_isolated_d3d11_preview_manifest,
    write_isolated_d3d11_preview_package,
)


ROOT = Path(__file__).resolve().parents[1]


def _i32_descriptor_values(descriptor: object) -> list[int]:
    if not isinstance(descriptor, dict):
        return []
    path = Path(str(descriptor.get("path") or ""))
    data = path.read_bytes()
    if len(data) % 4:
        return []
    return list(struct.unpack("<" + "i" * (len(data) // 4), data))


def _read(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def _static_alignment_source() -> str:
    return "\n".join(
        (
            _read("cdmw/ui/shell/app_window.py"),
            _read("cdmw/ui/archive_browser/static_replacement_dialog.py"),
            _read("cdmw/ui/archive_browser/static_replacement_dialog_prompt.py"),
            _read("cdmw/ui/archive_browser/static_replacement_dialog_prompt_deps.py"),
            _read("cdmw/ui/archive_browser/static_replacement_dialog_prompt_deps_base.py"),
            _read("cdmw/ui/archive_browser/static_replacement_dialog_prompt_deps_state_a.py"),
            _read("cdmw/ui/archive_browser/static_replacement_dialog_prompt_deps_state_b.py"),
            _read("cdmw/ui/archive_browser/static_replacement_dialog_prompt_deps_callbacks.py"),
            _read("cdmw/ui/archive_browser/static_replacement_dialog_callback_factories.py"),
            _read("cdmw/ui/archive_browser/static_replacement_dialog_remaining_callbacks.py"),
            _read("cdmw/ui/archive_browser/static_replacement_d3d11_cache.py"),
            _read("cdmw/ui/archive_browser/static_replacement_d3d11_presentation_state.py"),
            _read("cdmw/ui/archive_browser/static_replacement_d3d11_state.py"),
            _read("cdmw/ui/archive_browser/static_replacement_diagnostics.py"),
            _read("cdmw/ui/archive_browser/static_replacement_preview_mapping.py"),
            _read("cdmw/ui/archive_browser/static_replacement_preview_models.py"),
        )
    )


class MeshEditorLoadSpeedTests(unittest.TestCase):
    def test_numpy_vertex_blob_matches_python_reference(self) -> None:
        model = ModelPreviewData(
            path="synthetic.pac",
            format="pac",
            meshes=[
                ModelPreviewMesh(
                    material_name="body",
                    preview_color=(0.25, 0.5, 0.75),
                    positions=[(0, 0, 0), (1, 0, 0), (0, 1, 0), (1, 1, 0)],
                    normals=[(0, 0, 1), (0, 0, 1), (0, 0, 1), (0, 0, 1)],
                    texture_coordinates=[(0, 0), (1, 0), (0, 1), (1, 1)],
                    indices=[0, 1, 2, 2, 1, 3, 99, 1, 2],
                ),
                ModelPreviewMesh(
                    material_name="fallback_normals",
                    positions=[(0, 0, 1), (1, 0, 1), (0, 1, 1)],
                    indices=[0, 1, 2],
                ),
            ],
        )

        fast_blob, fast_count, fast_batches = build_vertex_blob(model)
        ref_blob, ref_count, ref_batches = build_vertex_blob_python_reference(model)

        self.assertEqual(ref_count, fast_count)
        self.assertEqual(ref_blob, fast_blob)
        self.assertEqual([batch.vertex_count for batch in ref_batches], [batch.vertex_count for batch in fast_batches])

    def test_vertex_blob_uses_native_geometry_writer_when_available(self) -> None:
        model = ModelPreviewData(
            path="native-geometry.pac",
            format="pac",
            meshes=[
                ModelPreviewMesh(
                    material_name="native",
                    positions=[(0, 0, 0), (1, 0, 0), (0, 1, 0)],
                    normals=[(0, 0, 1), (0, 0, 1), (0, 0, 1)],
                    texture_coordinates=[(0, 0), (1, 0), (0, 1)],
                    indices=[0, 1, 2],
                    source_submesh_index=4,
                    source_vertex_indices=[10, 11, 12],
                    source_face_indices=[100],
                )
            ],
        )
        calls: list[dict[str, object]] = []
        native_blob = b"\0" * (3 * ISOLATED_PREVIEW_VERTEX_STRIDE_BYTES)

        def _fake_native_geometry(output_path: Path, **kwargs: object) -> dict[str, object]:
            calls.append(dict(kwargs))
            Path(output_path).write_bytes(native_blob)
            identity_output_path = kwargs.get("identity_output_path")
            if identity_output_path:
                Path(identity_output_path).write_bytes(struct.pack("<iiiiiiiii", 4, 10, 100, 4, 11, 100, 4, 12, 100))
            return {
                "vertex_count": 3,
                "geometry_size": len(native_blob),
                "batches": [
                    {
                        "mesh_index": 0,
                        "first_vertex": 0,
                        "vertex_count": 3,
                        "bounds_min": [0.0, 0.0, 0.0],
                        "bounds_max": [1.0, 1.0, 0.0],
                        "base_color": [0.25, 0.5, 0.75],
                        "tangents_usable": True,
                        "has_texture_coordinates": True,
                        "texture_wrap_repeat": False,
                        "normal_finite_ratio": 1.0,
                        "normal_repair_count": 0,
                        "tangent_finite_ratio": 1.0,
                        "bitangent_finite_ratio": 1.0,
                        "uv_finite_ratio": 1.0,
                        "smooth_normal_ratio": 0.0,
                        "position_y_min": 0.0,
                        "position_y_max": 1.0,
                        "source_vertex_indices": [10, 11, 12],
                        "source_face_indices": [100],
                        "identity_offset": 0,
                        "identity_size": 36,
                    }
                ],
            }

        with patch("cdmw.modding.mesh_native_core.write_native_preview_geometry_blob", side_effect=_fake_native_geometry):
            blob, count, batches = build_vertex_blob(model)

        self.assertEqual(native_blob, blob)
        self.assertEqual(3, count)
        self.assertEqual(1, len(calls))
        self.assertEqual(0, calls[0]["meshes"][0]["index"])
        self.assertEqual(4, calls[0]["meshes"][0]["source_submesh_index"])
        self.assertEqual(10, calls[0]["meshes"][0]["source_vertex_start"])
        self.assertEqual(3, calls[0]["meshes"][0]["source_vertex_count"])
        self.assertEqual(100, calls[0]["meshes"][0]["source_face_start"])
        self.assertEqual(1, calls[0]["meshes"][0]["source_face_count"])
        self.assertTrue(calls[0]["identity_output_path"])
        self.assertEqual(3, batches[0].vertex_count)
        self.assertEqual((0.25, 0.5, 0.75), batches[0].base_color)
        self.assertEqual((0.0, 0.0, 0.0), batches[0].bounds_min)
        self.assertEqual((1.0, 1.0, 0.0), batches[0].bounds_max)
        self.assertTrue(batches[0].tangents_usable)
        self.assertTrue(batches[0].has_texture_coordinates)
        self.assertEqual((10, 11, 12), batches[0].source_vertex_indices)
        self.assertEqual((100,), batches[0].source_face_indices)
        self.assertEqual(
            (4, 10, 100, 4, 11, 100, 4, 12, 100),
            struct.unpack("<iiiiiiiii", batches[0].editor_identity_blob),
        )

    def test_vertex_blob_native_reuses_preview_model_binary_descriptors(self) -> None:
        with tempfile.TemporaryDirectory(prefix="cdmw-preview-descriptor-pack-") as temp_dir:
            root = Path(temp_dir)
            positions_path = root / "positions.bin"
            normals_path = root / "normals.bin"
            uvs_path = root / "uvs.bin"
            indices_path = root / "indices.bin"
            source_vertices_path = root / "source_vertices.bin"
            source_faces_path = root / "source_faces.bin"
            positions_path.write_bytes(struct.pack("<9d", 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0, 0.0))
            normals_path.write_bytes(struct.pack("<9d", *(0.0, 0.0, 1.0) * 3))
            uvs_path.write_bytes(struct.pack("<6d", 0.0, 0.0, 1.0, 0.0, 0.0, 1.0))
            indices_path.write_bytes(struct.pack("<3i", 0, 1, 2))
            source_vertices_path.write_bytes(struct.pack("<3i", 10, 11, 12))
            source_faces_path.write_bytes(struct.pack("<i", 100))
            model = ModelPreviewData(
                path="descriptor-geometry.pac",
                format="pac",
                meshes=[
                    ModelPreviewMesh(
                        material_name="native",
                        source_submesh_index=4,
                        positions_binary={"path": str(positions_path), "count": 3, "components": 3, "type": "f64"},
                        normals_binary={"path": str(normals_path), "count": 3, "components": 3, "type": "f64"},
                        texture_coordinates_binary={"path": str(uvs_path), "count": 3, "components": 2, "type": "f64"},
                        indices_binary={"path": str(indices_path), "count": 3, "components": 1, "type": "i32"},
                        source_vertex_indices_binary={"path": str(source_vertices_path), "count": 3, "components": 1, "type": "i32"},
                        source_face_indices_binary={"path": str(source_faces_path), "count": 1, "components": 1, "type": "i32"},
                    )
                ],
            )
            calls: list[dict[str, object]] = []
            native_blob = b"\0" * (3 * ISOLATED_PREVIEW_VERTEX_STRIDE_BYTES)

            def _fake_native_geometry(output_path: Path, **kwargs: object) -> dict[str, object]:
                calls.append(dict(kwargs))
                mesh_payload = kwargs["meshes"][0]  # type: ignore[index]
                for key in (
                    "positions_binary",
                    "normals_binary",
                    "texture_coordinates_binary",
                    "indices_binary",
                    "source_vertex_indices_binary",
                    "source_face_indices_binary",
                ):
                    self.assertIn(key, mesh_payload)
                    self.assertTrue(Path(mesh_payload[key]["path"]).is_file())  # type: ignore[index]
                for key in ("positions", "normals", "texture_coordinates", "indices", "source_vertex_indices", "source_face_indices"):
                    self.assertNotIn(key, mesh_payload)
                Path(output_path).write_bytes(native_blob)
                identity_output_path = kwargs.get("identity_output_path")
                if identity_output_path:
                    Path(identity_output_path).write_bytes(struct.pack("<iiiiiiiii", 4, 10, 100, 4, 11, 100, 4, 12, 100))
                return {
                    "vertex_count": 3,
                    "geometry_size": len(native_blob),
                    "batches": [
                        {
                            "mesh_index": 0,
                            "first_vertex": 0,
                            "vertex_count": 3,
                            "bounds_min": [0.0, 0.0, 0.0],
                            "bounds_max": [1.0, 1.0, 0.0],
                            "base_color": [0.25, 0.5, 0.75],
                            "tangents_usable": True,
                            "has_texture_coordinates": True,
                            "texture_wrap_repeat": False,
                            "source_vertex_indices_binary": {
                                "path": str(source_vertices_path),
                                "count": 3,
                                "components": 1,
                                "type": "i32",
                            },
                            "source_face_indices_binary": {
                                "path": str(source_faces_path),
                                "count": 1,
                                "components": 1,
                                "type": "i32",
                            },
                            "identity_offset": 0,
                            "identity_size": 36,
                        }
                    ],
                }

            with patch("cdmw.modding.mesh_native_core.write_native_preview_geometry_blob", side_effect=_fake_native_geometry):
                blob, count, batches = build_vertex_blob(model)

        self.assertEqual(native_blob, blob)
        self.assertEqual(3, count)
        self.assertEqual(1, len(calls))
        self.assertEqual((), batches[0].source_vertex_indices)
        self.assertEqual((), batches[0].source_face_indices)
        self.assertTrue(Path(str(batches[0].source_vertex_indices_binary["path"])).is_file())
        self.assertEqual([10, 11, 12], _i32_descriptor_values(batches[0].source_vertex_indices_binary))
        self.assertEqual(3, batches[0].source_vertex_indices_binary["count"])
        self.assertTrue(Path(str(batches[0].source_face_indices_binary["path"])).is_file())
        self.assertEqual([100], _i32_descriptor_values(batches[0].source_face_indices_binary))
        self.assertEqual(1, batches[0].source_face_indices_binary["count"])

    def test_vertex_blob_native_preserves_contiguous_source_ranges(self) -> None:
        model = ModelPreviewData(
            path="native-range.pac",
            format="pac",
            meshes=[
                ModelPreviewMesh(
                    material_name="native",
                    positions=[(0, 0, 0), (1, 0, 0), (0, 1, 0)],
                    normals=[(0, 0, 1)] * 3,
                    texture_coordinates=[(0, 0), (1, 0), (0, 1)],
                    indices=[0, 1, 2],
                    source_submesh_index=4,
                )
            ],
        )
        native_blob = b"\0" * (3 * ISOLATED_PREVIEW_VERTEX_STRIDE_BYTES)

        def _fake_native_geometry(output_path: Path, **kwargs: object) -> dict[str, object]:
            Path(output_path).write_bytes(native_blob)
            identity_output_path = kwargs.get("identity_output_path")
            if identity_output_path:
                Path(identity_output_path).write_bytes(struct.pack("<iiiiiiiii", 4, 10, 100, 4, 11, 100, 4, 12, 100))
            return {
                "vertex_count": 3,
                "geometry_size": len(native_blob),
                "batches": [
                    {
                        "mesh_index": 0,
                        "first_vertex": 0,
                        "vertex_count": 3,
                        "bounds_min": [0.0, 0.0, 0.0],
                        "bounds_max": [1.0, 1.0, 0.0],
                        "base_color": [0.25, 0.5, 0.75],
                        "tangents_usable": True,
                        "has_texture_coordinates": True,
                        "texture_wrap_repeat": False,
                        "source_vertex_start": 10,
                        "source_vertex_count": 3,
                        "source_face_start": 100,
                        "source_face_count": 1,
                        "identity_offset": 0,
                        "identity_size": 36,
                    }
                ],
            }

        with patch("cdmw.modding.mesh_native_core.write_native_preview_geometry_blob", side_effect=_fake_native_geometry):
            _blob, _count, batches = build_vertex_blob(model)

        self.assertEqual((), batches[0].source_vertex_indices)
        self.assertEqual((), batches[0].source_face_indices)
        self.assertEqual(10, batches[0].source_vertex_range_start)
        self.assertEqual(3, batches[0].source_vertex_range_count)
        self.assertEqual(100, batches[0].source_face_range_start)
        self.assertEqual(1, batches[0].source_face_range_count)

    def test_package_writer_routes_descriptor_backed_identity_through_native(self) -> None:
        with tempfile.TemporaryDirectory(prefix="cdmw-preview-identity-descriptor-") as temp_dir:
            root = Path(temp_dir)
            source_vertices_path = root / "source_vertices.bin"
            source_faces_path = root / "source_faces.bin"
            source_vertices_path.write_bytes(struct.pack("<3i", 10, 11, 12))
            source_faces_path.write_bytes(struct.pack("<i", 100))
            batch = PreparedModelPreviewBatch(
                material_name="descriptor-identity",
                vertex_blob=b"\0" * (3 * ISOLATED_PREVIEW_VERTEX_STRIDE_BYTES),
                index_count=3,
                source_submesh_index=4,
                source_vertex_indices_binary={"path": str(source_vertices_path), "count": 3, "components": 1, "type": "i32"},
                source_face_indices_binary={"path": str(source_faces_path), "count": 1, "components": 1, "type": "i32"},
                editor_identity_blob=struct.pack("<iiiiiiiii", 4, 10, 100, 4, 11, 100, 4, 12, 100),
            )
            prepared = PreparedModelPreviewData(
                source_path="descriptor-identity.pac",
                mesh_count=1,
                vertex_count=3,
                face_count=1,
                batches=(batch,),
            )
            calls: list[dict[str, object]] = []

            def _fake_native_identity(output_path: Path, **kwargs: object) -> dict[str, object]:
                calls.append(dict(kwargs))
                with Path(output_path).open("ab") as stream:
                    stream.write(struct.pack("<iiiiiiiii", 4, 10, 100, 4, 11, 100, 4, 12, 100))
                return {
                    "source_submesh_index": 4,
                    "source_vertex_count": 13,
                    "source_face_count": 101,
                    "identity_stride_bytes": 12,
                    "identity_size": 36,
                    "role": "replacement_preview",
                    "part_name": "descriptor-identity",
                    "editable": True,
                }

            with patch(
                "cdmw.rendering.native_preview_package_writer.write_native_preview_identity_blob",
                side_effect=_fake_native_identity,
            ):
                package_dir = write_isolated_d3d11_preview_package(
                    ModelPreviewData(path="descriptor-identity.pac"),
                    prepared,
                    output_root=root / "package",
                    use_textures=False,
                    high_quality_textures=False,
                )

            self.assertEqual(1, len(calls))
            self.assertIn("source_vertex_indices_binary", calls[0])
            self.assertEqual((), calls[0]["source_vertex_indices"])
            self.assertEqual((), calls[0]["source_face_indices"])
            self.assertEqual(str(source_vertices_path), calls[0]["source_vertex_indices_binary"]["path"])
            self.assertEqual(str(source_faces_path), calls[0]["source_face_indices_binary"]["path"])
            manifest = read_isolated_d3d11_preview_manifest(package_dir)
            identity = manifest["batches"][0]["editor_identity"]
            self.assertEqual(13, identity["source_vertex_count"])
            self.assertEqual(101, identity["source_face_count"])

    def test_package_writer_routes_range_backed_identity_through_native(self) -> None:
        batch = PreparedModelPreviewBatch(
            material_name="range-identity",
            vertex_blob=b"\0" * (3 * ISOLATED_PREVIEW_VERTEX_STRIDE_BYTES),
            index_count=3,
            source_submesh_index=4,
            source_vertex_range_start=10,
            source_vertex_range_count=3,
            source_face_range_start=100,
            source_face_range_count=1,
        )
        prepared = PreparedModelPreviewData(
            source_path="range-identity.pac",
            mesh_count=1,
            vertex_count=3,
            face_count=1,
            batches=(batch,),
        )
        calls: list[dict[str, object]] = []

        def _fake_native_identity(output_path: Path, **kwargs: object) -> dict[str, object]:
            calls.append(dict(kwargs))
            with Path(output_path).open("ab") as stream:
                stream.write(struct.pack("<iiiiiiiii", 4, 10, 100, 4, 11, 100, 4, 12, 100))
            return {
                "source_submesh_index": 4,
                "source_vertex_count": 13,
                "source_face_count": 101,
                "identity_stride_bytes": 12,
                "identity_size": 36,
                "role": "",
                "part_name": "",
                "editable": True,
            }

        range_identity: dict[str, object] = {}
        with tempfile.TemporaryDirectory(prefix="cdmw-preview-identity-range-") as temp_dir, patch(
            "cdmw.rendering.native_preview_package_writer.write_native_preview_identity_blob",
            side_effect=_fake_native_identity,
        ):
            package_dir = write_isolated_d3d11_preview_package(
                ModelPreviewData(path="range-identity.pac"),
                prepared,
                output_root=Path(temp_dir) / "package",
                use_textures=False,
                high_quality_textures=False,
            )
            range_identity = read_isolated_d3d11_preview_manifest(package_dir)["batches"][0]["editor_identity"]

        self.assertEqual(1, len(calls))
        self.assertEqual((), calls[0]["source_vertex_indices"])
        self.assertEqual((), calls[0]["source_face_indices"])
        self.assertEqual(10, calls[0]["source_vertex_start"])
        self.assertEqual(3, calls[0]["source_vertex_count"])
        self.assertEqual(100, calls[0]["source_face_start"])
        self.assertEqual(1, calls[0]["source_face_count"])
        self.assertIsNone(calls[0]["source_vertex_indices_binary"])
        self.assertIsNone(calls[0]["source_face_indices_binary"])
        self.assertEqual(13, range_identity["source_vertex_count"])
        self.assertEqual(101, range_identity["source_face_count"])

    def test_native_preview_geometry_bridge_uses_binary_sidecars(self) -> None:
        from cdmw.modding import mesh_native_core

        with tempfile.TemporaryDirectory(prefix="cdmw-native-geometry-test-") as temp_dir:
            output_path = Path(temp_dir) / "geometry.bin"
            identity_path = Path(temp_dir) / "identity.bin"

            def _native_job(_binary: Path, command: str, payload: object, *, timeout_seconds: float) -> dict[str, object]:
                self.assertEqual("preview-geometry-json", command)
                self.assertEqual("preview_geometry", payload["operation"])  # type: ignore[index]
                mesh_payload = payload["meshes"][0]  # type: ignore[index]
                for key in (
                    "positions_binary",
                    "normals_binary",
                    "texture_coordinates_binary",
                    "indices_binary",
                    "source_vertex_indices_binary",
                    "source_face_indices_binary",
                ):
                    self.assertIn(key, mesh_payload)
                    self.assertTrue(Path(mesh_payload[key]["path"]).is_file())
                for key in ("positions", "normals", "texture_coordinates", "indices", "source_vertex_indices", "source_face_indices"):
                    self.assertNotIn(key, mesh_payload)
                self.assertEqual(3, mesh_payload["positions_binary"]["count"])
                self.assertEqual(3, mesh_payload["indices_binary"]["count"])
                self.assertEqual(str(output_path), payload["output_path"])  # type: ignore[index]
                self.assertEqual(str(identity_path), payload["identity_output_path"])  # type: ignore[index]
                self.assertEqual(20.0, timeout_seconds)
                output_path.write_bytes(b"")
                identity_path.write_bytes(b"")
                return {"status": "ok", "vertex_count": 0, "geometry_size": 0, "batches": []}

            with (
                patch("cdmw.modding.mesh_native_core.find_native_mesh_core_binary", return_value=Path("native.exe")),
                patch("cdmw.modding.mesh_native_core._run_native_mesh_core_job", side_effect=_native_job),
            ):
                report = mesh_native_core.write_native_preview_geometry_blob(
                    output_path,
                    meshes=[
                        {
                            "index": 0,
                            "source_submesh_index": 4,
                            "source_vertex_indices": [10, 12, 13],
                            "source_face_indices": [100, 102],
                            "positions": [(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0)],
                            "normals": [(0.0, 0.0, 1.0)] * 3,
                            "texture_coordinates": [(0.0, 0.0), (1.0, 0.0), (0.0, 1.0)],
                            "indices": [0, 1, 2],
                            "color": (0.25, 0.5, 0.75),
                        }
                    ],
                    identity_output_path=identity_path,
                )

        self.assertEqual("ok", report["status"])

    def test_package_uses_aggregate_geometry_and_identity_offsets(self) -> None:
        batch_a = PreparedModelPreviewBatch(
            material_name="a",
            vertex_blob=b"\0" * (3 * ISOLATED_PREVIEW_VERTEX_STRIDE_BYTES),
            index_count=3,
            source_submesh_index=4,
            source_vertex_indices=(10, 11, 12),
            source_face_indices=(100,),
        )
        batch_b = PreparedModelPreviewBatch(
            material_name="b",
            vertex_blob=b"\1" * (6 * ISOLATED_PREVIEW_VERTEX_STRIDE_BYTES),
            index_count=6,
            source_submesh_index=8,
            source_vertex_indices=(20, 21, 22, 23, 24, 25),
            source_face_indices=(200, 201),
        )
        prepared = PreparedModelPreviewData(
            source_path="aggregate.pac",
            mesh_count=2,
            vertex_count=9,
            face_count=3,
            batches=(batch_a, batch_b),
        )
        with tempfile.TemporaryDirectory() as tmp:
            package_dir = write_isolated_d3d11_preview_package(
                ModelPreviewData(path="aggregate.pac"),
                prepared,
                output_root=Path(tmp) / "package",
                use_textures=False,
                high_quality_textures=False,
            )
            manifest = read_isolated_d3d11_preview_manifest(package_dir)

            geometry_path = package_dir / "geometry" / "geometry.bin"
            identity_path = package_dir / "geometry" / "identity.bin"
            first, second = manifest["batches"]
            self.assertTrue(geometry_path.is_file())
            self.assertTrue(identity_path.is_file())
            self.assertEqual("geometry/geometry.bin", first["vertex_file"])
            self.assertEqual("geometry/geometry.bin", second["vertex_file"])
            self.assertEqual(0, first["vertex_offset"])
            self.assertEqual(3 * ISOLATED_PREVIEW_VERTEX_STRIDE_BYTES, second["vertex_offset"])
            self.assertEqual("geometry/identity.bin", first["editor_identity"]["identity_file"])
            self.assertEqual(0, first["editor_identity"]["identity_offset"])
            self.assertEqual(3 * 12, second["editor_identity"]["identity_offset"])
            self.assertEqual(12, first["editor_identity"]["identity_stride_bytes"])
            self.assertEqual(12, second["editor_identity"]["identity_stride_bytes"])
            identity_blob = identity_path.read_bytes()
            self.assertEqual((4, 10, 100, 4, 11, 100, 4, 12, 100), struct.unpack_from("<iiiiiiiii", identity_blob, 0))
            self.assertEqual((8, 20, 200, 8, 21, 200, 8, 22, 200), struct.unpack_from("<iiiiiiiii", identity_blob, 3 * 12))

    def test_package_writer_uses_native_identity_writer_when_available(self) -> None:
        batch = PreparedModelPreviewBatch(
            material_name="native",
            vertex_blob=b"\0" * (3 * ISOLATED_PREVIEW_VERTEX_STRIDE_BYTES),
            index_count=3,
            source_submesh_index=4,
            source_vertex_indices=(10, 11, 12),
            source_face_indices=(100,),
            editor_role="replacement_preview",
            editor_part_name="native_part",
        )
        prepared = PreparedModelPreviewData(
            source_path="native.pac",
            mesh_count=1,
            vertex_count=3,
            face_count=1,
            batches=(batch,),
        )
        calls: list[dict[str, object]] = []

        def _fake_native_identity(output_path: Path, **kwargs: object) -> dict[str, object]:
            calls.append(dict(kwargs))
            with Path(output_path).open("ab") as stream:
                stream.write(struct.pack("<iiiiiiiii", 4, 10, 100, 4, 11, 100, 4, 12, 100))
            return {
                "source_submesh_index": 4,
                "source_vertex_count": 13,
                "source_face_count": 101,
                "identity_stride_bytes": 12,
                "identity_size": 36,
                "role": "replacement_preview",
                "part_name": "native_part",
                "editable": True,
            }

        with tempfile.TemporaryDirectory() as tmp, patch(
            "cdmw.rendering.native_preview_package_writer.write_native_preview_identity_blob",
            side_effect=_fake_native_identity,
        ):
            package_dir = write_isolated_d3d11_preview_package(
                ModelPreviewData(path="native.pac"),
                prepared,
                output_root=Path(tmp) / "package",
                use_textures=False,
                high_quality_textures=False,
            )

            manifest = read_isolated_d3d11_preview_manifest(package_dir)
            identity = manifest["batches"][0]["editor_identity"]
            self.assertEqual(1, len(calls))
            self.assertEqual("geometry/identity.bin", identity["identity_file"])
            self.assertEqual(0, identity["identity_offset"])
            self.assertEqual(36, identity["identity_size"])
            self.assertEqual(13, identity["source_vertex_count"])
            self.assertEqual(
                (4, 10, 100, 4, 11, 100, 4, 12, 100),
                struct.unpack("<iiiiiiiii", (package_dir / "geometry" / "identity.bin").read_bytes()),
            )

    def test_package_writer_uses_precomputed_native_identity_blob_before_writer(self) -> None:
        batch = PreparedModelPreviewBatch(
            material_name="precomputed-native",
            vertex_blob=b"\0" * (3 * ISOLATED_PREVIEW_VERTEX_STRIDE_BYTES),
            index_count=3,
            source_submesh_index=4,
            source_vertex_indices=(10, 11, 12),
            source_face_indices=(100,),
            editor_identity_blob=struct.pack("<iiiiiiiii", 4, 10, 100, 4, 11, 100, 4, 12, 100),
        )
        prepared = PreparedModelPreviewData(
            source_path="precomputed-native.pac",
            mesh_count=1,
            vertex_count=3,
            face_count=1,
            batches=(batch,),
        )
        with tempfile.TemporaryDirectory() as tmp, patch(
            "cdmw.rendering.native_preview_package_writer.write_native_preview_identity_blob",
            side_effect=AssertionError("precomputed native identity should be used"),
        ):
            package_dir = write_isolated_d3d11_preview_package(
                ModelPreviewData(path="precomputed-native.pac"),
                prepared,
                output_root=Path(tmp) / "package",
                use_textures=False,
                high_quality_textures=False,
            )

            manifest = read_isolated_d3d11_preview_manifest(package_dir)
            identity = manifest["batches"][0]["editor_identity"]
            self.assertEqual(36, identity["identity_size"])
            self.assertEqual(13, identity["source_vertex_count"])
            self.assertEqual(101, identity["source_face_count"])
            self.assertEqual(
                (4, 10, 100, 4, 11, 100, 4, 12, 100),
                struct.unpack("<iiiiiiiii", (package_dir / "geometry" / "identity.bin").read_bytes()),
            )

    def test_package_writer_uses_prepared_geometry_metadata_without_vertex_rescan(self) -> None:
        batch = PreparedModelPreviewBatch(
            material_name="metadata",
            vertex_blob=b"\0" * (3 * ISOLATED_PREVIEW_VERTEX_STRIDE_BYTES),
            index_count=3,
            preview_base_color=(0.2, 0.3, 0.4),
            tangents_usable=True,
        )
        prepared = PreparedModelPreviewData(
            source_path="metadata.pac",
            mesh_count=1,
            vertex_count=3,
            face_count=1,
            batches=(batch,),
        )
        with tempfile.TemporaryDirectory() as tmp:
            package_dir = write_isolated_d3d11_preview_package(
                ModelPreviewData(path="metadata.pac"),
                prepared,
                output_root=Path(tmp) / "package",
                use_textures=False,
                high_quality_textures=False,
            )
            manifest = read_isolated_d3d11_preview_manifest(package_dir)

        payload = manifest["batches"][0]
        self.assertEqual([0.2, 0.3, 0.4], payload["base_color"])
        self.assertTrue(payload["tangents_usable"])

    def test_main_window_cache_split_source_guards(self) -> None:
        source = _static_alignment_source()

        self.assertIn("class MeshPreviewDirtyFlags", _read("cdmw/rendering/model_preview_prepare.py"))
        self.assertIn("alignment_d3d11_material_cache_key as _alignment_d3d11_material_cache_key_helper", source)
        self.assertIn("def _alignment_d3d11_preview_cache_signature(", source)
        self.assertIn("reuse_prepared_geometry=bool(geometry_signature)", source)
        self.assertIn('if normalized_reason == "material":', source)
        self.assertIn('"last_cache_event"] = "material_dirty"', source)
        self.assertIn("manifest load trace:", source)
        self.assertIn("native_manifest_ms", source)
        self.assertIn("native_texture_ms", source)
        self.assertIn("native_geometry_ms", source)

        geometry_key_start = source.index("_source_preview_geometry_key = lambda current_mappings")
        geometry_key_body = source[geometry_key_start: source.index("_mapped_source_indices = lambda", geometry_key_start)]
        self.assertNotIn('"source_material_textures"', geometry_key_body)
        self.assertNotIn('"donor_material_plans"', geometry_key_body)

    def test_package_texture_caches_are_source_stat_and_slot_policy_based(self) -> None:
        source = "\n".join(
            (
                _read("cdmw/rendering/native_preview_package.py"),
                _read("cdmw/rendering/native_preview_package_writer.py"),
                _read("cdmw/rendering/native_preview_texture_sources.py"),
            )
        )

        self.assertIn("def _source_file_stat_key(", source)
        self.assertIn("def _texture_copy_slot_policy(", source)
        self.assertIn("slot_policy = _texture_copy_slot_policy(", source)
        self.assertIn("cache_key = _source_file_stat_key(source)", source)
        self.assertIn("dds_manifest_cache", source)
        self.assertIn('"texture_manifest": {', source)

    def test_native_loader_reads_aggregate_geometry_ranges(self) -> None:
        source = _read("native/cdmw_d3d11_preview/src/main.cpp")

        self.assertIn("std::uint64_t vertex_offset = 0;", source)
        self.assertIn("std::uint64_t identity_offset = 0;", source)
        self.assertIn("read_binary_range(batch.vertex_file, batch.vertex_offset, vertex_read_size)", source)
        self.assertIn("read_binary_range(\n                        batch.identity_file,", source)
        self.assertIn('\\"native_manifest_ms\\"', source)
        self.assertIn('\\"native_geometry_ms\\"', source)
        self.assertIn('\\"native_texture_ms\\"', source)


if __name__ == "__main__":
    unittest.main()
