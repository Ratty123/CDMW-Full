import unittest
from pathlib import Path

from cdmw.ui.archive_browser.icon_pipeline import ArchiveIconPipelineMixin
from cdmw.ui.archive_browser.render_lifecycle import ArchiveRenderLifecycleMixin


class _StartupReadinessHarness(ArchiveRenderLifecycleMixin):
    def __init__(self) -> None:
        self.shell = self
        self.archive = self
        self.textures = self
        self.archive_startup_hold_until_ready = True
        self.archive_startup_index_warmup_required = True
        self.archive_startup_saved_filter_apply_pending = False
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


    def test_background_icon_warmup_does_not_force_full_path_index(self) -> None:
        class Timer:
            def stop(self) -> None:
                pass

        class Harness(ArchiveIconPipelineMixin):
            def __init__(self):
                self.shell = self
                self.archive = self
                self.textures = self

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


    def test_remote_item_finder_warmup_starts_after_publish_and_is_shutdown_owned(self) -> None:
        root = Path(__file__).resolve().parents[1]
        files_source = (root / "cdmw/ui/archive_browser/files_panel.py").read_text(encoding="utf-8")
        bridge_source = (root / "cdmw/ui/archive_browser/remote_window_bridge.py").read_text(encoding="utf-8")
        close_source = (root / "cdmw/ui/shell/close_controller.py").read_text(encoding="utf-8")
        publish = bridge_source[
            bridge_source.index("    def _handle_query_published") : bridge_source.index(
                "    def _handle_facets",
                bridge_source.index("    def _handle_query_published"),
            )
        ]

        self.assertIn("RemoteItemFinderWarmupController(", files_source)
        self.assertIn("start_item_finder_warmup(", publish)
        self.assertIn("ui_generation=self._controller.generation", publish)
        self.assertIn("request_item_finder_shutdown()", close_source)
        self.assertLess(
            close_source.index("request_item_finder_shutdown()"),
            close_source.index("request_catalogue_shutdown()"),
        )


if __name__ == "__main__":
    unittest.main()
