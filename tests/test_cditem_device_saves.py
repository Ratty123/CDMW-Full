"""Disposable-save exchange/recovery contracts on independently owned fixtures."""
import json
import os
from pathlib import Path
import subprocess
import threading

import pytest

from cdmw.domain.cancellation import RunCancelled
from cdmw.domain.virtual_loader import VirtualLoaderError
from cdmw.services import cditem_device_saves as device


def quiet():
    return {'processes': [], 'writers': [], 'evidence': 'Exclusive ownership of offline fixture.'}


def put(root, name, content):
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return path


@pytest.fixture
def inputs(tmp_path, monkeypatch):
    monkeypatch.setenv('LOCALAPPDATA', str(tmp_path / 'actual-live-location'))
    root, test = tmp_path / 'offline-save', tmp_path / 'disposable-input'
    put(root, 'account/slot1/save.save', b'original progress')
    put(root, 'account/slot1/lobby.save', b'original lobby')
    put(root, 'user_input.save', b'original shared settings')
    (root / 'account/empty-slot').mkdir()
    put(test, 'account/slot1/save.save', b'disposable progress')
    put(test, 'account/slot1/lobby.save', b'disposable lobby')
    put(test, 'user_input.save', b'disposable settings')
    return root, test, tmp_path / 'run'


def prepare(inputs, **kwargs):
    return device.prepare_offline_context(*inputs, quiescence=quiet, **kwargs)


def test_whole_tree_exchange_output_and_exact_restore_keep_independent_copies(inputs):
    root, test, run = inputs
    original = device.snapshot_offline_root(root)
    intended = device.snapshot_offline_root(test)
    context = prepare(inputs)
    assert device.snapshot_offline_root(root) == original
    assert device.snapshot_offline_root(run / 'original') == original
    assert not os.path.samefile(root / 'user_input.save', run / 'original/user_input.save')
    assert device.inspect_offline_context(context)['live_ready'] is False
    device.exchange_offline_context(context, quiescence=quiet)
    assert device.snapshot_offline_root(root) == intended
    put(root, 'account/slot0/save.save', b'post attempt autosave')
    put(root, 'account/slot0/lobby.save', b'post attempt lobby')
    put(root, 'user_input.save', b'post attempt settings')
    post_attempt = device.snapshot_offline_root(root)
    output = device.retain_offline_outputs(context, post_attempt, quiescence=quiet)
    assert device.snapshot_offline_root(output) == post_attempt
    assert not os.path.samefile(root / 'user_input.save', output / 'user_input.save')
    device.restore_offline_context(context, quiescence=quiet)
    assert device.snapshot_offline_root(root) == original
    assert (root / 'account/empty-slot').is_dir()
    assert not (root / 'account/slot0').exists()
    assert device.snapshot_offline_root(output) == post_attempt
    assert device.snapshot_offline_root(run / 'original') == original
    assert device.snapshot_offline_root(run / 'input') == intended
    journal = json.loads((run / 'journal.json').read_bytes())
    assert journal['phase'] == 'restored'
    assert journal['observed'] == original
    assert journal['expected_current'] == post_attempt


def test_initially_absent_root_is_absent_after_restore(inputs):
    _root, test, run = inputs
    root = run.parent / 'initially-absent'
    context = prepare((root, test, run))
    assert not root.exists()
    device.exchange_offline_context(context, quiescence=quiet)
    assert root.is_dir()
    device.restore_offline_context(context, quiescence=quiet)
    assert not root.exists()
    assert (run / 'parked-test/account/slot1/save.save').read_bytes() == b'disposable progress'


@pytest.mark.parametrize('condition', ['new-file', 'same-size', 'mtime', 'backup', 'unknown-parked'])
def test_exchange_refuses_stale_or_unknown_state_without_touching_fixture(inputs, condition):
    root, _test, run = inputs
    context = prepare(inputs)
    if condition == 'new-file':
        put(root, 'account/slot0/save.save', b'unexpected autosave')
    elif condition == 'same-size':
        path = root / 'account/slot1/save.save'
        stamp = path.stat()
        path.write_bytes(b'concurrent change')
        os.utime(path, ns=(stamp.st_atime_ns, stamp.st_mtime_ns))
    elif condition == 'mtime':
        path = root / 'user_input.save'
        stamp = path.stat()
        os.utime(path, ns=(stamp.st_atime_ns, stamp.st_mtime_ns + 1_000_000_000))
    elif condition == 'backup':
        (run / 'original/user_input.save').write_bytes(b'tampered backup')
    else:
        (run / 'parked-original').mkdir()
    unchanged = device.snapshot_offline_root(root)
    with pytest.raises(VirtualLoaderError, match='Unexpected'):
        device.exchange_offline_context(context, quiescence=quiet)
    assert device.snapshot_offline_root(root) == unchanged
    assert device.inspect_offline_context(context)['phase'] == 'prepared'


def test_restore_refuses_unknown_writes_and_does_not_discard_them(inputs):
    root, _test, run = inputs
    context = prepare(inputs)
    device.exchange_offline_context(context, quiescence=quiet)
    put(root, 'unobserved.save', b'unknown writer')
    unchanged = device.snapshot_offline_root(root)
    with pytest.raises(VirtualLoaderError, match='Unexpected'):
        device.restore_offline_context(context, quiescence=quiet)
    with pytest.raises(VirtualLoaderError, match='Unknown concurrent'):
        device.recover_offline_context(context, quiescence=quiet)
    assert device.snapshot_offline_root(root) == unchanged
    assert (run / 'original/user_input.save').read_bytes() == b'original shared settings'


def test_durable_ownership_refuses_second_identical_context_until_recovery(inputs):
    root, test, run = inputs
    first = prepare(inputs)
    second_inputs = (root, test, run.parent / 'second-run')
    second = prepare(second_inputs)
    device.exchange_offline_context(first, quiescence=quiet)
    with pytest.raises(VirtualLoaderError, match='active owned save context'):
        device.exchange_offline_context(second, quiescence=quiet)
    with pytest.raises(VirtualLoaderError, match='active owned save context'):
        prepare((root, test, run.parent / 'third-run'))
    with pytest.raises(VirtualLoaderError, match='active owned save context'):
        device.recover_offline_context(second, quiescence=quiet)
    device.recover_offline_context(first, quiescence=quiet)
    device.exchange_offline_context(second, quiescence=quiet)
    device.restore_offline_context(second, quiescence=quiet)


def test_missing_ownership_or_changed_retained_output_refuses_restore(inputs):
    root, _test, run = inputs
    context = prepare(inputs)
    device.exchange_offline_context(context, quiescence=quiet)
    observed = device.snapshot_offline_root(root)
    output = device.retain_offline_outputs(context, observed, quiescence=quiet)
    (output / 'user_input.save').write_bytes(b'changed retained output')
    with pytest.raises(VirtualLoaderError, match='Unexpected'):
        device.restore_offline_context(context, quiescence=quiet)
    assert device.snapshot_offline_root(root) == observed
    device._owner_path(root).unlink()
    with pytest.raises(VirtualLoaderError, match='ownership record is missing'):
        device.restore_offline_context(context, quiescence=quiet)
    assert device.snapshot_offline_root(root) == observed


def test_restore_checks_writer_quiescence_before_reading_consistent_snapshots(inputs, monkeypatch):
    context = prepare(inputs)
    device.exchange_offline_context(context, quiescence=quiet)
    checked = []
    expect = device._expect

    def check():
        checked.append(True)
        return quiet()

    def guarded_expect(*args, **kwargs):
        assert checked, 'Writer inventory must be checked before a restoration snapshot.'
        return expect(*args, **kwargs)

    monkeypatch.setattr(device, '_expect', guarded_expect)
    device.restore_offline_context(context, quiescence=check)


@pytest.mark.parametrize('phase', ['exchange-first', 'exchange-second', 'restore-first', 'restore-second'])
def test_interrupted_rename_is_recovered_after_a_new_service_instance(inputs, monkeypatch, phase):
    root, _test, run = inputs
    original = device.snapshot_offline_root(root)
    context = prepare(inputs)
    rename = Path.rename
    count = 0
    if phase.startswith('restore'):
        device.exchange_offline_context(context, quiescence=quiet)
    fail_at = 1 if phase.endswith('first') else 2

    def interrupted(path, destination):
        nonlocal count
        result = rename(path, destination)
        count += 1
        if count == fail_at:
            raise OSError('simulated interpreter termination after rename')
        return result

    monkeypatch.setattr(Path, 'rename', interrupted)
    action = device.restore_offline_context if phase.startswith('restore') else device.exchange_offline_context
    with pytest.raises(OSError, match='interpreter termination'):
        action(context, quiescence=quiet)
    monkeypatch.setattr(Path, 'rename', rename)
    restarted = device.OfflineSaveContext(run, context.manifest_sha256)
    result = device.recover_offline_context(restarted, quiescence=quiet)
    assert result['phase'] == 'restored'
    assert device.snapshot_offline_root(root) == original
    assert device.snapshot_offline_root(run / 'original') == original


@pytest.mark.parametrize('action', ['exchange', 'restore', 'recover'])
@pytest.mark.parametrize('busy', ['processes', 'writers'])
def test_busy_process_or_writer_is_refused_before_changes(inputs, action, busy):
    root, _test, _run = inputs
    context = prepare(inputs)
    if action == 'restore':
        device.exchange_offline_context(context, quiescence=quiet)
    before = device.snapshot_offline_root(root)
    def not_quiet():
        return {**quiet(), busy: [{'pid': 77, 'creation_time': 'fixture-birth'}]}
    function = getattr(device, action + '_offline_context')
    with pytest.raises(VirtualLoaderError, match='process/writer'):
        function(context, quiescence=not_quiet)
    assert device.snapshot_offline_root(root) == before


@pytest.mark.parametrize('stage', ['prepare', 'exchange', 'restore'])
def test_cancellation_preserves_current_tree_and_retained_recovery(inputs, stage):
    root, _test, _run = inputs
    stop = threading.Event()
    context = None if stage == 'prepare' else prepare(inputs)
    if stage == 'restore':
        device.exchange_offline_context(context, quiescence=quiet)
    before = device.snapshot_offline_root(root)
    stop.set()
    with pytest.raises(RunCancelled):
        if stage == 'prepare':
            prepare(inputs, stop_event=stop)
        else:
            getattr(device, stage + '_offline_context')(context, quiescence=quiet, stop_event=stop)
    assert device.snapshot_offline_root(root) == before


def test_live_root_and_its_ancestors_are_refused(inputs):
    root, test, run = inputs
    live = device.saves.save_root()
    put(live, 'account/slot1/save.save', b'live player data')
    for path in (live, live.parent, live / 'account'):
        with pytest.raises(VirtualLoaderError, match='live save tree'):
            prepare((path, test, run))
    with pytest.raises(VirtualLoaderError, match='live save tree'):
        prepare((root, live, run))
    assert (live / 'account/slot1/save.save').read_bytes() == b'live player data'


def test_extended_windows_live_path_cannot_bypass_offline_guard(inputs):
    if os.name != 'nt':
        return
    _root, test, run = inputs
    live = device.saves.save_root()
    put(live, 'account/slot1/save.save', b'live player data')
    extended = Path('\\\\?\\' + str(live))
    assert os.path.samefile(live, extended)
    with pytest.raises(VirtualLoaderError, match='device paths|live save tree'):
        prepare((extended, test, run))
    assert (live / 'account/slot1/save.save').read_bytes() == b'live player data'


def test_windows_short_path_uses_canonical_live_identity(inputs, monkeypatch):
    if os.name != 'nt':
        return
    import ctypes
    _root, test, run = inputs
    live = run.parent / 'actual live save fixture'
    put(live, 'slot/save.save', b'live player data')
    monkeypatch.setattr(device.saves, 'save_root', lambda: live)
    function = ctypes.WinDLL('kernel32', use_last_error=True).GetShortPathNameW
    function.argtypes = [ctypes.c_wchar_p, ctypes.c_wchar_p, ctypes.c_uint32]
    function.restype = ctypes.c_uint32
    output = ctypes.create_unicode_buffer(32768)
    assert function(str(live), output, len(output)) > 0
    alias = Path(output.value)
    assert os.path.samefile(alias, live)
    assert device._absolute(alias) == device._absolute(live)
    with pytest.raises(VirtualLoaderError, match='live save tree'):
        prepare((alias, test, run))


def test_interrupted_owner_claim_before_publish_recovers_original(inputs, monkeypatch):
    root, _test, run = inputs
    context = prepare(inputs)
    original = device.snapshot_offline_root(root)
    publish = device.atomic_write_bytes
    def fail_claim(path, content):
        if Path(path) == device._owner_path(root):
            raise RuntimeError('interrupted before owner publication')
        return publish(path, content)
    monkeypatch.setattr(device, 'atomic_write_bytes', fail_claim)
    with pytest.raises(RuntimeError, match='owner publication'):
        device.exchange_offline_context(context, quiescence=quiet)
    assert not device._owner_path(root).exists()
    assert device.snapshot_offline_root(root) == original
    monkeypatch.setattr(device, 'atomic_write_bytes', publish)
    assert device.recover_offline_context(context, quiescence=quiet)['phase'] == 'restored'
    assert device.snapshot_offline_root(root) == original


def test_linked_or_hardlinked_fixture_is_refused(inputs):
    root, _test, _run = inputs
    os.link(root / 'user_input.save', root / 'hardlink.save')
    with pytest.raises(VirtualLoaderError, match='hard links'):
        prepare(inputs)


def test_junction_fixture_is_refused(inputs, tmp_path):
    root, _test, _run = inputs
    outside = tmp_path / 'outside'
    outside.mkdir()
    link = root / 'linked-folder'
    if os.name == 'nt':
        result = subprocess.run(['cmd', '/c', 'mklink', '/J', str(link), str(outside)],
                                capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW)
        assert result.returncode == 0, result.stderr
    else:
        link.symlink_to(outside, target_is_directory=True)
    with pytest.raises(VirtualLoaderError, match='linked'):
        prepare(inputs)
