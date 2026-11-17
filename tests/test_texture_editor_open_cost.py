"""Opening a texture in the Textures workspace: the window-thread work it costs.

The review measured 477 ms on the window thread opening one 4096 x 4096 texture
(``_create_session``): the document was loaded twice, the layer thumbnail found the
painted area through index arrays of every pixel, and the composite was flattened
again although the session had just flattened it.
"""

from __future__ import annotations

import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np  # noqa: E402

from cdmw.models import TextureEditorDocument, TextureEditorLayer  # noqa: E402


def _app():
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


def _editor(tmp_path: Path):
    from cdmw.services.settings_service import create_settings
    from cdmw.ui.texture_editor_tab import TextureEditorTab

    _app()
    return TextureEditorTab(settings=create_settings(settings_file_path=tmp_path / "settings.cfg"),
                            base_dir=tmp_path, get_png_root=lambda: str(tmp_path))


def _close(editor) -> None:
    from PySide6.QtCore import QEvent

    editor.request_shutdown()
    editor.deleteLater()
    _app().sendPostedEvents(None, QEvent.Type.DeferredDelete)


def _document(size: int = 32, title: str = "Opened") -> tuple[TextureEditorDocument, dict[str, np.ndarray]]:
    document = TextureEditorDocument(title, size, size, active_layer_id="base",
                                     layers=(TextureEditorLayer("base", "Base", "base.png"),))
    return document, {"base": np.full((size, size, 4), 200, dtype=np.uint8)}


def test_the_first_document_opened_is_loaded_once(tmp_path) -> None:
    editor = _editor(tmp_path)
    loads: list[int] = []
    load = editor._load_session_index

    def counted(index: int) -> None:
        loads.append(index)
        load(index)

    editor._load_session_index = counted
    try:
        document, pixels = _document()
        editor._create_session(document, pixels, label="Opened")
        assert loads == [0]
        assert editor.document.title == "Opened" and editor.document_tab_bar.currentIndex() == 0
        second, second_pixels = _document(title="Second")
        editor._create_session(second, second_pixels, label="Second")
        assert loads == [0, 1] and editor.document_tab_bar.currentIndex() == 1
        # Switching tabs by hand still loads the chosen document.
        editor.document_tab_bar.setCurrentIndex(0)
        assert loads == [0, 1, 0] and editor.document.title == "Opened"
    finally:
        _close(editor)
