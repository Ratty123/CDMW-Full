"""When the Mesh Editor's Textures panel and Texture Editor panel are shown (2026-11-17).

Fredric: the panels "shouldn't be open per default, but it should be a clear option to
click", "pressing close in Mesh Editor doesn't close the Texture editor", and "loading a
new mesh ... the loading window still contains the texture editor opened".
"""

from __future__ import annotations

import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QSettings, Signal
from PySide6.QtWidgets import QApplication, QPushButton, QScrollArea, QToolButton, QWidget

from cdmw.ui.mesh_editor.texture_panels import SHOWN_KEY
from cdmw.ui.mesh_editor.texture_tools_dock import EMPTY_TEXT, LiveTextureTarget
from cdmw.ui.mesh_editor.textures_panel import DOCK_LAYOUT_KEY, remember_dock_layout
from cdmw.ui.mesh_editor.workspace import MeshEditorWorkspace

_APP = QApplication.instance() or QApplication([])


class _FakeEditor(QWidget):
    resident_texture_patch_ready = Signal(object)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.opened: list[Path] = []
        self.history_index = 1
        self.undo_button = QPushButton("Undo", self)
        self.redo_button = QPushButton("Redo", self)
        self.tool_buttons = {key: QToolButton(self) for key in ("paint", "erase")}
        self.tool_settings_section = QWidget(self)
        self.layers_section = QWidget(self)
        self.canvas_scroll = QScrollArea(self)

    def open_source_path(self, path, *, binding=None) -> None:
        self.opened.append(Path(path))


def _manifest() -> dict[str, object]:
    return {
        "textures": [{"label": "cd_armor_01_d.dds", "role": "base_color",
                      "file": {"path": "texture-0000.dds", "sha256": "A" * 64},
                      "material_indices_by_lod": [[0]]}],
        "state": {"skeleton": {"parts": [{"index": 0, "name": "Chest"}]}},
    }


def _settle() -> None:
    for _ in range(5):
        _APP.processEvents()


def _page(settings: QSettings | None = None) -> MeshEditorWorkspace:
    page = MeshEditorWorkspace(theme_key="graphite", defer_legacy_panels=True)
    page.texture_tools_dock._editor_factory = _FakeEditor
    page.resize(1400, 800)
    page.show()
    if settings is not None:
        # As the Mesh Editor tab does: where the docks were, then whether they show.
        remember_dock_layout(page.dock_host, (page.textures_dock, page.texture_tools_dock), settings)
        page.texture_panels.use_settings(settings)
    _settle()
    return page


def _open_texture(page: MeshEditorWorkspace, tmp_path: Path, name: str = "a.dds") -> None:
    page.texture_tools_dock.open_target(LiveTextureTarget(
        session_id="doc", source_path=str(tmp_path / name), source_sha256="cd" * 32,
        channel="base_color", display_name=name))
    _settle()


def _shown(page: MeshEditorWorkspace) -> tuple[bool, bool]:
    return page.textures_dock.isVisible(), page.texture_tools_dock.isVisible()


def test_both_panels_are_off_until_the_user_asks_and_a_mesh_is_open(tmp_path: Path) -> None:
    page = _page()
    try:
        panels, textures = page.texture_panels, page.textures_dock
        assert _shown(page) == (False, False) and not panels.wanted
        # A mesh's textures alone do not open the panel.
        textures.set_manifest(_manifest(), session_root=tmp_path)
        _settle()
        assert _shown(page) == (False, False)
        # Asked for: the list shows. The Texture Editor waits for a double-click.
        panels.set_wanted(True)
        _settle()
        assert _shown(page) == (True, False)
        _open_texture(page, tmp_path)
        assert _shown(page) == (True, True)
        # Turned off, only the list goes; the open texture stays in its panel.
        panels.set_wanted(False)
        _settle()
        assert _shown(page) == (False, True)
        panels.set_wanted(True)
        _settle()
        assert _shown(page) == (True, True) and page.texture_tools_dock.title_label.text() == "a.dds"
        # Asked for with no mesh open, there is nothing to show yet.
        textures.clear()
        _settle()
        assert _shown(page) == (False, False) and panels.wanted
    finally:
        page.deleteLater()


def test_the_panels_go_when_the_mesh_closes_or_another_loads(tmp_path: Path) -> None:
    from cdmw.ui.mesh_editor.live_texture_reset import close_texture_editor_panel

    page = _page()
    try:
        panels, textures, tools = page.texture_panels, page.textures_dock, page.texture_tools_dock
        panels.set_wanted(True)
        textures.set_manifest(_manifest(), session_root=tmp_path)
        _open_texture(page, tmp_path)
        tools.set_kept_text("Texture edits are not kept yet: Finish keeps them in the draft.")
        assert _shown(page) == (True, True)
        # The editor's session ends (Close, or the first step of loading another mesh):
        # the list is cleared, and the Texture Editor goes with it.
        textures.show_session(None)
        _settle()
        assert _shown(page) == (False, False)
        # Close also empties the panel: it does not name the last mesh's texture again.
        close_texture_editor_panel(type("Tab", (), {"_texture_tools_panel": lambda self: tools})())
        assert tools.target is None and tools.title_label.text() == EMPTY_TEXT
        assert tools.kept_text == "" and not tools.warning_marker.isVisibleTo(tools)
        # The next mesh shows its list; the Texture Editor waits for a texture of this mesh.
        textures.set_manifest(_manifest(), session_root=tmp_path / "next")
        _settle()
        assert _shown(page) == (True, False)
        _open_texture(page, tmp_path, "b.dds")
        assert _shown(page) == (True, True)
    finally:
        page.deleteLater()


def test_a_floating_texture_editor_goes_with_the_mesh_too(tmp_path: Path) -> None:
    page = _page()
    try:
        page.texture_panels.set_wanted(True)
        page.textures_dock.set_manifest(_manifest(), session_root=tmp_path)
        # Floated before it shows: offscreen Qt crashes at exit when a shown dock is
        # floated after events ran (it does on the code before this change too).
        page.texture_tools_dock.setFloating(True)
        _open_texture(page, tmp_path)
        assert page.texture_tools_dock.isFloating() and page.texture_tools_dock.isVisible()
        page.textures_dock.clear()
        _settle()
        assert _shown(page) == (False, False)
    finally:
        page.deleteLater()


def test_the_choice_is_remembered_and_a_saved_layout_does_not_override_it(tmp_path: Path) -> None:
    settings = QSettings(str(tmp_path / "s.ini"), QSettings.Format.IniFormat)
    page = _page(settings)
    try:
        assert not page.texture_panels.wanted and settings.value(SHOWN_KEY) is None
        page.texture_panels.set_wanted(True)
        page.textures_dock.set_manifest(_manifest(), session_root=tmp_path)
        _settle()
        assert settings.value(SHOWN_KEY) in (True, "true")
        # The layout is saved while the list shows.
        settings.setValue(DOCK_LAYOUT_KEY, page.dock_host.saveState())
    finally:
        page.deleteLater()
    settings.sync()

    again = _page(QSettings(str(tmp_path / "s.ini"), QSettings.Format.IniFormat))
    try:
        # Remembered, but the saved layout does not show the list before a mesh is open.
        assert again.texture_panels.wanted and _shown(again) == (False, False)
        again.textures_dock.set_manifest(_manifest(), session_root=tmp_path)
        _settle()
        assert _shown(again) == (True, False)
        # The panel's own close button turns the choice off.
        again.textures_dock.close()
        _settle()
        assert not again.texture_panels.wanted and _shown(again) == (False, False)
    finally:
        again.deleteLater()

    off = _page(QSettings(str(tmp_path / "s.ini"), QSettings.Format.IniFormat))
    try:
        # Off is remembered too, although the saved layout had the list shown.
        off.textures_dock.set_manifest(_manifest(), session_root=tmp_path)
        _settle()
        assert not off.texture_panels.wanted and _shown(off) == (False, False)
    finally:
        off.deleteLater()


def test_only_the_textures_button_shows_a_panel_not_a_right_click_menu(tmp_path: Path) -> None:
    from PySide6.QtCore import Qt

    page = _page()
    try:
        page.textures_dock.set_manifest(_manifest(), session_root=tmp_path)
        # Qt offers every closable dock in the host's right-click menu; that would show
        # an empty Texture Editor, or the list with the Textures button still off.
        assert page.dock_host.contextMenuPolicy() == Qt.ContextMenuPolicy.PreventContextMenu
        for dock in (page.textures_dock, page.texture_tools_dock):
            action = dock.toggleViewAction()
            assert not action.isEnabled() and not action.isVisible()
            action.trigger()
        _settle()
        assert _shown(page) == (False, False) and not page.texture_panels.wanted
    finally:
        page.deleteLater()


def test_closing_the_texture_editor_panel_hides_it_and_a_texture_opens_it_again(tmp_path: Path) -> None:
    page = _page()
    try:
        page.texture_panels.set_wanted(True)
        page.textures_dock.set_manifest(_manifest(), session_root=tmp_path)
        _open_texture(page, tmp_path)
        page.texture_tools_dock.close()
        _settle()
        assert _shown(page) == (True, False)
        _open_texture(page, tmp_path)
        assert _shown(page) == (True, True)
        # Opening a texture while the list is off (Undo bringing one forward, a command)
        # shows the Texture Editor only: the list stays as the user left it.
        page.texture_panels.set_wanted(False)
        page.texture_tools_dock.close()
        _settle()
        assert _shown(page) == (False, False)
        _open_texture(page, tmp_path)
        assert not page.texture_panels.wanted and _shown(page) == (False, True)
    finally:
        page.deleteLater()


def test_closing_the_list_keeps_the_open_texture_in_its_own_panel(tmp_path: Path) -> None:
    """Fredric: "close only the texture list and keep the texture you opened/editing open,
    so you get a bigger workspace"."""

    page = _page()
    try:
        panels, textures, tools = page.texture_panels, page.textures_dock, page.texture_tools_dock
        panels.set_wanted(True)
        textures.set_manifest(_manifest(), session_root=tmp_path)
        _open_texture(page, tmp_path)
        target = tools.target
        tools.set_kept_text("Texture edits are not kept yet: Finish keeps them in the draft.")
        assert _shown(page) == (True, True)
        height = tools.height()
        # The list's own close: the list goes, the Texture Editor stays with its texture
        # and takes the list's room.
        textures.close()
        _settle()
        assert _shown(page) == (False, True) and not panels.wanted
        assert tools.target is target and tools.title_label.text() == "a.dds"
        assert tools.kept_text.startswith("Texture edits are not kept yet")
        assert tools.height() > height
        # The Textures button brings the list back; the texture is still open.
        panels.set_wanted(True)
        _settle()
        assert _shown(page) == (True, True) and tools.target is target
        # And turning it off by the button hides the list only, as its close does.
        panels.set_wanted(False)
        _settle()
        assert _shown(page) == (False, True) and tools.target is target
    finally:
        page.deleteLater()


def test_with_the_list_off_the_texture_editor_still_goes_with_the_mesh(tmp_path: Path) -> None:
    page = _page()
    try:
        panels, textures, tools = page.texture_panels, page.textures_dock, page.texture_tools_dock
        panels.set_wanted(True)
        textures.set_manifest(_manifest(), session_root=tmp_path)
        _open_texture(page, tmp_path)
        panels.set_wanted(False)
        _settle()
        assert _shown(page) == (False, True)
        # The session ends (Close, or the first step of loading another mesh).
        textures.show_session(None)
        _settle()
        assert _shown(page) == (False, False)
        # The next mesh does not bring back the last mesh's texture once it was emptied.
        tools.show_empty()
        textures.set_manifest(_manifest(), session_root=tmp_path / "next")
        _settle()
        assert _shown(page) == (False, False)
    finally:
        page.deleteLater()


def test_the_mesh_editor_has_a_textures_button_and_close_empties_the_texture_editor(tmp_path: Path) -> None:
    from tests.test_mesh_rust_embedding import _tab

    tab = _tab(tmp_path)
    try:
        button = tab.textures_toggle_button
        panels = tab.standalone_workspace.texture_panels
        tools = tab.standalone_workspace.texture_tools_dock
        tools._editor_factory = _FakeEditor
        assert button.text() == "Textures" and button.isCheckable() and button.toolTip()
        # Off by default, and the button says so.
        assert not button.isChecked() and not panels.wanted
        button.click()
        assert panels.wanted and tab.settings.value(SHOWN_KEY) in (True, "true")
        # Closing the panel by its own button unchecks it.
        tab.standalone_workspace.textures_dock.close()
        assert not button.isChecked()
        button.click()
        tools.open_target(LiveTextureTarget(session_id="doc", source_path=str(tmp_path / "a.dds"),
                                            source_sha256="cd" * 32, channel="base_color", display_name="a.dds"))
        assert tools.target is not None and panels.texture_open
        # A mesh is open and both panels show.
        tab.resize(1400, 800)
        tab.show()
        textures = tab.standalone_workspace.textures_dock
        textures.set_manifest(_manifest(), session_root=tmp_path)
        _settle()
        assert textures.isVisible() and tools.isVisible()
        # Close in the Mesh Editor (and every open of another mesh goes through it): both
        # go at once, not when the editor's session has been disposed of in the background.
        tab.close_standalone_session()
        assert tools.target is None and tools.title_label.text() == EMPTY_TEXT and not panels.texture_open
        assert not textures.has_session and not textures.isVisible() and not tools.isVisible()
        assert button.isChecked()  # the choice stands for the next mesh
    finally:
        tab.deleteLater()
        _APP.processEvents()


def test_the_textures_button_hides_the_list_only_and_close_still_hides_both(tmp_path: Path) -> None:
    from tests.test_mesh_rust_embedding import _tab

    tab = _tab(tmp_path)
    try:
        button = tab.textures_toggle_button
        workspace = tab.standalone_workspace
        textures, tools = workspace.textures_dock, workspace.texture_tools_dock
        tools._editor_factory = _FakeEditor
        tab.resize(1400, 800)
        tab.show()
        button.click()
        textures.set_manifest(_manifest(), session_root=tmp_path)
        tools.open_target(LiveTextureTarget(session_id="doc", source_path=str(tmp_path / "a.dds"),
                                            source_sha256="cd" * 32, channel="base_color", display_name="a.dds"))
        _settle()
        assert textures.isVisible() and tools.isVisible()
        # The button off: the list goes, the texture stays open beside the model.
        button.click()
        _settle()
        assert not button.isChecked() and tab.settings.value(SHOWN_KEY) in (False, "false")
        assert not textures.isVisible() and tools.isVisible() and tools.title_label.text() == "a.dds"
        # On again: the list is back and the texture still open.
        button.click()
        _settle()
        assert textures.isVisible() and tools.isVisible() and tools.title_label.text() == "a.dds"
        # Close in the Mesh Editor with the list off: the Texture Editor goes too.
        button.click()
        _settle()
        tab.close_standalone_session()
        assert not textures.isVisible() and not tools.isVisible() and tools.target is None
    finally:
        tab.deleteLater()
        _APP.processEvents()


def test_the_texture_editors_own_close_hides_it_and_keeps_the_edits(tmp_path: Path, monkeypatch) -> None:
    """The Texture Editor panel has its own clear close, apart from the list's and the
    Mesh Editor's Close: it hides the panel, the edits stay, and Close still asks."""

    from types import SimpleNamespace

    from PySide6.QtGui import QColor, QImage
    from PySide6.QtWidgets import QMessageBox

    from tests.test_mesh_rust_embedding import _tab

    tab = _tab(tmp_path)
    try:
        workspace = tab.standalone_workspace
        textures, tools = workspace.textures_dock, workspace.texture_tools_dock
        tools._editor_factory = _FakeEditor
        tab.resize(1400, 800)
        tab.show()
        # With no mesh loaded the tab disables its workspace; a loaded mesh enables it.
        workspace.setEnabled(True)
        tab.textures_toggle_button.click()
        textures.set_manifest(_manifest(), session_root=tmp_path)
        session =tab.live_edit._live_texture_session_id()
        tools.open_target(LiveTextureTarget(session_id=session, source_path=str(tmp_path / "a.dds"),
                                            source_sha256="ab" * 32, channel="base_color", display_name="a.dds"))
        image = QImage(4, 4, QImage.Format.Format_RGBA8888)
        image.fill(QColor("#336699"))
        tab.live_edit._on_texture_window_edit(session, "ab" * 32, image, True)
        keeper = tab.live_edit._live_texture_keeping
        tools.set_kept_text("Texture edits are not kept yet: Finish keeps them in the draft.")
        _settle()
        assert keeper.unkept_count() == 1 and textures.isVisible() and tools.isVisible()
        target = tools.target

        button = tools.close_button
        assert button.text() == "Close Editor" and button.toolTip() and button.isVisibleTo(tools)
        questions: list[str] = []
        monkeypatch.setattr(QMessageBox, "question",
                            staticmethod(lambda _parent, title, *_args: questions.append(title)
                                         or QMessageBox.StandardButton.No))
        button.click()
        _settle()
        # Only the Texture Editor goes, without asking: nothing is lost by hiding it.
        assert not tools.isVisible() and textures.isVisible() and not questions
        assert tools.target is target and tools.kept_text.startswith("Texture edits are not kept yet")
        assert keeper.unkept_count() == 1 and tab.live_edit._live_texture_updates.edited_textures()
        # A double-click (as open_texture_in_window does) opens it again with the texture.
        tools.open_target(target)
        _settle()
        assert tools.isVisible() and tools.target is target
        # Close in the Mesh Editor still asks about the edits that are not kept.
        tab.standalone_controller = SimpleNamespace(active_session_id="session", closing_loses_work=lambda: False)
        monkeypatch.setattr(tab, "show_empty_state", lambda *_args: None)
        tab._close_standalone_session_requested()
        assert questions and "Texture Edits" in questions[0] and keeper.unkept_count() == 1
    finally:
        tab.standalone_controller = None
        tab.deleteLater()
        _APP.processEvents()


def test_hair_tools_hides_unwired_textures_dock_without_losing_user_preference(tmp_path: Path) -> None:
    from types import SimpleNamespace

    from cdmw.ui.mesh_editor.texture_panels import SHOWN_KEY
    from tests.test_mesh_rust_embedding import _tab

    tab = _tab(tmp_path)
    try:
        workspace = tab.standalone_workspace
        textures, tools = workspace.textures_dock, workspace.texture_tools_dock
        panels = workspace.texture_panels
        tools._editor_factory = _FakeEditor
        tab.resize(1400, 800)
        tab.show()
        tab.textures_toggle_button.click()
        textures.set_manifest(_manifest(), session_root=tmp_path)
        tools.open_target(LiveTextureTarget(session_id="doc", source_path=str(tmp_path / "a.dds"),
                                            source_sha256="ab" * 32, channel="base_color", display_name="a.dds"))
        _settle()
        assert textures.isVisible() and tools.isVisible() and tab.textures_toggle_button.isVisible()

        panels.set_suppressed(True)
        _settle()
        assert panels.suppressed and panels.wanted
        assert tab.settings.value(SHOWN_KEY) in (True, "true")
        assert not textures.isVisible() and not tools.isVisible()

        panels.set_suppressed(False)
        _settle()
        assert textures.isVisible() and tools.isVisible()

        # Simulate an active Hair Tools session on the tab.
        tab.standalone_rust_authoring_session = SimpleNamespace(
            closed=False,
            hair_start_mode="existing",
            shadow_session_id="hair-1",
            shadow_service=SimpleNamespace(_session=lambda _sid: SimpleNamespace(hair_state=object())),
        )
        tab._refresh_textures_panel_availability()
        _settle()
        assert panels.suppressed and not tab.textures_toggle_button.isVisible()
        assert not textures.isVisible() and not tools.isVisible()
        assert panels.wanted and tab.settings.value(SHOWN_KEY) in (True, "true")

        # Leaving Hair Tools restores both the toggle button and the user's wanted panel.
        tab.standalone_rust_authoring_session = None
        tab._refresh_textures_panel_availability()
        _settle()
        assert not panels.suppressed and tab.textures_toggle_button.isVisible()
        assert textures.isVisible() and tools.isVisible()
    finally:
        tab.standalone_rust_authoring_session = None
        tab.deleteLater()
        _APP.processEvents()
