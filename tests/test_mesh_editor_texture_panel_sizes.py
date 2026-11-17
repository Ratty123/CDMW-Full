"""The Mesh Editor's texture panels open at a usable size, at any scale (2026-11-17).

Fredric: "Textures window is mashed and not properly showing", and the panels need "to be
aware of monitor resolution/dpi". Sizes here are logical pixels: Qt multiplies them by the
screen's scale, so what holds at 100 % holds at 150 %.
"""

from __future__ import annotations

import os
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QSettings, QThreadPool, Qt, Signal
from PySide6.QtGui import QColor, QFont, QImage
from PySide6.QtWidgets import QApplication, QPushButton, QScrollArea, QToolButton, QWidget

from cdmw.ui.mesh_editor.texture_panels import SIZES_KEY, SIZES_VERSION
from cdmw.ui.mesh_editor.texture_tools_dock import LiveTextureTarget
from cdmw.ui.mesh_editor.textures_panel import (
    COLUMN_THUMBNAIL,
    DOCK_LAYOUT_KEY,
    MeshEditorTexturesPanel,
    TextureThumbnailLoader,
    remember_dock_layout,
)
from cdmw.ui.mesh_editor.workspace import MeshEditorWorkspace

_APP = QApplication.instance() or QApplication([])


class _FakeEditor(QWidget):
    resident_texture_patch_ready = Signal(object)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.history_index = 1
        self.undo_button = QPushButton("Undo", self)
        self.redo_button = QPushButton("Redo", self)
        self.tool_buttons = {key: QToolButton(self) for key in ("paint", "erase")}
        self.tool_settings_section = QWidget(self)
        self.layers_section = QWidget(self)
        self.canvas_scroll = QScrollArea(self)

    def open_source_path(self, path, *, binding=None) -> None:
        pass


def _manifest(parts: int = 12) -> dict[str, object]:
    return {
        "textures": [{"label": f"cd_phm_00_ub_00_0440_{index:02d}_n.dds", "role": "normal",
                      "file": {"path": f"texture-{index:04d}.dds", "sha256": f"{index:064x}"},
                      "material_indices_by_lod": [[index]]} for index in range(parts)],
        "state": {"skeleton": {"parts": [{"index": index, "name": f"CD_PHM_00_UB_00_0440_{index:02d}"}
                                         for index in range(parts)]}},
    }


def _settle(turns: int = 8) -> None:
    for _ in range(turns):
        _APP.processEvents()
        time.sleep(0.005)


def _page(width: int, height: int, settings: QSettings | None = None) -> MeshEditorWorkspace:
    page = MeshEditorWorkspace(theme_key="graphite", defer_legacy_panels=True)
    page.texture_tools_dock._editor_factory = _FakeEditor
    page.resize(width, height)
    page.show()
    if settings is not None:
        remember_dock_layout(page.dock_host, (page.textures_dock, page.texture_tools_dock), settings)
        page.texture_panels.use_settings(settings)
    _settle()
    return page


def _show_list(page: MeshEditorWorkspace, tmp_path: Path) -> None:
    page.texture_panels.set_wanted(True)
    page.textures_dock.set_manifest(_manifest(), session_root=tmp_path)
    _settle()


def _open_texture(page: MeshEditorWorkspace, tmp_path: Path) -> None:
    page.texture_tools_dock.open_target(LiveTextureTarget(
        session_id="doc", source_path=str(tmp_path / "a.dds"), source_sha256="cd" * 32,
        channel="normal", display_name="a.dds"))
    _settle()


def _rows_in_view(panel: MeshEditorTexturesPanel) -> int:
    tree = panel.tree
    row = tree.visualItemRect(tree.topLevelItem(0)).height()
    return tree.viewport().height() // max(1, row)


def test_the_list_opens_at_a_usable_size_and_the_3d_view_keeps_its_room(tmp_path: Path) -> None:
    page = _page(1600, 900)
    try:
        _show_list(page, tmp_path)
        dock, host = page.textures_dock, page.dock_host
        least = dock.widget().minimumSize()
        # Not a strip: about a quarter of the editor, and every part's whole name in view.
        assert dock.width() >= max(least.width(), int(host.width() * 0.22))
        assert dock.width() <= host.width() * 0.4
        names = max(dock.tree.fontMetrics().horizontalAdvance(f"CD_PHM_00_UB_00_0440_{i:02d}") for i in range(12))
        assert dock.tree.viewport().width() >= names + dock.tree.indentation()
        assert _rows_in_view(dock) >= 12  # the whole height of the editor is the list's
        assert page.native_host_frame.width() >= host.width() * 0.55
    finally:
        page.deleteLater()


def test_with_a_texture_open_both_panels_are_usable_and_the_model_stays_in_view(tmp_path: Path) -> None:
    for width, height in ((1600, 900), (1280, 720)):
        page = _page(width, height)
        try:
            _show_list(page, tmp_path)
            _open_texture(page, tmp_path)
            textures, tools, host = page.textures_dock, page.texture_tools_dock, page.dock_host
            # The list keeps the header and at least five rows above the Texture Editor.
            assert textures.height() >= textures.widget().minimumSize().height(), (width, height)
            assert _rows_in_view(textures) >= 5, (width, height)
            # The Texture Editor gets the larger share, wide enough for tools and canvas.
            assert tools.height() > textures.height(), (width, height)
            assert tools.width() >= int(host.width() * 0.44), (width, height)
            assert tools.widget().minimumHeight() > 0 and tools.height() >= tools.widget().minimumHeight()
            # The 3D view is never squeezed out by them.
            assert page.native_host_frame.width() >= 320, (width, height)
            assert page.native_host_frame.width() >= host.width() * 0.4, (width, height)
        finally:
            page.deleteLater()


def test_with_the_list_hidden_the_texture_editor_has_the_whole_side(tmp_path: Path) -> None:
    """Fredric: close only the list "so you get a bigger workspace"."""

    for width, height in ((1600, 900), (1280, 720)):
        page = _page(width, height)
        try:
            _show_list(page, tmp_path)
            _open_texture(page, tmp_path)
            textures, tools, host = page.textures_dock, page.texture_tools_dock, page.dock_host
            split = (textures.height(), tools.height(), tools.width())
            page.texture_panels.set_wanted(False)
            _settle()
            assert textures.isHidden() and tools.isVisible(), (width, height)
            # The list's height is the Texture Editor's now; its width is as it was.
            assert tools.height() >= split[0] + split[1], (width, height)
            assert tools.height() >= host.height() - tools.fontMetrics().height() * 3, (width, height)
            assert tools.width() == split[2], (width, height)
            # Shown again, the list has today's split back.
            page.texture_panels.set_wanted(True)
            _settle()
            assert abs(textures.height() - split[0]) <= 2 and abs(tools.height() - split[1]) <= 2, (width, height)
            assert _rows_in_view(textures) >= 5, (width, height)
        finally:
            page.deleteLater()


def test_a_texture_opened_with_the_list_hidden_still_gets_the_split_when_the_list_shows(tmp_path: Path) -> None:
    page = _page(1600, 900)
    try:
        page.textures_dock.set_manifest(_manifest(), session_root=tmp_path)
        _settle()
        _open_texture(page, tmp_path)
        textures, tools, host = page.textures_dock, page.texture_tools_dock, page.dock_host
        assert textures.isHidden() and tools.isVisible() and not page.texture_panels.wanted
        assert tools.width() >= int(host.width() * 0.44)
        page.texture_panels.set_wanted(True)
        _settle()
        assert textures.height() >= textures.widget().minimumSize().height()
        assert _rows_in_view(textures) >= 5
        assert tools.height() > textures.height()
    finally:
        page.deleteLater()


def test_a_crushed_saved_layout_is_sized_again_once_and_the_users_size_stands_after(tmp_path: Path) -> None:
    """Fredric's saved layout holds the strip of the build before; it must not come back."""

    settings = QSettings(str(tmp_path / "s.ini"), QSettings.Format.IniFormat)
    old = _page(1600, 900)
    try:
        # As the build before left it: no minimum size, the panel dragged or defaulted
        # to a strip, and that layout saved.
        old.textures_dock.show()
        old.textures_dock.widget().setMinimumSize(0, 0)
        old.dock_host.resizeDocks([old.textures_dock], [70], Qt.Orientation.Horizontal)
        _settle()
        assert old.textures_dock.width() < 120
        settings.setValue(DOCK_LAYOUT_KEY, old.dock_host.saveState())
    finally:
        old.deleteLater()

    page = _page(1600, 900, settings)
    try:
        _show_list(page, tmp_path)
        dock, host = page.textures_dock, page.dock_host
        assert dock.width() >= max(dock.widget().minimumSize().width(), int(host.width() * 0.22))
        assert int(settings.value(SIZES_KEY)) == SIZES_VERSION
        # The user then makes it wider; that is theirs from now on.
        host.resizeDocks([dock], [640], Qt.Orientation.Horizontal)
        _settle()
        chosen = dock.width()
        assert chosen > int(host.width() * 0.3)
        page.texture_panels.set_wanted(False)
        page.texture_panels.set_wanted(True)
        _settle()
        assert dock.width() == chosen
        # It can be dragged narrow, but never to a strip.
        host.resizeDocks([dock], [10], Qt.Orientation.Horizontal)
        _settle()
        assert dock.width() >= dock.widget().minimumSize().width() >= 200
    finally:
        page.deleteLater()


def test_sizes_follow_the_font(tmp_path: Path) -> None:
    panel = MeshEditorTexturesPanel(thumbnail_loader=TextureThumbnailLoader(decoder=lambda *_args: None))
    try:
        panel.set_manifest(_manifest(2), session_root=tmp_path)
        sizes = {}
        for points in (9, 15):
            panel.sync_ui_font(QFont(_APP.font().family(), points))
            _settle()
            assert panel.tree.font().pointSizeF() == points and panel.tree.header().font().pointSizeF() == points
            assert panel.font().pointSizeF() == points  # the dock's title
            sizes[points] = (panel.tree.iconSize().height(), panel.widget().minimumSize().width(),
                             panel.widget().minimumSize().height())
            # A thumbnail stays about a line of text, at any size.
            line = panel.tree.fontMetrics().height()
            assert line * 0.8 <= panel.tree.iconSize().height() <= line * 2
        assert all(large > small for small, large in zip(sizes[9], sizes[15]))
    finally:
        panel.shutdown()
        panel.deleteLater()
    # The Mesh Editor hands its font to the list as it does to the Texture Editor panel.
    page = MeshEditorWorkspace(theme_key="graphite", defer_legacy_panels=True)
    try:
        font = QFont(_APP.font().family(), 13)
        page.sync_ui_font(font, font)
        assert page.textures_dock.tree.font().pointSizeF() == 13
    finally:
        page.deleteLater()


def test_thumbnails_are_decoded_for_the_screens_scale(tmp_path: Path, monkeypatch) -> None:
    """At 150 % a thumbnail has one and a half times the pixels in the same logical size."""

    image = QImage(64, 64, QImage.Format.Format_RGBA8888)
    image.fill(QColor(200, 40, 40))
    asked: list[int] = []

    def decoder(_path: Path, size: int, _role: str) -> QImage:
        asked.append(size)
        return image.scaled(size, size)

    (tmp_path / "texture-0000.dds").write_bytes(b"stand-in")
    pool = QThreadPool()
    for scale in (1.0, 1.5):
        asked.clear()
        loader = TextureThumbnailLoader(pool=pool, decoder=decoder)
        panel = MeshEditorTexturesPanel(thumbnail_loader=loader)
        monkeypatch.setattr(panel, "_device_pixel_ratio", lambda scale=scale: scale)
        try:
            panel.set_manifest(_manifest(1), session_root=tmp_path)
            item = panel.part_item(0).child(0)
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline and item.icon(COLUMN_THUMBNAIL).isNull():
                _settle(2)
            side = panel.thumbnail_side()
            assert asked == [round(side * scale)]
            sizes = item.icon(COLUMN_THUMBNAIL).availableSizes()
            # The same logical size on both screens.
            assert sizes and sizes[0].width() == round(side * scale)
            assert panel.tree.iconSize().width() == side
        finally:
            panel.shutdown()
            pool.waitForDone(5000)
            panel.deleteLater()
            loader.deleteLater()
            _settle(2)
