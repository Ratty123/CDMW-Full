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

from cdmw.ui.layout_utils import scaled_px
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
    from cdmw.ui.mesh_editor.textures_panel import COLUMN_FILE, COLUMN_ROLE, COLUMN_STATE

    for width, height in ((1600, 900), (1920, 1080), (1280, 720)):
        page = _page(width, height)
        try:
            _show_list(page, tmp_path)
            dock, host = page.textures_dock, page.dock_host
            least = dock.widget().minimumSize()
            # Compact default width (~380-440px, clamped proportionally on smaller screens):
            # never ~45% of the window, while keeping every part name and Game file readable.
            assert dock.width() >= max(least.width(), scaled_px(420, dock))
            assert dock.width() <= max(least.width(), scaled_px(500, dock))
            assert dock.width() <= host.width() * 0.36
            names = max(dock.tree.fontMetrics().horizontalAdvance(f"CD_PHM_00_UB_00_0440_{i:02d}") for i in range(12))
            assert dock.tree.viewport().width() >= names + dock.tree.indentation()
            assert _rows_in_view(dock) >= 12  # the whole height of the editor is the list's
            assert page.native_host_frame.width() >= host.width() * 0.6
            # Collapsed and expanded: Texture and State stay tight while Game file takes remaining width.
            base_role_w = dock.tree.fontMetrics().horizontalAdvance("Base colour")
            state_hdr_w = dock.tree.header().fontMetrics().horizontalAdvance("State")
            icon_side = dock.tree.iconSize().width()
            for expanded in (False, True, False):
                dock.part_item(0).setExpanded(expanded)
                _settle(3)
                role_w = dock.tree.columnWidth(COLUMN_ROLE)
                file_w = dock.tree.columnWidth(COLUMN_FILE)
                state_w = dock.tree.columnWidth(COLUMN_STATE)
                assert role_w <= base_role_w + icon_side + dock.tree.indentation() * 3 + 48
                assert state_w <= max(68, state_hdr_w + 32)
                assert file_w >= scaled_px(110, dock.tree)
        finally:
            page.deleteLater()


def test_closing_texture_editor_returns_the_list_to_its_compact_width(tmp_path: Path) -> None:
    page = _page(1600, 900)
    try:
        _show_list(page, tmp_path)
        compact = page.textures_dock.width()
        least = page.textures_dock.widget().minimumSize().width()
        assert compact <= max(least, scaled_px(500, page.textures_dock))
        _open_texture(page, tmp_path)
        assert page.texture_tools_dock.width() >= int(page.dock_host.width() * 0.44)
        page.texture_tools_dock.close()
        _settle()
        assert page.textures_dock.isVisible() and page.texture_tools_dock.isHidden()
        assert abs(page.textures_dock.width() - compact) <= 4
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
            # The list's height is the Texture Editor's now, and the side is wider: about
            # half the window, with the 3D view still usable.
            assert tools.height() >= split[0] + split[1], (width, height)
            assert tools.height() >= host.height() - tools.fontMetrics().height() * 3, (width, height)
            assert tools.width() >= int(host.width() * 0.49) > split[2], (width, height)
            assert page.native_host_frame.width() >= scaled_px(480, host), (width, height)
            # Shown again, the list has the width and split it had.
            page.texture_panels.set_wanted(True)
            _settle()
            assert abs(textures.height() - split[0]) <= 2 and abs(tools.height() - split[1]) <= 2, (width, height)
            assert abs(tools.width() - split[2]) <= 2, (width, height)
            assert _rows_in_view(textures) >= 5, (width, height)
        finally:
            page.deleteLater()


def _real_page(width: int, height: int, tmp_path: Path, settings: QSettings | None = None) -> MeshEditorWorkspace:
    """A page whose Texture Editor is the real one, so the canvas is fitted as in the app."""

    page = MeshEditorWorkspace(theme_key="graphite", defer_legacy_panels=True)
    page.texture_tools_dock.settings = settings or QSettings(str(tmp_path / "tools.ini"), QSettings.Format.IniFormat)
    page.texture_tools_dock.base_dir = tmp_path
    page.resize(width, height)
    page.show()
    if settings is not None:
        page.texture_panels.use_settings(settings)
    _settle()
    return page


def _open_real_texture(page: MeshEditorWorkspace, tmp_path: Path, side: int = 2048) -> None:
    source = tmp_path / f"texture-{side}.png"
    if not source.exists():
        image = QImage(side, side, QImage.Format.Format_RGBA8888)
        image.fill(QColor("#406080"))
        assert image.save(str(source))
    tools = page.texture_tools_dock
    tools.open_target(LiveTextureTarget(session_id="doc", source_path=str(source), source_sha256="ef" * 32,
                                        channel="base_color", display_name=source.name))
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline and not (
            getattr(tools.editor.document, "width", 0) == side and not tools.editor._busy()):
        _settle(2)
    _settle()


def _drawn(page: MeshEditorWorkspace) -> tuple[int, int]:
    canvas = page.texture_tools_dock.editor.canvas
    assert canvas.is_fit_to_view()
    return canvas.width(), canvas.height()


def test_hiding_the_list_draws_the_open_texture_larger(tmp_path: Path) -> None:
    """Fredric wants "a bigger workspace": the texture itself, not only the panel, grows."""

    for width, height in ((1600, 900), (1280, 720)):
        page = _real_page(width, height, tmp_path)
        try:
            _show_list(page, tmp_path)
            _open_real_texture(page, tmp_path)
            tools = page.texture_tools_dock
            before, side = _drawn(page), tools.width()
            page.texture_panels.set_wanted(False)
            _settle()
            after = _drawn(page)
            assert after[0] > before[0] * 1.1 and after[1] > before[1] * 1.1, (width, height, before, after)
            assert page.native_host_frame.width() >= scaled_px(480, page.dock_host), (width, height)
            # The list back: the texture as it was drawn beside it.
            page.texture_panels.set_wanted(True)
            _settle()
            assert abs(tools.width() - side) <= 2 and abs(_drawn(page)[0] - before[0]) <= 2, (width, height)
        finally:
            page.textures_dock.shutdown()
            page.deleteLater()
            _settle(2)


def test_a_width_the_user_drags_to_with_the_list_hidden_is_kept(tmp_path: Path) -> None:
    settings = QSettings(str(tmp_path / "s.ini"), QSettings.Format.IniFormat)
    page = _page(1600, 900, settings)
    try:
        _show_list(page, tmp_path)
        _open_texture(page, tmp_path)
        panels, tools, host = page.texture_panels, page.texture_tools_dock, page.dock_host
        narrow = tools.width()
        panels.set_wanted(False)
        _settle()
        assert tools.width() >= 790
        # The user drags the side narrower than CDMW made it, then shows the list again.
        host.resizeDocks([tools], [740], Qt.Orientation.Horizontal)
        _settle()
        chosen = tools.width()
        panels.set_wanted(True)
        _settle()
        assert abs(tools.width() - narrow) <= 2
        # Hidden again, the side goes back to the user's width, not CDMW's.
        panels.set_wanted(False)
        _settle()
        assert abs(tools.width() - chosen) <= 2
    finally:
        page.deleteLater()

    # And after a restart.
    again = _page(1600, 900, QSettings(str(tmp_path / "s.ini"), QSettings.Format.IniFormat))
    try:
        _show_list(again, tmp_path)
        _open_texture(again, tmp_path)
        again.texture_panels.set_wanted(False)
        _settle()
        assert abs(again.texture_tools_dock.width() - chosen) <= 4
    finally:
        again.deleteLater()


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
            # A framed preview thumbnail stays recognizable (~2x line height) and scales with font.
            line = panel.tree.fontMetrics().height()
            assert line * 1.5 <= panel.tree.iconSize().height() <= line * 3.0
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
            part = panel.part_item(0)
            part.setExpanded(True)
            item = part.child(0)
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
