"""Utilities wiring and the installed-item input delivered to the Rust viewport."""
import hashlib
import io
import json
import os
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import numpy as np
import pytest

from PIL import Image
from PySide6.QtCore import QEvent
from PySide6.QtWidgets import QApplication

from cdmw.core.archive_format import parse_archive_pamt
from cdmw.core.pac_xml_standard_material import STANDARD_SHADER
from cdmw.services.new_item_service import NewItemService
from cdmw.ui.new_item.controller import NewItemStudioController
from cdmw.ui.new_item.item_preview import ItemPreviewFrame, build_item_preview_package
from cdmw.ui.new_item.item_preview_materials import as_parsed_mesh
from cdmw.ui.new_item.model_import import ModelPlacement
from cdmw.ui.tools.mod_management import ModManagementTab
from tests.test_archive_overlay_manager import Backups, shop_spec
from tests.test_new_item_provenance import current_files
from tests.test_new_item_service import PAC, PAC_XML, build_package, _read
from tests.test_pac_xml_standard_material import HEAD, TAIL, texture, wrapper
from tests.test_static_skin_weight_export import _skinned_pac


def pump(app, predicate):
    deadline = time.monotonic() + 5
    while not predicate() and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(.002)
    assert predicate()


def test_rust_management_opens_without_importing_the_authoring_workspace():
    probe = """
import sys
from unittest.mock import patch
from PySide6.QtCore import QEvent
from PySide6.QtWidgets import QApplication
from cdmw.ui.tools.rust_mod_management import RustModManagementTab
from cdmw.ui.new_item.rust_ui_tab import RustNewItemStudioTab
app = QApplication([])
with patch.object(RustNewItemStudioTab, '_start_prepare'):
    tab = RustModManagementTab()
    try:
        tab.show()
        app.processEvents()
        assert tab.controller.snapshot is None
        assert not any(name == 'cdmw.ui.new_item.tab' or name.startswith('cdmw.ui.new_item.panels_')
                       for name in sys.modules), 'Mod Management imported the authoring workspace'
    finally:
        tab.request_shutdown()
        tab.deleteLater()
        app.sendPostedEvents(None, QEvent.DeferredDelete)
# Preserve the package's public compatibility import when explicitly requested.
from cdmw.ui.new_item import NewItemStudioTab
from cdmw.ui.new_item.tab import NewItemStudioTab as Owner
assert NewItemStudioTab is Owner
"""
    result = subprocess.run([sys.executable, '-c', probe], cwd=Path(__file__).resolve().parents[1],
                            capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr


def test_management_keeps_its_own_loading_title_when_the_renderer_launches(tmp_path):
    from unittest.mock import Mock, patch
    from PySide6.QtCore import QEvent, QProcess
    from cdmw.ui.new_item import rust_ui_tab
    from cdmw.ui.tools.rust_mod_management import RustModManagementTab

    app = QApplication.instance() or QApplication([])
    tab = RustModManagementTab()
    process = Mock(spec=QProcess)
    process.state.return_value = QProcess.NotRunning
    launch = SimpleNamespace(executable='owned-helper', manifest=tmp_path / 'session.json', cleanup=Mock())
    try:
        assert tab._host._status_label.text() == 'Preparing Mod Management…'
        tab._rust_mode = True
        with patch.object(rust_ui_tab, 'QProcess', return_value=process), \
                patch.object(tab._host, 'prepare_launch', return_value=0):
            tab._launch_ready(launch)
        assert tab._host._status_label.text() == 'Preparing Mod Management…'
        process.start.assert_called_once()
        assert tab.controller.snapshot is None
    finally:
        tab.request_shutdown()
        tab._process_finished()
        tab.deleteLater()
        app.sendPostedEvents(None, QEvent.DeferredDelete)


def test_management_retains_loading_until_the_first_rendered_state(monkeypatch):
    from unittest.mock import Mock
    from PySide6.QtCore import QEvent, QProcess
    from cdmw.ui.tools.rust_mod_management import RustModManagementTab
    from cdmw.ui.new_item.rust_ui_tab import RustNewItemStudioTab
    from tests.test_mesh_rust_embedding import _FakeUser32

    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr(RustNewItemStudioTab, '_start_prepare', lambda self: None)
    tab = RustModManagementTab()
    process = Mock(spec=QProcess)
    process.processId.return_value = 77
    process.state.return_value = QProcess.NotRunning
    tab._process = process
    tab._rust_mode = True
    tab._bridge = SimpleNamespace(session='first-frame', document=SimpleNamespace(portals={}), close=lambda: None)
    tab._sent_generation = 1
    monkeypatch.setattr(tab, '_publish_state', lambda: None)
    try:
        tab.show()
        parent = tab._host.prepare_launch()
        api = _FakeUser32(owner_pid=77, parent_hwnd=parent)
        monkeypatch.setattr('cdmw.ui.mesh_editor.rust_host._windows_api', lambda: api)
        tab._startup_deadline.start(30000)
        def message(kind, **kwargs):
            tab._handle_message({'session': 'first-frame', 'type': kind, **kwargs})
        message('ready', child_hwnd=123, embedded_parent_hwnd=parent)
        assert tab._ready and not tab._first_frame_ready
        assert tab._host._pages.isVisible() and tab._startup_deadline.isActive()
        message('state_received', generation=1)
        assert api.paints == [123]
        assert tab._host._pages.isVisible() and not tab._first_frame_ready
        message('layout', generation=0, pixels_per_point=1, portals=[])
        assert tab._host._pages.isVisible() and not tab._first_frame_ready
        message('layout', generation=1, pixels_per_point=1, portals=[])
        assert tab._host._editor_visible and not tab._host._pages.isVisible()
        assert not tab._startup_deadline.isActive()
    finally:
        tab.request_shutdown()
        tab._process_finished()
        tab.deleteLater()
        app.sendPostedEvents(None, QEvent.DeferredDelete)


@pytest.mark.usefixtures("retained_mod_folder_tools")
def test_rust_workspace_navigation_filter_and_scoped_activity(tmp_path, monkeypatch):
    from cdmw.ui.new_item.rust_ui_bridge import NewItemPresentationBridge
    from cdmw.ui.new_item.rust_ui_dialogs import PresentationDialogs
    from tests.test_new_item_rust_ui import _send
    from cdmw.ui.shell.compact.activity import ActivityHistory, tool_log_adapter_for
    from cdmw.ui.shell.compact.drawer import CompactActivityDrawer
    from unittest.mock import Mock, PropertyMock, patch
    from PySide6.QtWidgets import QWidget
    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr(ItemPreviewFrame, '_start_package', lambda *_args, **_kwargs: None)
    from tests.test_mod_package_retrofit_async import _ToolOwner
    repackage_owner = _ToolOwner(tmp_path)
    tab = ModManagementTab(controller=NewItemStudioController(synchronous=True), repackage_owner=repackage_owner)
    visible = QWidget()
    dialogs = PresentationDialogs(tab, visible)
    dialogs.active = True
    bridge = NewItemPresentationBridge(tab, dialogs=dialogs.dialogs)
    history = ActivityHistory()
    tab.status_message_requested.connect(lambda message, error: history.append(
        message, tool_key='mod_management', severity='error' if error else 'info'))
    drawer = CompactActivityDrawer(history)
    owner = SimpleNamespace(shell=SimpleNamespace(_tool_widgets_by_key={'mod_management': tab}))
    drawer.set_tool_log(tool_log_adapter_for(owner, 'mod_management'))
    tab.show()
    app.processEvents()
    try:
        assert not bridge.snapshot()['unsupported']
        assert not dialogs.dialogs(), 'Inline pages must never become Rust modal dialogs.'
        assert tab._current_page() is tab.mods_page
        for key, page in tab._page_by_key.items():
            tab.open_page(key)
            assert tab._current_page() in (page, tab.mods_page)
            assert not bridge.snapshot()['unsupported']
            assert not dialogs.dialogs()
        tab.controller.log_message.emit('Planning a different New Item')
        assert 'Planning a different New Item' not in tab.log.toPlainText()
        tab._append_activity('Full textures loaded.')
        assert 'Full textures loaded.' in tab.log.toPlainText()
        state = bridge.snapshot()
        for text in ('Full textures loaded.', 'Copy activity', '"Activity"'):
            assert text not in json.dumps(state['root'])
        assert not tab.operation_bar.isVisible()
        assert drawer._tool_log_binding.source_document is tab.log.document()
        assert drawer.tool_log_view.toPlainText() == tab.log.toPlainText()
        drawer.tabs.setCurrentIndex(1)
        drawer.copy_button.click()
        assert app.clipboard().text() == tab.log.toPlainText()

        # Only a running management operation gets a local status/cancel row;
        # unrelated preview updates must not replace its progress message.
        with patch.object(NewItemStudioController, 'busy', new_callable=PropertyMock, return_value=True):
            tab.controller._lane = 'mod_merge'
            tab._busy_changed(True)
            tab.controller.operation_progress.emit('mod_merge', 2, 4, 'Combining mod folders')
            tab._append_activity('Full textures loaded.')
            assert tab.operation_bar.isVisible()
            assert tab.status.text() == 'Combining mod folders'
            assert tab.progress.value() == 2 and tab.progress.maximum() == 4
            cancel = Mock()
            monkeypatch.setattr(tab.controller, 'cancel_operation', cancel)
            tab.cancel_button.click()
            cancel.assert_called_once_with('mod_merge')
        tab.controller._lane = ''
        tab._busy_changed(False)
        assert not tab.operation_bar.isVisible()
        drawer.clear_button.click()
        assert tab.log.toPlainText() == ''
    finally:
        dialogs.close()
        tab.request_shutdown()
        pump(app, lambda: not tab.iter_shutdown_workers())
        tab.deleteLater()
        visible.deleteLater()
        drawer.deleteLater()
        repackage_owner.deleteLater()


