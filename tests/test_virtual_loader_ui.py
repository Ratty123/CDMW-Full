import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import threading
from unittest.mock import patch

from PySide6.QtWidgets import QApplication, QMessageBox
from PySide6.QtCore import QEvent, Qt

from cdmw.ui.new_item.controller import NewItemStudioController
from cdmw.ui.new_item.virtual_loader_page import VirtualLoaderPage
from cdmw.ui.new_item.rust_ui_bridge import NewItemPresentationBridge
from cdmw.ui.tools.mod_management import ModManagementTab
from cdmw.services.virtual_loader_state import load_profile
from tests.test_virtual_loader import packages, game_bytes
from tests.test_mod_management import pump
from tests.test_new_item_rust_ui import _send


def test_selectable_page_projects_real_controls_and_saves_reviewed_profile(tmp_path):
    app = QApplication.instance() or QApplication([])
    root, files = packages(tmp_path, 1)
    before = game_bytes(root)
    controller = NewItemStudioController(synchronous=True)
    tab = ModManagementTab(controller=controller, get_package_root=lambda: str(root))
    bridge = NewItemPresentationBridge(tab)
    try:
        titles = [tab.pages.tabText(i) for i in range(tab.pages.count())]
        assert titles[titles.index('Independent items') + 1] == 'Virtual loader (Experimental)'
        tab.open_page('virtual')
        page = tab.virtual_page
        page._append_selection('item', files)
        state = bridge.snapshot()
        assert not state['unsupported']
        _send(bridge, page.prepare_button, 'activate')
        assert page._prepared is not None and page.save_button.isEnabled()
        assert not page.launch_button.isEnabled()
        with patch.object(QMessageBox, 'question', return_value=QMessageBox.Yes):
            _send(bridge, page.save_button, 'activate')
        assert len(load_profile(root)['items']) == 1
        assert game_bytes(root) == before
        assert page._prepared is None
    finally:
        tab.request_shutdown()
        controller.shutdown()
        tab.close()


def test_root_change_and_close_reject_late_results_and_cancel_work(tmp_path):
    app = QApplication.instance() or QApplication([])
    controller = NewItemStudioController()
    page = VirtualLoaderPage(controller, tmp_path)
    entered, release, cancelled = threading.Event(), threading.Event(), threading.Event()
    delivered = []
    def task(log, stop):
        entered.set()
        assert release.wait(5)
        if stop.is_set():
            cancelled.set()
        return 'obsolete'
    try:
        page._run(task, delivered.append)
        pump(app, entered.is_set)
        page.set_game_root(tmp_path / 'another-installation')
        page.request_shutdown()
        release.set()
        pump(app, lambda: not controller.busy)
        assert cancelled.is_set() and not delivered
        assert not page.launch_button.isEnabled()
    finally:
        release.set()
        page.request_shutdown()
        controller.shutdown()
        page.close()


def test_virtual_page_translations_preserve_selection_and_projected_controls(tmp_path):
    from cdmw.domain.localization import BUILTIN_LANGUAGE_CODES
    from cdmw.ui.localization import UiLocalizer
    app = QApplication.instance() or QApplication([])
    controller = NewItemStudioController(synchronous=True)
    page = VirtualLoaderPage(controller, tmp_path)
    page._append_selection('item', (tmp_path / 'author.cditem',))
    selected = page.selection.topLevelItem(0).data(0, Qt.UserRole)
    localizer = UiLocalizer(language_dir=tmp_path / 'languages', language_code='de')
    localizer.activate_runtime_tracking(page, application=app)
    bridge = NewItemPresentationBridge(page)
    try:
        for code in BUILTIN_LANGUAGE_CODES:
            localizer.load_language(code)
            localizer.apply_registered_roots()
            assert page.prepare_button.text() == localizer.translate('Inspect and prepare')
            assert page.trace_button.text() == localizer.translate('Review startup trace…')
            assert page.launch_button.text() == localizer.translate('Launch with virtual profile')
            assert page.selection.topLevelItem(0).data(0, Qt.UserRole) == selected
            assert not bridge.snapshot()['unsupported']
    finally:
        localizer.shutdown()
        page.request_shutdown()
        controller.shutdown()
        page.deleteLater()
        app.sendPostedEvents(None, QEvent.DeferredDelete)
