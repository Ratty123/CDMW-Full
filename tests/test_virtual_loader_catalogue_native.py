"""Native metadata guards and final output checks use the isolated test runtime."""
import json
import os
from pathlib import Path
import subprocess
import time

import pytest

from cdmw.services.new_item_provenance import _stamp
from tests.test_virtual_loader_native import fixture, TEST_HOST, pytestmark


@pytest.mark.parametrize('change', ['none', 'irrelevant_bytes', 'size', 'time', 'missing', 'appeared'])
def test_catalogue_metadata_policy_is_enforced_before_test_launch(tmp_path, change):
    path = tmp_path / 'game with spaces ü/0011/0.paz'
    path.parent.mkdir(parents=True)
    if change != 'appeared':
        path.write_bytes(b'irrelevant bytes')
    before = path.stat() if path.exists() else None
    root, request, _ = fixture(tmp_path, steam=True, catalogue=((str(path), _stamp(path)),))
    if change == 'irrelevant_bytes':
        path.write_bytes(b'other data here!')
        os.utime(path, ns=(before.st_atime_ns, before.st_mtime_ns))
    elif change == 'size':
        path.write_bytes(b'longer catalogue carrier')
    elif change == 'time':
        os.utime(path, ns=(before.st_atime_ns, before.st_mtime_ns + 1_000_000_000))
    elif change == 'missing':
        path.unlink()
    elif change == 'appeared':
        path.write_bytes(b'previously absent')
    result = subprocess.run([str(TEST_HOST), str(request)], capture_output=True, timeout=40)
    if change in ('none', 'irrelevant_bytes'):
        assert result.returncode == 0, result.stderr
        assert (root / '.cdmw/virtual-loader/harness-result.txt').read_text() == 'native IO passed'
    else:
        assert result.returncode != 0 and b'catalogue' in result.stderr
        assert b'0011' in result.stderr and b'0.paz' in result.stderr
        assert not (root / '.cdmw/virtual-loader/harness-result.txt').exists()
        assert not (root / '.cdmw/virtual-loader/session.bin').exists()


def test_catalogue_file_stays_pinned_until_test_session_ends(tmp_path):
    path = tmp_path / 'game with spaces ü/0011/0.paz'
    path.parent.mkdir(parents=True)
    path.write_bytes(b'catalogue source')
    root, request, token = fixture(tmp_path, catalogue=((str(path), _stamp(path)),))
    wait = root / '.cdmw/virtual-loader/harness-wait.flag'
    wait.touch()
    report = root / f'.cdmw/virtual-loader/session-{token}.json'
    host = subprocess.Popen([str(TEST_HOST), str(request)], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        deadline, running = time.monotonic() + 20, False
        while host.poll() is None and time.monotonic() < deadline:
            if report.exists() and json.loads(report.read_bytes())['state'] == 'running':
                running = True
                with pytest.raises(PermissionError):
                    path.write_bytes(b'changed')
                with pytest.raises(PermissionError):
                    path.rename(path.with_name('replacement.paz'))
                wait.unlink()
                break
            time.sleep(.01)
        _, error = host.communicate(timeout=10)
        assert running and host.returncode == 0, error
        path.write_bytes(b'writable after the session')
    finally:
        wait.unlink(missing_ok=True)
        if host.poll() is None:
            host.terminate()
        host.communicate(timeout=10)


def test_unknown_catalogue_wire_version_is_refused_before_launch(tmp_path):
    root, request, _ = fixture(tmp_path, steam=True)
    data = bytearray(request.read_bytes())
    data[:8] = b'CDVFS9\0\0'
    request.write_bytes(data)
    result = subprocess.run([str(TEST_HOST), str(request)], capture_output=True, timeout=10)
    assert result.returncode != 0
    assert not (root / '.cdmw/virtual-loader/harness-result.txt').exists()


def test_catalogue_path_cannot_escape_through_a_directory_junction(tmp_path):
    outside = tmp_path / 'other archive storage'
    outside.mkdir()
    (outside / '0.paz').write_bytes(b'outside catalogue bytes')
    root = tmp_path / 'game with spaces ü'
    root.mkdir()
    junction = root / '0011'
    linked = subprocess.run(['cmd.exe', '/d', '/c', 'mklink', '/J', str(junction), str(outside)],
                            capture_output=True, timeout=10)
    if linked.returncode:
        pytest.skip('This Windows fixture volume cannot create a directory junction.')
    path = junction / '0.paz'
    try:
        root, request, _ = fixture(tmp_path, catalogue=((str(path), _stamp(path)),))
        result = subprocess.run([str(TEST_HOST), str(request)], capture_output=True, timeout=10)
        assert result.returncode != 0 and b'linked virtual paths' in result.stderr.lower()
        assert not (root / '.cdmw/virtual-loader/harness-result.txt').exists()
    finally:
        os.rmdir(junction)
