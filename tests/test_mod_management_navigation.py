"""Unavailable Mod Management stays disabled across shell navigation routes."""

import os
from unittest.mock import patch

import pytest
from PySide6.QtCore import QCoreApplication, QEvent, Qt
from PySide6.QtGui import QHelpEvent
from PySide6.QtWidgets import QApplication, QToolTip

from cdmw.services.settings_service import create_settings
from cdmw.ui.main_window import MainWindow
from cdmw.ui.shell.app_context import AppContext


@pytest.mark.parametrize("variant", ["legacy", "compact_rail"])
def test_disabled_mod_management_navigation_and_hover_reason(tmp_path, variant):
    app = QApplication.instance() or QApplication([])
    font, palette, stylesheet = app.font(), app.palette(), app.styleSheet()
    settings = create_settings(settings_file_path=tmp_path / "navigation.cfg")
    settings.setValue("ui/shell_variant", variant)
    settings.setValue("ui/active_tool_key", "mod_management")
    settings.setValue("appearance/language", "en")
    with patch.dict(os.environ, {"CDMW_GUI_STARTUP_SMOKE": "1"}):
        window = MainWindow(app_context=AppContext.from_settings(settings))
    window.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
    window.show()
    app.processEvents()
    try:
        tool = window.mod_management_tab
        assert not tool.isEnabled()
        assert "DLC update" in tool.toolTip()
        assert window.tool_stack.currentWidget() is window.archive
        assert not window._tool_window_actions["mod_management"].isEnabled()
        assert window._tool_window_actions["mod_management"].toolTip() == tool.toolTip()
        for busy in (True, False):
            window.set_busy(busy)
            assert not window.mod_package_tool_action.isEnabled()
        for key in ("mod_management", "mod_package_retrofit"):
            window._activate_tool_key(key)
            settings.setValue("ui/active_tool_key", key)
            window._restore_saved_navigation()
            assert window.tool_stack.currentWidget() is window.archive
        window._activate_tool_widget(tool)
        window._detach_tool_key("mod_management")
        window._tool_window_actions["mod_management"].trigger()
        window.mod_package_tool_action.trigger()
        assert window.tool_stack.currentWidget() is window.archive
        assert "mod_management" not in window._detached_tool_windows
        assert tool.widget_if_created() is None

        # Exercise Qt's actual help event on the disabled control, including
        # a live language change, rather than checking only a stored string.
        for language in ("en", "fr"):
            window._handle_language_changed(language)
            app.processEvents()
            if variant == "compact_rail":
                control = window.compact_workspace.rail.tool_buttons["mod_management"]
                assert not control.isEnabled()
                position = control.rect().center()
                tooltip = control.toolTip()
            else:
                navigation = window.classic_navigation
                utilities = next(i for i in range(navigation.groups.count())
                                 if navigation.groups.tabData(i) == "Utilities")
                navigation.groups.setCurrentIndex(utilities)
                assert window._tool_key_for_widget(window.tool_stack.currentWidget()) != "mod_management"
                control = navigation.tools
                index = next(i for i in range(control.count()) if control.tabData(i) == "mod_management")
                assert not control.isTabEnabled(index)
                position = control.tabRect(index).center()
                tooltip = control.tabToolTip(index)
            assert tooltip == window.ui_localizer.translate(tool.toolTip())
            assert ("temporarily disabled" if language == "en" else "désactivée") in tooltip
            QToolTip.hideText()
            QApplication.sendEvent(control, QHelpEvent(QEvent.Type.ToolTip, position, control.mapToGlobal(position)))
            assert QToolTip.text() == tooltip
        assert tool.widget_if_created() is None
    finally:
        QToolTip.hideText()
        window._finalize_close()
        window.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        app.setPalette(palette)
        app.setStyleSheet(stylesheet)
        app.setFont(font)
        app.processEvents()
