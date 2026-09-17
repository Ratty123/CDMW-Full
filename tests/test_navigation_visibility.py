"""Navigation can collapse without hiding, replacing, or changing the active tool."""

from types import SimpleNamespace

import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QLineEdit

from cdmw.services.settings_service import create_settings
from cdmw.ui.shell.root_layout import ShellRootLayoutMixin
from cdmw.ui.shell.tab_registry import TabRegistry
from tests.test_compact_shell import _CompactOwner, _app


class _NavigationOwner(ShellRootLayoutMixin, _CompactOwner):
    def _tool_key_for_widget(self, widget):
        return next((key for key, value in self.tab_registry.widgets.items() if value is widget), "")


@pytest.mark.parametrize("variant", ["compact_rail", "legacy"])
@pytest.mark.parametrize("width,height,font_size", [(1440, 900, 10), (900, 600, 18)])
def test_navigation_toggle_preserves_tool_and_preferences(tmp_path, variant, width, height, font_size):
    app = _app()
    settings = create_settings(settings_file_path=tmp_path / "navigation.cfg")
    owner = _NavigationOwner(settings)
    owner.shell_variant = variant
    owner.tab_registry = TabRegistry()
    owner.ui_localizer = SimpleNamespace(
        language_changed=SimpleNamespace(connect=lambda callback: None),
        translate=str,
    )
    owner.setFont(QFont("Segoe UI", font_size))
    owner.setCentralWidget(owner._build_shell_root_tabs())
    tool = QLineEdit("Unsaved mesh session")
    owner.tab_registry.register("mesh_editor", tool, "Mesh Editor")
    owner.tool_stack.addWidget(tool)
    owner.tool_stack.setCurrentWidget(tool)
    if variant == "compact_rail":
        workspace = owner.compact_workspace
        workspace.set_active_tool("mesh_editor")
        navigation = workspace.rail
        toggle = workspace.navigation_toggle_button
    else:
        navigation = owner.classic_navigation
        navigation.set_active_tool("mesh_editor")
        toggle = owner.navigation_toggle_button
    owner.resize(width, height)
    owner.show()
    app.processEvents()
    tool.setFocus()
    tool.setSelection(8, 4)
    parent = tool.parentWidget()
    initial_size = owner.tool_stack.size()
    initial_selection = tool.selectedText()
    settings_before = {key: settings.value(key) for key in settings.allKeys()}
    requests_before = list(owner.requested_keys)
    try:
        for _ in range(2):
            QTest.mouseClick(toggle, Qt.LeftButton)
            app.processEvents()
            assert navigation.isHidden()
            assert toggle.isVisible() and toggle.isEnabled()
            assert toggle.accessibleName() == "Show navigation"
            assert tool.isVisible()
            assert app.focusWidget() is tool
            if variant == "compact_rail":
                assert owner.tool_stack.width() > initial_size.width() + 150
            else:
                assert owner.tool_stack.height() > initial_size.height()
            QTest.mouseClick(toggle, Qt.LeftButton)
            app.processEvents()
            assert navigation.isVisible()
            assert toggle.accessibleName() == "Hide navigation"
            assert owner.tool_stack.size() == initial_size
            assert owner.tool_stack.currentWidget() is tool
            assert tool.parentWidget() is parent
            assert tool.text() == "Unsaved mesh session"
            assert tool.selectedText() == initial_selection
        assert owner.requested_keys == requests_before
        assert {key: settings.value(key) for key in settings.allKeys()} == settings_before
    finally:
        owner.close()
        owner.deleteLater()
        app.processEvents()
