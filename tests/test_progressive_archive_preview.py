import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from cdmw.core import archive
from cdmw.models import ArchiveEntry, ModelPreviewData, ModelPreviewMesh
from cdmw.ui.archive_browser.preview_cache import ArchivePreviewCacheMixin


def _entry(path: str, extension: str) -> ArchiveEntry:
    return ArchiveEntry(
        path=path,
        pamt_path="package.pamt",
        paz_file="package_0.paz",
        offset=0,
        comp_size=100,
        orig_size=100,
        flags=0,
        paz_index=0,
    )


def _preview_model(face_count: int, *, fmt: str = "pac", lod_index: int = -1, lod_count: int = 0) -> ModelPreviewData:
    positions = []
    for index in range(face_count):
        base = float(index) * 2.0
        positions.extend(((base, 0.0, 0.0), (base + 1.0, 0.0, 0.0), (base, 1.0, 0.0)))
    indices = list(range(face_count * 3))
    mesh = ModelPreviewMesh(
        material_name="mat",
        positions=positions,
        normals=[(0.0, 0.0, 1.0)] * len(positions),
        texture_coordinates=[(0.0, 0.0)] * len(positions),
        indices=indices,
    )
    return ModelPreviewData(
        path=f"mesh.{fmt}",
        format=fmt,
        mesh_count=1,
        vertex_count=len(positions),
        face_count=face_count,
        lod_index=lod_index,
        lod_count=lod_count,
        meshes=[mesh],
    )


class ProgressiveArchivePreviewTests(unittest.TestCase):
    def test_loose_preview_bypasses_cache_so_dependency_changes_refresh(self) -> None:
        class CacheKeyHarness(ArchivePreviewCacheMixin):
            archive_sidecar_generation = 0

            @staticmethod
            def _archive_model_renderer_backend() -> str:
                return "software"

            @staticmethod
            def _current_model_preview_render_settings() -> object:
                return SimpleNamespace(
                    disable_all_support_maps=False,
                    disable_normal_map=False,
                    disable_material_map=False,
                    disable_height_map=False,
                    visible_texture_mode="mesh_base_first",
                    preview_texture_max_dimension=2048,
                    low_quality_texture_max_dimension=512,
                    flip_texture_v=False,
                    high_quality_by_default=True,
                    use_textures_by_default=True,
                )

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            loose_root = root / "loose"
            loose_path = loose_root / "ui" / "texture" / "icon.dds"
            loose_path.parent.mkdir(parents=True)
            loose_path.write_bytes(b"first")
            entry = ArchiveEntry(
                path="ui/texture/icon.dds",
                pamt_path=root / "0001" / "0.pamt",
                paz_file=root / "0001" / "0.paz",
                offset=0,
                comp_size=5,
                orig_size=5,
                flags=0,
                paz_index=0,
            )
            harness = CacheKeyHarness()
            archive_key = harness._archive_preview_cache_key(entry, None, [loose_root])
            first_key = harness._archive_preview_cache_key(
                entry,
                None,
                [loose_root],
                include_loose_preview_assets=True,
            )
            loose_path.write_bytes(b"second payload")
            second_key = harness._archive_preview_cache_key(
                entry,
                None,
                [loose_root],
                include_loose_preview_assets=True,
            )

            self.assertEqual("", first_key)
            self.assertEqual("", second_key)
            self.assertEqual(archive_key, harness._archive_preview_cache_key(entry, None, [loose_root]))

    def test_fast_preview_reduces_preview_only_geometry(self) -> None:
        full_model = _preview_model(60_000)
        reduced = archive._reduce_archive_preview_model_geometry(full_model, max_faces=10_000)

        self.assertEqual(60_000, full_model.face_count)
        self.assertLessEqual(reduced.face_count, 10_000)
        self.assertGreater(reduced.face_count, 0)
        self.assertLess(len(reduced.meshes[0].indices), len(full_model.meshes[0].indices))

    def test_pamlod_fast_tier_requests_low_detail_lod(self) -> None:
        calls = []

        def fake_build(_entry, _data, *, lod_index=None, stop_event=None):
            calls.append(lod_index)
            return _preview_model(3, fmt="pamlod", lod_index=2 if lod_index == -1 else 0, lod_count=3)

        with patch("cdmw.core.archive_model_preview.build_pamlod_model_preview", side_effect=fake_build):
            fast_model, _notes = archive._build_pamlod_model_preview_with_fallback(
                _entry("character/model/body.pamlod", ".pamlod"),
                b"data",
                set(),
                quality_tier="fast",
            )
            full_model, _notes = archive._build_pamlod_model_preview_with_fallback(
                _entry("character/model/body.pamlod", ".pamlod"),
                b"data",
                set(),
                quality_tier="full",
            )

        self.assertEqual([-1, None], calls)
        self.assertEqual(2, fast_model.lod_index)
        self.assertEqual(0, full_model.lod_index)

    def test_pac_fast_tier_reduces_but_full_tier_preserves_geometry(self) -> None:
        source_model = _preview_model(60_000, fmt="pac")
        parsed_mesh = object()

        with patch(
            "cdmw.core.archive_model_preview.build_mesh_preview_from_bytes",
            return_value=(source_model, parsed_mesh),
        ):
            fast_model, fast_parsed, _notes = archive._build_pac_model_preview_with_fallback(
                _entry("character/model/body.pac", ".pac"),
                b"data",
                set(),
                quality_tier="fast",
            )
            full_model, full_parsed, _notes = archive._build_pac_model_preview_with_fallback(
                _entry("character/model/body.pac", ".pac"),
                b"data",
                set(),
                quality_tier="full",
            )

        self.assertLess(fast_model.face_count, full_model.face_count)
        self.assertEqual(60_000, full_model.face_count)
        self.assertIs(parsed_mesh, fast_parsed)
        self.assertIs(parsed_mesh, full_parsed)

    def test_archive_preview_cache_key_has_quality_tier_source_guard(self) -> None:
        source = (
            Path("cdmw/ui/shell/app_window.py").read_text(encoding="utf-8")
            + "\n"
            + Path("cdmw/ui/archive_browser/preview_cache.py").read_text(encoding="utf-8")
            + "\n"
            + Path("cdmw/ui/archive_browser/workers.py").read_text(encoding="utf-8")
        )

        self.assertIn('quality_tier: str = "full"', source)
        self.assertIn('f"quality:{', source)
        self.assertIn('quality_tier="fast"', source)
        self.assertIn('quality_tier="full"', source)

    def test_fast_result_does_not_finalize_request_source_guard(self) -> None:
        source = Path("cdmw/ui/archive_browser/workers.py").read_text(encoding="utf-8")
        handler = source[source.index("def _handle_archive_preview_ready"):source.index("def _handle_archive_preview_error")]

        self.assertIn("is_fast_result = quality_tier == \"fast\"", handler)
        self.assertIn("is_interim_result = is_fast_result or quality_tier == \"quick\" or source == \"quick_preview\"", handler)
        self.assertIn("if not is_interim_result:", handler)
        self.assertIn("Fast preview loaded; refining full-quality preview", handler)

    def test_archive_preview_worker_owns_cache_and_quick_payloads_source_guard(self) -> None:
        source = Path("cdmw/ui/archive_browser/workers.py").read_text(encoding="utf-8")
        worker = Path("cdmw/workers/archive_preview_workers.py").read_text(encoding="utf-8")

        self.assertIn("class _ArchivePreviewWorkerPayload", worker)
        self.assertIn("preview_cache_snapshot", worker)
        self.assertIn("def _cached_preview_payload", worker)
        self.assertIn("def _durable_native_preview_cache_payload", worker)
        self.assertIn("def _quick_archive_model_preview_payload", worker)
        self.assertIn('source="preview_cache"', worker)
        self.assertIn('source="preview_cache_fast"', worker)
        self.assertIn('source="native_package_cache"', worker)
        self.assertIn('source="quick_preview"', worker)
        self.assertIn("emit_private_payloads=True", source)

    def test_preview_loading_watchdog_preserves_fast_result_source_guard(self) -> None:
        source = Path("cdmw/ui/archive_browser/preview_loading.py").read_text(encoding="utf-8")
        watchdog = source[
            source.index("def _handle_archive_preview_loading_stall")
            : source.index("def _stop_archive_preview_loading_indicator")
        ]

        self.assertIn("archive_preview_loading_request_id", source)
        self.assertIn("if int(getattr(self, \"archive_preview_loading_request_id\"", source)
        self.assertIn("preview_phase = \"full_after_fast\"", watchdog)
        self.assertIn("self.archive_preview_worker.stop()", watchdog)
        self.assertIn("self.archive_preview_thread.requestInterruption()", watchdog)
        self.assertIn("self.archive_preview_thread.quit()", watchdog)
        self.assertIn("shutdown_native_preview_core_service()", watchdog)
        self.assertIn('"archive_preview_stalled"', watchdog)
        self.assertIn("preview_stalled=True", watchdog)
        self.assertIn("request_id=request_id", watchdog)
        self.assertIn("self.archive_preview_request_id += 1", watchdog)
        self.assertIn("Fast preview remains visible; full preview timed out and was stopped.", watchdog)


if __name__ == "__main__":
    unittest.main()
