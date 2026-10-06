"""Runtime setup and lifecycle contracts using owned files, never the real game."""
import json
from pathlib import Path

import pytest

from cdmw.services import virtual_loader_runtime as runtime
from cdmw.services.independent_item_package import digest
from cdmw.services.virtual_loader_state import publish_profile
from cdmw.services.virtual_loader_composition import prepare_profile
from cdmw.domain.virtual_loader import VirtualProfile, VirtualLoaderError
from tests.test_virtual_loader import packages, game_bytes


def setup_fixture(tmp_path, monkeypatch):
    root = tmp_path / 'game'
    (root / 'bin64').mkdir(parents=True, exist_ok=True)
    (root / 'bin64/CrimsonDesert.exe').write_bytes(b'fixture executable')
    (root / 'bin64/winmm.dll').write_bytes(b'fixture bootstrap')
    bundle = tmp_path / 'bundle'
    bundle.mkdir()
    payload = b'fixture diagnostic runtime'
    (bundle / 'CDMWVirtualLoader.asi').write_bytes(payload)
    (bundle / 'cdmw_virtual_session.exe').write_bytes(b'fixture host')
    evidence = {'files': {'CDMWVirtualLoader.asi': digest(payload), 'cdmw_virtual_session.exe': digest(b'fixture host')}}
    monkeypatch.setattr(runtime, 'native_bundle', lambda **kw: (bundle, evidence))
    monkeypatch.setattr(runtime, 'GAME_SHA256', digest(b'fixture executable'))
    monkeypatch.setattr(runtime, 'BOOTSTRAP_SHA256', digest(b'fixture bootstrap'))
    monkeypatch.setattr('cdmw.services.new_item_service.game_is_running', lambda: False)
    launcher = tmp_path / 'steam.exe'
    launcher.write_bytes(b'fixture steam client')
    monkeypatch.setattr(runtime, '_steam_launcher', lambda: launcher)
    return root, payload


def test_runtime_setup_and_removal_are_reviewed_owned_and_recoverable(tmp_path, monkeypatch):
    root, payload = setup_fixture(tmp_path, monkeypatch)
    target = root / runtime.RUNTIME_PATH
    plan = runtime.prepare_runtime_setup(root)
    with pytest.raises(PermissionError):
        runtime.apply_runtime_setup(plan)
    assert not target.exists()
    runtime.apply_runtime_setup(plan, confirmed=True)
    assert target.read_bytes() == payload
    backup = runtime.remove_runtime(root, expected_sha256=digest(payload), confirmed=True)
    assert not target.exists() and (backup / 'CDMWVirtualLoader.asi').read_bytes() == payload
    target.write_bytes(b'foreign file')
    with pytest.raises(ValueError, match='not owned'):
        runtime.prepare_runtime_setup(root)
    assert target.read_bytes() == b'foreign file'
    assert (root / 'bin64/winmm.dll').read_bytes() == b'fixture bootstrap'


def test_runtime_setup_failure_rolls_back_new_files(tmp_path, monkeypatch):
    root, _ = setup_fixture(tmp_path, monkeypatch)
    plan = runtime.prepare_runtime_setup(root)
    original = runtime.atomic_write_bytes
    def fail_receipt(path, data):
        if path == root / runtime.OWNER_PATH:
            raise OSError('injected receipt failure')
        original(path, data)
    monkeypatch.setattr(runtime, 'atomic_write_bytes', fail_receipt)
    with pytest.raises(OSError, match='injected'):
        runtime.apply_runtime_setup(plan, confirmed=True)
    assert not (root / runtime.RUNTIME_PATH).exists()
    assert not (root / runtime.OWNER_PATH).exists()


def test_status_detects_early_host_exit_and_closed_game(tmp_path, monkeypatch):
    token = 'a' * 32
    monkeypatch.setattr(runtime, '_process_alive', lambda pid: False)
    assert runtime.session_status(tmp_path, token, host_pid=999).state == 'blocked'
    report = tmp_path / '.cdmw/virtual-loader' / f'session-{token}.json'
    report.parent.mkdir(parents=True)
    report.write_text(json.dumps({'state': 'tracing', 'pid': 123, 'error': 0}))
    assert runtime.session_status(tmp_path, token).state == 'stopped'
    report.write_text(json.dumps({'state': 'blocked', 'pid': 123, 'detail': 'verified hook conflict'}))
    assert runtime.session_status(tmp_path, token).detail == 'verified hook conflict'


def test_status_tracks_host_while_steam_game_is_not_bound(tmp_path, monkeypatch):
    token = 'a' * 32
    report = tmp_path / '.cdmw/virtual-loader' / f'session-{token}.json'
    report.parent.mkdir(parents=True)
    report.write_text(json.dumps({'state': 'starting', 'pid': 0, 'host_pid': 789,
                                 'detail': 'Checking mod contents and their game baseline...'}))
    monkeypatch.setattr(runtime, '_process_alive', lambda pid: pid == 789)
    assert runtime.session_status(tmp_path, token).state == 'starting'
    assert runtime.session_status(tmp_path, token).detail == 'Checking mod contents and their game baseline...'
    monkeypatch.setattr(runtime, '_process_alive', lambda pid: False)
    assert runtime.session_status(tmp_path, token).state == 'blocked'


def test_steam_discovery_requires_one_unambiguous_client(tmp_path, monkeypatch):
    from cdmw.core import archive_format
    first, second = tmp_path / 'first', tmp_path / 'second'
    for folder in (first, second):
        folder.mkdir()
        (folder / 'steam.exe').write_bytes(b'steam fixture')
    monkeypatch.setattr(archive_format, 'discover_steam_roots', lambda: [first])
    assert runtime._steam_launcher() == first / 'steam.exe'
    monkeypatch.setattr(archive_format, 'discover_steam_roots', lambda: [first, second])
    with pytest.raises(VirtualLoaderError, match='single installed Steam'):
        runtime._steam_launcher()


def test_snapshot_detects_content_changes_even_with_preserved_stamps(tmp_path):
    import os
    root, files = packages(tmp_path, 1)
    publish_profile(prepare_profile(VirtualProfile(files), root))
    assert runtime.verify_snapshot(root)
    path = files[0]
    stamp = path.stat()
    data = bytearray(path.read_bytes()); data[-1] ^= 1
    path.write_bytes(data)
    os.utime(path, ns=(stamp.st_atime_ns, stamp.st_mtime_ns))
    with pytest.raises(VirtualLoaderError, match='source changed'):
        runtime.verify_snapshot(root)


@pytest.mark.parametrize('mode', [0, 3])
def test_session_host_runs_from_persistent_storage_outside_app_job(tmp_path, monkeypatch, mode):
    from types import SimpleNamespace
    root, files = packages(tmp_path, 1)
    root, payload = setup_fixture(tmp_path, monkeypatch)
    (root / runtime.RUNTIME_PATH).write_bytes(payload)
    profile = publish_profile(prepare_profile(VirtualProfile(files), root))
    from cdmw.services.independent_item_package import canonical
    stored = root / '.cdmw/virtual-loader/profile.json'
    stored.parent.mkdir(parents=True, exist_ok=True)
    stored.write_bytes(canonical(profile))
    monkeypatch.setattr('cdmw.services.process_job_service.breakaway_creation_flags', lambda: 0x1000000)
    captured = []
    def start(command, **kwargs):
        captured.append((command, kwargs))
        return SimpleNamespace(pid=123)
    monkeypatch.setattr(runtime.subprocess, 'Popen', start)
    status = runtime._start(root, profile, mode=mode)
    executable = Path(captured[0][0][0])
    assert executable.is_relative_to(root / '.cdmw/virtual-loader/hosts')
    assert executable.read_bytes() == b'fixture host'
    assert captured[0][1]['creationflags'] & 0x1000000
    assert ('--controlled-probe' in captured[0][0]) == (mode == 3)
    assert status.pid == 123
    assert (root / '.cdmw/virtual-loader/launches' / (status.detail + '.log')).is_file()
    stored.write_bytes(b'changed')
    with pytest.raises(VirtualLoaderError, match='profile changed before launch'):
        runtime._start(root, profile, mode=0)
    assert len(captured) == 1


def test_diagnostic_plan_is_checked_again_after_review(tmp_path, monkeypatch):
    root, files = packages(tmp_path, 1)
    setup_fixture(tmp_path, monkeypatch)
    runtime.apply_runtime_setup(runtime.prepare_runtime_setup(root), confirmed=True)
    publish_profile(prepare_profile(VirtualProfile(files), root))
    plan = runtime.prepare_diagnostic_trace(root)
    publish_profile(prepare_profile(VirtualProfile(), root))
    with pytest.raises(VirtualLoaderError, match='plan changed'):
        runtime.start_diagnostic_trace(root, confirmed=True, expected_plan=plan)
    assert not (root / '.cdmw/virtual-loader/launches').exists()
    # Production loading remains unavailable even with a known installed runtime.
    assert runtime.runtime_status(root).state == 'blocked'


def test_controlled_probe_requires_review_rechecks_inputs_and_keeps_release_blocked(tmp_path, monkeypatch):
    root, files = packages(tmp_path, 1)
    setup_fixture(tmp_path, monkeypatch)
    runtime.apply_runtime_setup(runtime.prepare_runtime_setup(root), confirmed=True)
    publish_profile(prepare_profile(VirtualProfile(files), root))
    plan = runtime.prepare_diagnostic_trace(root)
    calls = []
    monkeypatch.setattr(runtime, '_start', lambda *args, **kw: calls.append(kw))
    with pytest.raises(PermissionError):
        runtime.start_controlled_probe(root, expected_plan=plan)
    with pytest.raises(PermissionError):
        runtime.start_controlled_probe(root, confirmed=True)
    assert not calls
    runtime.start_controlled_probe(root, confirmed=True, expected_plan=plan)
    assert len(calls) == 1 and calls[0]['mode'] == 3
    assert runtime.runtime_status(root).state == 'blocked'
    with pytest.raises(VirtualLoaderError):
        runtime.prepare_launch(root)
    publish_profile(prepare_profile(VirtualProfile(), root))
    with pytest.raises(VirtualLoaderError, match='plan changed'):
        runtime.start_controlled_probe(root, confirmed=True, expected_plan=plan)
    assert len(calls) == 1


@pytest.mark.parametrize('code', [225, 226])
@pytest.mark.parametrize('stage', ['bundle', 'retained', 'spawn'])
def test_security_refusal_identifies_build_and_blocks_retries_before_source_scan(tmp_path, monkeypatch, code, stage):
    from cdmw.services.independent_item_package import canonical
    original_bundle = runtime.native_bundle
    root, files = packages(tmp_path, 1)
    setup_fixture(tmp_path, monkeypatch)
    runtime.apply_runtime_setup(runtime.prepare_runtime_setup(root), confirmed=True)
    profile = publish_profile(prepare_profile(VirtualProfile(files), root))
    # Exercise the actual bundled-provenance path, without executing a helper.
    folder = tmp_path / 'native/cdmw_virtual_loader'
    folder.mkdir(parents=True)
    hashes = {}
    for file in (tmp_path / 'bundle').iterdir():
        data = file.read_bytes()
        (folder / file.name).write_bytes(data)
        hashes[file.name] = digest(data)
    (folder / 'provenance.json').write_bytes(canonical({'format': 'cdmw_virtual_runtime_v1', 'files': hashes}))
    monkeypatch.setattr(runtime, 'native_bundle', original_bundle)
    monkeypatch.setattr(runtime.sys, 'frozen', True, raising=False)
    monkeypatch.setattr(runtime.sys, '_MEIPASS', str(tmp_path), raising=False)
    monkeypatch.setattr(runtime, '_security_blocks', {})
    before, starts = game_bytes(root), []
    error = OSError('Windows refused this runtime')
    error.winerror = code
    def fail(*_args, **_kwargs):
        raise error
    if stage == 'bundle':
        hash_file = runtime.hash_file
        monkeypatch.setattr(runtime, 'hash_file', lambda path, *a: fail() if Path(path).name == 'cdmw_virtual_session.exe' else hash_file(path, *a))
    elif stage == 'retained':
        read = runtime.read_optional
        monkeypatch.setattr(runtime, 'read_optional', lambda path: fail() if Path(path).parent.name == 'hosts' else read(path))
    def spawn(*args, **kwargs):
        starts.append(args)
        fail()
    monkeypatch.setattr(runtime.subprocess, 'Popen', spawn)
    with pytest.raises(VirtualLoaderError, match='Windows security software blocked') as caught:
        runtime._start(root, profile, mode=3)
    assert caught.value.__cause__ is error
    assert hashes['cdmw_virtual_session.exe'] in str(caught.value)
    assert 'File:' in str(caught.value) and 'Protection history' in str(caught.value)
    assert len(starts) == int(stage == 'spawn')
    assert game_bytes(root) == before
    # Repeated launch review must fail before any multi-gigabyte validation.
    monkeypatch.setattr(runtime, 'verify_snapshot', lambda *_a, **_k: pytest.fail('Repeated expensive source scan'))
    with pytest.raises(VirtualLoaderError, match='Windows security software blocked'):
        runtime.prepare_diagnostic_trace(root)
    status = runtime.runtime_status(root, experimental=True)
    assert status.state == 'blocked' and 'Protection history' in status.detail
    assert len(starts) == int(stage == 'spawn')


def test_non_security_io_error_does_not_poison_runtime_status(tmp_path, monkeypatch):
    monkeypatch.setattr(runtime, '_security_blocks', {})
    error = PermissionError('ordinary file permission error')
    error.winerror = 5
    with pytest.raises(PermissionError) as caught:
        with runtime._runtime_file_access(tmp_path / 'host.exe', 'a' * 64):
            raise error
    assert caught.value is error and not runtime._security_blocks
