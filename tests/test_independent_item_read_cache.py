"""Preparation-local reuse retains ZIP admission, source guards and ownership."""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import io
import struct
import threading
from uuid import uuid4
import zipfile

import pytest

from cdmw.domain.cancellation import RunCancelled
from cdmw.services import independent_item_package as owner
from cdmw.services.independent_mod_package import migrate_v1
from tests.test_independent_item_streaming import package, single_write_zip


def another(package):
    metadata = deepcopy(owner.package_metadata(package))
    metadata['identity'] = uuid4().hex
    return owner._package(metadata, dict(package.blobs))


@pytest.mark.parametrize('v2', [False, True])
def test_exact_artifact_cache_reuses_decode_but_not_mutable_metadata(package, monkeypatch, v2):
    package = migrate_v1(package) if v2 else package
    raw = owner.package_bytes(package)
    cache = owner.PackageReadCache()
    first = owner.read_package(raw, cache=cache)
    if v2:
        first.manifest['metadata']['caller'] = True
    else:
        first.recipe['variants'].append({'caller': True})
    first.dependencies.clear()
    first.blobs.clear()
    monkeypatch.setattr(owner, '_read_member', lambda *args: pytest.fail('Cached artifact decoded again'))
    second = owner.read_package(raw, cache=cache)
    assert second == package and second.artifact_digest == owner.digest(raw)
    assert second.blobs is not first.blobs


def test_different_artifacts_share_only_verified_compressed_representations(package, monkeypatch):
    left, right = package, another(package)
    cache = owner.PackageReadCache()
    decoded = []
    read = zipfile.ZipExtFile.read
    def count(reader, size=-1):
        value = read(reader, size)
        if reader.name.startswith('assets/') and value:
            decoded.append(len(value))
        return value
    monkeypatch.setattr(zipfile.ZipExtFile, 'read', count)
    first = owner.read_package(owner.package_bytes(left), cache=cache)
    first_bytes = sum(decoded)
    second = owner.read_package(owner.package_bytes(right), cache=cache)
    assert first_bytes == sum(map(len, left.blobs.values())) == sum(decoded)
    assert first == left and second == right and first.identity != second.identity
    assert first.blobs is not second.blobs
    assert all(first.blobs[key] is second.blobs[key] for key in first.blobs)
    separate = owner.read_package(owner.package_bytes(left), cache=owner.PackageReadCache())
    assert all(separate.blobs[key] is not first.blobs[key] for key in first.blobs)


@pytest.mark.parametrize('failure', ['crc', 'size', 'local-name', 'payload', 'missing'])
def test_cached_blob_cannot_admit_a_malformed_new_archive(package, failure):
    cache = owner.PackageReadCache()
    original = single_write_zip(package, zipfile.ZIP_STORED)
    owner.read_package(original, cache=cache)
    data = bytearray(single_write_zip(another(package), zipfile.ZIP_STORED))
    if failure == 'missing':
        stream = io.BytesIO()
        with zipfile.ZipFile(stream, 'w') as archive:
            archive.writestr('item.json', owner.canonical(owner.package_metadata(another(package))))
        data = bytearray(stream.getvalue())
    else:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            entry = next(info for info in archive.infolist() if info.filename.startswith('assets/'))
            central = archive.start_dir
        if failure in ('crc', 'size'):
            while data[central:central + 4] == b'PK\x01\x02':
                name_len, extra_len, comment_len = struct.unpack_from('<HHH', data, central + 28)
                name = data[central + 46:central + 46 + name_len]
                if name.startswith(b'assets/'):
                    offset = 16 if failure == 'crc' else 24
                    value, = struct.unpack_from('<I', data, central + offset)
                    struct.pack_into('<I', data, central + offset, value + 1)
                    break
                central += 46 + name_len + extra_len + comment_len
        elif failure == 'local-name':
            data[entry.header_offset + 30] ^= 1
        else:
            name_len, extra_len = struct.unpack_from('<HH', data, entry.header_offset + 26)
            data[entry.header_offset + 30 + name_len + extra_len + entry.file_size - 1] ^= 1
    with pytest.raises(owner.IndependentItemError):
        owner.read_package(bytes(data), cache=cache)
    assert owner.read_package(original, cache=cache) == package


def test_a_claimed_hash_with_valid_crc_cannot_poison_shared_content(package):
    cache = owner.PackageReadCache()
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, 'w', zipfile.ZIP_DEFLATED) as archive:
        archive.writestr('item.json', owner.canonical(owner.package_metadata(package)))
        for key, data in package.blobs.items():
            archive.writestr('assets/' + key, data[:-1] + bytes([data[-1] ^ 1]))
    with pytest.raises(owner.IndependentItemError, match='checksum'):
        owner.read_package(stream.getvalue(), cache=cache)
    assert not cache._members and not cache._packages
    assert owner.read_package(owner.package_bytes(package), cache=cache) == package


def test_cache_hit_still_checks_a_mutable_artifact_after_read(package, monkeypatch):
    raw = owner.package_bytes(package)
    cache = owner.PackageReadCache()
    owner.read_package(raw, cache=cache)
    fingerprint = owner._artifact_hash
    calls = []
    def race(stream, event):
        value = fingerprint(stream, event)
        calls.append(value)
        if len(calls) == 1:
            stream.seek(0, 2)
            stream.write(b'external change')
        return value
    monkeypatch.setattr(owner, '_artifact_hash', race)
    with pytest.raises(owner.IndependentItemError, match='changed while'):
        owner.read_package(io.BytesIO(raw), cache=cache)
    assert len(calls) == 2


def test_cancelled_decode_never_publishes_partial_cache_entries(package, monkeypatch):
    cache, stop = owner.PackageReadCache(), threading.Event()
    read = zipfile.ZipExtFile.read
    def cancel(reader, size=-1):
        value = read(reader, size)
        if reader.name.startswith('assets/'):
            stop.set()
        return value
    monkeypatch.setattr(zipfile.ZipExtFile, 'read', cancel)
    with pytest.raises(RunCancelled):
        owner.read_package(owner.package_bytes(package), cache=cache, stop_event=stop)
    assert not cache._members and not cache._packages


def test_verified_cache_is_bounded_and_safe_for_concurrent_readers(package):
    raw = owner.package_bytes(package)
    size = sum(map(len, package.blobs.values()))
    cache = owner.PackageReadCache(max_bytes=size, max_packages=1)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: owner.read_package(raw, cache=cache), range(4)))
    assert all(result == package for result in results)
    assert all(left.blobs is not right.blobs for left, right in zip(results, results[1:]))
    assert cache._member_bytes <= size and cache._package_bytes <= size
    assert len(cache._packages) <= 1
    tiny = owner.PackageReadCache(max_bytes=max(0, size - 1))
    assert owner.read_package(raw, cache=tiny) == package
    assert not tiny._members and not tiny._packages


def test_cached_artifact_cannot_inherit_a_larger_admission_limit(package, monkeypatch):
    raw, cache = owner.package_bytes(package), owner.PackageReadCache()
    owner.read_package(raw, cache=cache)
    monkeypatch.setattr(owner, 'MAX_BLOB', max(map(len, package.blobs.values())) - 1)
    with pytest.raises(owner.IndependentItemError, match='Unsafe or unsupported'):
        owner.read_package(raw, cache=cache)


def test_shared_blobs_do_not_bypass_new_package_capability_refusal(package):
    package = migrate_v1(package)
    raw, cache = owner.package_bytes(package), owner.PackageReadCache()
    owner.read_package(raw, cache=cache)
    meta = deepcopy(owner.package_metadata(package))
    meta['requires']['unimplemented.behavior'] = 1
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, 'w', zipfile.ZIP_DEFLATED) as archive:
        archive.writestr('item.json', owner.canonical(meta))
        for key, value in package.blobs.items():
            archive.writestr('assets/' + key, value)
    with pytest.raises(owner.IndependentItemError, match='Unsupported required capability'):
        owner.read_package(stream.getvalue(), cache=cache)
    assert owner.read_package(raw, cache=cache) == package


def test_ordinary_package_semantic_dispatch_does_not_read_whole_artifact(package, tmp_path, monkeypatch):
    from cdmw.core import mod_compatibility
    path = tmp_path / 'ordinary.cditem'
    path.write_bytes(owner.package_bytes(package))
    monkeypatch.setattr(mod_compatibility, 'hash_file', lambda *args: pytest.fail('Ordinary package hashed for dispatch'))
    assert mod_compatibility.read_semantic_export(path) is None
