"""Cancellation during actual ZIP member I/O must stop before returning content."""
from dataclasses import replace
import io
import os
import struct
import threading
from uuid import uuid4
import zipfile

import pytest

from cdmw.core.item_icon_addition import NewItemIcon, icon_string_for_stem, icon_target_path
from cdmw.core.stringinfo_table import stringinfo_key
from cdmw.domain.cancellation import RunCancelled
from cdmw.domain.new_item.spec import IconSource
from cdmw.services import independent_item_package as owner
from cdmw.services.independent_mod_package import migrate_v1
from tests.test_archive_overlay_manager import shop_spec
from tests.test_independent_items import setup_game
from tests.test_new_item_service import _fake_dds


@pytest.fixture
def package(tmp_path):
    service, snapshot, _ = setup_game(tmp_path)
    spec = replace(shop_spec('ChunkedIcon'), icon=IconSource.GENERATED)
    name = icon_string_for_stem(service.allocate(spec, snapshot).stem)
    icon = NewItemIcon(name, stringinfo_key(name), icon_target_path(name), _fake_dds(), None, None)
    return owner.from_plan(service.plan(spec, snapshot, icon=icon, capture_independent=True), uuid4().hex)


def single_write_zip(package, compression=zipfile.ZIP_DEFLATED):
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, 'w') as archive:
        for name, payload in [('item.json', owner.canonical(owner.package_metadata(package))),
                              *[('assets/' + key, value) for key, value in sorted(package.blobs.items())]]:
            info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            info.create_system = 3
            info.external_attr = 0o600 << 16
            info.compress_type = compression
            archive.writestr(info, payload)
    return stream.getvalue()


@pytest.mark.parametrize('asset', [False, True])
def test_cancel_inside_member_read_never_returns_a_package(package, monkeypatch, asset):
    source = owner.package_bytes(package)
    stop, reads = threading.Event(), []
    read = zipfile.ZipExtFile.read
    monkeypatch.setattr(owner, '_ZIP_CHUNK_BYTES', 64, raising=False)
    def cancel(reader, size=-1):
        value = read(reader, size)
        if reader.name.startswith('assets/') == asset:
            reads.append(len(value))
            stop.set()
        return value
    monkeypatch.setattr(zipfile.ZipExtFile, 'read', cancel)
    with pytest.raises(RunCancelled):
        owner.read_package(source, stop_event=stop)
    assert reads and sum(reads) <= 64


@pytest.mark.parametrize('v2', [False, True])
def test_chunked_export_preserves_content_and_has_a_reproducible_artifact(package, tmp_path, monkeypatch, v2):
    package = migrate_v1(package) if v2 else package
    expected = single_write_zip(package)
    monkeypatch.setattr(owner, '_ZIP_CHUNK_BYTES', 64, raising=False)
    actual = owner.package_bytes(package)
    assert actual == owner.package_bytes(package)
    # DEFLATE output can depend on write boundaries. Artifact bytes are tracked
    # separately; the frozen wire meaning, logical UUID and content stay exact.
    before, after = owner.read_package(expected), owner.read_package(actual)
    assert before == after == package
    assert before.identity == after.identity and before.digest == after.digest
    assert after.artifact_digest == owner.digest(actual)
    output = tmp_path / 'streamed.cditem'
    owner.write_package(package, output)
    assert output.read_bytes() == actual


def test_crc_failure_is_not_hidden_by_member_streaming(package, monkeypatch):
    data = bytearray(single_write_zip(package, zipfile.ZIP_STORED))
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        entry = next(info for info in archive.infolist() if info.filename.startswith('assets/'))
        name_size, extra_size = struct.unpack_from('<HH', data, entry.header_offset + 26)
        data[entry.header_offset + 30 + name_size + extra_size + entry.file_size - 1] ^= 1
    monkeypatch.setattr(owner, '_ZIP_CHUNK_BYTES', 64, raising=False)
    with pytest.raises(ValueError, match='CRC'):
        owner.read_package(bytes(data))


def test_cancel_inside_export_preserves_existing_package(package, tmp_path, monkeypatch):
    path = tmp_path / 'existing.cditem'
    owner.write_package(package, path)
    original = path.read_bytes()
    stop, writes = threading.Event(), []
    write = zipfile._ZipWriteFile.write
    monkeypatch.setattr(owner, '_ZIP_CHUNK_BYTES', 64, raising=False)
    def cancel(writer, data):
        result = write(writer, data)
        if writer._zinfo.filename.startswith('assets/'):
            writes.append(len(data))
            stop.set()
        return result
    monkeypatch.setattr(zipfile._ZipWriteFile, 'write', cancel)
    with pytest.raises(RunCancelled):
        owner.write_package(package, path, expected_digest=package.digest, stop_event=stop)
    assert path.read_bytes() == original
    assert writes and sum(writes) <= 64


def test_update_can_cancel_while_validating_previous_package(package, tmp_path, monkeypatch):
    path = tmp_path / 'previous.cditem'
    owner.write_package(package, path)
    original = path.read_bytes()
    stop, reads = threading.Event(), []
    read = zipfile.ZipExtFile.read
    monkeypatch.setattr(owner, '_ZIP_CHUNK_BYTES', 64)
    def cancel(reader, size=-1):
        value = read(reader, size)
        if reader.name.startswith('assets/'):
            reads.append(len(value))
            stop.set()
        return value
    monkeypatch.setattr(zipfile.ZipExtFile, 'read', cancel)
    with pytest.raises(RunCancelled):
        owner.write_package(package, path, expected_digest=package.digest, stop_event=stop)
    assert reads and sum(reads) <= 64
    assert path.read_bytes() == original and not list(tmp_path.glob('.cditem-*.tmp'))


@pytest.mark.parametrize('budget', ['blob', 'expanded'])
@pytest.mark.parametrize('destination', ['bytes', 'file'])
def test_export_refuses_resources_that_its_reader_cannot_admit(package, tmp_path, monkeypatch, budget, destination):
    output = tmp_path / 'oversized.cditem'
    if budget == 'blob':
        monkeypatch.setattr(owner, 'MAX_BLOB', max(map(len, package.blobs.values())) - 1)
    else:
        # The expanded reader budget includes the manifest, not just assets.
        monkeypatch.setattr(owner, 'MAX_TOTAL', sum(map(len, package.blobs.values()))
                            + len(owner.canonical(owner.package_metadata(package))) - 1)
    with pytest.raises(owner.IndependentItemError):
        owner.package_bytes(package) if destination == 'bytes' else owner.write_package(package, output)
    assert not output.exists() and not list(tmp_path.glob('.cditem-*.tmp'))


def test_inflated_member_size_cannot_be_returned_as_zero_padded_content(package):
    data = bytearray(single_write_zip(package, zipfile.ZIP_STORED))
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        at = archive.start_dir
    while data[at:at + 4] == b'PK\x01\x02':
        name_len, extra_len, comment_len = struct.unpack_from('<HHH', data, at + 28)
        name = data[at + 46:at + 46 + name_len]
        if name.startswith(b'assets/'):
            size, = struct.unpack_from('<I', data, at + 24)
            struct.pack_into('<I', data, at + 24, size + 17)
            break
        at += 46 + name_len + extra_len + comment_len
    else:
        pytest.fail('No asset member in owned fixture')
    with pytest.raises(owner.IndependentItemError, match='size'):
        owner.read_package(bytes(data))


@pytest.mark.parametrize('existing', [False, True])
def test_destination_artifact_change_with_same_timestamp_is_preserved(package, tmp_path, monkeypatch, existing):
    path = tmp_path / 'changed.cditem'
    if existing:
        owner.write_package(package, path)
        with zipfile.ZipFile(path, 'a') as archive:
            archive.comment = b'old'
        original = path.read_bytes()
        changed = original[:-3] + b'new'  # Same manifest/content, different exact ZIP artifact.
        assert owner.read_package(original).digest == owner.read_package(changed).digest
        stamp = path.stat()
    else:
        changed = b'new external destination'
        stamp = None
    write, mutations = zipfile._ZipWriteFile.write, []
    def mutate(writer, data):
        value = write(writer, data)
        if writer._zinfo.filename.startswith('assets/') and not mutations:
            path.write_bytes(changed)
            if stamp:
                os.utime(path, ns=(stamp.st_atime_ns, stamp.st_mtime_ns))
            mutations.append(True)
        return value
    monkeypatch.setattr(zipfile._ZipWriteFile, 'write', mutate)
    with pytest.raises(owner.IndependentItemError, match='destination changed'):
        owner.write_package(package, path, expected_digest=package.digest if existing else None)
    assert mutations and path.read_bytes() == changed and not list(tmp_path.glob('.cditem-*.tmp'))


@pytest.mark.parametrize('failure', ['write', 'replace'])
def test_streamed_export_io_failure_preserves_previous_package(package, tmp_path, monkeypatch, failure):
    path = tmp_path / 'previous.cditem'
    owner.write_package(package, path)
    original = path.read_bytes()
    if failure == 'write':
        write = zipfile._ZipWriteFile.write
        def fail(writer, data):
            if writer._zinfo.filename.startswith('assets/'):
                raise OSError('injected resource write failure')
            return write(writer, data)
        monkeypatch.setattr(zipfile._ZipWriteFile, 'write', fail)
    else:
        def fail(*args):
            raise OSError('injected publication failure')
        monkeypatch.setattr(owner.os, 'replace', fail)
    with pytest.raises(OSError, match='injected'):
        owner.write_package(package, path, expected_digest=package.digest)
    assert path.read_bytes() == original and not list(tmp_path.glob('.cditem-*.tmp'))


def test_cancel_after_final_destination_guard_still_preserves_previous_export(package, tmp_path, monkeypatch):
    path = tmp_path / 'previous.cditem'
    owner.write_package(package, path)
    original = path.read_bytes()
    stop, writing, replacements = threading.Event(), [], []
    write, fingerprint = zipfile._ZipWriteFile.write, owner._artifact_hash
    def stage(writer, data):
        result = write(writer, data)
        writing.append(True)
        return result
    def cancel_after_guard(source, event):
        value = fingerprint(source, event)
        if writing:
            stop.set()
        return value
    monkeypatch.setattr(zipfile._ZipWriteFile, 'write', stage)
    monkeypatch.setattr(owner, '_artifact_hash', cancel_after_guard)
    monkeypatch.setattr(owner.os, 'replace', lambda *args: replacements.append(args))
    with pytest.raises(RunCancelled):
        owner.write_package(package, path, expected_digest=package.digest, stop_event=stop)
    assert not replacements and path.read_bytes() == original and not list(tmp_path.glob('.cditem-*.tmp'))


def test_cancel_during_final_validation_never_returns_a_completed_import(package, monkeypatch):
    raw = owner.package_bytes(package)
    stop, validate = threading.Event(), owner._package
    def finish(*args):
        result = validate(*args)
        stop.set()
        return result
    monkeypatch.setattr(owner, '_package', finish)
    with pytest.raises(RunCancelled):
        owner.read_package(raw, stop_event=stop)
