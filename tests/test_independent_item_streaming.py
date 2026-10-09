"""Cancellation during actual ZIP member I/O must stop before returning content."""
from dataclasses import replace
import io
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
def test_chunked_export_preserves_content_and_has_a_reproducible_artifact(package, monkeypatch, v2):
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
