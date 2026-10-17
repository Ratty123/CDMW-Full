"""A cloned record keeps its source provenance without inheriting donor edits."""
from copy import deepcopy
from dataclasses import replace
from uuid import uuid4

import pytest

from cdmw.core.iteminfo_row import parse_iteminfo_row
from cdmw.domain.archives.overlay_merge import OverlayConflict, _table
from cdmw.domain.virtual_loader import VirtualProfile
from cdmw.services import independent_item_install as install
from cdmw.services.independent_item_package import from_plan, package_bytes
from cdmw.services.virtual_loader_composition import prepare_profile
from cdmw.services.virtual_loader_state import load_profile, publish_profile
from tests.test_archive_overlay_manager import Backups, shop_spec, snapshot_of
from tests.test_independent_item_compatibility import mount_mod, table_change
from tests.test_independent_item_regressions import files_in
from tests.test_independent_items import authored, setup_game
from tests.test_new_item_service import TEMPLATE


@pytest.mark.parametrize('target', ['archive', 'virtual'])
def test_cloned_record_preserves_external_donor_edit_and_retained_source(tmp_path, target, monkeypatch):
    # This test publishes only the synthetic archive under tmp_path.
    monkeypatch.setattr('cdmw.services.new_item_service.game_is_running', lambda: False)
    _plan, package = authored(tmp_path / 'author')
    _, stock, _ = setup_game(tmp_path / 'recipient')
    root = tmp_path / 'recipient/game'
    body = stock.iteminfo.payload_entry.path
    head = stock.iteminfo.header_entry.path
    source = tmp_path / 'item.cditem'
    source.write_bytes(package_bytes(package))
    clean = install.resolve_items([source], root, target=target)
    key = clean.registry['items'][package.identity]['values']['iteminfo']['item']
    changes = clean.contributions[0][1]
    own_bytes = dict(_table(changes[body]['after'], changes[head]['after'])[1])[key.to_bytes(4, 'little')]
    foreign = table_change(stock, 'iteminfo', TEMPLATE)
    donor_bytes = dict(_table(foreign[body], foreign[head])[1])[TEMPLATE.to_bytes(4, 'little')]
    assert parse_iteminfo_row(own_bytes).max_stack_count != parse_iteminfo_row(donor_bytes).max_stack_count
    mounted = mount_mod(root, tmp_path / 'foreign', foreign, first=True)
    before = files_in(root)
    backups = Backups(tmp_path)

    def apply():
        if target == 'archive':
            preparation = install.prepare_install([source], root).preparation
            if preparation is not None:
                backups.apply(preparation)
        else:
            publish_profile(prepare_profile(VirtualProfile((source,)), root))

    def visible_rows():
        if target == 'archive':
            return {key: row.raw for key, row in snapshot_of(root).rows.items()}
        from cdmw.core.archive_extraction import read_archive_entry_data
        from cdmw.core.archive_format import parse_archive_pamt
        generation = root / '.cdmw/virtual-loader/generations' / load_profile(root)['generation'] / 'files'
        entries = {entry.path: entry for entry in parse_archive_pamt(next(generation.glob('*/0.pamt')))}
        payload, header = (read_archive_entry_data(entries[path])[0] for path in (body, head))
        return {int.from_bytes(raw_key, 'little'): raw for raw_key, raw in _table(payload, header)[1]}

    apply()
    assert visible_rows()[TEMPLATE] == donor_bytes
    assert visible_rows()[key] == own_bytes
    bindings = install.load_registry(root)['items'][package.identity]['binding_hash']
    # The retained-layer path must make the same decision as initial compilation.
    apply()
    assert visible_rows()[TEMPLATE] == donor_bytes
    assert visible_rows()[key] == own_bytes
    assert install.load_registry(root)['items'][package.identity]['binding_hash'] == bindings
    assert package.dependencies[body] == clean.contributions[0][0].dependencies[body]
    assert all(path.read_bytes() == data for path, data in mounted.items())
    assert all((root / path).read_bytes() == data for path, data in before.items()
               if path.parts[0] == '0009')
    if target == 'virtual':
        assert all((root / path).read_bytes() == data for path, data in before.items())
    else:
        backups.apply(install.prepare_remove(package.identity, root))
        assert snapshot_of(root).rows[TEMPLATE].raw == donor_bytes
        assert key not in snapshot_of(root).rows


@pytest.mark.parametrize('target', ['archive', 'virtual'])
def test_final_explicit_donor_reference_remains_protected(tmp_path, target):
    service, snapshot, _ = setup_game(tmp_path / 'author')
    choice = replace(shop_spec('BorrowedDonorRecord'), socket_items=(TEMPLATE,))
    plan = service.plan(choice, snapshot, capture_independent=True)
    package = from_plan(plan, uuid4().hex)
    _, stock, _ = setup_game(tmp_path / 'recipient')
    root = tmp_path / 'recipient/game'
    mount_mod(root, tmp_path / 'foreign', table_change(stock, 'iteminfo', TEMPLATE), first=True)
    before = files_in(root)
    with pytest.raises(OverlayConflict, match=rf'foreign.*iteminfo.*record {TEMPLATE}'):
        install.resolve_items([package_bytes(package)], root, target=target)
    assert files_in(root) == before


@pytest.mark.parametrize('identity', ['numeric', 'mixed-name', 'name-hash'])
def test_opaque_emitted_donor_identity_keeps_record_protection(tmp_path, identity):
    from cdmw.core.stringinfo_table import stringinfo_key
    from cdmw.services.independent_item_compatibility import (
        _required_keys, check_package_dependencies, external_mods,
    )
    from tests.test_new_item_service import _table4

    _, package = authored(tmp_path / 'author')
    _, stock, _ = setup_game(tmp_path / 'recipient')
    root = tmp_path / 'recipient/game'
    resolved = install.resolve_items([package_bytes(package)], root, target='virtual')
    changes = deepcopy(resolved.contributions[0][1])
    assert TEMPLATE not in _required_keys(package, stock, changes)['iteminfo']
    source_name = stock.rows[TEMPLATE].string_key
    token = {
        'numeric': TEMPLATE.to_bytes(4, 'little'),
        'mixed-name': source_name.swapcase().encode('ascii'),
        'name-hash': stringinfo_key(source_name.lower()).to_bytes(4, 'little'),
    }[identity]
    body, head = stock.iteminfo.payload_entry.path, stock.iteminfo.header_entry.path
    key = resolved.registry['items'][package.identity]['values']['iteminfo']['item']
    rows = [(int.from_bytes(raw_key, 'little'), raw + token if int.from_bytes(raw_key, 'little') == key else raw)
            for raw_key, raw in _table(changes[body]['after'], changes[head]['after'])[1]]
    changes[body]['after'], changes[head]['after'] = _table4(rows)
    # The opaque tail is carried, so absence of a decoded reference is insufficient.
    assert TEMPLATE in _required_keys(package, stock, changes)['iteminfo']
    mount_mod(root, tmp_path / 'foreign', table_change(stock, 'iteminfo', TEMPLATE), first=True)
    before = files_in(root)
    external = external_mods(root, resolved.state)
    with pytest.raises(OverlayConflict, match=rf'foreign.*iteminfo.*record {TEMPLATE}'):
        check_package_dependencies(package, stock, external, changes)
    assert files_in(root) == before


@pytest.mark.parametrize('reverse', [False, True])
@pytest.mark.parametrize('route', ['batch', 'later', 'virtual'])
def test_donor_field_operation_coexists_with_cloned_record_in_either_order(tmp_path, reverse, route, monkeypatch):
    from tests.test_independent_item_fields import field_package, virtual_row

    # The host's running game has no relation to these generated test archives.
    monkeypatch.setattr('cdmw.services.new_item_service.game_is_running', lambda: False)
    _, legacy = authored(tmp_path / 'author')
    _, stock, _ = setup_game(tmp_path / 'recipient')
    root = tmp_path / 'recipient/game'
    edited = field_package(stock, value=7)
    target = 'virtual' if route == 'virtual' else 'archive'
    clean = install.resolve_items([package_bytes(legacy)], root, target=target)
    key = clean.registry['items'][legacy.identity]['values']['iteminfo']['item']
    body, head = stock.iteminfo.payload_entry.path, stock.iteminfo.header_entry.path
    changes = clean.contributions[0][1]
    own_bytes = dict(_table(changes[body]['after'], changes[head]['after'])[1])[key.to_bytes(4, 'little')]
    packages = [legacy, edited][::-1] if reverse else [legacy, edited]
    before = files_in(root)
    backups = Backups(tmp_path)
    paths = {}
    if route == 'virtual':
        for package in packages:
            path = tmp_path / f'{package.identity}.cditem'
            path.write_bytes(package_bytes(package))
            paths[package.identity] = path
        publish_profile(prepare_profile(VirtualProfile(tuple(paths.values())), root))
    else:
        batches = [packages] if route == 'batch' else [[package] for package in packages]
        for batch in batches:
            backups.apply(install.prepare_install([package_bytes(package) for package in batch], root).preparation)

    def row(item_key):
        return virtual_row(root, item_key) if route == 'virtual' else snapshot_of(root).rows[item_key]

    assert row(TEMPLATE).max_stack_count == 7
    assert row(key).raw == own_bytes
    binding = install.load_registry(root)['items'][legacy.identity]['binding_hash']
    if route == 'virtual':
        publish_profile(prepare_profile(VirtualProfile((paths[legacy.identity],)), root))
    else:
        backups.apply(install.prepare_remove(edited.identity, root))
    assert row(TEMPLATE).raw == stock.rows[TEMPLATE].raw
    assert row(key).raw == own_bytes
    assert install.load_registry(root)['items'][legacy.identity]['binding_hash'] == binding
    assert all((root / path).read_bytes() == data for path, data in before.items()
               if path.parts[0] == '0009')
    if route == 'virtual':
        assert all((root / path).read_bytes() == data for path, data in before.items())


@pytest.mark.parametrize('name', ['Ziane_OneHandSword\u00e9', 'Ziane_OneHandSword\x00alias'])
def test_unknown_donor_name_encoding_keeps_record_protection(tmp_path, name):
    import struct
    from types import SimpleNamespace
    from cdmw.services.independent_item_compatibility import _required_keys
    from tests.test_new_item_service import _table4

    _, package = authored(tmp_path / 'author')
    _, stock, _ = setup_game(tmp_path / 'recipient')
    resolved = install.resolve_items([package_bytes(package)], tmp_path / 'recipient/game', target='virtual')
    changes = deepcopy(resolved.contributions[0][1])
    assert TEMPLATE not in _required_keys(package, stock, changes)['iteminfo']
    original = stock.rows[TEMPLATE]
    encoded = name.encode('utf-8')
    raw = original.raw[:4] + struct.pack('<I', len(encoded)) + encoded + original.raw[8 + len(original.string_key.encode('utf-8')):]
    donor = parse_iteminfo_row(raw)
    assert donor.string_key == name
    source = SimpleNamespace(rows={**stock.rows, TEMPLATE: donor})
    body, head = stock.iteminfo.payload_entry.path, stock.iteminfo.header_entry.path
    # Both sides carry the same source record. Only the clone has a new identity.
    for version in ('before', 'after'):
        rows = [(int.from_bytes(key, 'little'), raw if int.from_bytes(key, 'little') == TEMPLATE else data)
                for key, data in _table(changes[body][version], changes[head][version])[1]]
        changes[body][version], changes[head][version] = _table4(rows)
    assert TEMPLATE in _required_keys(package, source, changes)['iteminfo']


@pytest.mark.parametrize('target', ['archive', 'virtual'])
def test_external_iteminfo_record_key_must_match_its_directory(tmp_path, target):
    from cdmw.core.iteminfo_row import clone_iteminfo_row
    from tests.test_new_item_service import _table4

    _, package = authored(tmp_path / 'author')
    _, stock, _ = setup_game(tmp_path / 'recipient')
    root = tmp_path / 'recipient/game'
    clean = install.resolve_items([package_bytes(package)], root, target=target)
    key = clean.registry['items'][package.identity]['values']['iteminfo']['item']
    body, head = stock.iteminfo.payload_entry.path, stock.iteminfo.header_entry.path
    source_row = stock.rows[TEMPLATE]
    wrong_identity = clone_iteminfo_row(source_row, key=key, string_key=source_row.string_key,
                                      name_key=source_row.name_key, desc_key=source_row.desc_key)
    rows = [(int.from_bytes(directory_key, 'little'),
             wrong_identity if int.from_bytes(directory_key, 'little') == TEMPLATE else raw)
            for directory_key, raw in _table(stock.payload(body), stock.payload(head))[1]]
    payload, header = _table4(rows)
    # Directory parsing alone accepts this; the inline ItemInfo identity must agree.
    donor = dict(_table(payload, header)[1])[TEMPLATE.to_bytes(4, 'little')]
    assert donor == source_row.raw.replace(TEMPLATE.to_bytes(4, 'little'), key.to_bytes(4, 'little'))
    assert parse_iteminfo_row(donor).key == key
    mount_mod(root, tmp_path / 'foreign', {body: payload, head: header}, first=True)
    before = files_in(root)
    with pytest.raises(OverlayConflict,
                       match=rf'foreign.*iteminfo.*directory key {TEMPLATE}.*record key {key}'):
        install.resolve_items([package_bytes(package)], root, target=target)
    assert files_in(root) == before
