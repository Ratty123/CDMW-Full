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


@pytest.mark.parametrize('update', [False, True])
def test_launch_click_updates_owned_loader_and_starts_with_verified_backup(tmp_path, monkeypatch, update):
    from cdmw.domain.virtual_loader import VirtualSessionStatus
    from cdmw.services import virtual_loader_runtime as runtime
    from tests.test_virtual_loader_saves import experimental_fixture
    from cdmw.services.independent_item_package import digest
    root, _files, _save = experimental_fixture(tmp_path, monkeypatch)
    app = QApplication.instance() or QApplication([])
    controller = NewItemStudioController(synchronous=True)
    page = VirtualLoaderPage(controller, root)
    bridge = NewItemPresentationBridge(page)
    before, calls, messages = game_bytes(root), [], []
    page.activity.connect(messages.append)
    if update:
        folder, evidence = runtime.native_bundle()
        payload = b'new verified loader'
        (folder / 'CDMWVirtualLoader.asi').write_bytes(payload)
        evidence['files']['CDMWVirtualLoader.asi'] = digest(payload)
        before[runtime.RUNTIME_PATH] = payload
    def start(*args, **kwargs):
        calls.append(kwargs)
        return VirtualSessionStatus('starting', 'a' * 32, load_profile(root)['generation'], 123)
    monkeypatch.setattr(runtime, '_start', start)
    monkeypatch.setattr(runtime, '_process_alive', lambda pid: pid == 123)
    monkeypatch.setattr(QMessageBox, 'question', lambda *a: pytest.fail('Routine launch must not ask for another confirmation'))
    try:
        page.refresh()
        assert page.launch_button.isEnabled()
        assert not bridge.snapshot()['unsupported']
        _send(bridge, page.launch_button, 'activate')
        pump(app, lambda: page._queued is None and not page._working)
        assert len(calls) == 1
        assert any('save-backups' in message for message in messages)
        assert game_bytes(root) == before
        assert calls[0]['mode'] == 3 and calls[0]['extra_guards']
        assert page._session and not page.launch_button.isEnabled() and not page.apply_button.isEnabled()
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
    def prepare(root, *, stop_event, on_progress):
        entered.set()
        assert release.wait(5)
        if stop_event.is_set():
            cancelled.set()
        return object()
    monkeypatch.setattr(runtime, 'prepare_experimental_launch', prepare)
    monkeypatch.setattr(page, '_ensure_runtime', lambda continuation: continuation())
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


@pytest.mark.parametrize('failure', [False, True])
def test_late_cancel_keeps_launch_result_or_actual_failure(tmp_path, monkeypatch, failure):
    from types import SimpleNamespace
    from cdmw.services import virtual_loader_runtime as runtime
    from cdmw.domain.virtual_loader import VirtualProfile
    app = QApplication.instance() or QApplication([])
    controller = NewItemStudioController()
    page = VirtualLoaderPage(controller, tmp_path)
    page._saved_selection = VirtualProfile()
    entered, release = threading.Event(), threading.Event()
    delivered = []
    value = object()
    monkeypatch.setattr(runtime, 'prepare_experimental_launch',
                        lambda *args, **kwargs: SimpleNamespace(backup=SimpleNamespace(directory=tmp_path)))

    def launch(*args, **kwargs):
        entered.set()
        assert release.wait(5)
        if failure:
            raise OSError('owned launch failure')
        return value

    def started(result):
        delivered.append(result)
        page.status.setText('Owned launch completed')

    monkeypatch.setattr(runtime, 'launch_experimental', launch)
    monkeypatch.setattr(page, '_started', started)
    try:
        page._prepare_launch()
        pump(app, entered.is_set)
        page._cancel()
        assert page.status.text() == 'Cancelling…'
        release.set()
        pump(app, lambda: not controller.busy)
        if failure:
            assert delivered == [] and page.status.text() == 'owned launch failure'
        else:
            assert delivered == [value] and page.status.text() == 'Owned launch completed'
        assert page._queued is None
    finally:
        release.set()
        page.request_shutdown()
        controller.shutdown()
        page.close()


def test_apply_click_projects_real_controls_saves_and_enables_launch(tmp_path, monkeypatch):
    from cdmw.services import virtual_loader_runtime as runtime
    from tests.test_virtual_loader_runtime import setup_fixture
    app = QApplication.instance() or QApplication([])
    root, files = packages(tmp_path, 1)
    setup_fixture(tmp_path, monkeypatch)
    runtime.apply_runtime_setup(runtime.prepare_runtime_setup(root), confirmed=True)
    before = game_bytes(root)
    controller = NewItemStudioController()
    tab = ModManagementTab(controller=controller, get_package_root=lambda: str(root))
    bridge = NewItemPresentationBridge(tab)
    try:
        titles = [tab.pages.tabText(i) for i in range(tab.pages.count())]
        assert titles == ['Mods', 'Advanced']
        tab.open_page('virtual')
        page = tab.virtual_page
        pump(app, lambda: not controller.busy and page._queued is None)
        page._append_selection('item', files)
        state = bridge.snapshot()
        assert not state['unsupported']
        with patch.object(QMessageBox, 'question', side_effect=AssertionError('Apply must not ask to save again')):
            _send(bridge, page.apply_button, 'activate')
            pump(app, lambda: page._queued is None and not page._working and not controller.busy)
        assert len(load_profile(root)['items']) == 1
        assert game_bytes(root) == before
        assert page._prepared is None
        assert page.launch_button.isEnabled() and page.progress.isHidden()
        assert page.status.text() == 'Profile applied. Ready to launch.'
        page._append_selection('item', (tmp_path / 'different.cditem',))
        assert not page.launch_button.isEnabled()
    finally:
        tab.request_shutdown()
        controller.shutdown()
        tab.close()


@pytest.mark.parametrize('response', ['yes', 'no', 'stale', 'stale_no'])
def test_apply_handles_first_loader_install_inline_and_honours_decline_or_stale_review(tmp_path, monkeypatch, response):
    from cdmw.services import virtual_loader_runtime as runtime
    from tests.test_virtual_loader_runtime import setup_fixture
    root, files = packages(tmp_path, 1)
    setup_fixture(tmp_path, monkeypatch)
    app = QApplication.instance() or QApplication([])
    controller = NewItemStudioController()
    page = VirtualLoaderPage(controller, root)
    reviews = []
    def question(_parent, title, detail):
        reviews.append((title, detail))
        if response.startswith('stale'):
            page.set_game_root(tmp_path / 'different-game')
        return QMessageBox.No if response.endswith('no') else QMessageBox.Yes
    monkeypatch.setattr(QMessageBox, 'question', question)
    try:
        page._append_selection('item', files)
        _send(NewItemPresentationBridge(page), page.apply_button, 'activate')
        pump(app, lambda: page._queued is None and not page._working and not controller.busy)
        assert len(reviews) == 1 and 'Future updates' in reviews[0][1]
        assert (root / runtime.RUNTIME_PATH).exists() == (response == 'yes')
        assert bool(load_profile(root)) == (response == 'yes')
        assert page.launch_button.isEnabled() == (response == 'yes')
        assert page.progress.isHidden()
        if response.startswith('stale'):
            assert 'cancelled' not in page.status.text()
    finally:
        page.request_shutdown()
        controller.shutdown()
        page.close()


def test_failed_apply_keeps_previous_profile_and_does_not_enable_launch(tmp_path, monkeypatch):
    from tests.test_virtual_loader_saves import experimental_fixture
    root, files, _save = experimental_fixture(tmp_path, monkeypatch)
    before = (root / '.cdmw/virtual-loader/profile.json').read_bytes()
    app = QApplication.instance() or QApplication([])
    controller = NewItemStudioController(synchronous=True)
    page = VirtualLoaderPage(controller, root)
    try:
        page.refresh()
        files[0].write_bytes(b'broken package')
        _send(NewItemPresentationBridge(page), page.apply_button, 'activate')
        pump(app, lambda: page._queued is None and not page._working)
        assert (root / '.cdmw/virtual-loader/profile.json').read_bytes() == before
        assert not page.launch_button.isEnabled() and page.apply_button.isEnabled()
        assert page.progress.isHidden() and 'Ready to launch' not in page.status.text()
    finally:
        page.request_shutdown()
        controller.shutdown()
        page.close()


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
            assert page.apply_button.text() == localizer.translate('Apply profile')
            assert page.trace_button.text() == localizer.translate('Review startup trace…')
            assert page.launch_button.text() == localizer.translate('Launch game')
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
