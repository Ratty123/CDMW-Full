"""Exercise real Archive panes, startup defaults and detached window restoration."""

import os
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtWidgets import QApplication

from cdmw.app.events import AppEventBus
from cdmw.services.service_container import ServiceContainer
from cdmw.services.settings_service import create_settings
from cdmw.ui.main_window import MainWindow
from cdmw.ui.layout_persistence import saved_splitter_sizes
from cdmw.ui.shell.theme_controller import _DATA_FONT_CLASS_NAMES, _UI_FONT_CLASS_NAMES


def test_real_archive_layout_survives_startup_and_detach(tmp_path):
    app = QApplication.instance() or QApplication([])
    palette, stylesheet, font = app.palette(), app.styleSheet(), app.font()
    class_fonts = {name: app.font(name) for name in (*_DATA_FONT_CLASS_NAMES, *_UI_FONT_CLASS_NAMES)}
    config = tmp_path / "user.cfg"
    expected = None
    try:
        for attempt in range(2):
            from cdmw.ui.shell.app_context import AppContext

            settings = create_settings(settings_file_path=config)
            context = AppContext(settings=settings, services=ServiceContainer.create_default(settings=settings), event_bus=AppEventBus())
            with patch.dict(os.environ, {"CDMW_GUI_STARTUP_SMOKE": "1"}):
                window = MainWindow(app_context=context)
            try:
                window.show()
                for _ in range(4):
                    app.processEvents()
                split = window.archive.archive_preview_content_splitter
                window.archive.archive_preview_group.show()
                window.archive.archive_texture_refs_group.show()
                for _ in range(3):
                    app.processEvents()
                if not attempt:
                    split.moveSplitter(max(80, split.width() // 2), 1)
                    expected = saved_splitter_sizes(split)
                    assert expected
                else:
                    assert saved_splitter_sizes(split) == expected
                    assert window._layout_persistence.restore_splitter(split)
                window._apply_responsive_window_defaults(apply_expensive_metrics=False, adjust_window_geometry=False)
                assert saved_splitter_sizes(split) == expected
                assert split.sizes()[0] > 0
                before = split.sizes()
                window._apply_archive_preview_content_responsive_sizes()
                assert split.sizes() == before
                window._detach_tool_key("archive_browser")
                app.processEvents()
                detached = window._detached_tool_windows["archive_browser"]
                detached.resize(700, 550)
                app.processEvents()
                window._layout_persistence.flush()
                assert settings.value("window/detached/archive_browser/geometry")
                window._attach_detached_tool("archive_browser")
                app.processEvents()
                assert saved_splitter_sizes(split) == expected
            finally:
                window._finalize_close()
                window.deleteLater()
                QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
    finally:
        app._cdmw_layout_persistence = None
        app.setPalette(palette)
        app.setStyleSheet(stylesheet)
        app.setFont(font)
        for name, class_font in class_fonts.items():
            app.setFont(class_font, name)
        app.processEvents()
