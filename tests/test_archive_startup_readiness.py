import unittest
from pathlib import Path
from types import SimpleNamespace

from cdmw.ui.archive_browser.icon_pipeline import ArchiveIconPipelineMixin
from cdmw.ui.archive_browser.render_lifecycle import ArchiveRenderLifecycleMixin
from cdmw.ui.archive_browser.workers import ArchivePreviewWorkerMixin


class _StartupReadinessHarness(ArchiveRenderLifecycleMixin):
    def __init__(self) -> None:
        self.archive_startup_hold_until_ready = True
        self.archive_startup_index_warmup_required = True
        self.archive_startup_saved_filter_apply_pending = False
        self.archive_basic_index_state = "warming"
        self.archive_enhanced_index_state = "warming"
        self.archive_basic_index_thread = object()
        self.archive_enhanced_index_thread = object()
        self.archive_derived_cache_thread = object()
        self.archive_derived_cache_write_pending = True
        self.archive_deferred_derived_cache_write_pending = True
        self.archive_scan_finalize_pending = False
        self.worker_thread = None
        self._startup_splash_window = object()
        self.render_ready = True
        self.events: list[object] = []

    def _startup_archive_browser_render_ready(self) -> bool:
        return self.render_ready

    def _update_startup_splash(self, *args: object) -> None:
        self.events.append(("splash", args))

    def _write_heartbeat(self, phase: str) -> None:
        self.events.append(("heartbeat", phase))

    def _release_startup_splash(self) -> None:
        self.events.append("release")

    def _schedule_archive_post_ready_background_work(self, delay_ms: int | None = None) -> None:
        self.events.append(("background", delay_ms))


class ArchiveStartupReadinessTests(unittest.TestCase):
    def test_background_index_and_cache_workers_do_not_block_startup_readiness(self) -> None:
        harness = _StartupReadinessHarness()

        self.assertTrue(harness._startup_archive_core_ready())

    def test_ready_list_releases_splash_before_background_warmup(self) -> None:
        harness = _StartupReadinessHarness()

        harness._maybe_release_startup_after_archive_ready()

        self.assertFalse(harness.archive_startup_hold_until_ready)
        self.assertFalse(harness.archive_startup_index_warmup_required)
        self.assertEqual(harness.events[-2:], ["release", ("background", None)])

    def test_headless_startup_still_schedules_background_warmup(self) -> None:
        harness = _StartupReadinessHarness()
        harness._startup_splash_window = None

        harness._maybe_release_startup_after_archive_ready()

        self.assertFalse(harness.archive_startup_hold_until_ready)
        self.assertFalse(harness.archive_startup_index_warmup_required)
        self.assertEqual(harness.events, [("background", None)])

    def test_autoload_completes_indexes_before_splash_release(self) -> None:
        root = Path(__file__).resolve().parents[1]
        scan_source = (root / "cdmw/ui/archive_browser/scan_lifecycle.py").read_text(encoding="utf-8")
        render_source = (root / "cdmw/ui/archive_browser/render_lifecycle.py").read_text(encoding="utf-8")
        startup_source = (root / "cdmw/ui/shell/startup_controller.py").read_text(encoding="utf-8")
        app_source = (root / "cdmw/ui/shell/app_window.py").read_text(encoding="utf-8")
        source = "\n".join((app_source, startup_source, scan_source, render_source))
        autoload = source[source.index("    def _maybe_autoload_archive_on_startup(self) -> None:") : source.index("    def _load_game_executable_fingerprints")]
        scan = scan_source[scan_source.index("    def scan_archives(") : scan_source.index("    def _ensure_archive_extension_index_ready")]
        complete = scan_source[scan_source.index("    def _handle_archive_scan_complete(self, result: object) -> None:") : scan_source.index("    def _finalize_archive_scan_complete")]
        ready = render_source[render_source.index("    def _startup_archive_core_ready(self) -> bool:") : render_source.index("    def _maybe_release_startup_after_archive_ready")]
        release = render_source[render_source.index("    def _maybe_release_startup_after_archive_ready(self) -> None:") : render_source.index("    def _try_apply_startup_saved_filters")]
        first_paint = render_source[render_source.index("    def _handle_archive_browser_first_visible_paint") : render_source.index("\n\n__all__")]

        self.assertIn("self.archive_startup_index_warmup_required = True", autoload)
        self.assertNotIn("self._release_startup_splash()", autoload[autoload.index("        self.scan_archives(") :])
        self.assertIn("startup_index_warmup = bool(", scan)
        self.assertIn("startup_index_warmup\n                or self.archive_startup_saved_filter_apply_pending", scan)
        self.assertIn("load_name_search_index_cache=startup_index_warmup", scan)
        self.assertIn(
            "defer_enhanced_index_build=bool(startup_deferred_archive_load and not startup_index_warmup)",
            scan,
        )
        self.assertNotIn("startup_index_warmup = bool(", complete)
        basic_prewarm = complete[
            complete.index("        prewarm_basic_index = bool(") : complete.index("        self.archive_basic_index_state =")
        ]
        enhanced_prewarm = complete[
            complete.index("        prewarm_enhanced_index = bool(") : complete.index("        self.archive_enhanced_index_auto_prewarm_pending =")
        ]
        self.assertNotIn("startup_index_warmup", basic_prewarm)
        self.assertNotIn("startup_index_warmup", enhanced_prewarm)
        self.assertIn("self.archive_enhanced_index_auto_prewarm_pending = False", complete)
        self.assertIn("and priority_prewarm_indexes", complete)
        self.assertNotIn("_start_archive_structure_filter_worker", first_paint)
        self.assertIn("self._startup_archive_browser_render_ready()", ready)
        for thread_name in ("archive_basic_index_thread", "archive_enhanced_index_thread", "archive_derived_cache_thread"):
            self.assertNotIn(thread_name, ready)
        self.assertIn("self._release_startup_splash()\n        self._schedule_archive_post_ready_background_work()", release)

    def test_background_icon_warmup_does_not_force_full_path_index(self) -> None:
        class Timer:
            def stop(self) -> None:
                pass

        class Harness(ArchiveIconPipelineMixin):
            archive_item_asset_catalog = [{"icon_paths": ("icon.dds",)}]
            archive_item_icon_preload_pending_after_ready = False
            archive_item_icon_preload_timer = Timer()
            archive_item_icon_preload_queue: list[object] = []
            archive_item_icon_preload_next_index = 0

            def _archive_icon_warmup_should_run(self) -> bool:
                return True

            def _archive_browser_background_work_allowed(self) -> bool:
                return True

            def _archive_item_icon_lookup_index_missing(self) -> bool:
                return True

            def _ensure_archive_basic_index_worker_started(self) -> bool:
                raise AssertionError("background icon warmup forced the full path index")

        harness = Harness()
        harness._schedule_archive_asset_catalog_icon_preload()

        self.assertTrue(harness.archive_item_icon_preload_pending_after_ready)

    def test_model_preview_waits_for_material_lookup_index(self) -> None:
        class Harness(ArchivePreviewWorkerMixin):
            scheduled_archive_preview_request = (
                3,
                SimpleNamespace(extension=".pac", path="character/sword.pac"),
                False,
                False,
            )
            ensured = False
            detail = ""
            status = ""

            def _mesh_replacement_builder_active(self) -> bool:
                return False

            def _archive_basic_index_missing_for_lookup(self) -> bool:
                return True

            def _ensure_archive_basic_index_worker_started(self) -> bool:
                self.ensured = True
                return True

            def _set_archive_preview_base_detail_text(self, text: str, **_kwargs: object) -> None:
                self.detail = text

            def set_status_message(self, text: str) -> None:
                self.status = text

        harness = Harness()
        harness._flush_scheduled_archive_preview_request()

        self.assertTrue(harness.ensured)
        self.assertIsNotNone(harness.scheduled_archive_preview_request)
        self.assertIn("material and texture lookup", harness.detail)


if __name__ == "__main__":
    unittest.main()
