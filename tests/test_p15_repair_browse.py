"""Section 8.7 F1: an edit in Browse's view holds that view."""

from __future__ import annotations

from types import SimpleNamespace

from cdmw.models import ArchivePreviewResult
from cdmw.ui.archive_browser.edit_in_place import BrowseEditInPlaceMixin
from cdmw.ui.mesh_editor.live_edit import end_edit_prompt
from tests.test_archive_d3d11_process_lifecycle import _PreviewResultHarness


class _Stack:
    def __init__(self) -> None:
        self.shown: list[object] = []

    def setCurrentWidget(self, widget) -> None:  # noqa: N802 - Qt shape
        self.shown.append(widget)


class _EditingHarness(_PreviewResultHarness):
    def __init__(self, editing: bool) -> None:
        super().__init__()
        self.editing_in_place = editing
        self.archive_preview_stack = _Stack()
        self.archive_texture_preview = SimpleNamespace(load_path=lambda _path: None)
        self.deactivated = 0

    def _deactivate_archive_model_renderers_for_non_model_preview(self) -> None:
        self.deactivated += 1


def test_a_texture_selected_while_editing_leaves_the_edit_in_view() -> None:
    result = ArchivePreviewResult(status="ok", preferred_view="image", preview_texture_path="body.dds")
    editing = _EditingHarness(editing=True)
    editing._show_archive_preview_result(result, use_loose=False, request_id=0)
    assert editing.deactivated == 0 and editing.archive_preview_stack.shown == []
    # Without an edit the texture is shown, as before.
    browsing = _EditingHarness(editing=False)
    browsing._show_archive_preview_result(result, use_loose=False, request_id=0)
    assert browsing.deactivated == 1 and browsing.archive_preview_stack.shown


def test_preview_selected_while_the_edit_prepares_cancels_it(monkeypatch) -> None:
    """In the first seconds nothing is pending yet; the prepared edit must not open later."""

    closed, ended = [], []
    tab = SimpleNamespace(
        has_active_standalone_session=lambda: False,
        live_edit=SimpleNamespace(is_ready=False),
        close_standalone_session=lambda: closed.append(True) or True,
    )
    browse = SimpleNamespace(
        _browse_edit_document=lambda: tab,
        _archive_edit_layout=lambda: SimpleNamespace(entry=SimpleNamespace(basename="sword.pac")),
        _edit_in_place_binding=SimpleNamespace(end=lambda: ended.append(True), is_ended=False),
    )
    monkeypatch.setattr(end_edit_prompt, "prompt_override", lambda parent, label: end_edit_prompt.KEEP)
    BrowseEditInPlaceMixin._preview_selected_instead_of_edit(browse)
    assert ended == [True]
    assert closed == [True], "the edit being prepared would open through the ended binding"


def test_replace_mesh_from_file_says_why_it_is_unavailable(qapp=None) -> None:
    """Section 8.7 F5: the held-back command gave the mesh-selection reason, or none."""

    from PySide6.QtWidgets import QApplication, QPushButton

    from cdmw.ui.archive_browser.action_controls import (
        MESH_REPLACEMENT_HELD_BACK_REASON,
        ArchiveBrowserActionControlsMixin,
    )
    from cdmw.ui.archive_browser.actions import ArchiveBrowserActionMixin
    from cdmw.ui.archive_browser.browse_commands import REASON_PROPERTY

    QApplication.instance() or QApplication([])

    class _Browse(ArchiveBrowserActionControlsMixin, ArchiveBrowserActionMixin):
        def __init__(self) -> None:
            self.shell = SimpleNamespace(worker_thread=None)
            self.archive_preview_showing_loose = False
            self._buttons: dict[str, QPushButton] = {}

        def __getattr__(self, name: str):
            if name.endswith("_button"):
                return self.__dict__["_buttons"].setdefault(name, QPushButton())
            return _Nothing()

    class _Nothing:
        """Every other part of Browse: answers anything, holds nothing."""

        def __getattr__(self, _name):
            return self

        def __call__(self, *args, **kwargs):
            return self

        def __bool__(self) -> bool:
            return False

        def __iter__(self):
            return iter(())

        def __len__(self) -> int:
            return 0

    browse = _Browse()
    browse._update_archive_model_action_controls(None)
    button = browse.archive_model_import_mesh_button
    assert not button.isEnabled()
    assert button.property(REASON_PROPERTY) == MESH_REPLACEMENT_HELD_BACK_REASON


def test_a_selection_made_while_editing_shows_when_the_edit_ends() -> None:
    """Section 8.8 R9: the texture selected meanwhile was dropped and never shown."""

    result = ArchivePreviewResult(status="ok", preferred_view="image", preview_texture_path="body.dds")
    browse = _EditingHarness(editing=True)
    browse._show_archive_preview_result(result, use_loose=False, request_id=0)
    assert browse.deactivated == 0
    browse.editing_in_place = False  # the edit ended
    browse._show_preview_held_for_edit()
    assert browse.deactivated == 1 and browse.archive_preview_stack.shown, "the held selection never showed"
    # Shown once: a second end shows nothing again.
    browse._show_preview_held_for_edit()
    assert browse.deactivated == 1
