from __future__ import annotations

import os
import time
from unittest.mock import patch

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QObject, QThread, Signal, Slot
from PySide6.QtWidgets import QApplication, QLabel

from cdmw.ui.archive_browser.workspace import ArchiveBrowserWorkspace
from cdmw.ui.shell.workbench import WorkbenchWindow
from cdmw.ui.texture_workflow.workspace import TexturesWorkspace


def test_feature_state_and_callbacks_belong_to_their_workspaces() -> None:
    app = QApplication.instance() or QApplication([])
    window = WorkbenchWindow()
    window.archive = ArchiveBrowserWorkspace(window)
    window.textures = TexturesWorkspace(window)
    try:
        window.archive.archive_entries = ["archive asset"]
        window.textures.compare_relative_paths = ["texture asset"]
        assert "archive_entries" not in window.__dict__
        assert "compare_relative_paths" not in window.__dict__
        assert window.archive._current_archive_entry.__self__ is window.archive
        assert window.textures._handle_current_file.__self__ is window.textures
        assert window.archive.textures is window.textures
        assert window.textures.archive is window.archive
        assert window.archive.parent() is window
        assert window.textures.parent() is window
        assert not hasattr(WorkbenchWindow, "__cdmw_composed_members__")
    finally:
        window.deleteLater()
        app.processEvents()


def test_texture_worker_signal_reaches_the_owning_widget_on_the_ui_thread() -> None:
    app = QApplication.instance() or QApplication([])
    window = WorkbenchWindow()
    textures = TexturesWorkspace(window)
    observed_threads = []

    class Label(QLabel):
        def setText(self, value: str) -> None:
            observed_threads.append(QThread.currentThread())
            super().setText(value)

    class Worker(QObject):
        current_file = Signal(str, bool)
        finished = Signal()

        @Slot()
        def run(self) -> None:
            self.current_file.emit("asset.dds", False)
            self.finished.emit()

    textures.current_file_value = Label(textures)
    worker = Worker()
    thread = QThread()
    worker.moveToThread(thread)
    thread.started.connect(worker.run)
    worker.current_file.connect(textures._handle_current_file)
    worker.finished.connect(thread.quit)
    worker.finished.connect(worker.deleteLater)
    try:
        thread.start()
        deadline = time.monotonic() + 2.0
        while time.monotonic() < deadline and (thread.isRunning() or not observed_threads):
            app.processEvents()
            time.sleep(0.001)
        assert textures.current_file_value.text() == "asset.dds"
        assert observed_threads == [app.thread()]
        assert not thread.isRunning()
    finally:
        thread.quit()
        thread.wait(2000)
        window.deleteLater()
        thread.deleteLater()
        app.processEvents()


@pytest.mark.parametrize("variant", ["legacy", "compact_rail"])
def test_both_navigation_styles_restore_and_reattach_the_same_content(tmp_path, variant) -> None:
    from cdmw.services.settings_service import create_settings
    from cdmw.ui.main_window import MainWindow
    from cdmw.ui.shell.app_context import AppContext

    app = QApplication.instance() or QApplication([])
    font, palette, stylesheet = app.font(), app.palette(), app.styleSheet()
    settings = create_settings(settings_file_path=tmp_path / "navigation.cfg")
    settings.setValue("ui/shell_variant", variant)
    settings.setValue("ui/active_tool_key", "archive_browser")
    settings.setValue("appearance/language", "de")
    with patch.dict(os.environ, {"CDMW_GUI_STARTUP_SMOKE": "1"}):
        window = MainWindow(app_context=AppContext.from_settings(settings))
    try:
        archive = window.archive
        original_count = window.tool_stack.count()
        assert window.tool_stack.currentWidget() is archive
        assert window.tab_registry.widgets["archive_browser"] is archive
        if variant == "legacy":
            navigation = window.classic_navigation
            assert navigation.tools.tabData(navigation.tools.currentIndex()) == "archive_browser"
            label = navigation.tools.tabText(navigation.tools.currentIndex())
        window._detach_tool_key("archive_browser")
        assert window._detached_tool_windows["archive_browser"].centralWidget() is archive
        assert window.tool_stack.count() == original_count
        window._attach_detached_tool("archive_browser")
        assert window.tool_stack.currentWidget() is archive
        assert window.tool_stack.count() == original_count
        if variant == "legacy":
            assert navigation.tools.tabText(navigation.tools.currentIndex()) == label
        else:
            assert window.compact_workspace.rail.tool_buttons["archive_browser"].isChecked()
    finally:
        window._close_force_accept = True
        window.close()
        window.deleteLater()
        app.processEvents()
        app.setFont(font)
        app.setPalette(palette)
        app.setStyleSheet(stylesheet)


@pytest.mark.parametrize("initial_mode, final_mode", [
    ("edit", "edit"), ("recolor", "upscale"), ("recolor", "recolor"),
])
def test_texture_controls_stay_in_the_selected_page_when_recolor_finishes_loading(
    tmp_path, monkeypatch, initial_mode, final_mode,
) -> None:
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QPushButton
    from cdmw.services.settings_service import create_settings
    from cdmw.ui.main_window import MainWindow
    from cdmw.ui.shell.app_context import AppContext
    from cdmw.ui.themes import build_app_palette, build_app_stylesheet

    app = QApplication.instance() or QApplication([])
    font, palette, stylesheet = app.font(), app.palette(), app.styleSheet()
    settings = create_settings(settings_file_path=tmp_path / "textures.cfg")
    settings.setValue("ui/active_tool_key", "archive_browser")
    settings.setValue("ui/textures_mode", initial_mode)
    monkeypatch.setenv("CDMW_GUI_STARTUP_SMOKE", "1")
    window = MainWindow(app_context=AppContext.from_settings(settings))
    try:
        app.setPalette(build_app_palette("nord"))
        app.setStyleSheet(build_app_stylesheet("nord"))
        window.setAttribute(Qt.WA_DontShowOnScreen)
        window.resize(1450, 1000)
        window.show()
        window._activate_tool_key("textures")
        editor = window.texture_editor_tab.ensure_widget()
        textures = window.textures
        assert textures.job.mode == initial_mode
        textures.set_texture_mode("recolor")
        textures.set_texture_mode(final_mode)
        recolor = window.recolor_variants_tab.ensure_widget()
        app.processEvents()

        assert textures.job.mode == final_mode
        assert editor.left_scroll.isVisible() == (final_mode == "edit")
        assert recolor.isVisible() == (final_mode == "recolor")
        assert textures.upscale_controls.isVisible() == (final_mode == "upscale")
        for index in range(textures.mode_controls.count()):
            page = textures.mode_controls.widget(index)
            assert page.isVisible() == (page is textures.mode_controls.currentWidget())

        for mode, button in textures.mode_buttons.items():
            assert isinstance(button, QPushButton)
            QTest.mouseClick(button, Qt.LeftButton)
            app.processEvents()
            assert textures.job.mode == mode
            assert button.isChecked()
            assert sum(other.isChecked() for other in textures.mode_buttons.values()) == 1
            checked = button.grab().toImage().pixelColor(8, button.height() // 2)
            other = next(other for other in textures.mode_buttons.values() if other is not button)
            QTest.mouseClick(other, Qt.LeftButton)
            app.processEvents()
            unchecked = button.grab().toImage().pixelColor(8, button.height() // 2)
            assert checked != unchecked, f"{mode} has no painted selected state"
    finally:
        window._close_force_accept = True
        window.close()
        window.deleteLater()
        app.processEvents()
        app.setFont(font)
        app.setPalette(palette)
        app.setStyleSheet(stylesheet)


def test_texture_aliases_share_documents_and_review(tmp_path, monkeypatch) -> None:
    import time
    from PIL import Image
    from PySide6.QtCore import QPoint, Qt
    from cdmw.models import TextureEditorSourceBinding
    from cdmw.services.settings_service import create_settings
    from cdmw.ui.main_window import MainWindow
    from cdmw.ui.shell.app_context import AppContext
    from cdmw.ui.shell.lazy_tool_tab import created_tool_widget

    app = QApplication.instance() or QApplication([])
    settings = create_settings(settings_file_path=tmp_path / "textures.cfg")
    settings.setValue("ui/active_tool_key", "archive_browser")
    monkeypatch.setenv("CDMW_GUI_STARTUP_SMOKE", "1")
    window = MainWindow(app_context=AppContext.from_settings(settings))

    def wait_for(predicate):
        deadline = time.monotonic() + 15
        while not predicate() and time.monotonic() < deadline:
            app.processEvents()
            time.sleep(.005)
        assert predicate()

    try:
        window._activate_tool_key("texture_editor")
        wait_for(lambda: created_tool_widget(window.texture_editor_tab) is not None)
        editor = created_tool_widget(window.texture_editor_tab)
        assert editor.job is window.textures.job
        assert editor.main_splitter.count() == 2
        source = tmp_path / "color.png"
        Image.new("RGBA", (8, 8), (150, 75, 25, 255)).save(source)
        binding = TextureEditorSourceBinding(source_path=str(source), archive_relative_path="armor/color.dds")
        window.textures.open_texture_sources([source], binding=binding)
        wait_for(lambda: len(editor._sessions) == 1 and not editor._busy())
        window.setAttribute(Qt.WA_DontShowOnScreen)
        window.resize(1450, 900)
        window.show()
        wait_for(lambda: editor.top_ruler._viewport_offset == editor.canvas.mapTo(editor.canvas_scroll.viewport(), QPoint()).x())
        session = editor._sessions[0]
        window.textures._synchronize_texture_job()
        history = session.history_snapshots
        for alias, mode in (("texture_workflow", "upscale"), ("recolor_variants", "recolor"), ("texture_editor", "edit")):
            window._activate_tool_key(alias)
            wait_for(lambda: mode != "recolor" or created_tool_widget(window.recolor_variants_tab) is not None)
            assert window.tool_stack.currentWidget() is window.textures
            assert window.textures.job.mode == mode
            assert editor._sessions[0] is session
            assert session.history_snapshots is history
            assert session.document.source_binding.archive_relative_path == "armor/color.dds"
        editor.open_source_path(source)
        assert editor.document.source_binding.archive_relative_path == "armor/color.dds"
        from PySide6.QtGui import QImage, QColor
        from PySide6.QtTest import QTest
        import numpy as np

        original_pixels = editor._current_composite_rgba().copy()
        canvas = editor.canvas
        before = QImage(8, 8, QImage.Format_RGBA8888)
        before.fill(QColor(150, 75, 25))
        after = QImage(8, 8, QImage.Format_RGBA8888)
        after.fill(QColor(25, 75, 150))
        window.textures.set_texture_mode("recolor")
        window.textures.show_texture_result_preview(before, after)
        assert editor.canvas is canvas
        assert not canvas._editable
        assert editor.right_scroll.isHidden()
        assert not any(shortcut.isEnabled() for shortcut in editor._shortcut_objects)
        assert tuple(canvas._edited_rgba[0, 0]) == (25, 75, 150, 255)
        assert tuple(canvas._original_rgba[0, 0]) == (150, 75, 25, 255)
        strokes = []
        canvas.stroke_committed.connect(strokes.append)
        QTest.mouseClick(canvas, Qt.LeftButton, pos=QPoint(2, 2))
        assert not strokes
        editor.view_mode_combo.setCurrentIndex(editor.view_mode_combo.findData("split"))
        assert canvas._view_mode == "split"
        editor._refresh_canvas()
        assert tuple(canvas._edited_rgba[0, 0]) == (25, 75, 150, 255)
        assert np.array_equal(editor._current_composite_rgba(), original_pixels)
        window.textures.set_texture_mode("edit")
        assert canvas._editable
        assert editor.workspace_preview is None
        assert np.array_equal(canvas._edited_rgba, original_pixels)
        assert session.history_snapshots is history
        window.textures.show_texture_review(operation="recolor")
        assert window.textures.export_operation.currentData() == "recolor"
        assert set(window.tab_registry.widgets).isdisjoint({"texture_editor", "recolor_variants", "texture_workflow", "replace_assistant"})
        assert window.textures.asset_list.topLevelItemCount() == 1
        assert editor.document_tab_bar.isHidden()
        window._activate_tool_key("replace_assistant")
        wait_for(lambda: created_tool_widget(window.replace_assistant_tab) is not None)
        matcher = created_tool_widget(window.replace_assistant_tab)
        wait_for(lambda: len(matcher.items) == 1 and not editor._busy())
        assert matcher.workspace is window.textures
        assert matcher.main_splitter.count() == 2
        assert all(button.isHidden() for button in (matcher.add_files_button, matcher.add_folder_button, matcher.remove_selected_button, matcher.clear_all_button))
        assert window.textures.export_operation.currentData() == "replacement"
        assert matcher.items[0].source_path.is_file()
        assert editor._sessions[0] is session
        operation = window.textures.begin_texture_operation("test")
        window.textures.set_texture_job_busy(False)
        assert window.textures.job.busy
        window.textures.finish_texture_operation()
        assert not window.textures.job.busy
        from cdmw.models import ReplaceAssistantBuildSummary
        prior_output = tmp_path / "previous-package"
        prior_output.mkdir()
        matcher.last_built_output_root = prior_output
        matcher._handle_build_complete(ReplaceAssistantBuildSummary(total_items=1, built_items=0, skipped_items=0, unresolved_items=0, failed_items=1))
        matcher._handle_build_cancelled("Cancelled")
        matcher._handle_build_error("Failed")
        assert matcher.last_built_output_root is prior_output
        window.textures._remove_texture_asset()
        assert not window.textures.job.assets
        assert not window.textures.job.selected
        assert not editor._sessions
        assert source.is_file()
    finally:
        window._close_force_accept = True
        window.close()
        window.deleteLater()
        app.processEvents()
