"""Explicit native proof. Build with scripts/build_virtual_loader.py first."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import time
from uuid import uuid4

import pytest

from cdmw.services.virtual_loader_composition import hash_file
from cdmw.services.virtual_loader_runtime import session_manifest
from cdmw.services.independent_item_package import digest

BUILD = Path(__file__).resolve().parents[1] / 'native/cdmw_virtual_loader/build/Release'
pytestmark = pytest.mark.skipif(os.name != 'nt' or not (BUILD / 'CDMWVirtualLoader.asi').exists(), reason='Requires the explicitly built Windows native virtual runtime')


def fixture(tmp_path, *, steam=False):
    root = tmp_path / 'game with spaces ü'
    (root / 'bin64').mkdir(parents=True)
    for name in ('CDMWVirtualLoader.asi', 'cdmw_virtual_loader_harness.exe'):
        shutil.copy2(BUILD / name, root / 'bin64' / name)
    (root / 'meta').mkdir()
    (root / 'meta/0.papgt').write_bytes(b'original')
    generation = uuid4().hex
    snapshot = root / '.cdmw/virtual-loader/generations' / generation / 'files/meta'
    snapshot.mkdir(parents=True)
    (snapshot / '0.papgt').write_bytes(b'virtual')
    archive = snapshot.parent / '0042'
    archive.mkdir()
    for name in ('0.pamt', '0.paz'):
        (archive / name).write_bytes(b'virtual')
    profile = {'generation': generation, 'files': {p: digest(b'virtual') for p in ('meta/0.papgt', '0042/0.pamt', '0042/0.paz')}}
    launcher = root / 'bin64/cdmw_virtual_steam_fixture.exe' if steam else None
    if launcher:
        shutil.copy2(BUILD / 'cdmw_virtual_loader_harness.exe', launcher)
    token, manifest = session_manifest(root, profile, mode=2, executable_sha256=hash_file(root / 'bin64/cdmw_virtual_loader_harness.exe'), launcher=launcher)
    request = root / '.cdmw/virtual-loader/request.bin'
    request.write_bytes(manifest)
    return root, request, token


@pytest.mark.parametrize('steam', [False, True])
def test_native_session_redirects_real_handles_without_touching_original(tmp_path, steam):
    root, request, token = fixture(tmp_path, steam=steam)
    result = subprocess.run([str(BUILD / 'cdmw_virtual_session.exe'), str(request)], capture_output=True, timeout=40)
    assert result.returncode == 0, result.stderr.decode(errors='replace')
    assert (root / 'meta/0.papgt').read_bytes() == b'original'
    assert (root / '.cdmw/virtual-loader/harness-result.txt').read_text() == 'native IO passed'
    status = json.loads((root / f'.cdmw/virtual-loader/session-{token}.json').read_text())
    assert status['state'] == 'stopped' and status['error'] == 0
    assert not (root / '.cdmw/virtual-loader/session.bin').exists()
    assert (root / f'.cdmw/virtual-loader/trace-{token}.bin').stat().st_size > 0


def test_native_changed_steam_client_is_refused_before_launch(tmp_path):
    root, request, token = fixture(tmp_path, steam=True)
    with (root / 'bin64/cdmw_virtual_steam_fixture.exe').open('ab') as handle:
        handle.write(b'changed launcher')
    result = subprocess.run([str(BUILD / 'cdmw_virtual_session.exe'), str(request)], capture_output=True, timeout=10)
    assert result.returncode != 0 and b'Steam client changed' in result.stderr
    assert not (root / '.cdmw/virtual-loader/harness-result.txt').exists()
    assert not (root / '.cdmw/virtual-loader/session.bin').exists()


def test_native_steam_claim_from_wrong_parent_is_refused(tmp_path):
    root, request, token = fixture(tmp_path, steam=True)
    shutil.copy2(BUILD / 'cdmw_virtual_loader_harness.exe', root / 'bin64/cdmw_virtual_steam_bridge.exe')
    (root / '.cdmw/virtual-loader/harness-wrong-parent.flag').touch()
    result = subprocess.run([str(BUILD / 'cdmw_virtual_session.exe'), str(request)], capture_output=True, timeout=15)
    assert result.returncode != 0 and b'not started by the reviewed Steam client' in result.stderr
    assert not (root / '.cdmw/virtual-loader/harness-result.txt').exists()
    assert (root / 'meta/0.papgt').read_bytes() == b'original'


def test_native_abandoned_unbound_request_does_not_activate_ordinary_game(tmp_path):
    root, request, _token = fixture(tmp_path, steam=True)
    data = bytearray(request.read_bytes())
    data[16:20] = (12345).to_bytes(4, 'little')
    (root / '.cdmw/virtual-loader/session.bin').write_bytes(data)
    result = subprocess.run([str(root / 'bin64/cdmw_virtual_loader_harness.exe'), '--inert'], capture_output=True, timeout=10)
    assert result.returncode == 0, result.stderr


def test_native_corrupt_snapshot_refuses_before_start(tmp_path):
    root, request, token = fixture(tmp_path)
    next((root / '.cdmw/virtual-loader/generations').glob('*/files/meta/0.papgt')).write_bytes(b'bad')
    result = subprocess.run([str(BUILD / 'cdmw_virtual_session.exe'), str(request)], capture_output=True, timeout=10)
    assert result.returncode != 0 and b'checksum' in result.stderr
    assert not (root / '.cdmw/virtual-loader/harness-result.txt').exists()
    assert (root / 'meta/0.papgt').read_bytes() == b'original'


def test_native_create_process_failure_cancels_pending_connection(tmp_path):
    root, request, token = fixture(tmp_path)
    invalid = b'not a Windows executable'
    (root / 'bin64/cdmw_virtual_loader_harness.exe').write_bytes(invalid)
    data = bytearray(request.read_bytes()); data[20:52] = bytes.fromhex(digest(invalid))
    request.write_bytes(data)
    result = subprocess.run([str(BUILD / 'cdmw_virtual_session.exe'), str(request)], capture_output=True, timeout=10)
    assert result.returncode != 0 and b'Cannot start fixture executable' in result.stderr
    assert not (root / '.cdmw/virtual-loader/session.bin').exists()
    from cdmw.services.installation_lane import installation_lane
    with installation_lane(root):
        pass


@pytest.mark.skipif(not os.environ.get('CDMW_TEST_ASI_BOOTSTRAP'), reason='Requires an explicitly selected verified ASI bootstrap')
@pytest.mark.parametrize('changed_binary', [False, True])
def test_verified_asi_bootstrap_handoff(tmp_path, changed_binary):
    from cdmw.services.virtual_loader_runtime import BOOTSTRAP_SHA256
    bootstrap = Path(os.environ['CDMW_TEST_ASI_BOOTSTRAP'])
    assert hash_file(bootstrap) == BOOTSTRAP_SHA256
    root, request, token = fixture(tmp_path)
    shutil.copy2(bootstrap, root / 'bin64/winmm.dll')
    if changed_binary:
        with (root / 'bin64/winmm.dll').open('ab') as handle:
            handle.write(b'changed build')
    (root / '.cdmw/virtual-loader/harness-bootstrap.flag').touch()
    result = subprocess.run([str(BUILD / 'cdmw_virtual_session.exe'), str(request)], capture_output=True, timeout=40)
    report = root / f'.cdmw/virtual-loader/session-{token}.json'
    detail = report.read_text() if report.exists() else result.stderr.decode(errors='replace')
    if changed_binary:
        assert result.returncode != 0 and 'Coexistence is unverified' in detail
        assert not (root / '.cdmw/virtual-loader/harness-result.txt').exists()
        return
    assert result.returncode == 0, detail
    assert (root / '.cdmw/virtual-loader/harness-result.txt').read_text() == 'native IO passed'
    assert (root / 'meta/0.papgt').read_bytes() == b'original'
    from scripts.probe_virtual_loader import inspect_trace
    rows = inspect_trace(root / f'.cdmw/virtual-loader/trace-{token}.bin')['events']
    assert any(row['operation'] == 'verified bootstrap forwarding' and row['last_error'] > 0 for row in rows)
    assert any(row['operation'] == 'loader callout context' and row['last_error'] == 0 for row in rows)


def test_native_production_redirect_gate_cannot_be_enabled_by_manifest(tmp_path):
    root, request, _token = fixture(tmp_path)
    data = bytearray(request.read_bytes())
    data[8:12] = (1).to_bytes(4, 'little')
    request.write_bytes(data)
    result = subprocess.run([str(BUILD / 'cdmw_virtual_session.exe'), str(request)], capture_output=True, timeout=10)
    assert result.returncode != 0 and b'Game launch blocked' in result.stderr
    assert not (root / '.cdmw/virtual-loader/session.bin').exists()


@pytest.mark.parametrize('opt_in', [False, True])
def test_controlled_probe_requires_host_opt_in_and_exact_game(tmp_path, opt_in):
    root, request, _token = fixture(tmp_path)
    shutil.copy2(BUILD / 'cdmw_virtual_loader_harness.exe', root / 'bin64/CrimsonDesert.exe')
    launcher = root / 'bin64/steam.exe'
    shutil.copy2(BUILD / 'cdmw_virtual_loader_harness.exe', launcher)
    profile = {'generation': next((root / '.cdmw/virtual-loader/generations').iterdir()).name,
               'files': {p: digest(b'virtual') for p in ('meta/0.papgt', '0042/0.pamt', '0042/0.paz')}}
    # Mode 2's serializer avoids requiring game-only runtime guards in this
    # synthetic root. The resulting mode 3 still must pass all native guards.
    _token, data = session_manifest(root, profile, mode=2,
        executable_sha256=hash_file(root / 'bin64/CrimsonDesert.exe'), launcher=launcher)
    data = bytearray(data); data[8:12] = (3).to_bytes(4, 'little'); request.write_bytes(data)
    command = [str(BUILD / 'cdmw_virtual_session.exe'), str(request)]
    if opt_in:
        command.append('--controlled-probe')
    result = subprocess.run(command, capture_output=True, timeout=10)
    assert result.returncode != 0
    assert (b'Unsupported executable build' if opt_in else b'reviewed host opt-in') in result.stderr
    assert not (root / '.cdmw/virtual-loader/session.bin').exists()
    assert not (root / '.cdmw/virtual-loader/harness-result.txt').exists()


def test_normal_launch_is_inert_and_foreign_import_hook_is_refused(tmp_path):
    root, request, token = fixture(tmp_path)
    child = root / 'bin64/cdmw_virtual_loader_harness.exe'
    result = subprocess.run([str(child), '--inert'], capture_output=True, timeout=10)
    assert result.returncode == 0, result.stderr
    (root / '.cdmw/virtual-loader/harness-conflict.flag').touch()
    result = subprocess.run([str(BUILD / 'cdmw_virtual_session.exe'), str(request)], capture_output=True, timeout=40)
    assert result.returncode != 0
    detail = json.loads((root / f'.cdmw/virtual-loader/session-{token}.json').read_text())['detail']
    assert 'CreateFile2 is already hooked by cdmw_virtual_loader_harness.exe' in detail
    assert (root / 'meta/0.papgt').read_bytes() == b'original'


@pytest.mark.parametrize('steam', [False, True])
def test_runtime_retains_lease_and_files_when_session_host_dies(tmp_path, steam):
    from cdmw.services.installation_lane import installation_lane
    from cdmw.domain.virtual_loader import VirtualLoaderError
    import ctypes
    root, request, token = fixture(tmp_path, steam=steam)
    wait = root / '.cdmw/virtual-loader/harness-wait.flag'
    wait.touch()
    host = subprocess.Popen([str(BUILD / 'cdmw_virtual_session.exe'), str(request)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    game = None
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.OpenProcess.restype = ctypes.c_void_p
    kernel.WaitForSingleObject.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
    kernel.CloseHandle.argtypes = [ctypes.c_void_p]
    kernel.TerminateProcess.argtypes = [ctypes.c_void_p, ctypes.c_uint]
    try:
        deadline = time.monotonic() + 20
        while not (root / '.cdmw/virtual-loader/harness-result.txt').exists() and time.monotonic() < deadline:
            assert host.poll() is None
            time.sleep(.02)
        assert (root / '.cdmw/virtual-loader/harness-result.txt').exists()
        status = json.loads((root / f'.cdmw/virtual-loader/session-{token}.json').read_text())
        game = kernel.OpenProcess(0x100000 | 0x0001, False, status['pid'])
        assert game
        # Replaying the same request cannot steal the lane or delete the live
        # descriptor, even though its token equals the already running one.
        bound = (root / '.cdmw/virtual-loader/session.bin').read_bytes()
        duplicate = subprocess.run([str(BUILD / 'cdmw_virtual_session.exe'), str(request)], capture_output=True, timeout=10)
        assert duplicate.returncode != 0 and b'already in use' in duplicate.stderr
        assert (root / '.cdmw/virtual-loader/session.bin').read_bytes() == bound
        assert json.loads((root / f'.cdmw/virtual-loader/session-{token}.json').read_text())['state'] == 'running'
        host.terminate(); host.wait(timeout=5)
        assert kernel.WaitForSingleObject(game, 0) == 258
        with pytest.raises(VirtualLoaderError, match='in use'):
            with installation_lane(root):
                pass
        mapped = next((root / '.cdmw/virtual-loader/generations').glob('*/files/meta/0.papgt'))
        with pytest.raises(PermissionError):
            mapped.write_bytes(b'changed')
    finally:
        wait.unlink(missing_ok=True)
        if game:
            if kernel.WaitForSingleObject(game, 5000) == 258:
                kernel.TerminateProcess(game, 1)
                kernel.WaitForSingleObject(game, 5000)
            kernel.CloseHandle(game)
        if host.poll() is None:
            host.terminate()
        host.wait(timeout=5)


def test_native_host_and_game_survive_app_lifetime_job_exit(tmp_path):
    import ctypes
    import sys
    root, request, token = fixture(tmp_path)
    wait = root / '.cdmw/virtual-loader/harness-wait.flag'
    wait.touch()
    script = '''
import os,subprocess,sys
from cdmw.services.process_job_service import bind_process_tree_to_app_lifetime,breakaway_creation_flags
assert bind_process_tree_to_app_lifetime()
host=subprocess.Popen(sys.argv[1:],creationflags=breakaway_creation_flags(),stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
print(host.pid,flush=True)
os._exit(0)
'''
    driver = subprocess.run([sys.executable, '-c', script, str(BUILD / 'cdmw_virtual_session.exe'), str(request)],
                            capture_output=True, timeout=15)
    assert driver.returncode == 0, driver.stderr.decode(errors='replace')
    host_pid = int(driver.stdout)
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.OpenProcess.argtypes = [ctypes.c_ulong, ctypes.c_int, ctypes.c_ulong]
    kernel.OpenProcess.restype = ctypes.c_void_p
    kernel.WaitForSingleObject.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
    kernel.TerminateProcess.argtypes = [ctypes.c_void_p, ctypes.c_uint]
    kernel.CloseHandle.argtypes = [ctypes.c_void_p]
    host = kernel.OpenProcess(0x100001, False, host_pid)
    game = None
    try:
        assert host, 'The host died with the app lifetime job.'
        deadline = time.monotonic() + 20
        result = root / '.cdmw/virtual-loader/harness-result.txt'
        while not result.exists() and time.monotonic() < deadline:
            assert kernel.WaitForSingleObject(host, 0) == 258
            time.sleep(.02)
        assert result.is_file()
        report = json.loads((root / f'.cdmw/virtual-loader/session-{token}.json').read_text())
        game = kernel.OpenProcess(0x100001, False, report['pid'])
        assert game and kernel.WaitForSingleObject(game, 0) == 258
    finally:
        wait.unlink(missing_ok=True)
        for handle in (game, host):
            if handle:
                if kernel.WaitForSingleObject(handle, 5000) == 258:
                    kernel.TerminateProcess(handle, 1)
                    kernel.WaitForSingleObject(handle, 5000)
                kernel.CloseHandle(handle)
