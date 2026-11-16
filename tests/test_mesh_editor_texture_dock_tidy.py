"""The docked Texture Editor looks like part of the Mesh Editor.

No notice lines above the tools (a status line at the bottom and a warning marker by
the file name carry them), no Undo or Redo buttons of its own (the Mesh Editor's cover
both kinds of edits, and so do its keys pressed in the panel), and the Mesh Editor's
font size throughout.
"""

from __future__ import annotations

import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPoint, QSettings, Qt, Signal
from PySide6.QtGui import QFont
from PySide6.QtTest import QTest
from PySide6.QtWidgets import (
    QAbstractButton,
    QApplication,
    QLabel,
    QListWidget,
    QMainWindow,
    QPushButton,
    QScrollArea,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from cdmw.ui.mesh_editor.live_texture_keeping import KEPT_TEXT, NOT_KEPT_TEXT
from cdmw.ui.mesh_editor.shared_texture_check import CHECKING_TEXT, OTHER_FILES_TEXT
from cdmw.ui.mesh_editor.texture_tools_dock import LiveTextureTarget, MeshEditorTextureTools

_APP = QApplication.instance() or QApplication([])
SHA = "cd" * 32
GAME_PATH = "character/texture/cd_phm_00_belt_0008_02.dds"
USERS = ("CD_PHM_00_Belt_00_0374_01", "CD_PHM_00_Belt_00_0374", "CD_PHM_00_Belt_0008_02")


class _Editor(QWidget):
    resident_texture_patch_ready = Signal(object)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.history_index = 1
        self.undone = []
        self.undo_button = QPushButton("Undo", self)
        self.redo_button = QPushButton("Redo", self)
        self.undo_button.clicked.connect(self.undo)
        self.redo_button.clicked.connect(self.redo)
        self.tool_buttons = {key: QToolButton(self) for key in ("paint", "erase", "fill")}
        for key, button in self.tool_buttons.items():
            button.setText(key)
        self.tool_settings_section = QWidget(self)
        self.layers_section = QWidget(self)
        layout = QVBoxLayout(self.layers_section)
        self.layers_list = QListWidget(self.layers_section)
        self.layers_list.addItem("Background")
        layout.addWidget(self.layers_list)
        self.canvas_scroll = QScrollArea(self)

    def open_source_path(self, path, *, binding=None) -> None:
        pass

    def undo(self) -> None:
        self.undone.append("undo")

    def redo(self) -> None:
        self.undone.append("redo")


def _target(tmp_path: Path, **extra) -> LiveTextureTarget:
    values = dict(session_id="doc", source_path=str(tmp_path / "belt.dds"), source_sha256=SHA,
                  channel="base_color", display_name="cd_phm_00_belt_0008_02.dds", game_path=GAME_PATH)
    values.update(extra)
    return LiveTextureTarget(**values)


def _shown(tools: MeshEditorTextureTools) -> QMainWindow:
    host = QMainWindow()
    host.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, tools)
    host.resize(900, 700)
    host.show()
    host.activateWindow()
    QTest.qWaitForWindowExposed(host)
    for _ in range(10):
        QApplication.processEvents()
    return host


def _settle() -> None:
    for _ in range(10):
        QApplication.processEvents()


def test_no_notice_lines_sit_above_the_tools(tmp_path: Path) -> None:
    tools = MeshEditorTextureTools(editor_factory=_Editor)
    host = _shown(tools)
    try:
        tools.open_target(_target(tmp_path, users=USERS, in_renderer=False))
        tools.set_sharing_text(GAME_PATH, CHECKING_TEXT)
        tools.set_kept_text(KEPT_TEXT)
        _settle()
        body = tools.widget()
        top_of_tools = tools.split.mapTo(body, QPoint(0, 0)).y()
        above = [label for label in body.findChildren(QLabel)
                 if label.isVisible() and label.mapTo(body, QPoint(0, 0)).y() < top_of_tools]
        # Only the file name and its warning marker; every text line is below the tools.
        assert {label.text() for label in above} <= {"cd_phm_00_belt_0008_02.dds", ""}
        for text in (CHECKING_TEXT, KEPT_TEXT):
            (label,) = [each for each in body.findChildren(QLabel) if each.isVisible() and each.text() == text]
            assert label.mapTo(body, QPoint(0, 0)).y() >= top_of_tools + tools.split.height()
    finally:
        host.deleteLater()


def test_the_status_line_and_the_marker_carry_the_texts_with_tooltips(tmp_path: Path) -> None:
    tools = MeshEditorTextureTools(editor_factory=_Editor)
    host = _shown(tools)
    try:
        tools.open_target(_target(tmp_path))
        _settle()
        assert tools.warning_marker.isHidden()  # one user, drawn live: nothing to warn about
        tools.open_target(_target(tmp_path, users=USERS))
        _settle()
        assert tools.warning_marker.isVisible()
        tip = tools.warning_marker.toolTip()
        assert all(user in tip for user in USERS) and "shared" in tip
        assert tools.notice_text and tools.notice_text in tip
        # The sharing check: its progress is a status, what it found is a warning too.
        tools.set_sharing_text(GAME_PATH, CHECKING_TEXT)
        assert tools.sharing_label.text() == CHECKING_TEXT and tools.sharing_label.toolTip() == CHECKING_TEXT
        assert CHECKING_TEXT not in tools.warning_marker.toolTip()
        still = "Checking whether other game files use this texture: none found yet, still searching..."
        tools.set_sharing_text(GAME_PATH, still)
        assert still not in tools.warning_marker.toolTip() and tools.sharing_label.objectName() == "HintLabel"
        found = OTHER_FILES_TEXT.format(files="a.pac, b.pac")
        tools.set_sharing_text(GAME_PATH, found)
        assert found in tools.warning_marker.toolTip() and tools.sharing_text == found
        tools.set_kept_text(KEPT_TEXT)
        _settle()
        assert tools.kept_label.text() == KEPT_TEXT and tools.kept_label.toolTip() == KEPT_TEXT
        # One line: a narrow panel shortens the shown text, the tooltip keeps all of it.
        tools.sharing_label.resize(60, tools.sharing_label.height())
        shown = QLabel.text(tools.sharing_label)
        assert shown != found and shown.endswith("…") and tools.sharing_label.toolTip() == found
        assert not tools.sharing_label.wordWrap() and not tools.kept_label.wordWrap()
    finally:
        host.deleteLater()


def test_edits_not_kept_yet_stand_out(tmp_path: Path) -> None:
    tools = MeshEditorTextureTools(editor_factory=_Editor)
    tools.open_target(_target(tmp_path))
    tools.set_kept_text(NOT_KEPT_TEXT)
    assert tools.kept_label.objectName() == "WarningText" and not tools.kept_label.isHidden()
    tools.set_kept_text(KEPT_TEXT)
    assert tools.kept_label.objectName() == "HintLabel"
    tools.set_kept_text("")
    assert tools.kept_label.isHidden() and tools.kept_text == ""
    tools.deleteLater()


def test_the_panel_has_no_undo_or_redo_buttons(tmp_path: Path) -> None:
    tools = MeshEditorTextureTools(editor_factory=_Editor)
    host = _shown(tools)
    try:
        tools.open_target(_target(tmp_path))
        _settle()
        shown = [button.text() for button in tools.widget().findChildren(QAbstractButton) if button.isVisible()]
        assert "Undo" not in shown and "Redo" not in shown
        assert tools.editor.undo_button.parent() is not tools.widget()
    finally:
        host.deleteLater()


def _press(widget: QWidget, key: Qt.Key, modifiers=Qt.KeyboardModifier.ControlModifier) -> None:
    QTest.keyClick(widget, key, modifiers)
    _settle()


def test_undo_and_redo_keys_in_the_panel_take_the_shared_step(tmp_path: Path) -> None:
    tools = MeshEditorTextureTools(editor_factory=_Editor)
    host = _shown(tools)
    try:
        tools.open_target(_target(tmp_path))
        _settle()
        asked = []
        tools.step_handler = lambda step: asked.append(step) or True
        tool = tools.editor.tool_buttons["paint"]
        tool.setFocus()
        _settle()
        _press(tool, Qt.Key.Key_Z)
        _press(tool, Qt.Key.Key_Y)
        _press(tool, Qt.Key.Key_Z, Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier)
        assert asked == ["undo", "redo", "redo"] and tools.editor.undone == []
        # Not joined to a Mesh Editor: the texture's own undo.
        tools.step_handler = None
        _press(tool, Qt.Key.Key_Z)
        _press(tool, Qt.Key.Key_Y)
        assert tools.editor.undone == ["undo", "redo"]
    finally:
        host.deleteLater()


def test_the_texture_editors_own_undo_key_works_in_the_panel(tmp_path: Path) -> None:
    from cdmw.services.keymap_store import set_override

    settings = QSettings(str(tmp_path / "s.ini"), QSettings.Format.IniFormat)
    set_override(settings, "texture_editor.undo", ["Ctrl+U"])
    tools = MeshEditorTextureTools(settings=settings, editor_factory=_Editor)
    host = _shown(tools)
    try:
        tools.open_target(_target(tmp_path))
        _settle()
        asked = []
        tools.step_handler = lambda step: asked.append(step) or True
        tool = tools.editor.tool_buttons["erase"]
        tool.setFocus()
        _settle()
        _press(tool, Qt.Key.Key_U)
        assert asked == ["undo"]
    finally:
        host.deleteLater()


def _sizes(root: QWidget) -> set[float]:
    return {widget.font().pointSizeF() for widget in (root, *root.findChildren(QWidget))}


def test_the_panel_uses_the_mesh_editors_font_size_and_follows_a_change(tmp_path: Path) -> None:
    from cdmw.ui.mesh_editor.workspace import MeshEditorWorkspace
    from cdmw.ui.shell.theme_controller import (
        _apply_data_fonts_to_widget_tree,
        _apply_ui_fonts_to_widget_tree,
        _install_app_fonts,
        _resolved_app_fonts,
        apply_app_fonts,
    )

    before = QFont(_APP.font())
    settings = QSettings(str(tmp_path / "app.ini"), QSettings.Format.IniFormat)
    page = MeshEditorWorkspace(theme_key="graphite", defer_legacy_panels=True)
    tools = page.texture_tools_dock
    tools._editor_factory = _Editor

    def change_in_settings(ui_points: int, data_points: int) -> None:
        # What Settings > Appearance does: the app's fonts, every widget's, the lists'
        # data font, then the Mesh Editor's (which sends its size to the Rust editor).
        settings.setValue("appearance/ui_font_size", ui_points)
        settings.setValue("appearance/data_font_size", data_points)
        ui_font, data_font = apply_app_fonts(_APP, settings)
        _apply_ui_fonts_to_widget_tree(page, ui_font)
        _apply_data_fonts_to_widget_tree(page, data_font)
        page.sync_ui_font(ui_font, data_font)
        _settle()

    try:
        page.show()
        change_in_settings(11, 8)
        tools.open_target(_target(tmp_path))  # the editor is made after the change
        _settle()
        # The size the Rust editor is sent ("font_point_size") is the app's UI font size.
        rust_points = _resolved_app_fonts(_APP, settings)[0].pointSizeF()
        assert rust_points == 11
        assert tools.editor.layers_list.font().pointSizeF() == rust_points
        assert _sizes(tools) == {rust_points}
        change_in_settings(14, 9)
        assert _sizes(tools) == {14}
    finally:
        page.deleteLater()
        _install_app_fonts(_APP, before, before)
