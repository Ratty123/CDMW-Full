"""Source roles retain runtime dependencies and fail closed on uncertain closure."""
from dataclasses import replace
import json
import os
from pathlib import Path
import threading
from uuid import uuid4

import pytest

from cdmw.core.archive_format import parse_archive_pamt
from cdmw.core.archive_overlay import OverlayFile, build_overlay_archive
from cdmw.core.pappt_format import parse_pappt, encode_pappt
from cdmw.core.papgt_format import papgt_with_directory
from cdmw.domain.virtual_loader import VirtualProfile, VirtualLoaderError
from cdmw.services import virtual_loader_composition as composition
from cdmw.services import virtual_loader_runtime as runtime
from cdmw.services.independent_item_package import from_plan, package_bytes
from cdmw.services.new_item_service import NewItemService
from cdmw.services.virtual_loader_state import publish_profile
from tests.test_archive_overlay_manager import shop_spec
from tests.test_independent_items import setup_game
from tests.test_new_item_service import build_package, STEM, HKX, _read


def source_fixture(tmp_path, *, unparsed=False):
    _, initial, _ = setup_game(tmp_path)
    root = tmp_path / 'game'
    files = {path: initial.payload(path) for path in initial.entries}
    texture = f'character/texture/1_pc/{STEM}_d.dds'
    dds = files.pop(texture)
    if not unparsed:
        files.pop(HKX, None)
        path = 'character/bin__/partprefabtable.pappt'
        table = parse_pappt(files[path])
        files[path] = encode_pappt(replace(table, records=tuple(replace(row, sockets_path='') for row in table.records)))
    pamt = build_package(root, files)
    indexes = [pamt]
    for folder, path, raw in (('0010', texture, dds), ('0011', 'character/unrelated.bin', b'unrelated payload')):
        archive = build_overlay_archive([OverlayFile(path, raw, len(raw), 0)])
        target = root / folder
        target.mkdir()
        (target / '0.pamt').write_bytes(archive.pamt_bytes)
        (target / '0.paz').write_bytes(archive.paz_bytes)
        mount = root / 'meta/0.papgt'
        mount.write_bytes(papgt_with_directory(mount.read_bytes(), folder, archive.pamt_checksum, first=True))
        indexes.append(target / '0.pamt')
    entries = tuple(entry for index in indexes for entry in parse_archive_pamt(index))
    service = NewItemService()
    snapshot = service.build_snapshot(entries, read_entry=_read)
    plan = service.plan(shop_spec('SourceClosure'), snapshot, capture_independent=True)
    item = from_plan(plan, uuid4().hex)
    package = tmp_path / 'source-closure.cditem'
    package.write_bytes(package_bytes(item))
    return root, package, texture


def test_runtime_only_texture_keeps_content_guard_and_unused_carrier_keeps_metadata(tmp_path):
    root, package, texture = source_fixture(tmp_path)
    prepared = composition.prepare_profile(VirtualProfile((package,)), root)
    profile = json.loads(prepared.profile)
    content, catalogue = dict(profile['sources']), dict(profile['catalogue'])
    required, unused = root / '0010/0.paz', root / '0011/0.paz'
    assert str(required) in content and str(required) not in catalogue
    assert str(unused) in catalogue and str(unused) not in content
    assert str(root / '0011/0.pamt') in content
    assert any(row.entry.path == texture and row.entry.paz_file == required for row in prepared.source_revision.payloads)
    assert not (root / '.cdmw').exists()


@pytest.mark.parametrize('fallback', ['unparsed', 'provider'])
def test_uncertain_or_competing_provider_closure_retains_full_carrier_guards(tmp_path, fallback):
    root, package, _ = source_fixture(tmp_path, unparsed=fallback == 'unparsed')
    mods = ()
    if fallback == 'provider':
        folder = tmp_path / 'external'
        path = folder / 'files/character/unrelated.bin'
        path.parent.mkdir(parents=True)
        path.write_bytes(b'external provider')
        mods = (folder,)
    prepared = composition.prepare_profile(VirtualProfile((package,), mods), root)
    profile = json.loads(prepared.profile)
    assert str(root / '0011/0.paz') in dict(profile['sources'])
    assert str(root / '0011/0.paz') not in dict(profile['catalogue'])


def test_required_runtime_content_mutation_with_restored_size_and_time_is_refused(tmp_path):
    root, package, _ = source_fixture(tmp_path)
    prepared = composition.prepare_profile(VirtualProfile((package,)), root)
    publish_profile(prepared)
    path = root / '0010/0.paz'
    before = path.stat()
    raw = bytearray(path.read_bytes()); raw[-1] ^= 1
    path.write_bytes(raw)
    os.utime(path, ns=(before.st_atime_ns, before.st_mtime_ns))
    with pytest.raises(VirtualLoaderError, match='0010.*0.paz'):
        runtime.verify_snapshot(root)


def test_child_cannot_relabel_a_read_carrier_as_catalogue_only(tmp_path):
    from cdmw.services import virtual_loader_process as child
    root, package, _ = source_fixture(tmp_path)
    prepared = composition.prepare_profile(VirtualProfile((package,)), root)
    value = json.loads(json.dumps(child._revision_data(prepared.source_revision)))
    value['catalogue'].append(str(root / '0010/0.paz'))
    with pytest.raises(VirtualLoaderError):
        child._revision(value, (root,))


def test_preflight_defers_output_hashes_but_native_manifest_keeps_their_checksums(tmp_path, monkeypatch):
    root, package, _ = source_fixture(tmp_path)
    prepared = composition.prepare_profile(VirtualProfile((package,)), root)
    publish_profile(prepared)
    reads, original = [], runtime.hash_file
    def record(path, *args, **kwargs):
        reads.append(Path(path))
        return original(path, *args, **kwargs)
    monkeypatch.setattr(runtime, 'hash_file', record)
    profile = runtime._snapshot_preflight(root)
    assert package in reads
    assert not any('generations' in path.parts for path in reads)
    _, manifest = runtime.session_manifest(root, profile, mode=2, executable_sha256='a' * 64)
    assert manifest[:8] == b'CDVFS3\0\0'
    assert all(bytes.fromhex(checksum) in manifest for checksum in profile['files'].values())
    missing = root / '.cdmw/virtual-loader/generations' / prepared.generation / 'files/meta/0.papgt'
    missing.unlink()
    with pytest.raises(VirtualLoaderError, match='prepared virtual file changed'):
        runtime._snapshot_preflight(root)


def test_source_progress_counts_bytes_and_cancellation_never_reports_completion(tmp_path):
    from cdmw.domain.cancellation import RunCancelled
    paths = [tmp_path / 'small.bin', tmp_path / 'large.bin']
    paths[0].write_bytes(b'x' * 127)
    paths[1].write_bytes(b'y' * (5 * 1024 * 1024))
    reports = []
    actual = composition._hash_sources(paths, on_progress=lambda *value: reports.append(value))
    assert len(actual) == 2
    assert reports[-1][0] == reports[-1][1] == sum(path.stat().st_size for path in paths)
    assert all('bytes' in detail and ' s;' in detail for _, _, detail in reports)
    assert [value for value, _, _ in reports] == sorted(value for value, _, _ in reports)
    stop = threading.Event()
    cancelled = []
    def cancel(*value):
        cancelled.append(value)
        stop.set()
    with pytest.raises(RunCancelled):
        composition._hash_sources(paths, stop_event=stop, on_progress=cancel)
    assert cancelled and cancelled[-1][0] < cancelled[-1][1]
