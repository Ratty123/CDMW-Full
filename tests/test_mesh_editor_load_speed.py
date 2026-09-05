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
from cdmw.rendering.native_preview_payloads import ISOLATED_PREVIEW_VERTEX_STRIDE_BYTES
from tests.static_replacement_source_support import static_replacement_callback_factory_source


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
    if relative == "cdmw/ui/archive_browser/static_replacement_dialog_callback_factories.py":
        return static_replacement_callback_factory_source(ROOT)
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
                _read("cdmw/rendering/native_preview_texture_sources.py"),
            )
        )

        self.assertIn("def _source_file_stat_key(", source)
        self.assertIn("def _texture_copy_slot_policy(", source)
        self.assertIn("slot_policy = _texture_copy_slot_policy(", source)
        self.assertIn("cache_key = _source_file_stat_key(source)", source)



if __name__ == "__main__":
    unittest.main()
