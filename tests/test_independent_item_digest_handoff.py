"""Raw-resource hash receipts require exact immutable, fully admitted bytes."""
from dataclasses import replace
import threading

import pytest

from cdmw.core.papgt_format import serialize_papgt
from cdmw.domain.cancellation import RunCancelled
from cdmw.domain.new_item.compilation import compilation_record
from cdmw.domain.virtual_loader import VirtualProfile
from cdmw.services import independent_item_package as package_owner
from cdmw.services import virtual_loader_cache as cache_owner
from cdmw.services import virtual_loader_composition as composition
from tests.test_independent_item_streaming import package


def test_receipts_require_admitted_exact_bytes_and_ignore_caller_metadata(package):
    cache = package_owner.PackageReadCache()
    original = next(iter(package.blobs.values()))
    assert cache.verified_blob_digests([package]).digest(original) is None
    admitted = package_owner.read_package(package_owner.package_bytes(package), cache=cache)
    checksum, raw = next(iter(admitted.blobs.items()))
    copied = bytes(bytearray(raw))
    assert copied == raw and copied is not raw
    nominated = replace(admitted, blobs={'0' * 64: raw, checksum: copied})
    receipts = cache.verified_blob_digests([nominated])
    assert receipts.digest(raw) == checksum
    assert receipts.digest(copied) is None
    assert receipts.digest(bytearray(raw)) is None
    assert receipts.digest(memoryview(raw)) is None
    assert package_owner.PackageReadCache().verified_blob_digests([admitted]).digest(raw) is None
    # The receipt owns immutable evidence, not a mutable package mapping or a
    # bare object id that could outlive the bytes it originally identified.
    admitted.blobs.clear()
    nominated.blobs.clear()
    del cache
    assert receipts.digest(raw) == checksum


def test_uncached_large_package_cannot_supply_digest_receipts(package):
    cache = package_owner.PackageReadCache(max_bytes=0)
    admitted = package_owner.read_package(package_owner.package_bytes(package), cache=cache)
    receipts = cache.verified_blob_digests([admitted])
    assert all(receipts.digest(raw) is None for raw in admitted.blobs.values())


def test_cache_record_skips_only_proven_resource_hashes(package, monkeypatch):
    cache = package_owner.PackageReadCache()
    admitted = package_owner.read_package(package_owner.package_bytes(package), cache=cache)
    raw = next(iter(admitted.blobs.values()))
    copied = bytes(bytearray(raw))
    generated = b'<Record Value="New"/>'
    files = {'character/verified.dds': raw, 'character/copied.dds': copied, 'gamedata/new.txt': generated}
    compiled = compilation_record(scope='virtual-profile', packages=[], sources={}, allocations={},
        order=[], runtime_abi='CDVFS3', outputs={}, providers={})
    options = dict(directory='9000', files=files, flags={}, mount=serialize_papgt(()), pathc=b'texture registry')
    expected = cache_owner.make_cache_record(compiled, **options)
    receipts = cache.verified_blob_digests([admitted])
    hashed = []
    hash_bytes = cache_owner._hash_bytes
    def track(value, event=None):
        hashed.append(value)
        return hash_bytes(value, event)
    monkeypatch.setattr(cache_owner, '_hash_bytes', track)
    assert cache_owner.make_cache_record(compiled, **options, resource_digests=receipts) == expected
    assert all(value is not raw for value in hashed)
    assert all(any(value is required for value in hashed)
               for required in (copied, generated, options['mount'], options['pathc']))
    stop = threading.Event()
    stop.set()
    with pytest.raises(RunCancelled):
        cache_owner.make_cache_record(compiled, **options, resource_digests=receipts, stop_event=stop)


def test_real_lowering_preserves_admitted_dds_identity_into_cache_record(package, tmp_path, monkeypatch):
    path = tmp_path / 'icon.cditem'
    path.write_bytes(package_owner.package_bytes(package))
    make_record = cache_owner.make_cache_record
    observed = []
    def check(compiled, **kwargs):
        resources = [raw for path, raw in kwargs['files'].items() if path.endswith('.dds')]
        assert resources
        receipts = kwargs['resource_digests']
        assert all(receipts.digest(raw) == package_owner.digest(raw) for raw in resources)
        actual = make_record(compiled, **kwargs)
        assert actual == make_record(compiled, **{**kwargs, 'resource_digests': None})
        observed.extend(resources)
        return actual
    monkeypatch.setattr(cache_owner, 'make_cache_record', check)
    prepared = composition.prepare_profile(VirtualProfile((path,)), tmp_path / 'game')
    assert observed and prepared.files
