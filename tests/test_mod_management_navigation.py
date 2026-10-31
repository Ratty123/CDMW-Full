"""Mod Management is reachable for .cditem packages; the retired repackage route stays closed."""

import os
from unittest.mock import patch

import pytest
from PySide6.QtCore import QCoreApplication, QEvent, Qt
from PySide6.QtWidgets import QApplication

from cdmw.services.settings_service import create_settings
from cdmw.ui.main_window import MainWindow
from cdmw.ui.shell.app_context import AppContext


@pytest.mark.parametrize("variant", ["legacy", "compact_rail"])
def test_mod_management_navigation_opens_and_repackage_stays_retired(tmp_path, variant):
    app = QApplication.instance() or QApplication([])
    font, palette, stylesheet = app.font(), app.palette(), app.styleSheet()
    settings = create_settings(settings_file_path=tmp_path / "navigation.cfg")
    settings.setValue("ui/shell_variant", variant)
    settings.setValue("ui/active_tool_key", "archive_browser")
    settings.setValue("appearance/language", "en")
    with patch.dict(os.environ, {"CDMW_GUI_STARTUP_SMOKE": "1"}):
        window = MainWindow(app_context=AppContext.from_settings(settings))
    window.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
    window.show()
    app.processEvents()
    try:
        tool = window.mod_management_tab
        assert tool.isEnabled()
        assert "DLC update" not in tool.toolTip()
        assert window._tool_window_actions["mod_management"].isEnabled()
        for busy in (True, False):
            window.set_busy(busy)
            assert not window.mod_package_tool_action.isEnabled()
            assert not window.mod_package_tool_action.isVisible()
        if variant == "compact_rail":
            assert window.compact_workspace.rail.tool_buttons["mod_management"].isEnabled()
        else:
            navigation = window.classic_navigation
            utilities = next(i for i in range(navigation.groups.count())
                             if navigation.groups.tabData(i) == "Utilities")
            navigation.groups.setCurrentIndex(utilities)
            control = navigation.tools
            index = next(i for i in range(control.count()) if control.tabData(i) == "mod_management")
            assert control.isTabEnabled(index)
        # A saved or menu route to the retired repackage page lands on Mod Management.
        window._activate_tool_key("mod_package_retrofit")
        app.processEvents()
        assert window.tool_stack.currentWidget() is tool
    finally:
        window._finalize_close()
        window.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        app.setPalette(palette)
        app.setStyleSheet(stylesheet)
        app.setFont(font)
        app.processEvents()
