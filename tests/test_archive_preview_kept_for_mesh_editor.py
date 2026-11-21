"""Browse keeps its 3D view when the Mesh Editor opens the model it shows (2026-11-21).

The view used to be cleared on every Mesh Editor open, so Browse stayed empty until
Refresh. Now only a texture load the paused (hidden) view cannot acknowledge is settled.
"""
from __future__ import annotations

from types import SimpleNamespace

from cdmw.ui.archive_browser.preview_cache import ArchivePreviewCacheMixin
from cdmw.ui.archive_browser.preview_dotnet_lifecycle import ArchivePreviewDotNetLifecycleMixin


class _Controller:
    def __init__(self) -> None:
        self.cleared = 0
        self.shut_down = 0

    def clear_preview(self) -> None:
        self.cleared += 1

    def shutdown(self) -> None:
        self.shut_down += 1


class _Archive(ArchivePreviewDotNetLifecycleMixin, ArchivePreviewCacheMixin):
    def __init__(self, shown: object) -> None:
        self.shown = shown
        self.events: list[str] = []
        self.applied: list[tuple[str, int]] = []
        self.shell = SimpleNamespace(_shutting_down=False,
                                     _record_runtime_event=lambda name, **_kw: self.events.append(name))
        self.archive_d3d11_preview_host = SimpleNamespace(controller=_Controller())
        self.archive_preview_cache = {}
        self.current_archive_preview_result = None
        self.archive_isolated_renderer_active_package = "geometry"
        self._archive_texture_request_loading = False
        self._archive_texture_request_id = 0
        self._archive_texture_package_path = ""
        self._archive_texture_package_generation = 0
        self._archive_textures_visible = False

    def _current_archive_entry(self):
        return self.shown

    @staticmethod
    def _same_archive_entry(first, second) -> bool:
        return first is second

    def _sync_archive_texture_action_state(self) -> None:
        pass

    def _handle_archive_resident_package_applied(self, package_path: str, generation: int) -> None:
        self.applied.append((package_path, generation))
        self._archive_texture_request_loading = False
        self.archive_isolated_renderer_active_package = package_path


ENTRY = SimpleNamespace(path="character/model/sword.pac")


def test_opening_the_shown_model_keeps_browse_view() -> None:
    archive = _Archive(ENTRY)
    archive._strip_archive_preview_heavy_payloads_for_mesh_editor(ENTRY)
    controller = archive.archive_d3d11_preview_host.controller
    assert controller.cleared == 0 and controller.shut_down == 0
    assert archive.archive_isolated_renderer_active_package == "geometry"
    assert "mesh_editor_archive_preview_payloads_stripped" in archive.events


def test_a_textured_package_sent_to_the_paused_view_is_taken_as_applied() -> None:
    archive = _Archive(ENTRY)
    archive._archive_texture_request_loading = True
    archive._archive_texture_request_id = 7
    archive._archive_texture_package_path = "textured"
    archive._archive_texture_package_generation = 3
    archive._strip_archive_preview_heavy_payloads_for_mesh_editor(ENTRY)
    assert archive.applied == [("textured", 3)]
    assert not archive._archive_texture_request_loading
    assert archive.archive_isolated_renderer_active_package == "textured"
    assert archive.archive_d3d11_preview_host.controller.cleared == 0


def test_a_texture_load_still_being_prepared_is_withdrawn_so_the_next_model_can_load() -> None:
    archive = _Archive(ENTRY)
    archive._archive_texture_request_loading = True
    archive._archive_texture_request_id = 7
    archive._strip_archive_preview_heavy_payloads_for_mesh_editor(ENTRY)
    assert archive.applied == []
    assert not archive._archive_texture_request_loading and archive._archive_texture_request_id == 0
    assert archive.archive_isolated_renderer_active_package == "geometry"
    assert archive.archive_d3d11_preview_host.controller.cleared == 0


def test_another_model_leaves_browse_texture_load_alone() -> None:
    archive = _Archive(SimpleNamespace(path="other.pac"))
    archive._archive_texture_request_loading = True
    archive._archive_texture_request_id = 7
    archive._strip_archive_preview_heavy_payloads_for_mesh_editor(ENTRY)
    assert archive._archive_texture_request_loading and archive._archive_texture_request_id == 7
