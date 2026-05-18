from pathlib import Path
import json
import unittest
import tempfile
from unittest import mock

from cdmw.core.archive_accelerator import prepare_archive_browser_state_accelerated
from cdmw.core.mesh_native import _native_rebuild_is_in_place_safe, audit_mesh_native, build_mesh_native, parse_mesh_native
from cdmw.core.mesh_native_parity import native_mesh_full_rebuild_parity_enabled, native_mesh_rebuild_parity_enabled, run_mesh_native_archive_parity_corpus, run_mesh_native_parity_corpus
from cdmw.modding.mesh_importer import _split_pamlod_lod0_edit_by_entries
from cdmw.modding.mesh_parser import ParsedMesh, SubMesh
from cdmw.models import ArchiveEntry


def _entry(path: str, index: int = 0) -> ArchiveEntry:
    return ArchiveEntry(
        path=path,
        pamt_path=Path("C:/game/0000/0.pamt"),
        paz_file=Path("C:/game/0000/0.paz"),
        offset=index,
        comp_size=10,
        orig_size=20,
        flags=0,
        paz_index=0,
    )


class NativeAccelerationPlanTests(unittest.TestCase):
    @staticmethod
    def _static_mesh(*, faces: list[tuple[int, int, int]] | None = None, uvs: list[tuple[float, float]] | None = None) -> ParsedMesh:
        vertices = [(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0)]
        return ParsedMesh(
            path="object/test.pam",
            format="pam",
            submeshes=[
                SubMesh(
                    name="mesh",
                    material="mesh",
                    vertices=vertices,
                    uvs=uvs if uvs is not None else [(0.0, 0.0), (1.0, 0.0), (0.0, 1.0)],
                    faces=faces if faces is not None else [(0, 1, 2)],
                )
            ],
        )

    def test_archive_accelerator_python_fallback_is_preserved(self) -> None:
        state = prepare_archive_browser_state_accelerated(
            [_entry("texture/example.dds")],
            filter_text="",
            exclude_filter_text="",
            extension_filter="*",
            package_filter_text="",
            structure_filter="",
            role_filter="all",
            exclude_common_technical_suffixes=False,
            min_size_kb=0,
            previewable_only=False,
            native_enabled=False,
        )

        self.assertEqual("python_fallback", state["archive_accelerator"]["backend"])
        self.assertFalse(state["archive_accelerator"]["native_used"])
        self.assertEqual(1, len(state["filtered_entries"]))

    def test_archive_accelerator_protocol_and_packaging_are_wired(self) -> None:
        adapter = Path("cdmw/core/archive_accelerator.py").read_text(encoding="utf-8")
        archive = Path("cdmw/core/archive.py").read_text(encoding="utf-8")
        native = Path("native/cdmw_archive_accelerator/src/main.cpp").read_text(encoding="utf-8")
        build = Path("build_native_windows.ps1").read_text(encoding="utf-8")
        spec = Path("CrimsonDesertModWorkbench.spec").read_text(encoding="utf-8")
        main_window = Path("cdmw/ui/main_window.py").read_text(encoding="utf-8")

        self.assertIn("ARCHIVE_ACCELERATOR_PROTOCOL = 1", adapter)
        self.assertIn("scan_archive_entries_cached_accelerated", adapter)
        self.assertIn("scan_archive_entries_cached_accelerated", main_window)
        self.assertIn("scan-job", native)
        self.assertIn("browser-state-job", native)
        self.assertIn("entry-read-job", native)
        self.assertIn("read_archive_entry_data_native", adapter)
        self.assertIn("read_archive_entry_data_native", archive)
        self.assertIn("constexpr int kProtocol = 1", native)
        self.assertIn("native\\cdmw_archive_accelerator", build)
        self.assertIn("cdmw-archive-accelerator.exe", spec)

    def test_mesh_native_falls_back_when_binary_is_missing(self) -> None:
        with mock.patch("cdmw.core.mesh_native.find_native_preview_core_binary", return_value=None):
            audit = audit_mesh_native(b"not a mesh", "bad.pam")
            parsed = parse_mesh_native(b"not a mesh", "bad.pam")
            rebuilt = build_mesh_native(mock.Mock(), b"original")

        self.assertEqual("missing", audit["status"])
        self.assertIsNone(parsed)
        self.assertIsNone(rebuilt)

    def test_mesh_native_static_rebuild_gate_keeps_topology_changes_on_python_path(self) -> None:
        original = self._static_mesh()
        moved = self._static_mesh()
        moved.submeshes[0].vertices[1] = (2.0, 0.0, 0.0)
        rewired_faces = self._static_mesh(faces=[(0, 2, 1)])
        changed_uvs = self._static_mesh(uvs=[(0.0, 0.0), (0.5, 0.5), (0.0, 1.0)])
        extra_vertex = self._static_mesh()
        extra_vertex.submeshes[0].vertices.append((0.0, 0.0, 1.0))
        extra_vertex.submeshes[0].uvs.append((0.25, 0.25))

        with mock.patch("cdmw.modding.mesh_parser.parse_pam", return_value=original):
            self.assertTrue(_native_rebuild_is_in_place_safe("pam", moved, b"PAR fake"))
            self.assertFalse(_native_rebuild_is_in_place_safe("pam", rewired_faces, b"PAR fake"))
            self.assertFalse(_native_rebuild_is_in_place_safe("pam", changed_uvs, b"PAR fake"))
            self.assertFalse(_native_rebuild_is_in_place_safe("pam", extra_vertex, b"PAR fake"))

    def test_mesh_native_command_is_exposed_by_preview_core(self) -> None:
        wrapper = Path("cdmw/core/mesh_native.py").read_text(encoding="utf-8")
        parity = Path("cdmw/core/mesh_native_parity.py").read_text(encoding="utf-8")
        native = Path("native/cdmw_preview_core/src/main.cpp").read_text(encoding="utf-8")
        importer = Path("cdmw/modding/mesh_importer.py").read_text(encoding="utf-8")

        self.assertIn("audit_mesh_native", wrapper)
        self.assertIn("parse_mesh_native", wrapper)
        self.assertIn("build_mesh_native", wrapper)
        self.assertIn("mesh-audit-job", native)
        self.assertIn("mesh-parse-job", native)
        self.assertIn("mesh-rebuild-job", native)
        self.assertIn("target_format", wrapper)
        self.assertIn("build_mesh_native", importer)
        self.assertIn("native_mesh_rebuild_parity_enabled", wrapper)
        self.assertIn("cdmw_mesh_native_parity_v1", parity)
        self.assertIn("run_mesh_native_archive_parity_corpus", parity)
        self.assertIn("formats:", parity)
        self.assertIn("parity_ready", native)
        self.assertIn("rebuild_supported", native)
        self.assertIn("fallback_reason", native)
        self.assertIn("rebuild_pac_in_place_native", native)
        self.assertIn("decompress_internal_par_sections", native)
        self.assertIn("pac_submeshes_tsv_path", wrapper)
        self.assertIn("static_quantized_patch_tsv_path", wrapper)
        self.assertIn("_native_rebuild_is_in_place_safe", wrapper)
        self.assertIn("static_full_rebuild_tsv_path", wrapper)
        self.assertIn("pac_full_submeshes_tsv_path", wrapper)
        self.assertIn("pamlod_full_rebuild_tsv_path", wrapper)
        self.assertIn("enabled_full_rebuild_layouts", parity)
        self.assertIn("rebuild_static_quantized_in_place_native", native)
        self.assertIn("rebuild_pam_full_native", native)
        self.assertIn("rebuild_pac_full_native", native)
        self.assertIn("rebuild_pamlod_lod0_full_native", native)
        self.assertIn("_serialize_pamlod_lod0_full_rebuild", importer)
        self.assertIn("native_pam_scan_combined", native)
        self.assertIn("native_pam_backward_scan_combined", native)

    def test_pamlod_lod0_splitter_handles_ambiguous_flattened_edits(self) -> None:
        original_parts = [
            SubMesh(vertices=[(0.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0)], faces=[(0, 1, 2)]),
            SubMesh(vertices=[(10.0, 0.0, 0.0), (10.0, 1.0, 0.0), (10.0, 0.0, 1.0)], faces=[(0, 1, 2)]),
        ]
        combined_vertices = [
            *original_parts[0].vertices,
            *original_parts[1].vertices,
            (10.1, 0.0, 0.0),
            (10.0, 0.1, 0.0),
            (10.0, 0.0, 0.1),
            (10.2, 0.2, 0.2),
        ]
        combined = SubMesh(
            vertices=combined_vertices,
            uvs=[(0.0, 0.0)] * len(combined_vertices),
            faces=[
                (0, 3, 4),
                (6, 7, 8),
            ],
        )

        split = _split_pamlod_lod0_edit_by_entries([combined], original_parts)

        self.assertEqual(2, len(split))
        self.assertEqual([], split[0].faces)
        self.assertEqual(3, len(split[0].vertices))
        self.assertEqual([(3, 0, 1), (4, 5, 6)], split[1].faces)
        self.assertEqual(8, len(split[1].vertices))
        self.assertEqual(len(split[1].vertices), len(split[1].uvs))

        deleted = SubMesh(
            vertices=[
                original_parts[0].vertices[0],
                original_parts[0].vertices[2],
                *original_parts[1].vertices,
            ],
            uvs=[(0.0, 0.0)] * 5,
            faces=[(2, 3, 4)],
        )
        split_deleted = _split_pamlod_lod0_edit_by_entries([deleted], original_parts)

        self.assertEqual(2, len(split_deleted[0].vertices))
        self.assertEqual(3, len(split_deleted[1].vertices))
        self.assertEqual([(0, 1, 2)], split_deleted[1].faces)

    def test_mesh_native_parity_requires_real_fixtures_and_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            report = run_mesh_native_parity_corpus(root)

            self.assertEqual("missing_fixtures", report.status)
            self.assertEqual([], report.cases)

            manifest_path = root / "mesh_native_parity.json"
            manifest_path.write_text(
                json.dumps(
                    {
                        "schema": "cdmw_mesh_native_parity_v1",
                        "status": "ok",
                        "enabled_rebuild_layouts": {"pac": ["native_pac"]},
                        "enabled_full_rebuild_layouts": {"pam": ["native_pam_combined"], "pac": ["native_pac"], "pamlod": ["native_pamlod_lod0"]},
                    }
                ),
                encoding="utf-8",
            )
            with mock.patch.dict("os.environ", {"CDMW_MESH_NATIVE_PARITY_MANIFEST": str(manifest_path)}):
                self.assertTrue(native_mesh_rebuild_parity_enabled("pac", "native_pac"))
                self.assertFalse(native_mesh_rebuild_parity_enabled("pam", "native_pam_local"))
                self.assertTrue(native_mesh_full_rebuild_parity_enabled("pam", "native_pam_combined"))
                self.assertFalse(native_mesh_full_rebuild_parity_enabled("pam", "native_pam_local"))
                self.assertTrue(native_mesh_full_rebuild_parity_enabled("pac", "native_pac"))
                self.assertTrue(native_mesh_full_rebuild_parity_enabled("pamlod", "native_pamlod_lod0"))

    def test_mesh_native_archive_parity_reports_scan_unavailable(self) -> None:
        with mock.patch("cdmw.core.archive_accelerator.scan_archive_entries_native", return_value=None):
            report = run_mesh_native_archive_parity_corpus(Path("C:/missing/game"), per_format_limit=1)

        self.assertEqual("archive_scan_unavailable", report.status)
        self.assertEqual([], report.cases)

    def test_hkx_optional_binary_is_packaged_and_frozen_lookup_is_supported(self) -> None:
        hkx_native = Path("cdmw/core/hkx_native.py").read_text(encoding="utf-8")
        build = Path("build_native_windows.ps1").read_text(encoding="utf-8")
        spec = Path("CrimsonDesertModWorkbench.spec").read_text(encoding="utf-8")

        self.assertIn('getattr(sys, "_MEIPASS"', hkx_native)
        self.assertIn("native/cd_hkx/target/release/cd-hkx.exe", spec)
        self.assertIn('native\\cd_hkx', build)
        self.assertIn("cargo", build)


if __name__ == "__main__":
    unittest.main()
