"""Actual immutable receipt lifecycle on owned fixtures, without launching a game."""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
import json
import os
from pathlib import Path
import shutil
import subprocess
import threading
from types import SimpleNamespace

import pytest

from cdmw.domain.cancellation import RunCancelled
from cdmw.domain.virtual_loader import VirtualLoaderError
from cdmw.domain.virtual_session_receipt import CLAIMS, inspect_receipt
from cdmw.services import virtual_loader_receipts as receipts, virtual_loader_runtime as runtime
from cdmw.services import virtual_loader_saves as saves
from cdmw.services.independent_item_package import canonical, digest
from tests.test_virtual_loader import game_bytes
from tests.test_virtual_loader_saves import experimental_fixture


def prepared(tmp_path, monkeypatch, *, two=False):
    root, files, save = experimental_fixture(tmp_path, monkeypatch)
    if two:
        save.with_name('second.save').write_bytes(b'second selected member')
    review = runtime.prepare_experimental_launch(root)
    assert not review.diagnostics, review.diagnostics
    return root, files, save, review


def start(root, review, monkeypatch, *, stop=None, fail=False):
    calls = []
    def spawn(command, **kwargs):
        calls.append((command, kwargs))
        if fail:
            raise OSError('injected spawn failure')
        if stop is not None:
            stop.set()
        return SimpleNamespace(pid=123)
    monkeypatch.setattr(runtime.subprocess, 'Popen', spawn)
    return runtime.launch_experimental(review, confirmed=True, stop_event=stop), calls


def report(root, token, state, *, pid=456, **extra):
    path = root / '.cdmw/virtual-loader' / ('session-' + token + '.json')
    path.write_bytes(canonical({'state': state, 'pid': pid, **extra}))
    return path


def last(root, token):
    return receipts.read_session_receipts(root, token)[-1]


def test_actual_backup_receipt_pins_verified_files_and_preserves_unknown_origin(tmp_path, monkeypatch):
    root, _files, save, review = prepared(tmp_path, monkeypatch)
    chain = receipts.read_session_receipts(root, review.receipt_token)
    assert [row.to_dict()['event'] for row in chain] == ['begin', 'backup-verified']
    value = chain[-1].to_dict()
    name = digest(b'account/slot1/save.save')
    assert value['selected'] == [name]
    assert value['before']['files'][name] == {'size': save.stat().st_size, 'sha256': digest(save.read_bytes())}
    assert value['backup']['backup_id'] == review.backup.directory.name
    assert value['backup']['manifest_sha256'] == review.backup.manifest_sha256
    assert value['backup']['status'] == 'verified'
    assert value['slot_layout_sha256'] is None and value['membership_complete'] is False
    assert value['proposed']['profile_sha256'] == review.plan.manifest_sha256
    assert value['proposed']['runtime']['host'] is None
    inspected = inspect_receipt(chain[-1])
    assert inspected['claims'] == CLAIMS
    assert inspected['file_effect']['classification'] == 'unobserved'
    assert inspected['parent_save_set_sha256'] is None
    assert inspected['producer_witness'] is None
    assert inspected['decision']['status'] == 'unknown'


def test_actual_launch_uses_receipt_token_and_keeps_success_after_late_cancel(tmp_path, monkeypatch):
    root, _files, save, review = prepared(tmp_path, monkeypatch)
    before, backup = game_bytes(root), review.backup.directory
    stop = threading.Event()
    result, calls = start(root, review, monkeypatch, stop=stop)
    assert stop.is_set() and result.state == 'starting' and result.pid == 123
    assert result.detail == review.receipt_token and not result.diagnostics
    assert calls and '--controlled-probe' in calls[0][0]
    manifest = Path(calls[0][0][1]).read_bytes()
    assert result.detail.encode('utf-16le') in manifest
    value = last(root, result.detail).to_dict()
    assert value['event'] == 'launch-started' and value['process']['host_pid'] == 123
    assert value['process']['expected_session_token'] == result.detail
    assert value['process']['observed_session_token'] is None
    assert value['process']['birth_sha256'] is None and value['process']['image_sha256'] is None
    assert value['proposed']['runtime']['host'] == digest(b'fixture host')
    assert Path(result.receipt_path).read_bytes() == last(root, result.detail).data
    assert backup.is_dir() and save.read_bytes() == b'unchanged player progress'
    assert game_bytes(root) == before


@pytest.mark.parametrize('fault', ['begin', 'backup', 'launch'])
def test_receipt_failure_is_diagnostic_and_does_not_erase_launched_outcome(tmp_path, monkeypatch, fault):
    root, _files, _save = experimental_fixture(tmp_path, monkeypatch)
    def fail(*args, **kwargs):
        raise OSError('injected receipt storage failure')
    monkeypatch.setattr(receipts, {'begin': 'begin_attempt', 'backup': 'record_backup', 'launch': 'record_launch'}[fault], fail)
    review = runtime.prepare_experimental_launch(root)
    result, calls = start(root, review, monkeypatch)
    assert calls and result.state == 'starting'
    assert 'injected receipt storage failure' in ' '.join(result.diagnostics)
    assert result.detail and (root / '.cdmw/virtual-loader/launches' / (result.detail + '.bin')).is_file()
    assert review.backup.directory.is_dir()
    assert runtime.GAME_REDIRECTION_APPROVED is False


@pytest.mark.parametrize('fault', ['spawn', 'save', 'cancel'])
def test_failed_or_cancelled_launch_retains_backup_and_attempt(tmp_path, monkeypatch, fault):
    root, _files, save, review = prepared(tmp_path, monkeypatch)
    if fault == 'spawn':
        with pytest.raises(OSError, match='spawn failure'):
            start(root, review, monkeypatch, fail=True)
    elif fault == 'save':
        save.write_bytes(b'changed save after review')
        with pytest.raises(VirtualLoaderError, match='saved game changed'):
            runtime.launch_experimental(review, confirmed=True)
    else:
        stop = threading.Event()
        stop.set()
        with pytest.raises(RunCancelled):
            runtime.launch_experimental(review, confirmed=True, stop_event=stop)
    chain = receipts.read_session_receipts(root, review.receipt_token)
    assert chain[-1].to_dict()['terminal'] == ('interrupted' if fault == 'cancel' else 'failed')
    assert chain[-1].to_dict()['claims'] == CLAIMS
    assert chain[-1].to_dict()['after'] is None
    assert review.backup.directory.is_dir()
    assert (review.backup.directory / 'files/account/slot1/save.save').read_bytes() == b'unchanged player progress'


def test_cancelled_backup_retains_an_interrupted_receipt_without_partial_backup(tmp_path, monkeypatch):
    root, _files, _save = experimental_fixture(tmp_path, monkeypatch)
    copy, stop = saves._copy, threading.Event()
    def interrupted(*args):
        result = copy(*args)
        stop.set()
        return result
    monkeypatch.setattr(saves, '_copy', interrupted)
    with pytest.raises(RunCancelled):
        runtime.prepare_experimental_launch(root, stop_event=stop)
    attempts = list((root / receipts.RECEIPT_PATH).iterdir())
    assert len(attempts) == 1
    value = last(root, attempts[0].name).to_dict()
    assert value['terminal'] == 'interrupted' and value['backup']['status'] == 'failed'
    assert not list((root / saves.BACKUP_PATH).iterdir())


def test_progress_polls_do_not_hash_saves_or_grow_receipts_and_terminal_hashes_once(tmp_path, monkeypatch):
    root, _files, _save, review = prepared(tmp_path, monkeypatch)
    result, _calls = start(root, review, monkeypatch)
    monkeypatch.setattr(runtime, '_process_alive', lambda pid: True)
    observed, original = [], receipts.observe_files
    def observe(*args, **kwargs):
        observed.append(args)
        return original(*args, **kwargs)
    monkeypatch.setattr(receipts, 'observe_files', observe)
    for progress in range(10):
        report(root, result.detail, 'starting', pid=0, host_pid=123, progress=progress)
        runtime.session_status(root, result.detail, host_pid=123)
    report(root, result.detail, 'running')
    runtime.session_status(root, result.detail, host_pid=123)
    count = len(receipts.read_session_receipts(root, result.detail))
    for _ in range(5):
        runtime.session_status(root, result.detail, host_pid=123)
    assert not observed and len(receipts.read_session_receipts(root, result.detail)) == count
    report(root, result.detail, 'stopped')
    final = runtime.session_status(root, result.detail, host_pid=123)
    assert final.state == 'stopped' and not final.diagnostics
    assert len(observed) == 1
    runtime.session_status(root, result.detail, host_pid=123)
    assert len(observed) == 1 and len(receipts.read_session_receipts(root, result.detail)) == count + 1


@pytest.mark.parametrize('change,classification', [
    ('unchanged', 'unchanged'), ('all', 'changed'), ('one', 'partially-changed'),
    ('missing', 'missing'), ('read-error', 'unknown'), ('autosave', 'unchanged'),
])
def test_terminal_observation_distinguishes_file_effects_from_save_claims(tmp_path, monkeypatch, change, classification):
    root, _files, save, review = prepared(tmp_path, monkeypatch, two=True)
    result, _calls = start(root, review, monkeypatch)
    if change in ('all', 'one'):
        stamp = save.stat()
        save.write_bytes(b'changed   player progress')
        os.utime(save, ns=(stamp.st_atime_ns, stamp.st_mtime_ns))
        if change == 'all':
            save.with_name('second.save').write_bytes(b'other new selected bytes')
    elif change == 'missing':
        save.unlink()
    elif change == 'read-error':
        original = receipts._stable_file
        def unreadable(path, *args):
            if path.name == 'save.save':
                raise OSError('injected read failure')
            return original(path, *args)
        monkeypatch.setattr(receipts, '_stable_file', unreadable)
    elif change == 'autosave':
        save.with_name('autosave.save').write_bytes(b'unexpected autosave')
    report(root, result.detail, 'stopped')
    final = runtime.session_status(root, result.detail, host_pid=123)
    assert final.state == 'stopped' and not final.diagnostics, final.diagnostics
    value = last(root, result.detail)
    inspected = inspect_receipt(value)
    assert inspected['file_effect']['classification'] == classification
    assert inspected['save_attempt'] == 'unreported'
    assert inspected['claims'] == CLAIMS and inspected['decision']['status'] == 'unknown'
    if change == 'autosave':
        assert inspected['file_effect']['other_files_changed'] is True
    if change == 'read-error':
        assert inspected['file_effect']['errors_after'] == {digest(b'account/slot1/save.save'): 'read-failed'}
    assert (review.backup.directory / 'files/account/slot1/save.save').read_bytes() == b'unchanged player progress'


@pytest.mark.parametrize('change', ['deleted-backup', 'manifest', 'save-location', 'transferred'])
def test_unavailable_backup_context_does_not_invent_terminal_file_evidence(tmp_path, monkeypatch, change):
    root, _files, _save, review = prepared(tmp_path, monkeypatch)
    result, _calls = start(root, review, monkeypatch)
    if change == 'deleted-backup':
        shutil.rmtree(review.backup.directory)
    elif change == 'manifest':
        (review.backup.directory / 'manifest.json').write_bytes(b'{}')
    elif change == 'save-location':
        monkeypatch.setenv('LOCALAPPDATA', str(tmp_path / 'different-local'))
    else:
        other = tmp_path / 'other-game'
        destination = other / receipts.RECEIPT_PATH / result.detail
        shutil.copytree(root / receipts.RECEIPT_PATH / result.detail, destination)
        root = other
    report(root, result.detail, 'stopped')
    final = runtime.session_status(root, result.detail, host_pid=123)
    assert final.state == 'stopped' and 'unavailable' in ' '.join(final.diagnostics)
    value = last(root, result.detail)
    assert value.to_dict()['after'] is None
    assert inspect_receipt(value)['file_effect']['classification'] == 'unobserved'
    assert value.to_dict()['claims'] == CLAIMS


def test_pid_and_foreign_declared_process_fields_cannot_become_verified_identity(tmp_path, monkeypatch):
    root, _files, _save, review = prepared(tmp_path, monkeypatch)
    result, _calls = start(root, review, monkeypatch)
    monkeypatch.setattr(runtime, '_process_alive', lambda pid: False)
    report(root, result.detail, 'running', birth_sha256='1' * 64,
           image_sha256=runtime.GAME_SHA256, observed_session_token=result.detail)
    status = runtime.session_status(root, result.detail, host_pid=123)
    assert status.state == 'stopped'
    value = last(root, result.detail).to_dict()
    assert value['process']['reported_game_pid'] == 456
    assert value['process']['birth_sha256'] is None and value['process']['observed_session_token'] is None
    assert 'missing-events' in value['indicators']
    assert value['claims'] == CLAIMS


def test_status_receipt_failure_preserves_true_status_and_prior_observations(tmp_path, monkeypatch):
    root, _files, _save, review = prepared(tmp_path, monkeypatch)
    result, _calls = start(root, review, monkeypatch)
    before = tuple(row.data for row in receipts.read_session_receipts(root, result.detail))
    report(root, result.detail, 'stopped')
    def failed(*args, **kwargs):
        raise OSError('receipt device full')
    monkeypatch.setattr(receipts, '_publish', failed)
    status = runtime.session_status(root, result.detail, host_pid=123)
    assert status.state == 'stopped' and 'receipt device full' in ' '.join(status.diagnostics)
    assert tuple(row.data for row in receipts.read_session_receipts(root, result.detail)) == before


def test_status_read_failure_is_recorded_without_fabricating_a_terminal_result(tmp_path, monkeypatch):
    root, _files, _save, review = prepared(tmp_path, monkeypatch)
    result, _calls = start(root, review, monkeypatch)
    report(root, result.detail, 'running', progress=True)
    with pytest.raises(VirtualLoaderError, match='progress'):
        runtime.session_status(root, result.detail, host_pid=123)
    value = last(root, result.detail).to_dict()
    assert value['terminal'] == 'pending' and value['after'] is None
    assert 'Runtime observation failed' in ' '.join(value['diagnostics'])


def test_terminal_observation_cancellation_keeps_pending_evidence_and_real_status(tmp_path, monkeypatch):
    root, _files, _save, review = prepared(tmp_path, monkeypatch)
    result, _calls = start(root, review, monkeypatch)
    report(root, result.detail, 'stopped')
    stop = threading.Event()
    original = receipts.observe_files
    def observe(*args, **kwargs):
        stop.set()
        return original(*args, **kwargs)
    monkeypatch.setattr(receipts, 'observe_files', observe)
    status = runtime.session_status(root, result.detail, host_pid=123, stop_event=stop)
    assert status.state == 'stopped' and status.diagnostics
    assert last(root, result.detail).to_dict()['terminal'] == 'pending'
    assert last(root, result.detail).to_dict()['after'] is None


def test_reused_review_starts_a_distinct_attempt_and_keeps_prior_receipts(tmp_path, monkeypatch):
    root, _files, _save, review = prepared(tmp_path, monkeypatch)
    first, _calls = start(root, review, monkeypatch)
    before = tuple(row.data for row in receipts.read_session_receipts(root, first.detail))
    second, _calls = start(root, review, monkeypatch)
    assert second.detail != first.detail and second.state == 'starting' and not second.diagnostics
    assert tuple(row.data for row in receipts.read_session_receipts(root, first.detail)) == before
    latest = last(root, second.detail).to_dict()
    assert latest['backup']['backup_id'] == review.backup.directory.name
    assert latest['process']['expected_session_token'] == second.detail


def test_atomic_append_refuses_racing_foreign_file_without_replacing_it(tmp_path, monkeypatch):
    root, _files, _save, review = prepared(tmp_path, monkeypatch)
    chain = receipts.read_session_receipts(root, review.receipt_token)
    old = tuple(row.data for row in chain)
    original = receipts.os.link
    foreign = b'foreign receipt bytes'
    def competing(source, target):
        Path(target).write_bytes(foreign)
        return original(source, target)
    monkeypatch.setattr(receipts.os, 'link', competing)
    with pytest.raises(VirtualLoaderError):
        receipts.append_observation(root, review.receipt_token, 'runtime-status')
    folder = root / receipts.RECEIPT_PATH / review.receipt_token
    assert (folder / '0002.json').read_bytes() == foreign
    assert tuple((folder / f'{i:04d}.json').read_bytes() for i in range(2)) == old
    assert not list(folder.glob('.pending-*.tmp'))


def test_concurrent_appenders_form_one_complete_chain_and_do_not_take_installation_lane(tmp_path, monkeypatch):
    root, _files, _save, review = prepared(tmp_path, monkeypatch)
    from cdmw.services.installation_lane import installation_lane
    def append(index):
        return receipts.append_observation(root, review.receipt_token, 'runtime-status',
            diagnostics=(f'Independent observer {index}',))
    with installation_lane(root):
        with ThreadPoolExecutor(max_workers=3) as executor:
            results = list(executor.map(append, range(3)))
    chain = receipts.read_session_receipts(root, review.receipt_token)
    assert len(chain) == 5 and len({row[1].identity for row in results}) == 3
    assert {row.to_dict()['diagnostics'][0] for row in chain[2:]} == {
        'Independent observer 0', 'Independent observer 1', 'Independent observer 2'}


@pytest.mark.parametrize('change', ['gap', 'bound', 'linked'])
def test_receipt_storage_rejects_incomplete_or_unsupported_chains(tmp_path, monkeypatch, change):
    root, _files, _save, review = prepared(tmp_path, monkeypatch)
    folder = root / receipts.RECEIPT_PATH / review.receipt_token
    if change == 'gap':
        (folder / '0001.json').rename(folder / '0002.json')
    elif change == 'bound':
        monkeypatch.setattr(receipts, 'MAX_CHAIN_BYTES', 1)
    else:
        outside = tmp_path / 'outside-receipts'
        folder.rename(outside)
        if os.name == 'nt':
            result = subprocess.run(['cmd', '/c', 'mklink', '/J', str(folder), str(outside)],
                                    capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW)
            assert result.returncode == 0, result.stderr
        else:
            folder.symlink_to(outside, target_is_directory=True)
    with pytest.raises(VirtualLoaderError):
        receipts.read_session_receipts(root, review.receipt_token)


def test_failed_launch_receipt_still_reserves_native_token_and_keeps_old_manifest(tmp_path, monkeypatch):
    root, _files, _save, review = prepared(tmp_path, monkeypatch)
    original = receipts.record_launch
    def fail(*args, **kwargs):
        raise OSError('receipt publication after spawn failed')
    monkeypatch.setattr(receipts, 'record_launch', fail)
    first, _calls = start(root, review, monkeypatch)
    assert first.state == 'starting' and first.diagnostics
    manifest = root / '.cdmw/virtual-loader/launches' / (first.detail + '.bin')
    before = manifest.read_bytes()
    monkeypatch.setattr(receipts, 'record_launch', original)
    second, _calls = start(root, review, monkeypatch)
    assert second.detail != first.detail and second.state == 'starting' and not second.diagnostics
    assert manifest.read_bytes() == before
    assert last(root, first.detail).to_dict()['terminal'] == 'pending'


def test_retry_failure_does_not_relabel_a_previously_started_attempt(tmp_path, monkeypatch):
    root, _files, _save, review = prepared(tmp_path, monkeypatch)
    first, _calls = start(root, review, monkeypatch)
    before = tuple(row.data for row in receipts.read_session_receipts(root, first.detail))
    with pytest.raises(OSError, match='spawn failure'):
        start(root, review, monkeypatch, fail=True)
    assert tuple(row.data for row in receipts.read_session_receipts(root, first.detail)) == before
    attempts = list((root / receipts.RECEIPT_PATH).iterdir())
    assert len(attempts) == 2
    failed = next(path for path in attempts if path.name != first.detail)
    assert last(root, failed.name).to_dict()['terminal'] == 'failed'


@pytest.mark.parametrize('receipt_failure', [False, True])
def test_late_backup_cancellation_retains_truthful_committed_backup_facts(tmp_path, monkeypatch, receipt_failure):
    root, _files, _save = experimental_fixture(tmp_path, monkeypatch)
    original, stop, retained = saves.backup_saves, threading.Event(), []
    def complete(*args, **kwargs):
        backup = original(*args, **kwargs)
        retained.append(backup)
        stop.set()
        return backup
    monkeypatch.setattr(saves, 'backup_saves', complete)
    if receipt_failure:
        def failed(*args, **kwargs):
            raise OSError('backup receipt temporarily unavailable')
        monkeypatch.setattr(receipts, 'record_backup', failed)
    with pytest.raises(RunCancelled):
        runtime.prepare_experimental_launch(root, stop_event=stop)
    attempt = next((root / receipts.RECEIPT_PATH).iterdir()).name
    value = last(root, attempt).to_dict()
    assert value['terminal'] == 'interrupted' and retained[0].directory.is_dir()
    if receipt_failure:
        assert value['backup']['status'] == 'unknown'
    else:
        assert value['backup']['status'] == 'verified'
        assert value['backup']['backup_id'] == retained[0].directory.name
        assert value['backup']['manifest_sha256'] == retained[0].manifest_sha256
    assert (retained[0].directory / 'files/account/slot1/save.save').read_bytes() == b'unchanged player progress'
