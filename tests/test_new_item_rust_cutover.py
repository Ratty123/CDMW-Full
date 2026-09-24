"""The shell exposes one New Item workspace and preserves its existing handoffs."""

from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path
from unittest.mock import patch

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from cdmw.services.settings_service import create_settings
from cdmw.ui.main_window import MainWindow
from cdmw.ui.new_item.rust_ui_tab import RustNewItemStudioTab
from cdmw.ui.shell.app_context import AppContext
from cdmw.ui.shell.compact.activity import tool_log_adapter_for
from cdmw.ui.shell.compact.snapshots import compact_status_snapshot_for
from tests.test_new_item_rust_ui import TEMPLATE, studio


@pytest.mark.parametrize("variant", ["legacy", "compact"])
@pytest.mark.parametrize("saved_key", ["new_item_studio", "new_item_rust_studio"])
def test_shell_opens_only_rust_and_keeps_navigation_and_handoffs(tmp_path, variant, saved_key):
    # The real shell installs process-wide Qt settings/localization hooks. Keep
    # those out of other workflow fixtures, which deliberately omit that shell.
    probe = """
import sys
from pathlib import Path
from tests.test_new_item_rust_cutover import _check_shell_navigation, studio
fixture = studio.__wrapped__()
try:
    _check_shell_navigation(next(fixture), Path(sys.argv[3]), sys.argv[1], sys.argv[2])
finally:
    fixture.close()
"""
    result = subprocess.run(
        [sys.executable, "-c", probe, variant, saved_key, str(tmp_path)],
        cwd=Path(__file__).resolve().parents[1], capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def _check_shell_navigation(studio, tmp_path, variant, saved_key):
    _, workflow, _ = studio
    app = QApplication.instance()
    font, palette, stylesheet = app.font(), app.palette(), app.styleSheet()
    settings = create_settings(settings_file_path=tmp_path / "new-item-navigation.cfg")
    settings.setValue("ui/shell_variant", variant)
    settings.setValue("ui/active_tool_key", saved_key)
    settings.setValue("appearance/language", "en")
    with patch.dict(os.environ, {"CDMW_GUI_STARTUP_SMOKE": "1"}), \
            patch("cdmw.ui.new_item.tab.NewItemStudioTab", return_value=workflow) as constructor, \
            patch.object(RustNewItemStudioTab, "_start_prepare"), \
            patch.object(workflow.controller, "persist_issued_identities") as persist:
        window = MainWindow(app_context=AppContext.from_settings(settings))
        window._new_item_controller = workflow.controller
        try:
            keys = [key for key in window._tool_widgets_by_key if key.startswith("new_item")]
            assert keys == ["new_item_studio"]
            assert window.tab_registry.titles["new_item_studio"] == "Create New Item"
            assert window._detachable_tool_order.count("new_item_studio") == 1
            assert "new_item_rust_studio" not in window._detachable_tool_order
            container = window.new_item_studio_tab
            window._restore_saved_navigation()
            assert window.tool_stack.currentWidget() is container

            model = Path("owned-model.gltf")
            with patch.object(workflow, "prefill_template") as prefill, \
                    patch.object(workflow, "open_model_source") as open_model:
                window.open_new_item_studio(TEMPLATE, model_path=model)
                deadline = time.monotonic() + 5
                while container.widget_if_created() is None and time.monotonic() < deadline:
                    app.processEvents()
                    time.sleep(0.001)
                presentation = container.widget_if_created()
                assert isinstance(presentation, RustNewItemStudioTab)
                assert presentation.workflow is workflow
                assert presentation.objectName() == "new_item_studio"
                prefill.assert_called_once_with(TEMPLATE)
                open_model.assert_called_once_with(model)
                constructor.assert_called_once_with(window=window, controller=workflow.controller)
                persist.assert_called_once_with()
                window._use_model_in_new_item_studio(str(model), object())
                assert open_model.call_count == 2

            workflow.show_step(2)
            assert "Step 3/7" in compact_status_snapshot_for(window, "new_item_studio").facts
            adapter = tool_log_adapter_for(window, "new_item_studio")
            assert adapter.document is workflow.log.document()
            with patch.object(window, "set_status_message") as status:
                presentation.status_message_requested.emit("Item ready", False)
                status.assert_called_once_with("Item ready", error=False, tool_key="new_item_studio")

            window._activate_tool_key("mod_management")
            deadline = time.monotonic() + 5
            while window.mod_management_tab.widget_if_created() is None and time.monotonic() < deadline:
                app.processEvents()
                time.sleep(.001)
            management = window.mod_management_tab.widget_if_created()
            assert management.controller is workflow.controller

            window._activate_tool_key("archive_browser")
            window._activate_tool_key("new_item_rust_studio")
            assert window.tool_stack.currentWidget() is container
            if variant == "compact":
                assert window.compact_workspace.rail.tool_buttons["new_item_studio"].isChecked()
                assert "new_item_rust_studio" not in window.compact_workspace.rail.tool_buttons
            else:
                tabs = window.classic_navigation.tools
                assert tabs.tabData(tabs.currentIndex()) == "new_item_studio"
                assert tabs.tabText(tabs.currentIndex()) == "Create New Item"
            window._detach_tool_key("new_item_studio")
            detached = window._detached_tool_windows["new_item_studio"]
            assert detached.windowTitle() == "Create New Item"
            assert detached.centralWidget() is container
            window._attach_detached_tool("new_item_studio")
            assert window.tool_stack.currentWidget() is container
            assert presentation.workflow is workflow
            assert workflow.testAttribute(Qt.WA_DontShowOnScreen)
        finally:
            window.new_item_studio_tab.request_shutdown()
            workflow.setParent(None)
            window._close_force_accept = True
            window.close()
            window.deleteLater()
            app.processEvents()
            app.setFont(font)
            app.setPalette(palette)
            app.setStyleSheet(stylesheet)
