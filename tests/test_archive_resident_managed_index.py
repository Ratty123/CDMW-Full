"""The Python reader must consume the managed writer's actual published bytes."""
import json
from pathlib import Path
from queue import Queue
import subprocess
import threading
from uuid import uuid4

import pytest

from cdmw.core.archive_format import parse_archive_pamt
from cdmw.core.archive_resident_index import ResidentArchiveIndex, ResidentArchiveSource
from cdmw.domain.archives.catalogue import ArchiveSessionHandle
from tests.test_new_item_service import build_package, synthetic_files


def test_reads_managed_worker_generation(tmp_path):
    worker = Path(__file__).resolve().parents[1] / (
        'tools/dotnet_archive_backend/src/Cdmw.FullArchive.Worker/'
        'bin/Release/net10.0-windows/win-x64/cdmw-full-archive-worker.exe')
    if not worker.is_file():
        pytest.skip('Build the Release FullArchive.Worker before running managed index interop')
    root = tmp_path / 'packages'
    expected = tuple(parse_archive_pamt(build_package(root, synthetic_files())))
    process = subprocess.Popen([str(worker), '--cache-root', str(tmp_path / 'cache')],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    messages = Queue()
    def read():
        for line in process.stdout:
            messages.put(json.loads(line))
        messages.put({'status': 'error', 'error': process.stderr.read()})
    reader = threading.Thread(target=read)
    reader.start()
    try:
        request = dict(protocol_version=3, request_id=str(uuid4()), ui_generation=1,
                       session_id=None, operation='open_archive', status='request',
                       payload=dict(package_root=str(root)))
        process.stdin.write(json.dumps(request) + '\n')
        process.stdin.flush()
        while True:
            message = messages.get(timeout=20)
            if message['status'] in ('result', 'error'):
                break
        assert message['status'] == 'result', message
        session = ArchiveSessionHandle.from_wire(message['payload'])
        source = ResidentArchiveSource(session.package_root, session.fingerprint, session.index_path, session.entry_count)
        index = source.open()
        assert sorted(index, key=lambda row: row.path) == sorted(expected, key=lambda row: row.path)
        assert all(index.active_entry(row.path) == row for row in expected)
        for row in expected:
            assert list(index.by_basename[row.basename.lower()]) == [row]
        if Path(session.index_path).with_suffix('.adi').is_file():
            # A fresh reader has no retry delay if ADI1 arrived during the first
            # queries. Exercise its mapped basename records, not cached answers.
            mapped = ResidentArchiveIndex(source)
            try:
                assert mapped._dependency_index() is not None
                for row in expected:
                    assert list(mapped.by_basename[row.basename.lower()]) == [row]
            finally:
                mapped._mapping.close()
                if mapped._dependency_mapping is not None:
                    mapped._dependency_mapping.close()
    finally:
        process.stdin.close()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)
        reader.join(timeout=5)
        process.stdout.close()
        process.stderr.close()
