"""Launcher-independent profile contracts using owned files, never the real game."""
import json
import struct

import pytest

from cdmw.domain.virtual_loader import VirtualProfile, VirtualLoaderError
from cdmw.services import virtual_loader_runtime as runtime
from cdmw.services import virtual_loader_standalone as standalone
from cdmw.services.virtual_loader_composition import prepare_profile
from cdmw.services.virtual_loader_state import publish_profile
from tests.test_virtual_loader import packages
from tests.test_virtual_loader_runtime import setup_fixture


def decode_manifest(data):
    """Read back the CDVFS3 fields the native runtime validates."""
    assert data[:8] == b'CDVFS3\0\0'
    mode, pid, host_pid = struct.unpack_from('<III', data, 8)
    offset = 8 + 12 + 32
    def number(fmt='<I'):
        nonlocal offset
        values = struct.unpack_from(fmt, data, offset)
        offset += struct.calcsize(fmt)
        return values if len(values) > 1 else values[0]
    def string():
        nonlocal offset
        length = number() * 2
        offset += length
        return data[offset - length:offset].decode('utf-16le')
    def digest():
        nonlocal offset
        offset += 32
        return data[offset - 32:offset].hex()
    root, generation, _token, lane = string(), string(), string(), string()
    files = {}
    for _ in range(number()):
        logical, path = string(), string()
        files[logical] = (path, digest())
    guards = {}
    for _ in range(number()):
        path = string()
        present, checksum = number(), digest()
        guards[path] = checksum if present else None
    catalogue = {}
    for _ in range(number()):
        path = string()
        catalogue[path] = number('<IQQ')
    launcher = number()
    assert offset == len(data)
    return dict(mode=mode, pid=pid, host_pid=host_pid, root=root, generation=generation, lane=lane,
                files=files, guards=guards, catalogue=catalogue, launcher=launcher)


def published(tmp_path, monkeypatch):
    root, files = packages(tmp_path, 1)
    setup_fixture(tmp_path, monkeypatch)
    runtime.apply_runtime_setup(runtime.prepare_runtime_setup(root), confirmed=True)
    profile = publish_profile(prepare_profile(VirtualProfile(files), root))
    return root, files, profile


def test_publication_is_hostless_and_guards_every_source(tmp_path, monkeypatch):
    root, files, profile = published(tmp_path, monkeypatch)
    assert profile['sources']
    publication = standalone.publish_standalone(root)
    assert publication.path == root / standalone.STANDALONE_PATH and standalone.standalone_published(root)
    assert publication.generation == profile['generation']
    manifest = decode_manifest(publication.path.read_bytes())
    assert (manifest['mode'], manifest['pid'], manifest['host_pid'], manifest['launcher']) == (4, 0, 0, 0)
    assert manifest['root'] == str(root) and manifest['generation'] == profile['generation']
    assert set(manifest['files']) == {logical.replace('/', '\\') for logical in profile['files']}
    for path, checksum in profile['sources']:
        assert manifest['guards'][path] == checksum and path not in manifest['catalogue']
    # The installed runtime, its bootstrap and CDMW's own state are content-guarded too.
    for relative in (runtime.RUNTIME_PATH, 'bin64/winmm.dll', '.cdmw/virtual-loader/profile.json'):
        assert str(root / relative) in manifest['guards']
    assert publication.hashed_sources == len(profile['sources']) and publication.catalogue_sources == len(profile['catalogue'])


def test_large_sources_become_size_and_write_time_guards(tmp_path, monkeypatch):
    root, files, profile = published(tmp_path, monkeypatch)
    package = str(files[0])
    assert package in dict(profile['sources'])
    monkeypatch.setattr(standalone, 'HASHED_SOURCE_LIMIT', files[0].stat().st_size - 1)
    publication = standalone.publish_standalone(root)
    manifest = decode_manifest(publication.path.read_bytes())
    stat = files[0].stat()
    assert package not in manifest['guards']
    assert manifest['catalogue'][package] == (1, stat.st_size, stat.st_mtime_ns // 100 + 116444736000000000)
    assert publication.catalogue_sources >= 1
    # Indexes stay content-guarded at any size; a launcher may rewrite them with identical bytes.
    monkeypatch.setattr(standalone, 'HASHED_SOURCE_LIMIT', 0)
    manifest = decode_manifest(standalone.publish_standalone(root).path.read_bytes())
    for path, checksum in profile['sources']:
        if path.endswith(('.papgt', '.pathc', '.pamt')):
            assert manifest['guards'][path] == checksum
        else:
            assert path in manifest['catalogue'] and path not in manifest['guards']


def test_publication_refuses_changed_sources_running_game_and_missing_runtime(tmp_path, monkeypatch):
    root, files, _ = published(tmp_path, monkeypatch)
    monkeypatch.setattr('cdmw.services.new_item_service.game_is_running', lambda: True)
    with pytest.raises(VirtualLoaderError, match='Close Crimson Desert'):
        standalone.publish_standalone(root)
    monkeypatch.setattr('cdmw.services.new_item_service.game_is_running', lambda: False)
    data = bytearray(files[0].read_bytes()); data[-1] ^= 1
    files[0].write_bytes(data)
    with pytest.raises(VirtualLoaderError, match='source changed'):
        standalone.publish_standalone(root)
    assert not standalone.standalone_published(root)
    (root / runtime.RUNTIME_PATH).unlink()
    (root / runtime.OWNER_PATH).unlink()
    with pytest.raises(VirtualLoaderError, match='set up the virtual loader'):
        standalone.publish_standalone(root)
    assert not standalone.standalone_published(root)


def test_republication_clears_the_previous_launch_report_and_withdraw_keeps_profile(tmp_path, monkeypatch):
    root, _, profile = published(tmp_path, monkeypatch)
    report = root / standalone.STATUS_PATH
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(json.dumps({'state': 'refused', 'pid': 7, 'generation': 'old', 'error': 50,
                                  'elapsed_ms': 3, 'detail': 'stale'}))
    standalone.publish_standalone(root)
    assert standalone.read_standalone_status(root) is None
    assert standalone.withdraw_standalone(root) is True
    assert not standalone.standalone_published(root) and standalone.withdraw_standalone(root) is False
    assert (root / '.cdmw/virtual-loader/profile.json').is_file()


def test_status_report_is_validated(tmp_path):
    report = tmp_path / standalone.STATUS_PATH
    report.parent.mkdir(parents=True)
    report.write_text(json.dumps({'state': 'ready', 'pid': 42, 'generation': 'g1', 'error': 0,
                                  'elapsed_ms': 12, 'detail': ''}))
    status = standalone.read_standalone_status(tmp_path)
    assert (status.state, status.pid, status.generation, status.elapsed_ms) == ('ready', 42, 'g1', 12)
    assert json.loads(standalone.status_text(status))['state'] == 'ready'
    for broken in ({'state': 'tracing', 'pid': 42, 'elapsed_ms': 1}, {'state': 'ready', 'pid': 0, 'elapsed_ms': 1},
                   {'state': 'ready', 'pid': 42, 'elapsed_ms': -1}, ['ready']):
        report.write_text(json.dumps(broken))
        with pytest.raises(VirtualLoaderError):
            standalone.read_standalone_status(tmp_path)


def test_trace_rows_decode_with_probe_names_and_ignore_a_torn_tail(tmp_path):
    trace = tmp_path / standalone.TRACE_PATH
    trace.parent.mkdir(parents=True)
    def row(api, redirected, path):
        return struct.pack('<IIIIq1024s', api, 9, redirected, 0, 5, path.encode('utf-16le'))
    trace.write_bytes(row(0, 0, 'CDMW virtual trace v1 (standalone)') + row(1, 1, 'C:\\game\\meta\\0.papgt') + b'torn')
    rows = standalone.read_standalone_trace(tmp_path)
    assert [(r.operation, r.redirected, r.path) for r in rows] == [
        ('initialize', False, 'CDMW virtual trace v1 (standalone)'), ('CreateFileW', True, 'C:\\game\\meta\\0.papgt')]
    assert standalone.read_standalone_trace(tmp_path / 'missing') == []
