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
        # Turned off, both go; the open texture is still there when they come back.
        panels.set_wanted(False)
        _settle()
        assert _shown(page) == (False, False)
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
        # Opening a texture while the panels are off (a command, not a click) asks for them.
        page.texture_panels.set_wanted(False)
        _open_texture(page, tmp_path)
        assert page.texture_panels.wanted and _shown(page) == (True, True)
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
        # Close in the Mesh Editor (and every open of another mesh goes through it).
        tab.close_standalone_session()
        assert tools.target is None and tools.title_label.text() == EMPTY_TEXT and not panels.texture_open
    finally:
        tab.deleteLater()
        _APP.processEvents()
