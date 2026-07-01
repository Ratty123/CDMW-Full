from __future__ import annotations

import os
import tempfile
import threading
import time
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QPlainTextEdit, QScrollArea, QSizePolicy

from cdmw.services.settings_service import create_settings
from cdmw.ui.model_library import ModelLibraryTab
from tests.test_model_library_preview import _write_triangle_gltf


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


class _QtPreviewModelLibraryTab(ModelLibraryTab):
    def _inline_preview_renderer_backend(self) -> str:
        return "qt"


class ModelLibraryInlinePreviewUiTests(unittest.TestCase):
    def test_controls_panel_uses_width_and_bottom_space(self) -> None:
        app = _app()
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            settings = create_settings(settings_file_path=root / "settings.ini")
            tab = _QtPreviewModelLibraryTab(settings=settings, base_dir=root)
            try:
                tab.resize(1200, 760)
                tab.show()
                app.processEvents()

                controls_scroll = tab.findChild(QScrollArea, "ModelLibraryControlsScroll")
                self.assertIsNotNone(controls_scroll)
                assert controls_scroll is not None
                self.assertGreaterEqual(controls_scroll.minimumWidth(), 430)
                self.assertEqual(
                    controls_scroll.horizontalScrollBarPolicy(),
                    Qt.ScrollBarPolicy.ScrollBarAsNeeded,
                )
                self.assertIsInstance(tab.details_text, QPlainTextEdit)
                self.assertEqual(tab.details_text.lineWrapMode(), QPlainTextEdit.LineWrapMode.WidgetWidth)
                self.assertGreaterEqual(tab.details_text.minimumHeight(), 180)
                self.assertEqual(tab.details_text.sizePolicy().verticalPolicy(), QSizePolicy.Policy.Expanding)
                tab._show_details(None)
                self.assertIn("Select a local file", tab.details_text.toPlainText())
            finally:
                tab.close()
                tab.deleteLater()
                app.processEvents()

    def test_task_completion_handler_runs_on_ui_thread(self) -> None:
        app = _app()
        main_thread_id = threading.get_ident()
        completed: dict[str, object] = {}
        worker_thread_ids: list[int] = []
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            settings = create_settings(settings_file_path=root / "settings.ini")
            tab = _QtPreviewModelLibraryTab(settings=settings, base_dir=root)
            try:
                def task(_progress: object) -> object:
                    worker_thread_ids.append(threading.get_ident())
                    return {"ok": True}

                def complete(result: object) -> None:
                    completed["thread_id"] = threading.get_ident()
                    completed["result"] = result

                tab._run_task("Testing task bridge...", task, complete)
                deadline = time.perf_counter() + 5.0
                while "thread_id" not in completed and time.perf_counter() < deadline:
                    app.processEvents()
                    time.sleep(0.01)

                self.assertEqual({"ok": True}, completed.get("result"))
                self.assertEqual(main_thread_id, completed.get("thread_id"))
                self.assertTrue(worker_thread_ids)
                self.assertNotEqual(main_thread_id, worker_thread_ids[0])
                deadline = time.perf_counter() + 5.0
                while tab._task_thread is not None and time.perf_counter() < deadline:
                    app.processEvents()
                    time.sleep(0.01)
                self.assertIsNone(tab._task_thread)
                self.assertIsNone(tab._task_ui_bridge)
            finally:
                if tab._task_thread is not None and tab._task_thread.isRunning():
                    tab._task_thread.quit()
                    tab._task_thread.wait(2000)
                tab.close()
                tab.deleteLater()
                app.processEvents()

    def test_auto_preview_local_selection_loads_inline_preview_via_worker(self) -> None:
        app = _app()
        events: list[tuple[str, dict[str, object]]] = []
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            scene_path = _write_triangle_gltf(root, triangle_count=1200)
            settings = create_settings(settings_file_path=root / "settings.ini")
            tab = _QtPreviewModelLibraryTab(
                settings=settings,
                base_dir=root,
                record_runtime_event=lambda event, **fields: events.append((str(event), dict(fields))),
            )
            try:
                tab.show()
                tab.auto_preview_checkbox.setChecked(True)
                tab._set_active_results_view("local", persist=False)
                payload = {
                    "kind": "local",
                    "name": "Dense Triangle",
                    "path": str(scene_path),
                    "extension": ".gltf",
                    "size": scene_path.stat().st_size,
                    "source": "Local",
                }
                tab._populate_results([payload])
                while tab._populating_results:
                    app.processEvents()
                    time.sleep(0.01)

                tab._schedule_auto_inline_preview()
                deadline = time.perf_counter() + 10.0
                while tab._inline_preview_loaded_import_path is None and time.perf_counter() < deadline:
                    app.processEvents()
                    time.sleep(0.01)

                self.assertEqual(tab._inline_preview_loaded_import_path, scene_path)
                self.assertEqual(tab._inline_preview_loaded_renderer_backend, "qt")
                self.assertIn("model_library_preview_start", [event for event, _fields in events])
                self.assertIn("model_library_preview_prepared", [event for event, _fields in events])
                self.assertGreater(int(getattr(tab.inline_preview_widget, "_vertex_count", 0) or 0), 0)
            finally:
                if tab._task_thread is not None and tab._task_thread.isRunning():
                    if tab._stop_event is not None and hasattr(tab._stop_event, "set"):
                        tab._stop_event.set()
                    tab._task_thread.quit()
                    tab._task_thread.wait(2000)
                tab.close()
                tab.deleteLater()
                app.processEvents()


if __name__ == "__main__":
    unittest.main()
