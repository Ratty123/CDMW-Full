"""Focused proof for Mod Management read scheduling and Details performance."""
import io
import json
import os
import threading
import zipfile

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import pytest
from PySide6.QtCore import QEvent
from PySide6.QtWidgets import QApplication

from cdmw.domain.cancellation import raise_if_cancelled
from cdmw.domain.virtual_loader import VirtualSessionStatus
from cdmw.services import archive_overlay_manager as overlays
from cdmw.services.overlay_inventory_details import overlay_details
from cdmw.ui.tools.mod_management import ModManagementTab
from tests.test_mod_management import pump


def management_fixture(tmp_path, monkeypatch, runtime):
    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr('cdmw.services.virtual_loader_runtime.runtime_status', runtime)
    monkeypatch.setattr('cdmw.services.virtual_loader_state.load_profile', lambda *_: None)
    monkeypatch.setattr('cdmw.services.mod_management_inventory.mod_sources',
                        lambda *_args, **_kwargs: ({}, (), False))
    monkeypatch.setattr('cdmw.services.overlay_inventory_details.external_overlay_summary',
                        lambda *_args, **_kwargs: '')
    monkeypatch.setattr('cdmw.ui.tools.mod_management_overview.mounted_archive_status',
                        lambda *_args, **_kwargs: ())
    tab = ModManagementTab(get_package_root=lambda: str(tmp_path))
    return app, tab


def close_management(app, tab):
    tab.request_shutdown()
    pump(app, lambda: not tab.iter_shutdown_workers())
    tab.deleteLater()
    app.sendPostedEvents(None, QEvent.DeferredDelete)


def test_status_read_keeps_inventory_and_details_available(tmp_path, monkeypatch):
    inventory_started, inventory_release = threading.Event(), threading.Event()
    status_started, status_release = threading.Event(), threading.Event()
    inventory_stops, status_stops = [], []

    def read_inventory(_root, *, stop_event):
        inventory_stops.append(stop_event)
        inventory_started.set()
        assert inventory_release.wait(5)
        raise_if_cancelled(stop_event)
        return (overlays.InstalledOverlay('a', 'Alpha', (), '0041', 2, 1),)

    def runtime(_root, *, stop_event, **_kwargs):
        status_stops.append(stop_event)
        status_started.set()
        assert status_release.wait(5)
        raise_if_cancelled(stop_event)
        return VirtualSessionStatus('unavailable', 'Synthetic status')

    app, tab = management_fixture(tmp_path, monkeypatch, runtime)
    monkeypatch.setattr('cdmw.ui.new_item.overlay_manager_dialog.list_installed_overlays', read_inventory)
    try:
        tab.inventory.refresh()
        pump(app, inventory_started.is_set)
        tab.virtual_page.refresh()
        pump(app, status_started.is_set)
        tab.virtual_page.refresh()  # Same root coalesces while its read is active.
        assert not tab.controller.busy
        assert not inventory_stops[0].is_set()
        inventory_release.set()
        pump(app, lambda: len(tab.inventory._entries) == 1 and tab.virtual_page._sources is not None)
        page = tab.virtual_page
        assert page._status_reading and len(status_stops) == 1
        assert page.selection.isEnabled()
        page.selection.setCurrentItem(page.selection.topLevelItem(0))
        page._buttons()
        assert page.details_button.isEnabled()
        assert not page.apply_button.isEnabled() and not page.launch_button.isEnabled()
        assert page.cancel_button.isEnabled()
        status_release.set()
        pump(app, lambda: not page._status_reading)
        assert page._runtime.detail == 'Synthetic status'
        assert len(inventory_stops) == 1
    finally:
        inventory_release.set()
        status_release.set()
        close_management(app, tab)


def test_mutation_cancels_status_and_rechecks_after_completion(tmp_path, monkeypatch):
    status_started, status_release = threading.Event(), threading.Event()
    operation_started, operation_release = threading.Event(), threading.Event()
    stops = []

    def runtime(_root, *, stop_event, **_kwargs):
        stops.append(stop_event)
        if len(stops) == 1:
            status_started.set()
            assert status_release.wait(5)
            return VirtualSessionStatus('ready', 'Obsolete status')
        return VirtualSessionStatus('ready', 'Current status')

    app, tab = management_fixture(tmp_path, monkeypatch, runtime)
    try:
        page = tab.virtual_page
        page.refresh()
        pump(app, status_started.is_set)

        def operation(_log, _stop):
            operation_started.set()
            assert operation_release.wait(5)

        assert tab.controller._run('install', operation, lambda _: None, lambda message: pytest.fail(message))
        pump(app, operation_started.is_set)
        assert stops[0].is_set() and not page._status_reading
        status_release.set()
        pump(app, lambda: not page._status_lane.busy)
        assert page._runtime is None
        operation_release.set()
        pump(app, lambda: page._runtime is not None)
        assert page._runtime.detail == 'Current status' and len(stops) == 2
        assert page.status.text() != page.tr('Checking virtual loader…')
    finally:
        status_release.set()
        operation_release.set()
        close_management(app, tab)


@pytest.mark.parametrize('action', ['root', 'close', 'cancel'])
def test_obsolete_status_never_replaces_current_state(tmp_path, monkeypatch, action):
    entered, release = threading.Event(), threading.Event()
    stops = []

    def runtime(_root, *, stop_event, **_kwargs):
        stops.append(stop_event)
        if len(stops) == 1:
            entered.set()
            assert release.wait(5)
            return VirtualSessionStatus('ready', 'Obsolete status')
        return VirtualSessionStatus('ready', 'Replacement status')

    app, tab = management_fixture(tmp_path, monkeypatch, runtime)
    try:
        page = tab.virtual_page
        page.refresh()
        pump(app, entered.is_set)
        if action == 'root':
            page.set_game_root(tmp_path / 'new-root')
            page.refresh()
        elif action == 'close':
            tab.request_shutdown()
        else:
            page.cancel_button.click()
        assert stops[0].is_set()
        release.set()
        if action == 'root':
            pump(app, lambda: page._runtime is not None)
            assert page._runtime.detail == 'Replacement status'
        else:
            pump(app, lambda: not page._status_lane.busy)
            assert page._runtime is None
            if action == 'cancel':
                assert page.status.text() == page.tr('Processing stopped by user.')
                page.refresh()
                pump(app, lambda: page._runtime is not None)
                assert page._runtime.detail == 'Replacement status'
    finally:
        release.set()
        close_management(app, tab)


def test_status_failure_can_be_retried_without_blocking_the_operation_lane(tmp_path, monkeypatch):
    calls = []

    def runtime(_root, **_kwargs):
        calls.append(None)
        if len(calls) == 1:
            raise ValueError('Synthetic read failure')
        return VirtualSessionStatus('ready', 'Recovered status')

    app, tab = management_fixture(tmp_path, monkeypatch, runtime)
    try:
        page = tab.virtual_page
        page.refresh()
        pump(app, lambda: bool(page._error))
        assert page._error == 'Synthetic read failure' and not tab.controller.busy
        assert page.refresh_button.isEnabled()
        page.refresh()
        pump(app, lambda: page._runtime is not None)
        assert page._runtime.detail == 'Recovered status' and not page._error
    finally:
        close_management(app, tab)


def journal_fixture(tmp_path):
    changes = {
        'textures/example.dds': {'before': b'a' * (1024 * 1024), 'after': b'b' * (1024 * 1024), 'flags': 0},
        'models/new.pac': {'before': None, 'after': b'c' * (1024 * 1024), 'flags': 0},
    }
    state = {'format': overlays._FORMAT, 'directory': '0041', 'layers': [], 'sources': {}, 'published': {}}
    pending = {}
    layer = overlays._add_layer(state, pending, 'Synthetic overlay', changes)
    for relative, raw in pending.items():
        target = tmp_path / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(raw)
    (tmp_path / overlays.INDEX_PATH).write_bytes(overlays._inventory_bytes(state))
    return state, layer, changes


def replace_journal(tmp_path, state, layer, mutate):
    path = tmp_path / overlays.overlay_journal_path(layer)
    with zipfile.ZipFile(io.BytesIO(path.read_bytes())) as source:
        contents = {info.filename: source.read(info) for info in source.infolist()}
    mutate(contents)
    output = io.BytesIO()
    with zipfile.ZipFile(output, 'w', zipfile.ZIP_DEFLATED) as target:
        for name, data in contents.items():
            target.writestr(name, data)
    raw = output.getvalue()
    path.write_bytes(raw)
    layer['sha256'] = overlays._digest(raw)
    (tmp_path / overlays.INDEX_PATH).write_bytes(overlays._inventory_bytes(state))


def test_details_reads_metadata_without_inflating_payloads(tmp_path, monkeypatch):
    _state, layer, changes = journal_fixture(tmp_path)
    decoded = overlays._unpack_changes(tmp_path, layer, {}, None)
    assert all(decoded[path]['before'] == value['before'] and decoded[path]['after'] == value['after']
               for path, value in changes.items())
    calls = []
    original_read = zipfile.ZipFile.read

    def read(archive, name, *args, **kwargs):
        calls.append(name.filename if isinstance(name, zipfile.ZipInfo) else name)
        return original_read(archive, name, *args, **kwargs)

    monkeypatch.setattr(zipfile.ZipFile, 'read', read)
    text = overlay_details(tmp_path, layer['id'])
    assert 'Changed: textures/example.dds' in text and 'Added: models/new.pac' in text
    assert calls == ['changes.json']


def test_details_retains_the_whole_journal_digest_guard(tmp_path):
    _state, layer, _changes = journal_fixture(tmp_path)
    path = tmp_path / overlays.overlay_journal_path(layer)
    path.write_bytes(path.read_bytes() + b'changed')
    with pytest.raises(ValueError, match='journal.*changed'):
        overlay_details(tmp_path, layer['id'])


@pytest.mark.parametrize('field,value,match', [
    ('path', '../escaped.dds', 'Invalid overlay path'),
    ('flags', 256, 'Invalid archive storage flags'),
    ('after', 'bad', 'Invalid overlay payload checksum'),
])
def test_details_validates_journal_metadata(tmp_path, field, value, match):
    state, layer, _changes = journal_fixture(tmp_path)

    def mutate(contents):
        metadata = json.loads(contents['changes.json'])
        metadata['files'][0][field] = value
        contents['changes.json'] = json.dumps(metadata).encode()

    replace_journal(tmp_path, state, layer, mutate)
    with pytest.raises(ValueError, match=match):
        overlay_details(tmp_path, layer['id'])


def test_details_checks_zip_members_and_declared_payload_bounds(tmp_path, monkeypatch):
    state, layer, _changes = journal_fixture(tmp_path)
    path = tmp_path / overlays.overlay_journal_path(layer)
    monkeypatch.setattr(overlays, '_MAX_JOURNAL_BYTES', path.stat().st_size + 1)
    with pytest.raises(ValueError, match='payloads exceed'):
        overlay_details(tmp_path, layer['id'])
    monkeypatch.undo()
    replace_journal(tmp_path, state, layer,
                    lambda contents: contents.pop(next(name for name in contents if name.startswith('payloads/'))))
    with pytest.raises(KeyError):
        overlay_details(tmp_path, layer['id'])


def test_full_journal_decode_still_checks_every_payload_digest(tmp_path):
    state, layer, _changes = journal_fixture(tmp_path)

    def mutate(contents):
        name = next(name for name in contents if name.startswith('payloads/'))
        contents[name] = b'wrong-payload'

    replace_journal(tmp_path, state, layer, mutate)
    with pytest.raises(ValueError, match='payload failed its checksum'):
        overlays._unpack_changes(tmp_path, layer, {}, None)


@pytest.mark.parametrize('action', ['cancel', 'failure', 'root'])
def test_incomplete_status_cannot_reenable_old_apply_or_launch_state(tmp_path, monkeypatch, action):
    entered, release = threading.Event(), threading.Event()
    calls = []

    def runtime(_root, *, stop_event, **_kwargs):
        calls.append(stop_event)
        if len(calls) == 2:
            entered.set()
            assert release.wait(5)
            if action == 'failure':
                raise ValueError('Synthetic refresh failure')
            return VirtualSessionStatus('ready', 'Obsolete status')
        return VirtualSessionStatus('ready', 'Current status')

    app, tab = management_fixture(tmp_path, monkeypatch, runtime)
    try:
        page = tab.virtual_page
        page.refresh()
        pump(app, lambda: page._status_current)
        page._append_selection('item', (tmp_path / 'fixture.cditem',))
        assert page.apply_button.isEnabled()
        page.refresh()
        pump(app, entered.is_set)
        if action == 'cancel':
            page.cancel_button.click()
        elif action == 'root':
            page.set_game_root(tmp_path / 'other-installation')
        release.set()
        pump(app, lambda: not page._status_reading and not page._status_lane.busy)
        assert not page._status_current
        page._buttons()
        assert not page.apply_button.isEnabled()
        # Retained ordinary-launch state also must not bypass the new read gate.
        page.selection.clear()
        page._draft_loaded = True
        page._saved_selection = None
        page._sources = ({}, (), True)
        page._buttons()
        assert not page.launch_button.isEnabled()
        assert page.refresh_button.isEnabled()
        page.refresh()
        pump(app, lambda: page._status_current)
        assert page._runtime.detail == 'Current status'
    finally:
        release.set()
        close_management(app, tab)


@pytest.mark.parametrize('terminal_state', ['stopped', 'blocked'])
def test_runtime_recheck_waits_for_session_and_preserves_its_result(tmp_path, monkeypatch, terminal_state):
    calls, phase = [], ['starting']

    def runtime(_root, **_kwargs):
        calls.append(None)
        return VirtualSessionStatus('blocked', 'Underlying runtime status')

    def session_status(*_args, **_kwargs):
        if phase[0] == 'starting':
            return VirtualSessionStatus('starting', 'Owned session is starting', progress=37)
        return VirtualSessionStatus(terminal_state, 'Owned terminal session result')

    app, tab = management_fixture(tmp_path, monkeypatch, runtime)
    monkeypatch.setattr('cdmw.services.virtual_loader_runtime.session_status', session_status)
    try:
        page = tab.virtual_page
        page.refresh()
        pump(app, lambda: page._status_current)
        assert len(calls) == 1
        assert page._run(lambda _log, _stop: VirtualSessionStatus('starting', 'owned-session', pid=123),
                         page._started)
        pump(app, lambda: not tab.controller.busy and not page._session_lookup.busy
             and page.status.text() == 'Owned session is starting')
        page._session_timer.stop()
        page.refresh()  # An explicit request during the session also waits.
        app.processEvents()
        assert page._session and page._status_pending and not page._status_reading
        assert len(calls) == 1
        assert page.status.text() == 'Owned session is starting'
        assert not page.progress.isHidden() and page.progress.value() == 37
        phase[0] = terminal_state
        page._poll_session()
        pump(app, lambda: page._session is None and page._status_current)
        assert len(calls) == 2 and page._runtime.detail == 'Underlying runtime status'
        assert page.status.text() == 'Owned terminal session result'
        assert page.progress.isHidden()
        page.refresh()
        pump(app, lambda: page._status_current and not page._status_reading)
        assert len(calls) == 3 and page.status.text() == 'Underlying runtime status'
    finally:
        close_management(app, tab)


@pytest.mark.parametrize('operation_outcome', ['failure', 'cancel'])
@pytest.mark.parametrize('read_fails', [False, True])
def test_background_recheck_preserves_operation_failure_or_cancellation(
        tmp_path, monkeypatch, operation_outcome, read_fails):
    calls, completed = [], []
    entered, release = threading.Event(), threading.Event()

    def runtime(_root, **_kwargs):
        calls.append(None)
        if len(calls) == 2 and read_fails:
            raise ValueError('Background runtime read failed')
        return VirtualSessionStatus('blocked', 'Underlying runtime status')

    app, tab = management_fixture(tmp_path, monkeypatch, runtime)
    try:
        page = tab.virtual_page
        page.refresh()
        pump(app, lambda: page._status_current)

        def operation(_log, _progress, stop):
            entered.set()
            assert release.wait(5)
            raise_if_cancelled(stop)
            raise ValueError('Owned operation failure')

        assert page._run(operation, completed.append, with_progress=True)
        pump(app, entered.is_set)
        if operation_outcome == 'cancel':
            page.cancel_button.click()
        release.set()
        pump(app, lambda: not tab.controller.busy and len(calls) == 2
             and not page._status_reading and not page._status_lane.busy)
        expected = 'Owned operation failure' if operation_outcome == 'failure' else page.tr('Processing stopped by user.')
        assert not completed and page.status.text() == expected
        assert page.progress.isHidden()
        if operation_outcome == 'failure':
            assert page._error == expected
        assert page._status_current is not read_fails
        if read_fails:
            assert not page.apply_button.isEnabled() and not page.launch_button.isEnabled()
        page.refresh()
        pump(app, lambda: page._status_current and not page._status_reading)
        assert len(calls) == 3
        assert page.status.text() == 'Underlying runtime status' and not page._error
    finally:
        release.set()
        close_management(app, tab)
