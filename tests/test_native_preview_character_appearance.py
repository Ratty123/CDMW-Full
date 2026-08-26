from __future__ import annotations

import json
import struct
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from cdmw.models import ArchiveEntry, RunCancelled
from cdmw.rendering import native_preview_core
from cdmw.rendering.native_preview_core import NativePreviewCoreAttempt, run_native_preview_core_preview_job
from cdmw.rendering.native_preview_package_cache import NATIVE_PREVIEW_PACKAGE_CACHE_SCHEMA
from cdmw.workers.archive_preview_native import (
    ArchivePreviewNativeMixin,
    _native_presentation_geometry_payload,
)


def _entry() -> ArchiveEntry:
    return ArchiveEntry(
        path="character/model/1_pc/2_phw/head/head/cd_phw_00_head_00_0111.pac",
        pamt_path=Path("C:/game/0009/0.pamt"),
        paz_file=Path("C:/game/0009/1.paz"),
        offset=128,
        comp_size=64,
        orig_size=64,
        flags=0,
        paz_index=1,
    )


class _NativePreviewHarness(ArchivePreviewNativeMixin):
    def __init__(self) -> None:
        self.entry = _entry()
        self.companion_entry = None
        self.native_preview_core_cache_root = Path("C:/cache/native")
        self.native_preview_core_package_root = Path("C:/game")
        self.native_preview_dependency_entries = ()
        self.native_preview_dependency_entries_complete = False
        self.enabled_prefab_component_paths = ()
        self.texture_entries_by_normalized_path = {}
        self.texture_entries_by_basename = {}
        self.render_settings = SimpleNamespace(use_textures_by_default=False)
        self.stop_event = threading.Event()


class NativePreviewCharacterAppearanceTests(unittest.TestCase):
    def test_presentation_geometry_payload_preserves_submesh_vertices_and_normals(self) -> None:
        mesh = SimpleNamespace(
            submeshes=[
                SimpleNamespace(
                    vertices=[(1.0, 2.0, 3.0), (4.0, 5.0, 6.0)],
                    normals=[(0.0, 1.0, 0.0), (0.0, 0.0, 1.0)],
                )
            ]
        )

        payload = _native_presentation_geometry_payload(mesh, threading.Event())

        magic, submesh_count, vertex_total = struct.unpack_from("<8sII", payload, 0)
        submesh_index, vertex_count = struct.unpack_from("<II", payload, 16)
        first = struct.unpack_from("<ffffff", payload, 24)
        second = struct.unpack_from("<ffffff", payload, 48)
        self.assertEqual(b"CDMWPG1\0", magic)
        self.assertEqual((1, 2), (submesh_count, vertex_total))
        self.assertEqual((0, 2), (submesh_index, vertex_count))
        self.assertEqual((1.0, 2.0, 3.0, 0.0, 1.0, 0.0), first)
        self.assertEqual((4.0, 5.0, 6.0, 0.0, 0.0, 1.0), second)

    def test_native_job_keeps_presentation_sidecar_alive_through_dispatch(self) -> None:
        payload = b"presentation-geometry"
        observed: dict[str, object] = {}

        def fake_run_process(command, **_kwargs):
            job_path = Path(command[2])
            report_path = Path(command[3])
            job = json.loads(job_path.read_text(encoding="utf-8"))
            presentation_path = Path(job["presentation_geometry_path"])
            observed["source"] = job["presentation_geometry_source"]
            observed["payload"] = presentation_path.read_bytes()
            output_root = Path(job["output_root"])
            output_root.mkdir(parents=True, exist_ok=True)
            (output_root / "manifest.json").write_text('{"schema_version":8,"batches":[]}', encoding="utf-8")
            report_path.write_text(
                json.dumps(
                    {
                        "status": "ok",
                        "package_path": str(output_root),
                        "presentation_geometry_applied": True,
                    }
                ),
                encoding="utf-8",
            )
            return 0, "", ""

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            binary = root / "cdmw-preview-core.exe"
            binary.write_text("stub", encoding="utf-8")
            with (
                patch.object(native_preview_core, "find_native_preview_core_binary", return_value=binary),
                patch.object(native_preview_core, "run_process_with_cancellation", side_effect=fake_run_process),
            ):
                attempt = run_native_preview_core_preview_job(
                    _entry(),
                    cache_root=root / "cache",
                    output_root=root / "package",
                    use_service=False,
                    presentation_geometry_payload=payload,
                    presentation_geometry_source="character/example/head.pabc",
                )

        self.assertTrue(attempt.succeeded)
        self.assertEqual(payload, observed["payload"])
        self.assertEqual("character/example/head.pabc", observed["source"])

    def test_cancel_after_service_dispatch_retains_the_presentation_sidecar(self) -> None:
        class _CancellingService:
            @property
            def process_id(self) -> int:
                return 0

            def preview_job(self, _job_path, _report_path, **kwargs):
                kwargs["on_dispatched"]()
                raise RunCancelled("cancelled after dispatch")

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            binary = root / "cdmw-preview-core.exe"
            binary.write_text("stub", encoding="utf-8")
            job_root = root / "job"
            job_root.mkdir()
            with (
                patch.object(native_preview_core, "find_native_preview_core_binary", return_value=binary),
                patch.object(native_preview_core.tempfile, "mkdtemp", return_value=str(job_root)),
                patch.object(native_preview_core, "_get_native_preview_core_service", return_value=_CancellingService()),
                self.assertRaises(RunCancelled),
            ):
                run_native_preview_core_preview_job(
                    _entry(),
                    cache_root=root / "cache",
                    presentation_geometry_payload=b"presentation-geometry",
                    presentation_geometry_source="character/example/head.pabc",
                )

            self.assertEqual(
                b"presentation-geometry",
                (job_root / "presentation_geometry.bin").read_bytes(),
            )

    def test_presentation_geometry_serialization_honors_cancellation(self) -> None:
        stop_event = threading.Event()
        stop_event.set()
        mesh = SimpleNamespace(
            submeshes=[SimpleNamespace(vertices=[(1.0, 2.0, 3.0)], normals=[(0.0, 1.0, 0.0)])]
        )

        with self.assertRaises(RunCancelled):
            _native_presentation_geometry_payload(mesh, stop_event)

    def test_archive_worker_prepares_the_resolved_pabc_neutral_clone(self) -> None:
        harness = _NativePreviewHarness()
        raw_mesh = SimpleNamespace(
            submeshes=[SimpleNamespace(vertices=[(0.0, 0.0, 0.0)], normals=[(0.0, 1.0, 0.0)])]
        )
        presentation_mesh = SimpleNamespace(
            submeshes=[SimpleNamespace(vertices=[(1.0, 2.0, 3.0)], normals=[(0.0, 0.0, 1.0)])],
            _cdmw_skeleton_variation_source="character/example/head.pabc",
        )
        resolution = SimpleNamespace(skeleton_variation_entry=SimpleNamespace(path="character/example/head.pabc"))
        with (
            patch(
                "cdmw.core.skeleton_resolver.resolve_skeleton_descriptor_for_model",
                return_value=resolution,
            ),
            patch("cdmw.core.archive_extraction.read_archive_entry_data", return_value=(b"PAC", False, "")),
            patch("cdmw.modding.mesh_parser.parse_mesh", return_value=raw_mesh),
            patch(
                "cdmw.core.archive_mesh_appearance.apply_archive_mesh_appearance_for_preview",
                return_value=(presentation_mesh, ("Applied neutral face.",)),
            ),
        ):
            payload, source, notes = harness._prepare_native_preview_presentation_geometry()

        self.assertTrue(payload)
        self.assertEqual("character/example/head.pabc", source)
        self.assertEqual(("Applied neutral face.",), notes)
        self.assertEqual((1.0, 2.0, 3.0), struct.unpack_from("<fff", payload, 24))

    def test_worker_requires_native_acknowledgement_before_publishing_character_geometry(self) -> None:
        harness = _NativePreviewHarness()
        with (
            patch.object(
                harness,
                "_prepare_native_preview_presentation_geometry",
                return_value=(b"payload", "character/example/head.pabc", ("Applied neutral face.",)),
            ),
            patch(
                "cdmw.workers.archive_preview_native.run_native_preview_core_preview_job",
                return_value=NativePreviewCoreAttempt(status="ok", package_path="C:/package", diagnostics={}),
            ),
        ):
            attempt = harness._run_native_preview_core_with_presentation(
                output_root=Path("C:/staging/package"),
                dds_cache_max_bytes=1024,
                dds_cache_target_bytes=512,
            )

        self.assertEqual("error", attempt.status)
        self.assertFalse(attempt.package_path)
        self.assertIn("did not apply", attempt.fallback_reason)
        self.assertEqual(["Applied neutral face."], attempt.diagnostics["character_appearance_notes"])

    def test_worker_publishes_acknowledged_character_geometry_and_notes(self) -> None:
        harness = _NativePreviewHarness()
        with (
            patch.object(
                harness,
                "_prepare_native_preview_presentation_geometry",
                return_value=(b"payload", "character/example/head.pabc", ("Applied neutral face.",)),
            ),
            patch(
                "cdmw.workers.archive_preview_native.run_native_preview_core_preview_job",
                return_value=NativePreviewCoreAttempt(
                    status="ok",
                    package_path="C:/package",
                    diagnostics={"presentation_geometry_applied": True},
                ),
            ),
        ):
            attempt = harness._run_native_preview_core_with_presentation(
                output_root=Path("C:/staging/package"),
                dds_cache_max_bytes=1024,
                dds_cache_target_bytes=512,
            )

        self.assertTrue(attempt.succeeded)
        self.assertEqual(["Applied neutral face."], attempt.diagnostics["character_appearance_notes"])

    def test_character_preview_cache_schema_invalidates_raw_native_packages(self) -> None:
        self.assertEqual(2, NATIVE_PREVIEW_PACKAGE_CACHE_SCHEMA)


if __name__ == "__main__":
    unittest.main()
