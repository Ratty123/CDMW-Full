import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import threading
from unittest.mock import patch
import pytest

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


@pytest.mark.parametrize('response', ['yes', 'no', 'stale'])
def test_experimental_launch_projects_review_and_preserves_profile_selection(tmp_path, monkeypatch, response):
    from cdmw.domain.virtual_loader import VirtualSessionStatus
    from cdmw.services import virtual_loader_runtime as runtime
    from tests.test_virtual_loader_saves import experimental_fixture
    root, _files, _save = experimental_fixture(tmp_path, monkeypatch)
    app = QApplication.instance() or QApplication([])
    controller = NewItemStudioController(synchronous=True)
    page = VirtualLoaderPage(controller, root)
    bridge = NewItemPresentationBridge(page)
    before, calls, reviews = game_bytes(root), [], []
    def start(*args, **kwargs):
        calls.append(kwargs)
        return VirtualSessionStatus('starting', 'a' * 32, load_profile(root)['generation'], 123)
    monkeypatch.setattr(runtime, '_start', start)
    def question(_parent, _title, detail):
        reviews.append(detail)
        if response == 'stale':
            page._append_selection('item', (tmp_path / 'different.cditem',))
        return QMessageBox.No if response == 'no' else QMessageBox.Yes
    monkeypatch.setattr(QMessageBox, 'question', question)
    try:
        page.refresh()
        assert page.launch_button.isEnabled()
        assert not bridge.snapshot()['unsupported']
        _send(bridge, page.launch_button, 'activate')
        pump(app, lambda: page._queued is None and not page._working)
        assert len(reviews) == 1 and 'save-backups' in reviews[0]
        assert len(calls) == (1 if response == 'yes' else 0)
        assert game_bytes(root) == before
        if response == 'yes':
            assert calls[0]['mode'] == 3 and calls[0]['extra_guards']
            assert page._session and not page.launch_button.isEnabled()
        else:
            page._append_selection('item', (tmp_path / 'other.cditem',))
            page.refresh()
            assert not page.launch_button.isEnabled()  # Never launch a different saved selection.
    finally:
        page.request_shutdown()
        controller.shutdown()
        page.close()


@pytest.mark.parametrize('action', ['close', 'cancel'])
def test_close_during_save_backup_cancels_launch_review(tmp_path, monkeypatch, action):
    from cdmw.services import virtual_loader_runtime as runtime
    from cdmw.domain.virtual_loader import VirtualProfile, VirtualSessionStatus
    app = QApplication.instance() or QApplication([])
    controller = NewItemStudioController()
    page = VirtualLoaderPage(controller, tmp_path)
    page._saved_selection = VirtualProfile()
    page._runtime = VirtualSessionStatus('ready', '')
    entered, release, cancelled = threading.Event(), threading.Event(), threading.Event()
    def prepare(root, *, stop_event):
        entered.set()
        assert release.wait(5)
        if stop_event.is_set():
            cancelled.set()
        return object()
    monkeypatch.setattr(runtime, 'prepare_experimental_launch', prepare)
    try:
        with patch.object(QMessageBox, 'question') as question:
            page._launch()
            pump(app, entered.is_set)
            assert page.cancel_button.isEnabled()
            if action == 'close':
                page.request_shutdown()
            else:
                _send(NewItemPresentationBridge(page), page.cancel_button, 'activate')
            release.set()
            pump(app, lambda: not controller.busy)
            assert cancelled.is_set() and not question.called
    finally:
        release.set()
        page.request_shutdown()
        controller.shutdown()
        page.close()


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
            page.tools_toggle.setChecked(True)
            localizer.apply_registered_roots()
            assert page.prepare_button.text() == localizer.translate('Inspect and prepare')
            assert page.trace_button.text() == localizer.translate('Review startup trace…')
            assert page.launch_button.text() == localizer.translate('Launch with virtual profile')
            assert page.backups_button.text() == localizer.translate('Open save backups')
            assert page.selection.topLevelItem(0).data(0, Qt.UserRole) == selected
            assert not bridge.snapshot()['unsupported']
            page.tools_toggle.setChecked(False)
    finally:
        localizer.shutdown()
        page.request_shutdown()
        controller.shutdown()
        page.deleteLater()
        app.sendPostedEvents(None, QEvent.DeferredDelete)


@pytest.mark.parametrize('action', ['cancel', 'root', 'close'])
def test_prepare_helper_receives_immutable_selection_and_discards_late_result(tmp_path, monkeypatch, action):
    from types import SimpleNamespace
    from cdmw.services import virtual_loader_process
    app = QApplication.instance() or QApplication([])
    controller = NewItemStudioController()
    page = VirtualLoaderPage(controller, tmp_path)
    package = tmp_path / 'item.cditem'
    page._append_selection('item', (package,))
    entered, release, stopped = threading.Event(), threading.Event(), threading.Event()
    captured = []
    def prepare(profile, root, *, on_log, stop_event, on_progress):
        captured.append((profile, root))
        entered.set()
        on_progress(25, 100, 'Reading game data…')
        assert release.wait(5)
        if stop_event.is_set():
            stopped.set()
        on_progress(90, 100, 'This progress is stale')
        return SimpleNamespace(summary=('obsolete',))
    monkeypatch.setattr(virtual_loader_process, 'prepare_profile_in_subprocess', prepare)
    try:
        page._prepare()
        pump(app, entered.is_set)
        assert controller.busy and page.cancel_button.isEnabled()
        if action == 'root':
            page.set_game_root(tmp_path / 'other')
        elif action == 'close':
            page.request_shutdown()
        else:
            page._cancel()
        release.set()
        pump(app, lambda: not controller.busy)
        assert captured[0][0].packages == (package,)
        assert captured[0][1] == str(tmp_path)
        assert stopped.is_set() and page._prepared is None
        assert 'obsolete' not in page.review.toPlainText()
        assert 'stale' not in page.status.text()
    finally:
        release.set()
        page.request_shutdown()
        controller.shutdown()
        page.close()
