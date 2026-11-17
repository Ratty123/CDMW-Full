"""The Mesh Editor's texture tools, docked beside the model (step 8)."""

from __future__ import annotations

import os
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
from PySide6.QtCore import Signal
from PySide6.QtWidgets import QApplication, QDockWidget, QPushButton, QScrollArea, QToolButton, QWidget

from cdmw.ui.mesh_editor.texture_tools_dock import (
    EMPTY_TEXT,
    LiveTextureTarget,
    MeshEditorTextureTools,
    rgba_array_image,
    shared_texture_notice,
    unseen_texture_notice,
)

SHA = "cd" * 32


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


class _FakeEditor(QWidget):
    resident_texture_patch_ready = Signal(object)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.opened: list[tuple[Path, object]] = []
        self.history_index = 1
        self.undo_button = QPushButton("Undo", self)
        self.redo_button = QPushButton("Redo", self)
        self.tool_buttons = {key: QToolButton(self) for key in ("paint", "erase", "fill")}
        self.tool_settings_section = QWidget(self)
        self.layers_section = QWidget(self)
        self.canvas_scroll = QScrollArea(self)

    def open_source_path(self, path, *, binding=None) -> None:
        self.opened.append((Path(path), binding))


def _target(tmp_path: Path, name: str = "a.dds", **extra) -> LiveTextureTarget:
    values = dict(session_id="doc-1", source_path=str(tmp_path / name), source_sha256=SHA,
                  channel="normal", display_name=name)
    values.update(extra)
    return LiveTextureTarget(**values)


def _tools() -> MeshEditorTextureTools:
    _app()
    return MeshEditorTextureTools(editor_factory=_FakeEditor)


def test_the_tools_are_a_dock_that_waits_for_a_texture_and_closing_it_only_hides_it() -> None:
    tools = _tools()
    assert isinstance(tools, QDockWidget)
    assert tools.features() & QDockWidget.DockWidgetFeature.DockWidgetFloatable
    assert tools.features() & QDockWidget.DockWidgetFeature.DockWidgetClosable
    asked: list[bool] = []
    tools.close_requested.connect(lambda: asked.append(True))
    tools.show()
    tools.close()  # the host hides it; nothing is closed or lost here
    assert asked == [True] and tools.isVisible()
    assert tools.editor is None and tools.title_label.text() == EMPTY_TEXT
    tools.deleteLater()


def test_opening_lays_out_only_the_editing_parts_beside_the_canvas(tmp_path: Path) -> None:
    tools = _tools()
    tools.open_target(_target(tmp_path, "a.dds"))
    editor = tools.editor
    assert editor.isHidden()  # the full editor never shows; its editing parts do
    body = tools.widget()
    # No Undo or Redo of its own: the Mesh Editor's cover texture edits (they stay hidden).
    assert editor.undo_button.parent() is editor and editor.redo_button.parent() is editor
    rail = tools.split.widget(0).widget()
    assert all(button.parent() is rail for button in editor.tool_buttons.values())
    assert editor.tool_settings_section.parent() is rail and editor.layers_section.parent() is rail
    assert tools.split.widget(1) is editor.canvas_scroll
    tools.open_target(_target(tmp_path, "b.dds", source_sha256="ef" * 32))
    assert tools.editor is editor and tools.title_label.text() == "b.dds"
    assert [path.name for path, _ in editor.opened] == ["a.dds", "b.dds"]
    binding = editor.opened[0][1]
    assert (binding.launch_origin, binding.mesh_session_id, binding.mesh_resource_id, binding.mesh_commit_mode) == (
        "mesh_editor", "doc-1", SHA, "live")
    tools.deleteLater()


def test_a_committed_edit_reaches_the_document(tmp_path: Path) -> None:
    tools = _tools()
    tools.open_target(_target(tmp_path))
    edits: list[tuple[str, str, int, int, bool]] = []
    tools.texture_edited.connect(lambda s, h, image, changed: edits.append((s, h, image.width(), image.height(), changed)))
    binding = tools.editor.opened[0][1]
    rgba = np.zeros((2, 3, 4), dtype=np.uint8)
    tools.editor.resident_texture_patch_ready.emit(SimpleNamespace(binding=binding, current_rgba=rgba))
    tools.editor.history_index = 0  # undone back to the texture as opened
    tools.editor.resident_texture_patch_ready.emit(SimpleNamespace(binding=binding, current_rgba=rgba))
    assert edits == [("doc-1", SHA, 3, 2, True), ("doc-1", SHA, 3, 2, False)]
    tools.forget_session("doc-1")
    tools.editor.resident_texture_patch_ready.emit(SimpleNamespace(binding=binding, current_rgba=rgba))
    assert len(edits) == 2
    tools.deleteLater()


def test_shared_and_shader_layer_textures_say_so(tmp_path: Path) -> None:
    tools = _tools()
    tools.open_target(_target(tmp_path, users=("Upper body", "Belt"), in_renderer=False))
    text = tools.notice_text
    assert "Upper body" in text and "Belt" in text and "not shown" in text
    tip = tools.warning_marker.toolTip()  # one line each: shared, then not drawn live
    assert tip.splitlines() == [shared_texture_notice(tools.target), unseen_texture_notice(tools.target)]
    assert not tools.warning_marker.isHidden()
    assert shared_texture_notice(_target(tmp_path, users=("Upper body",))) == ""
    assert unseen_texture_notice(_target(tmp_path)) == ""
    tools.deleteLater()


def test_the_mesh_editor_docks_the_tools_under_the_textures_panel() -> None:
    from PySide6.QtCore import Qt

    from cdmw.ui.mesh_editor.workspace import MeshEditorWorkspace

    _app()
    page = MeshEditorWorkspace(theme_key="graphite", defer_legacy_panels=True)
    host = page.dock_host
    assert host.dockWidgetArea(page.texture_tools_dock) == Qt.DockWidgetArea.RightDockWidgetArea
    assert host.dockWidgetArea(page.textures_dock) == Qt.DockWidgetArea.RightDockWidgetArea
    page.deleteLater()


def test_the_real_texture_editor_fits_in_the_dock(tmp_path: Path) -> None:
    from PySide6.QtCore import QSettings

    _app()
    tools = MeshEditorTextureTools(settings=QSettings(str(tmp_path / "s.ini"), QSettings.Format.IniFormat),
                                   base_dir=tmp_path)
    editor = tools._ensure_editor()
    assert editor.isHidden() and tools.split.count() == 2
    assert tools.split.widget(1) is editor.canvas_scroll
    # Nothing in the rail is cut off on the right: it is never narrower than its rows.
    rail_scroll = tools.split.widget(0)
    tools.show()
    for _ in range(5):
        QApplication.processEvents()
    assert rail_scroll.minimumWidth() >= rail_scroll.widget().minimumSizeHint().width()
    editor.layers_section.toggle_button.click()  # a section opening re-fits the rail
    for _ in range(5):
        QApplication.processEvents()
    assert rail_scroll.minimumWidth() >= rail_scroll.widget().minimumSizeHint().width()
    tools.deleteLater()


def test_rgba_arrays_become_detached_images() -> None:
    _app()
    rgba = np.zeros((2, 2, 4), dtype=np.uint8)
    rgba[0, 1] = (10, 20, 30, 255)
    image = rgba_array_image(rgba)
    rgba[0, 1] = 0
    colour = image.pixelColor(1, 0)
    assert (colour.red(), colour.green(), colour.blue(), colour.alpha()) == (10, 20, 30, 255)
