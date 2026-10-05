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


def fixture(tmp_path):
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
    token, manifest = session_manifest(root, profile, mode=2, executable_sha256=hash_file(root / 'bin64/cdmw_virtual_loader_harness.exe'))
    request = root / '.cdmw/virtual-loader/request.bin'
    request.write_bytes(manifest)
    return root, request, token


def test_native_session_redirects_real_handles_without_touching_original(tmp_path):
    root, request, token = fixture(tmp_path)
    result = subprocess.run([str(BUILD / 'cdmw_virtual_session.exe'), str(request)], capture_output=True, timeout=40)
    assert result.returncode == 0, result.stderr.decode(errors='replace')
    assert (root / 'meta/0.papgt').read_bytes() == b'original'
    assert (root / '.cdmw/virtual-loader/harness-result.txt').read_text() == 'native IO passed'
    status = json.loads((root / f'.cdmw/virtual-loader/session-{token}.json').read_text())
    assert status['state'] == 'stopped' and status['error'] == 0
    assert not (root / '.cdmw/virtual-loader/session.bin').exists()
    assert (root / f'.cdmw/virtual-loader/trace-{token}.bin').stat().st_size > 0


def test_native_corrupt_snapshot_refuses_before_start(tmp_path):
    root, request, token = fixture(tmp_path)
    next((root / '.cdmw/virtual-loader/generations').glob('*/files/meta/0.papgt')).write_bytes(b'bad')
    result = subprocess.run([str(BUILD / 'cdmw_virtual_session.exe'), str(request)], capture_output=True, timeout=10)
    assert result.returncode != 0 and b'checksum' in result.stderr
    assert not (root / '.cdmw/virtual-loader/harness-result.txt').exists()
    assert (root / 'meta/0.papgt').read_bytes() == b'original'


def test_native_production_redirect_gate_cannot_be_enabled_by_manifest(tmp_path):
    root, request, _token = fixture(tmp_path)
    data = bytearray(request.read_bytes())
    data[8:12] = (1).to_bytes(4, 'little')
    request.write_bytes(data)
    result = subprocess.run([str(BUILD / 'cdmw_virtual_session.exe'), str(request)], capture_output=True, timeout=10)
    assert result.returncode != 0 and b'Game launch blocked' in result.stderr
    assert not (root / '.cdmw/virtual-loader/session.bin').exists()


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


def test_runtime_retains_lease_and_files_when_session_host_dies(tmp_path):
    from cdmw.services.installation_lane import installation_lane
    from cdmw.domain.virtual_loader import VirtualLoaderError
    import ctypes
    root, request, token = fixture(tmp_path)
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
