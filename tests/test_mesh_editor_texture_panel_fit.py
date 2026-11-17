"""A texture opened from the Mesh Editor's Textures panel fits its canvas (2026-11-17)."""

from __future__ import annotations

import os
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QSettings
from PySide6.QtGui import QColor, QImage
from PySide6.QtWidgets import QApplication

from cdmw.ui.mesh_editor.texture_tools_dock import LiveTextureTarget, MeshEditorTextureTools


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


def _wait_for(app: QApplication, done, timeout: float = 30.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        app.processEvents()
        if done():
            return True
        time.sleep(0.01)
    return bool(done())


def _texture(path: Path, side: int, colour: str) -> Path:
    image = QImage(side, side, QImage.Format.Format_RGBA8888)
    image.fill(QColor(colour))
    assert image.save(str(path))
    return path


def test_every_texture_opens_fitted_to_the_canvas_and_stays_fitted(tmp_path: Path) -> None:
    app = _app()
    tools = MeshEditorTextureTools(settings=QSettings(str(tmp_path / "s.ini"), QSettings.Format.IniFormat),
                                   base_dir=tmp_path)
    tools.resize(900, 520)
    tools.show()
    try:
        for index, (name, side) in enumerate((("first.png", 2048), ("second.png", 1024))):
            source = _texture(tmp_path / name, side, "#406080")
            tools.open_target(LiveTextureTarget(
                session_id="doc-1", source_path=str(source), source_sha256=f"{index:02x}" * 32,
                channel="base_color", display_name=name))
            editor = tools.editor
            assert _wait_for(app, lambda: getattr(editor.document, "width", 0) == side and not editor._busy())
            for _ in range(5):
                app.processEvents()
            canvas, viewport = editor.canvas, editor.canvas_scroll.viewport()
            # Far larger than the canvas area, it is shown whole: no scroll bars to find it.
            assert canvas.is_fit_to_view(), name
            assert canvas.current_display_scale() < 1.0
            assert canvas.width() <= viewport.width() and canvas.height() <= viewport.height()
        # A smaller panel still shows it whole.
        tools.resize(620, 380)
        for _ in range(5):
            app.processEvents()
        assert canvas.width() <= viewport.width() and canvas.height() <= viewport.height()
    finally:
        tools.close()
        tools.deleteLater()
