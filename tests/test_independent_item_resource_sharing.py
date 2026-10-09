"""Shared immutable payload memory must not share package ownership or trust."""
from dataclasses import replace
import io
from uuid import uuid4
import zipfile

import pytest

from cdmw.core.item_icon_addition import NewItemIcon, icon_string_for_stem, icon_target_path
from cdmw.core.stringinfo_table import stringinfo_key
from cdmw.domain.new_item.spec import IconSource
from cdmw.domain.virtual_loader import VirtualProfile
from cdmw.services import independent_item_install as install
from cdmw.services.independent_item_package import canonical, from_plan, package_bytes, package_metadata
from cdmw.services.independent_mod_package import migrate_v1
from cdmw.services.virtual_loader_composition import prepare_profile
from cdmw.services.virtual_loader_state import load_profile, publish_profile
from tests.test_archive_overlay_manager import Backups, shop_spec, snapshot_of
from tests.test_independent_items import setup_game
from tests.test_new_item_service import _fake_dds
from tests.test_virtual_loader import game_bytes


def authored(tmp_path, v2):
    service, snapshot, _ = setup_game(tmp_path)
    choice = replace(shop_spec('SharedResource'), icon=IconSource.GENERATED)
    name = icon_string_for_stem(service.allocate(choice, snapshot).stem)
    payload = _fake_dds()
    icon = NewItemIcon(name, stringinfo_key(name), icon_target_path(name), payload, None, None)
    plan = service.plan(choice, snapshot, icon=icon, capture_independent=True)
    first, second = (from_plan(plan, uuid4().hex) for _ in range(2))
    updated = from_plan(service.plan(choice, snapshot,
                        icon=replace(icon, payload_data=payload[:-1] + b'\x01'), capture_independent=True), first.identity)
    return tmp_path / 'game', (first, migrate_v1(second) if v2 else second), updated


@pytest.mark.parametrize('v2', [False, True])
@pytest.mark.parametrize('target', ['archive', 'virtual'])
def test_equal_resources_share_memory_only_within_one_preparation(tmp_path, v2, target):
    root, packages, _ = authored(tmp_path, v2)
    before = game_bytes(root)
    sources = tuple(map(package_bytes, packages))
    resolved = install.resolve_items(sources, root, target=target)
    left, right = (package for package, _ in resolved.contributions)
    key, = left.blobs
    assert left.blobs[key] is right.blobs[key]
    assert left.blobs is not right.blobs
    assert (left.identity, left.digest, left.artifact_digest) != (right.identity, right.digest, right.artifact_digest)
    assert left == packages[0] and right == packages[1]
    first, second = (resolved.registry['items'][package.identity] for package in packages)
    assert first['stem'] != second['stem'] and set(first['paths']).isdisjoint(second['paths'])
    again = install.resolve_items(sources, root, target=target)
    assert again.contributions[0][0].blobs[key] is not left.blobs[key]
    assert game_bytes(root) == before and not (root / install.REGISTRY_PATH).exists()


@pytest.mark.parametrize('v2', [False, True])
@pytest.mark.parametrize('target', ['archive', 'virtual'])
def test_shared_payloads_keep_independent_update_removal_and_bindings(tmp_path, v2, target):
    root, packages, updated = authored(tmp_path, v2)
    before = game_bytes(root)
    sources = [tmp_path / f'{index}.cditem' for index in range(2)]
    for source, package in zip(sources, packages):
        source.write_bytes(package_bytes(package))
    backups = Backups(tmp_path)
    def apply(selected):
        if target == 'archive':
            backups.apply(install.prepare_install(selected, root).preparation)
        else:
            publish_profile(prepare_profile(VirtualProfile(tuple(selected)), root))
    def payload(path):
        if target == 'archive':
            return snapshot_of(root).payload(path)
        from cdmw.core.archive_format import parse_archive_pamt
        from cdmw.core.archive_extraction import read_archive_entry_data
        generation = root / '.cdmw/virtual-loader/generations' / load_profile(root)['generation'] / 'files'
        entries = {entry.path: entry for entry in parse_archive_pamt(next(generation.glob('*/0.pamt')))}
        return read_archive_entry_data(entries[path])[0]
    apply(sources)
    rows = install.load_registry(root)['items']
    paths = [next(path for path in rows[package.identity]['paths'] if path.endswith('.dds')) for package in packages]
    assert paths[0] != paths[1] and payload(paths[0]) == payload(paths[1]) == _fake_dds()
    sources[0].write_bytes(package_bytes(updated))
    apply(sources)
    assert payload(paths[0]) == _fake_dds()[:-1] + b'\x01'
    assert payload(paths[1]) == _fake_dds()
    if target == 'archive':
        backups.apply(install.prepare_remove(packages[0].identity, root))
    else:
        apply(sources[1:])
    assert payload(paths[1]) == _fake_dds()
    after = install.load_registry(root)['items']
    assert all(after[identity]['binding_hash'] == row['binding_hash'] for identity, row in rows.items())
    assert all((root / name).read_bytes() == data for name, data in before.items() if name.startswith('0009/'))
    if target == 'virtual':
        assert game_bytes(root) == before


@pytest.mark.parametrize('v2', [False, True])
def test_shared_hash_does_not_bypass_validation_of_later_package(tmp_path, v2):
    root, packages, _ = authored(tmp_path, v2)
    original = game_bytes(root)
    second = packages[1]
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, 'w') as archive:
        archive.writestr('item.json', canonical(package_metadata(second)))
        for key, data in second.blobs.items():
            archive.writestr('assets/' + key, data[:-1] + b'\x01')
    with pytest.raises(install.IndependentItemError, match='checksum'):
        install.resolve_items((package_bytes(packages[0]), stream.getvalue()), root, target='virtual')
    assert game_bytes(root) == original and not (root / install.REGISTRY_PATH).exists()


def test_shared_memory_does_not_increase_the_logical_batch_budget(tmp_path, monkeypatch):
    root, packages, _ = authored(tmp_path, True)
    size = sum(len(canonical(package_metadata(p))) + sum(map(len, p.blobs.values())) for p in packages)
    monkeypatch.setattr(install, 'MAX_TOTAL', size - 1)
    with pytest.raises(install.IndependentItemError, match='batch size limit'):
        install.resolve_items(tuple(map(package_bytes, packages)), root, target='virtual')
    assert not (root / install.REGISTRY_PATH).exists()
