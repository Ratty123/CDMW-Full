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


def _bounds_by_index_arrays(pixels: np.ndarray) -> np.ndarray:
    ys, xs = np.where(pixels[..., 3] > 0)
    if xs.size == 0:
        return pixels
    return pixels[int(ys.min()):int(ys.max()) + 1, int(xs.min()):int(xs.max()) + 1]


def test_the_layer_thumbnail_crop_is_the_painted_area_without_per_pixel_index_arrays() -> None:
    import tracemalloc

    from cdmw.ui.texture_workflow.editor_images import texture_editor_layer_thumbnail_preview_pixels as crop

    rng = np.random.default_rng(7)
    for _ in range(25):
        pixels = np.zeros((int(rng.integers(1, 40)), int(rng.integers(1, 40)), 4), dtype=np.uint8)
        if rng.random() < 0.8:
            y, x = int(rng.integers(0, pixels.shape[0])), int(rng.integers(0, pixels.shape[1]))
            pixels[y:y + int(rng.integers(1, 9)), x:x + int(rng.integers(1, 9)), 3] = int(rng.integers(1, 256))
        assert np.array_equal(crop(pixels), _bounds_by_index_arrays(pixels))
    assert crop(None) is None and crop(np.zeros((0, 0, 4), dtype=np.uint8)) is None

    opaque = np.full((2048, 2048, 4), 255, dtype=np.uint8)
    tracemalloc.start()
    try:
        assert crop(opaque).shape == opaque.shape
        _current, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    # Index arrays of every pixel would take 64 MiB here; the layer itself is 16 MiB.
    assert peak < 8 * 1024 * 1024


def test_opening_a_texture_flattens_it_on_the_worker_and_not_again_on_the_window_thread(tmp_path, monkeypatch) -> None:
    import threading
    import time

    from PIL import Image

    from cdmw.ui.texture_workflow import editor_session, editor_view_state

    source = tmp_path / "opened.png"
    Image.fromarray(np.full((64, 64, 4), 180, dtype=np.uint8), "RGBA").save(source)
    on_window_thread: list[str] = []

    def watched(module, name):
        original = getattr(module, name)

        def run(*args, **kwargs):
            if threading.current_thread() is threading.main_thread():
                on_window_thread.append(f"{module.__name__}.{name}")
            return original(*args, **kwargs)

        monkeypatch.setattr(module, name, run)

    watched(editor_session, "flatten_texture_editor_layers")
    watched(editor_view_state, "flatten_texture_editor_layers")
    editor = _editor(tmp_path)
    try:
        editor.open_source_path(source)
        end = time.perf_counter() + 30
        while time.perf_counter() < end and (editor.document is None or editor._task_thread is not None):
            _app().processEvents()
            time.sleep(0.005)
        assert editor.document is not None and editor.document.width == 64
        assert editor._current_composite_rgba() is not None
        assert on_window_thread == []
    finally:
        _close(editor)
