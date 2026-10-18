"""Exact, bounded rollback for supported CDMW test setup on owned fixtures."""
import os

import pytest

from cdmw.domain.virtual_loader import VirtualLoaderError
from cdmw.services import cditem_device_installation as device


@pytest.fixture
def recovery(tmp_path, monkeypatch):
    monkeypatch.setattr(device, '_native_processes', lambda: [(os.getpid(), 0, 'python.exe')])
    root = tmp_path / 'game'
    proposed = {}
    for index, name in enumerate(device.FILES):
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b'original-' + bytes([index]))
        proposed[name] = b'proposed-' + bytes([index])
    context = device.prepare_installation_recovery(root, tmp_path / 'recovery',
        run_id='fixture-run-123', proposed=proposed)
    return root, context, proposed


def apply(root, proposed):
    for name, raw in proposed.items():
        (root / name).write_bytes(raw)


def test_prepare_is_readonly_and_exact_restore_preserves_original_metadata(recovery):
    root, context, proposed = recovery
    before = {name: ((root/name).read_bytes(), (root/name).stat().st_mtime_ns) for name in device.FILES}
    assert device.verify_installation_recovery(context)['phase'] == 'prepared'
    apply(root, proposed)
    device.seal_installation_recovery(context)
    assert device.restore_installation_recovery(context)['phase'] == 'restored'
    assert {name: ((root/name).read_bytes(), (root/name).stat().st_mtime_ns) for name in device.FILES} == before
    assert device.restore_installation_recovery(context)['phase'] == 'restored'


def test_changed_last_target_refuses_before_restoring_any_file(recovery):
    root, context, proposed = recovery
    apply(root, proposed)
    last = device.FILES[-1]
    (root/last).write_bytes(b'foreign user update')
    with pytest.raises(VirtualLoaderError, match='outside this run'):
        device.restore_installation_recovery(context)
    assert all((root/name).read_bytes() == raw for name, raw in proposed.items() if name != last)
    assert (root/last).read_bytes() == b'foreign user update'


def test_recognized_setup_interruption_can_restore_before_seal(recovery):
    root, context, proposed = recovery
    first = device.FILES[0]
    (root/first).write_bytes(proposed[first])
    device.restore_installation_recovery(context)
    assert all((root/name).read_bytes() == b'original-' + bytes([index]) for index, name in enumerate(device.FILES))


def test_restore_interruption_recovers_known_partial_state(recovery, monkeypatch):
    root, context, proposed = recovery
    apply(root, proposed)
    original = device.atomic_write_bytes
    failed = False
    def fail_second(path, raw):
        nonlocal failed
        if path == root/device.FILES[1] and not failed:
            failed = True
            raise OSError('simulated write failure')
        return original(path, raw)
    monkeypatch.setattr(device, 'atomic_write_bytes', fail_second)
    with pytest.raises(OSError, match='simulated'):
        device.restore_installation_recovery(context)
    assert device.verify_installation_recovery(context)['phase'] == 'restoring'
    assert device.restore_installation_recovery(context)['phase'] == 'restored'


@pytest.mark.parametrize('relative', ['manifest.json', 'before/0', 'after/0', 'journal.json'])
def test_tampered_recovery_never_changes_installed_state(recovery, relative):
    root, context, proposed = recovery
    apply(root, proposed)
    (context.directory/relative).write_bytes(b'tampered')
    with pytest.raises((VirtualLoaderError, ValueError)):
        device.restore_installation_recovery(context)
    assert all((root/name).read_bytes() == raw for name, raw in proposed.items())


def test_seal_refuses_partial_or_different_supported_output(recovery):
    _, context, _ = recovery
    with pytest.raises(VirtualLoaderError, match='exact reviewed'):
        device.seal_installation_recovery(context)


def test_live_game_or_pending_profile_journal_refuses_restore(recovery, monkeypatch):
    root, context, proposed = recovery
    apply(root, proposed)
    monkeypatch.setattr(device, '_native_processes', lambda: [(os.getpid(), 0, 'python.exe'), (1, 0, 'CrimsonDesert.exe')])
    with pytest.raises(VirtualLoaderError, match='Settle the game'):
        device.restore_installation_recovery(context)
    monkeypatch.setattr(device, '_native_processes', lambda: [(os.getpid(), 0, 'python.exe')])
    (root/'.cdmw/virtual-loader/transaction.json').write_bytes(b'pending')
    with pytest.raises(VirtualLoaderError, match='interrupted virtual profile transaction'):
        device.restore_installation_recovery(context)
    assert all((root/name).read_bytes() == raw for name, raw in proposed.items())


def test_target_set_cannot_expand_to_archives(recovery, tmp_path):
    root, _, proposed = recovery
    proposed['0000/0.pamt'] = b'not permitted'
    with pytest.raises(VirtualLoaderError, match='Invalid exact'):
        device.prepare_installation_recovery(root, tmp_path/'other', run_id='fixture-run-234', proposed=proposed)
    assert not (root/'0000/0.pamt').exists()


def test_recovery_storage_cannot_overlap_installation(recovery):
    root, _, proposed = recovery
    with pytest.raises(VirtualLoaderError, match='Invalid exact'):
        device.prepare_installation_recovery(root, root/'recovery', run_id='fixture-run-234', proposed=proposed)


def test_unavailable_native_census_never_restores(recovery, monkeypatch):
    root, context, proposed = recovery
    apply(root, proposed)
    def unavailable():
        raise VirtualLoaderError('native census unavailable')
    monkeypatch.setattr(device, '_native_processes', unavailable)
    with pytest.raises(VirtualLoaderError, match='census unavailable'):
        device.restore_installation_recovery(context)
    assert all((root/name).read_bytes() == raw for name, raw in proposed.items())


@pytest.mark.parametrize('name', ['CrimsonDesert.exe', 'CDMW_VIRTUAL_SESSION.EXE', 'a'*64+'.exe'])
def test_live_native_session_candidates_refuse(recovery, monkeypatch, name):
    _, context, _ = recovery
    monkeypatch.setattr(device, '_native_processes', lambda: [(os.getpid(), 0, 'python.exe'), (12, 1, name)])
    with pytest.raises(VirtualLoaderError, match='Settle the game'):
        device.restore_installation_recovery(context)


def test_completed_old_context_cannot_rollback_later_identical_setup(recovery, tmp_path):
    root, old, proposed = recovery
    apply(root, proposed)
    device.seal_installation_recovery(old)
    device.restore_installation_recovery(old)
    current = device.prepare_installation_recovery(root, tmp_path/'later-recovery',
        run_id='fixture-run-later', proposed=proposed)
    apply(root, proposed)
    device.seal_installation_recovery(current)
    old_journal = (old.directory/'journal.json').read_bytes()
    with pytest.raises(VirtualLoaderError, match='earlier run'):
        device.restore_installation_recovery(old)
    with pytest.raises(VirtualLoaderError, match='cannot be reopened'):
        device.seal_installation_recovery(old)
    assert (old.directory/'journal.json').read_bytes() == old_journal
    assert all((root/name).read_bytes() == raw for name, raw in proposed.items())
    assert device.restore_installation_recovery(current)['phase'] == 'restored'
