"""Repeat preview requests must not restart the work or blank the panel.

Twelve call sites ask for an archive preview and several fire for one user
action, so an asset was routinely requested two or three times in a row. Each
repeat took a new generation and reset the whole visible preview surface, which
is what the panel blanking and the Details tab jumping back to Preview were.
"""

import unittest
from pathlib import Path
from types import SimpleNamespace
from typing import Optional

from cdmw.models import ArchiveEntry
from cdmw.ui.archive_browser.preview_dotnet_lifecycle import (
    ArchivePreviewDotNetLifecycleMixin,
)
from cdmw.ui.archive_browser.preview_loading import ArchivePreviewLoadingMixin
from cdmw.ui.archive_browser.workers import ArchivePreviewWorkerMixin


def _entry(path: str) -> ArchiveEntry:
    return ArchiveEntry(
        path=path,
        pamt_path=Path("package.pamt"),
        paz_file=Path("package_0.paz"),
        offset=0,
        comp_size=100,
        orig_size=100,
        flags=0,
        paz_index=0,
    )


class _Timer:
    def __init__(self) -> None:
        self.starts: list[object] = []

    def start(self, interval: object = None) -> None:
        self.starts.append(interval)

    def stop(self) -> None:
        pass


class _DispatchHost(ArchivePreviewWorkerMixin):
    """The dispatcher's collaborators, reduced to what it actually calls."""

    def __init__(self) -> None:
        self.archive_preview_request_id = 0
        self.scheduled_archive_preview_request = None
        self.pending_archive_preview_request = None
        self.archive_preview_cache_keys: dict[int, str] = {}
        self.archive_preview_request_started_at: dict[int, float] = {}
        self.archive_preview_request_phase_timings: dict[int, dict] = {}
        self.archive_preview_request_sources: dict[int, str] = {}
        self.archive_preview_quick_result_active = False
        self.archive_preview_requested_loose = False
        self.archive_preview_track_index = 0
        self.archive_preview_debounce_timer = _Timer()
        self.archive_remote_bridge = None
        self._archive_texture_request_id = 0
        self.loading_states_shown: list[str] = []
        self.runtime_events: list[tuple[str, dict]] = []

    def _ensure_archive_preview_startup_state(self) -> None:
        pass

    def _mesh_replacement_builder_active(self) -> bool:
        return False

    def _archive_model_renderer_backend(self) -> str:
        return "software"

    def _show_archive_preview_loading_state(self, entry: Optional[ArchiveEntry]) -> None:
        self.loading_states_shown.append(str(getattr(entry, "path", "") or ""))

    def append_archive_log(self, message: str, verbose: bool = False) -> None:
        pass

    def _set_last_active_operation(self, operation: str, **fields: object) -> None:
        pass

    def _record_runtime_event(self, event: str, **fields: object) -> None:
        self.runtime_events.append((event, dict(fields)))


class _TextureRequestHost(ArchivePreviewDotNetLifecycleMixin):
    def __init__(self) -> None:
        self.entry = _entry("character/model/body.pac")
        self.archive_preview_request_id = 4
        self._archive_texture_request_loading = False
        self.builder_active = False
        self.deferred: list[object] = []
        self.render_requests: list[tuple[object, bool]] = []
        self.status_messages: list[str] = []

    def _current_archive_entry(self) -> object:
        return self.entry

    def _mesh_replacement_builder_active(self) -> bool:
        return self.builder_active

    def _defer_archive_preview_refresh_for_builder(self, entry: object) -> None:
        self.deferred.append(entry)

    def _sync_archive_texture_action_state(self) -> None:
        pass

    def set_status_message(self, message: str, *, error: bool = False) -> None:
        self.status_messages.append(str(message))

    def _render_archive_preview(self, entry: object, *, force: bool = False) -> None:
        self.render_requests.append((entry, bool(force)))


class _Label:
    def __init__(self) -> None:
        self.text = ""
        self.visible = False
        self.tooltip = ""
        self.cleared = 0

    def setText(self, value: str) -> None:
        self.text = str(value)

    def setVisible(self, value: bool) -> None:
        self.visible = bool(value)

    def setToolTip(self, value: str) -> None:
        self.tooltip = str(value)

    def clear(self) -> None:
        self.cleared += 1
        self.text = ""

    def setPlainText(self, value: str) -> None:
        self.text = str(value)

    def setEnabled(self, value: bool) -> None:
        pass


class _Tabs:
    def __init__(self) -> None:
        self.index = 2

    def setCurrentIndex(self, value: int) -> None:
        self.index = int(value)


class _LoadingHost(ArchivePreviewLoadingMixin):
    """The loading state's collaborators, reduced the same way."""

    def __init__(self) -> None:
        self.archive_preview_requested_loose = False
        self.current_archive_preview_result = SimpleNamespace(quality_tier="full")
        self.archive_preview_surface_identity_shown = ""
        self.archive_preview_loading_reuses_surface = False
        self.archive_preview_loading_started_at = 0.0
        self.archive_preview_loading_request_id = 0
        self.archive_preview_loading_stall_reported = False
        self.archive_preview_loading_entry_name = ""
        self.archive_preview_loading_loose = False
        self.archive_preview_quick_result_active = False
        self.archive_preview_request_id = 7
        self.archive_preview_title_label = _Label()
        self.archive_preview_meta_label = _Label()
        self.archive_preview_role_badge = _Label()
        self.archive_preview_warning_badge = _Label()
        self.archive_preview_warning_label = _Label()
        self.archive_preview_loose_toggle_button = _Label()
        self.archive_preview_info_edit = _Label()
        self.archive_preview_text_edit = _Label()
        self.archive_preview_tabs = _Tabs()
        self.archive_preview_loading_timer = _Timer()
        self.archive_d3d11_preview_host = None
        self.texture_reference_views_cleared = 0
        self.status_messages: list[str] = []

    def _archive_entry_role_label(self, entry: Optional[ArchiveEntry]) -> str:
        return "Model"

    def _archive_model_renderer_backend(self) -> str:
        return "software"

    def _set_archive_preview_health_message(self, message: str, visible: bool = False) -> None:
        pass

    def _clear_archive_texture_reference_views(self) -> None:
        self.texture_reference_views_cleared += 1

    def _set_archive_preview_base_detail_text(self, text: str, include_current_model_debug: bool = True) -> None:
        pass

    def _update_archive_model_action_controls(self, value: object) -> None:
        pass

    def _set_archive_preview_image_controls_enabled(self, value: bool) -> None:
        pass

    def _update_archive_preview_loading_indicator(self) -> None:
        pass

    def set_status_message(self, message: str, error: bool = False) -> None:
        self.status_messages.append(str(message))

    @property
    def archive_preview_stack(self) -> SimpleNamespace:
        return SimpleNamespace(setCurrentWidget=lambda widget: None)

    @property
    def archive_preview_label(self) -> SimpleNamespace:
        return SimpleNamespace(clear_preview=lambda message: None)

    @property
    def archive_media_preview(self) -> SimpleNamespace:
        return SimpleNamespace(clear_media=lambda message: None)


class ArchivePreviewRequestCoalescingTests(unittest.TestCase):
    def test_automatic_texture_request_waits_while_mesh_builder_is_active(self) -> None:
        host = _TextureRequestHost()
        host.builder_active = True

        self.assertFalse(host._request_archive_preview_textures(automatic=True))

        self.assertEqual(host.deferred, [host.entry])
        self.assertEqual(host.render_requests, [])
        self.assertFalse(host._archive_texture_request_loading)
        self.assertEqual(host.archive_preview_request_id, 4)

    def test_explicit_texture_request_remains_available_while_builder_is_active(self) -> None:
        host = _TextureRequestHost()
        host.builder_active = True

        self.assertTrue(host._request_archive_preview_textures(automatic=False))

        self.assertEqual(host.deferred, [])
        self.assertEqual(host.render_requests, [(host.entry, True)])
        self.assertTrue(host._archive_texture_request_loading)
        self.assertEqual(host._archive_texture_request_id, 5)

    def test_repeat_request_folds_into_the_scheduled_one(self) -> None:
        host = _DispatchHost()
        entry = _entry("character/model/sword.pac")

        host._render_archive_preview(entry)
        first_generation = host.archive_preview_request_id
        host._render_archive_preview(entry)
        host._render_archive_preview(entry)

        self.assertEqual(host.archive_preview_request_id, first_generation)
        self.assertEqual(host.loading_states_shown, [entry.path])
        self.assertEqual(
            [name for name, _ in host.runtime_events].count("archive_preview_request_coalesced"),
            2,
        )

    def test_a_forced_repeat_upgrades_the_scheduled_request(self) -> None:
        host = _DispatchHost()
        entry = _entry("character/model/sword.pac")

        host._render_archive_preview(entry)
        self.assertFalse(host.scheduled_archive_preview_request[3])
        host._render_archive_preview(entry, force=True)

        self.assertTrue(host.scheduled_archive_preview_request[3])
        self.assertEqual(host.archive_preview_request_id, 1)

    def test_a_different_entry_is_never_folded(self) -> None:
        host = _DispatchHost()

        host._render_archive_preview(_entry("a.pac"))
        host._render_archive_preview(_entry("b.pac"))

        self.assertEqual(host.archive_preview_request_id, 2)
        self.assertEqual(host.loading_states_shown, ["a.pac", "b.pac"])

    def test_a_different_loose_preference_is_never_folded(self) -> None:
        host = _DispatchHost()
        entry = _entry("a.pac")

        host._render_archive_preview(entry)
        host._render_archive_preview(entry, include_loose_preview_assets=True)

        self.assertEqual(host.archive_preview_request_id, 2)

    def test_an_armed_texture_request_is_never_folded(self) -> None:
        """The texture action reserves the next generation before it asks.

        `_request_archive_preview_textures` sets `_archive_texture_request_id`
        to `archive_preview_request_id + 1` and then calls the dispatcher,
        expecting it to create exactly that generation. Folding that call means
        the generation never arrives, `_archive_texture_request_loading` stays
        true, and Load Textures is stuck reporting itself busy for good.
        """

        host = _DispatchHost()
        entry = _entry("a.pac")
        host._render_archive_preview(entry)
        armed_generation = host.archive_preview_request_id + 1
        host._archive_texture_request_id = armed_generation

        host._render_archive_preview(entry, force=True)

        self.assertEqual(host.archive_preview_request_id, armed_generation)

    def test_a_stale_scheduled_request_is_never_folded(self) -> None:
        host = _DispatchHost()
        entry = _entry("a.pac")
        host._render_archive_preview(entry)
        # Something else advanced the generation without clearing the schedule.
        host.archive_preview_request_id += 1

        host._render_archive_preview(entry)

        self.assertEqual(host.archive_preview_request_id, 3)


class ArchivePreviewLoadingSurfaceTests(unittest.TestCase):
    def test_the_same_entry_keeps_the_surface_it_already_has(self) -> None:
        host = _LoadingHost()
        entry = _entry("character/model/sword.pac")
        host.archive_preview_warning_badge.setText("2 unresolved textures")
        host.archive_preview_tabs.setCurrentIndex(2)

        host._show_archive_preview_loading_state(entry)
        self.assertEqual(host.archive_preview_tabs.index, 0)
        self.assertEqual(host.texture_reference_views_cleared, 1)

        host.archive_preview_warning_badge.setText("2 unresolved textures")
        host.archive_preview_tabs.setCurrentIndex(2)
        host._show_archive_preview_loading_state(entry)

        self.assertTrue(host.archive_preview_loading_reuses_surface)
        self.assertEqual(host.archive_preview_tabs.index, 2)
        self.assertEqual(host.archive_preview_warning_badge.text, "2 unresolved textures")
        self.assertEqual(host.texture_reference_views_cleared, 1)

    def test_a_different_entry_still_resets_everything(self) -> None:
        host = _LoadingHost()

        host._show_archive_preview_loading_state(_entry("a.pac"))
        host.archive_preview_tabs.setCurrentIndex(2)
        host._show_archive_preview_loading_state(_entry("b.pac"))

        self.assertFalse(host.archive_preview_loading_reuses_surface)
        self.assertEqual(host.archive_preview_tabs.index, 0)
        self.assertEqual(host.texture_reference_views_cleared, 2)

    def test_an_empty_surface_resets_even_for_the_same_entry(self) -> None:
        """A cleared preview holds no result, so there is nothing to keep."""

        host = _LoadingHost()
        entry = _entry("a.pac")

        host._show_archive_preview_loading_state(entry)
        host.current_archive_preview_result = None
        host.archive_preview_tabs.setCurrentIndex(2)
        host._show_archive_preview_loading_state(entry)

        self.assertFalse(host.archive_preview_loading_reuses_surface)
        self.assertEqual(host.archive_preview_tabs.index, 0)

    def test_the_loose_view_of_one_path_is_a_different_surface(self) -> None:
        host = _LoadingHost()
        entry = _entry("a.pac")

        host._show_archive_preview_loading_state(entry)
        host.archive_preview_requested_loose = True
        host.archive_preview_tabs.setCurrentIndex(2)
        host._show_archive_preview_loading_state(entry)

        self.assertFalse(host.archive_preview_loading_reuses_surface)
        self.assertEqual(host.archive_preview_tabs.index, 0)


if __name__ == "__main__":
    unittest.main()
