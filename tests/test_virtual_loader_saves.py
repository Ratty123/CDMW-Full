"""Save-backed experimental launches through the production service boundary."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import os
import subprocess
import threading

import pytest

from cdmw.domain.cancellation import RunCancelled
from cdmw.domain.virtual_loader import VirtualLoaderError, VirtualProfile, VirtualSessionStatus
from cdmw.services import virtual_loader_runtime as runtime, virtual_loader_saves as saves
from cdmw.services.installation_lane import installation_lane
from cdmw.services.virtual_loader_composition import prepare_profile
from cdmw.services.virtual_loader_state import publish_profile
from tests.test_virtual_loader import packages, game_bytes
from tests.test_virtual_loader_runtime import setup_fixture


def experimental_fixture(tmp_path, monkeypatch):
    root, files = packages(tmp_path, 1)
    setup_fixture(tmp_path, monkeypatch)
    runtime.apply_runtime_setup(runtime.prepare_runtime_setup(root), confirmed=True)
    publish_profile(prepare_profile(VirtualProfile(files), root))
    monkeypatch.setenv('LOCALAPPDATA', str(tmp_path / 'local'))
    save = saves.save_root() / 'account/slot1/save.save'
    save.parent.mkdir(parents=True)
    save.write_bytes(b'unchanged player progress')
    return root, files, save


def test_review_copies_saves_and_only_confirmed_launch_receives_backup_guards(tmp_path, monkeypatch):
    root, _files, save = experimental_fixture(tmp_path, monkeypatch)
    original = game_bytes(root)
    assert runtime.runtime_status(root).state == 'blocked'
    assert runtime.runtime_status(root, experimental=True).state == 'ready'
    review = runtime.prepare_experimental_launch(root)
    assert (review.backup.directory / 'files/account/slot1/save.save').read_bytes() == save.read_bytes()
    calls = []
    def acquire_in_another_thread():
        with installation_lane(root):
            return True
    def start(*args, **kwargs):
        # The native host must be able to acquire the lane immediately.
        with ThreadPoolExecutor(max_workers=1) as executor:
            assert executor.submit(acquire_in_another_thread).result(timeout=2)
        calls.append(kwargs)
        return VirtualSessionStatus('starting', 'a' * 32, review.plan.generation, 123)
    monkeypatch.setattr(runtime, '_start', start)
    with pytest.raises(PermissionError):
        runtime.launch_experimental(review)
    assert not calls
    assert runtime.launch_experimental(review, confirmed=True).state == 'starting'
    assert calls[0]['mode'] == 3
    guards = dict(calls[0]['extra_guards'])
    assert guards[str(save)] == guards[str(review.backup.directory / 'files/account/slot1/save.save')]
    assert guards[str(review.backup.directory / 'manifest.json')] == review.backup.manifest_sha256
    assert save.read_bytes() == b'unchanged player progress' and game_bytes(root) == original


@pytest.mark.parametrize('change,match', [
    ('save', 'saved game changed'), ('backup', 'save backup'),
    ('manifest', 'save backup'), ('profile', 'plan changed'),
    ('package', 'source changed'), ('location', 'save folder changed'),
])
def test_review_refuses_changed_inputs_without_starting(tmp_path, monkeypatch, change, match):
    root, files, save = experimental_fixture(tmp_path, monkeypatch)
    review = runtime.prepare_experimental_launch(root)
    calls = []
    monkeypatch.setattr(runtime, '_start', lambda *a, **kw: calls.append(kw))
    if change == 'save':
        stamp = save.stat()
        save.write_bytes(b'changed  player progress')
        os.utime(save, ns=(stamp.st_atime_ns, stamp.st_mtime_ns))
    elif change == 'backup':
        (review.backup.directory / 'files/account/slot1/save.save').write_bytes(b'bad')
    elif change == 'manifest':
        (review.backup.directory / 'manifest.json').write_bytes(b'{}')
    elif change == 'profile':
        publish_profile(prepare_profile(VirtualProfile(), root))
    elif change == 'package':
        files[0].write_bytes(files[0].read_bytes() + b'changed')
    else:
        monkeypatch.setenv('LOCALAPPDATA', str(tmp_path / 'elsewhere'))
    with pytest.raises(VirtualLoaderError, match=match):
        runtime.launch_experimental(review, confirmed=True)
    assert not calls


@pytest.mark.parametrize('failure', ['cancel', 'changed', 'io'])
def test_interrupted_backup_does_not_publish_partial_copies_or_touch_previous_backup(tmp_path, monkeypatch, failure):
    root, _files, save = experimental_fixture(tmp_path, monkeypatch)
    retained = runtime.prepare_experimental_launch(root).backup
    original = saves._copy
    stop = threading.Event()
    def copy(*args):
        result = original(*args)
        if failure == 'cancel':
            stop.set()
        elif failure == 'changed':
            save.write_bytes(b'concurrent save')
        else:
            raise OSError('injected copy failure')
        return result
    monkeypatch.setattr(saves, '_copy', copy)
    with pytest.raises((RunCancelled, VirtualLoaderError, OSError)):
        runtime.prepare_experimental_launch(root, stop_event=stop)
    assert list((root / saves.BACKUP_PATH).iterdir()) == [retained.directory]
    assert (retained.directory / 'files/account/slot1/save.save').read_bytes() == b'unchanged player progress'


@pytest.mark.parametrize('condition', ['empty', 'limit', 'running', 'bootstrap'])
def test_unusable_launch_refuses_before_backup_or_spawn(tmp_path, monkeypatch, condition):
    root, _files, save = experimental_fixture(tmp_path, monkeypatch)
    if condition == 'empty':
        save.unlink()
    elif condition == 'limit':
        monkeypatch.setattr(saves, 'MAX_BYTES', 1)
    elif condition == 'running':
        monkeypatch.setattr('cdmw.services.new_item_service.game_is_running', lambda: True)
    else:
        (root / 'bin64/winmm.dll').write_bytes(b'different bootstrap')
    with pytest.raises(VirtualLoaderError):
        runtime.prepare_experimental_launch(root)
    assert not (root / saves.BACKUP_PATH).exists()


def test_linked_save_folder_is_refused(tmp_path, monkeypatch):
    root, _files, save = experimental_fixture(tmp_path, monkeypatch)
    outside = tmp_path / 'outside'
    outside.mkdir()
    (outside / 'private.txt').write_bytes(b'do not copy')
    link = save.parent / 'linked'
    if os.name == 'nt':
        result = subprocess.run(['cmd', '/c', 'mklink', '/J', str(link), str(outside)],
                                capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW)
        assert result.returncode == 0, result.stderr
    else:
        link.symlink_to(outside, target_is_directory=True)
    with pytest.raises(VirtualLoaderError, match='linked'):
        runtime.prepare_experimental_launch(root)
    assert not (root / saves.BACKUP_PATH).exists()


def test_cancelled_launch_keeps_verified_backup_without_starting(tmp_path, monkeypatch):
    root, _files, _save = experimental_fixture(tmp_path, monkeypatch)
    review = runtime.prepare_experimental_launch(root)
    stop = threading.Event()
    stop.set()
    calls = []
    monkeypatch.setattr(runtime, '_start', lambda *a, **kw: calls.append(kw))
    with pytest.raises(RunCancelled):
        runtime.launch_experimental(review, confirmed=True, stop_event=stop)
    assert review.backup.directory.is_dir() and not calls
