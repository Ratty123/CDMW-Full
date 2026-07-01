from __future__ import annotations

import os
import tempfile
import threading
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication

from cdmw.ui.texture_editor_tab import TextureEditorTab


def _wait_for(app: QApplication, predicate, timeout: float = 3.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        app.processEvents()
        if predicate():
            return True
        time.sleep(0.005)
    app.processEvents()
    return bool(predicate())


def _make_texture_editor_tab(root: Path) -> TextureEditorTab:
    settings = QSettings(str(root / "settings.ini"), QSettings.Format.IniFormat)
    return TextureEditorTab(
        settings=settings,
        base_dir=root,
        get_texconv_path=lambda: "",
        get_png_root=lambda: "",
    )


def test_texture_editor_async_task_success_runs_on_gui_thread() -> None:
    app = QApplication.instance() or QApplication([])
    main_thread_id = threading.get_ident()
    with tempfile.TemporaryDirectory() as temp_dir:
        tab = _make_texture_editor_tab(Path(temp_dir))
        callback_threads: list[int] = []
        worker_threads: list[int] = []

        def _task() -> int:
            worker_thread_id = threading.get_ident()
            worker_threads.append(worker_thread_id)
            return worker_thread_id

        def _on_success(worker_thread_id: object) -> None:
            callback_threads.append(threading.get_ident())
            worker_threads.append(int(worker_thread_id))

        try:
            assert tab._run_async_task(label="Thread probe", task=_task, on_success=_on_success)
            assert _wait_for(app, lambda: bool(callback_threads) and not tab._busy())
            assert callback_threads == [main_thread_id]
            assert worker_threads
            assert all(thread_id != main_thread_id for thread_id in worker_threads)
        finally:
            tab.request_shutdown()
            tab.deleteLater()
            app.processEvents()


def test_texture_editor_sidebar_dds_controls_stack_on_compact_widths() -> None:
    app = QApplication.instance() or QApplication([])
    with tempfile.TemporaryDirectory() as temp_dir:
        tab = _make_texture_editor_tab(Path(temp_dir))
        try:
            assert tab.tool_panel.minimumWidth() >= 220
            assert tab.tool_panel.maximumWidth() >= 374
            actions_layout = tab.export_dds_button.parentWidget().layout()
            native_grid = None
            for index in range(actions_layout.count()):
                child_layout = actions_layout.itemAt(index).layout()
                if child_layout is not None and child_layout.indexOf(tab.export_dds_button) >= 0:
                    native_grid = child_layout
                    break
            assert native_grid is not None
            assert native_grid.getItemPosition(native_grid.indexOf(tab.native_dds_format_combo)) == (2, 0, 1, 2)
            assert native_grid.getItemPosition(native_grid.indexOf(tab.native_dds_mip_combo)) == (3, 0, 1, 2)
            assert native_grid.getItemPosition(native_grid.indexOf(tab.export_dds_button)) == (4, 0, 1, 2)
            assert native_grid.getItemPosition(native_grid.indexOf(tab.preview_compressed_button)) == (5, 0, 1, 2)
        finally:
            tab.request_shutdown()
            tab.deleteLater()
            app.processEvents()


def test_texture_editor_splitter_sizes_are_persisted_and_not_reset_on_document_reveal() -> None:
    source = "\n".join(
        (
            Path("cdmw/ui/texture_workflow/editor_ui_shell.py").read_text(encoding="utf-8"),
            Path("cdmw/ui/texture_workflow/editor_settings_persistence.py").read_text(encoding="utf-8"),
        )
    )
    assert 'texture_editor/main_splitter_sizes' in source
    assert "self.main_splitter.splitterMoved.connect(self._handle_main_splitter_moved)" in source
    assert "self._texture_editor_document_splitter_sizes()" in source
    assert "self._apply_responsive_splitter_defaults" not in source[
        source.index("if has_doc and not right_sidebar_was_visible:") :
        source.index("def _handle_main_splitter_moved", source.index("if has_doc and not right_sidebar_was_visible:"))
    ]
