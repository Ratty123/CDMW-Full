from __future__ import annotations

import struct
import tempfile
import unittest
from pathlib import Path

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
