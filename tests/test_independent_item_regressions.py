"""Reproduce independent-package review failures through their owning callers."""
from copy import deepcopy
from dataclasses import replace
import threading
from uuid import uuid4

import pytest

from cdmw.domain.new_item.independent import IndependentItemError
from cdmw.services import archive_overlay_manager as overlays
from cdmw.services.independent_item_install import (
    REGISTRY_PATH, inventory, load_registry, prepare_install, prepare_remove,
)
from cdmw.services.independent_item_package import digest, from_plan, package_bytes
from tests.test_archive_overlay_manager import Backups, shop_spec, snapshot_of
from tests.test_independent_items import authored, imported_game, setup_game


def files_in(root):
    return {path.relative_to(root): path.read_bytes() for path in root.rglob('*') if path.is_file()}


def test_effect_clone_rebinds_declared_emitter_file_references():
    from cdmw.core.effect_binary import decode_effect_binary
    from cdmw.core.effect_edit import same_length_stem
    from cdmw.services.independent_item_references import rename_effect_references
    from tests.test_effect_edit import EFFECT, TRAIL

    source = EFFECT.read_bytes()
    clone = same_length_stem(TRAIL.stem, '_n90012')
    result = rename_effect_references(source, {TRAIL.stem: clone})
    document = decode_effect_binary(result)
    expected = '/effect/binary__/emitter/' + clone + '.paem'
    original = '/effect/binary__/emitter/' + TRAIL.name
    assert document.walk_complete and len(result) == len(source)
    assert 'emitter/' + clone in document.emitter_names()
    assert expected in [node.type_name for node in document.root.walk()]
    assert expected in [row.type_name for row in document.types]
    assert original not in [row.type_name for row in document.types]
    assert 'emitter/cdem_material_firefly_alpha_uberstandard' in document.emitter_names()
    # A similarly named stem is not a complete reference, even in the header.
    assert rename_effect_references(source, {TRAIL.stem[:-1]: clone[:-1]}) == source


def test_effect_audit_rejects_missing_embedded_emitter_type(tmp_path):
    from cdmw.core.effect_binary import decode_effect_binary, write_value
    from cdmw.core.effect_edit import same_length_stem
    from cdmw.domain.new_item.spec import EffectLook, ModelSource
    from cdmw.services.independent_item_references import audit_references, rename_effect_references
    from cdmw.services.new_item_planning import ModelFiles
    from tests.test_effect_edit import EFFECT
    from tests.test_new_item_service import PAC_XML, imported_pac

    service, snapshot = imported_game(tmp_path / 'author', auxiliaries=True)
    choice = replace(shop_spec('OwnedEffect'), model_source=ModelSource.IMPORTED,
        include_perk_prices=False, effect=EFFECT.stem + '.level.effect',
        effect_look=EffectLook(color=(0, 0, 1), emitter_order=(0,)))
    plan = service.plan(choice, snapshot,
        model=ModelFiles(imported_pac(100), {PAC_XML: snapshot.payload(PAC_XML)}),
        capture_independent=True)
    request = next(item for item in plan.additions if item.path.endswith('.pae'))
    document = decode_effect_binary(request.payload_data)
    emitter = document.emitter_names()[0].split('/')[-1]
    missing = same_length_stem(emitter, '_absent')
    data = rename_effect_references(request.payload_data, {emitter: missing})
    # Keep the ordinary emitter-name reference valid; only the embedded type is missing.
    for value in decode_effect_binary(data).root.all_values():
        if value.name == '_emitterDataName':
            data = write_value(data, value, ('emitter/' + emitter).encode())
    changed = replace(plan, additions=tuple(
        replace(item, payload_data=data) if item is request else item for item in plan.additions))
    with pytest.raises(IndependentItemError, match='Unresolved item dependency: .*' + missing):
        audit_references(changed, snapshot)


def add_external_group(tmp_path, root, name, files, *, present=True):
    from cdmw.core.papgt_format import papgt_with_directory
    from tests.test_new_item_service import build_package
    pamt = build_package(tmp_path / name, files)
    if present:
        directory = root / name
        directory.mkdir()
        for source in pamt.parent.iterdir():
            if source.is_file():
                (directory / source.name).write_bytes(source.read_bytes())
    mount = root / 'meta/0.papgt'
    checksum = int.from_bytes(pamt.read_bytes()[:4], 'little')
    mount.write_bytes(papgt_with_directory(mount.read_bytes(), name, checksum))


@pytest.mark.parametrize('imported', [False, True])
def test_independent_plan_uses_shipped_data_with_named_manager_archives(tmp_path, imported):
    from cdmw.domain.new_item.spec import ModelSource
    from cdmw.services.new_item_planning import ModelFiles
    from cdmw.workers.new_item_workers import plan_task
    from tests.test_new_item_service import PAC_XML, imported_pac
    service, snapshot, _ = setup_game(tmp_path / 'author')
    root = tmp_path / 'author/game'
    choice = replace(shop_spec('NamedArchives'),
                     model_source=ModelSource.IMPORTED if imported else ModelSource.TEMPLATE)
    model = ModelFiles(imported_pac(1), {PAC_XML: snapshot.payload(PAC_XML)}) if imported else None
    task = plan_task(choice, snapshot, service=service, model=model, independent=True)
    expected = task(lambda _: None, threading.Event())
    identity = uuid4().hex
    expected_dependencies = from_plan(expected, identity).dependencies
    for name in ('dmmgen', 'dmmsa'):
        # Valid external archives, but their replacement table is not a verified
        # game input. Authoring must ignore it even when mounted first.
        add_external_group(tmp_path, root, name, {snapshot.iteminfo.payload_entry.path: b'external table'})
    nested = root / 'external-cache/0009'
    nested.mkdir(parents=True)
    (nested / '0.pamt').write_bytes(b'not a shipped archive')
    before = files_in(root)
    actual = task(lambda _: None, threading.Event())
    assert actual.loose_files == expected.loose_files
    assert from_plan(actual, identity).dependencies == expected_dependencies
    assert all(row.entry.pamt_path.parent == root / '0009' for row in actual.source_revision.payloads)
    assert files_in(root) == before


@pytest.mark.parametrize('present', [True, False])
def test_named_manager_archives_survive_independent_item_lifecycle(tmp_path, present):
    from cdmw.core.papgt_format import parse_papgt
    from cdmw.services.archive_overlay_rebuild import prepare_overlay_rebuild
    _, package = authored(tmp_path / 'author')
    _, update = authored(tmp_path / 'update', package.identity, 'UpdatedItem')
    setup_game(tmp_path / 'recipient')
    root, backups = tmp_path / 'recipient/game', Backups(tmp_path)
    for name in ('dmmgen', 'dmmsa'):
        # Deleting a manager folder leaves its name and checksum in PAPGT.
        add_external_group(tmp_path, root, name, {f'ui/texture/{name}.dds': b'unrelated external asset'},
                           present=present)
    groups = {name: files_in(root / name) for name in ('0009', 'dmmgen', 'dmmsa')}
    mount = root / 'meta/0.papgt'
    original_mount = parse_papgt(mount.read_bytes())
    backups.apply(prepare_install([package_bytes(package)], root).preparation)
    binding = load_registry(root)['items'][package.identity]['values']
    backups.apply(prepare_install([package_bytes(update)], root).preparation)
    backups.apply(prepare_overlay_rebuild(root))
    assert inventory(root)[0][3] == 'Installed'
    assert load_registry(root)['items'][package.identity]['values'] == binding
    backups.apply(prepare_remove(package.identity, root))
    assert parse_papgt(mount.read_bytes()) == original_mount
    assert {name: files_in(root / name) for name in groups} == groups


@pytest.mark.parametrize('name', ['dmmgen', 'dmmsa'])
def test_named_external_archive_cannot_claim_an_owned_asset(tmp_path, name):
    from cdmw.core.item_icon_addition import NewItemIcon, icon_string_for_stem, icon_target_path
    from cdmw.core.stringinfo_table import stringinfo_key
    from cdmw.domain.new_item.spec import IconSource
    from tests.test_new_item_service import _fake_dds
    service, snapshot, _ = setup_game(tmp_path / 'recipient')
    root = tmp_path / 'recipient/game'
    choice = replace(shop_spec('OwnedIcon'), icon=IconSource.GENERATED)
    stem = icon_string_for_stem(service.allocate(choice, snapshot).stem)
    icon = NewItemIcon(stem, stringinfo_key(stem), icon_target_path(stem), _fake_dds(), None, None)
    package = from_plan(service.plan(choice, snapshot, icon=icon, capture_independent=True), uuid4().hex)
    add_external_group(tmp_path, root, name, {icon_target_path(stem): _fake_dds()})
    before = files_in(root)
    with pytest.raises(IndependentItemError, match='owned asset name is already reserved'):
        prepare_install([package_bytes(package)], root)
    assert files_in(root) == before


@pytest.mark.parametrize('name', ['../outside', 'nested/mod', r'nested\mod', 'C:mod', '.', 'mod.'])
def test_unsafe_mounted_archive_names_are_refused(tmp_path, name):
    from cdmw.core.papgt_format import papgt_with_directory
    from cdmw.services.independent_item_install import _external_paths
    setup_game(tmp_path / 'recipient')
    root = tmp_path / 'recipient/game'
    mount = root / 'meta/0.papgt'
    mount.write_bytes(papgt_with_directory(mount.read_bytes(), name, 0))
    before = files_in(root)
    with pytest.raises(IndependentItemError, match='Unsupported mounted archive folder'):
        _external_paths(root, {'directory': '0036'})
    assert files_in(root) == before


@pytest.mark.parametrize('operation', ['install', 'remove', 'disable', 'enable', 'rebuild'])
def test_concurrent_package_install_cannot_be_lost_by_an_ordinary_overlay(tmp_path, monkeypatch, operation):
    from cdmw.services.archive_overlay_rebuild import prepare_overlay_rebuild
    _, package = authored(tmp_path / 'author')
    service, snapshot, _ = setup_game(tmp_path / 'recipient')
    root, backups = tmp_path / 'recipient/game', Backups(tmp_path)
    ordinary = service.plan(shop_spec('OrdinaryItem'), snapshot)
    if operation != 'install':
        backups.apply(overlays.prepare_item_overlay(ordinary, root))
        layer = overlays.list_installed_overlays(root)[0].id
        if operation == 'enable':
            backups.apply(overlays.prepare_overlay_enabled(root, layer, False))
    compose = overlays._compose
    installed = None

    def interleave(*args, **kwargs):
        nonlocal installed
        if installed is None:
            installed = {}  # Avoid recursion in the concurrent composition.
            backups.apply(prepare_install([package_bytes(package)], root).preparation)
            installed = files_in(root)
        return compose(*args, **kwargs)

    monkeypatch.setattr(overlays, '_compose', interleave)
    with pytest.raises(ValueError, match='changed'):
        if operation == 'install':
            prepared = overlays.prepare_item_overlay(ordinary, root)
        elif operation == 'remove':
            prepared = overlays.prepare_overlay_removal(root, layer)
        elif operation in ('disable', 'enable'):
            prepared = overlays.prepare_overlay_enabled(root, layer, operation == 'enable')
        else:
            prepared = prepare_overlay_rebuild(root)
        backups.apply(prepared)
    assert installed and files_in(root) == installed
    row = load_registry(root)['items'][package.identity]
    assert snapshot_of(root).rows[row['values']['iteminfo']['item']].string_key == 'CDI_' + package.identity
    assert inventory(root)[0][3] == 'Installed'


@pytest.mark.parametrize('existing', [False, True])
@pytest.mark.parametrize('phase', ['review', 'backup'])
def test_ordinary_publication_rechecks_present_and_absent_identity_ledgers(tmp_path, monkeypatch, existing, phase):
    service, snapshot, _ = setup_game(tmp_path / 'recipient')
    root, backups = tmp_path / 'recipient/game', Backups(tmp_path)
    path = root / REGISTRY_PATH
    empty = b'{"format":"cdmw_independent_identity_profile_v1","items":{}}'
    path.parent.mkdir()
    if existing:
        path.write_bytes(empty)
    prepared = overlays.prepare_item_overlay(service.plan(shop_spec('OrdinaryItem'), snapshot), root)
    before = files_in(root)
    if phase == 'review':
        path.write_bytes(empty + b' ')
    else:
        backup = backups.backup_files

        def change_during_backup(*args, **kwargs):
            result = backup(*args, **kwargs)
            path.write_bytes(empty + b' ')
            return result

        monkeypatch.setattr(backups, 'backup_files', change_during_backup)
    with pytest.raises(ValueError, match='independent-items.json changed after preparation'):
        backups.apply(prepared)
    assert files_in(root) == {**before, path.relative_to(root): empty + b' '}
    assert backups.count == (1 if phase == 'backup' else 0)


@pytest.mark.parametrize('imported', [False, True])
def test_author_another_item_after_installing_a_generated_icon(tmp_path, imported):
    from cdmw.core.item_icon_addition import NewItemIcon, icon_string_for_stem, icon_target_path
    from cdmw.core.stringinfo_table import stringinfo_key
    from cdmw.domain.new_item.spec import IconSource, ModelSource
    from cdmw.services.new_item_planning import ModelFiles
    from cdmw.workers.new_item_workers import plan_task
    from tests.test_new_item_service import PAC_XML, _fake_dds, imported_pac
    service, snapshot, _ = setup_game(tmp_path / 'recipient')
    root, backups = tmp_path / 'recipient/game', Backups(tmp_path)
    shipped = files_in(root / '0009')
    choice = replace(shop_spec('SameSourceName'), icon=IconSource.GENERATED,
                     model_source=ModelSource.IMPORTED if imported else ModelSource.TEMPLATE)
    name = icon_string_for_stem(service.allocate(choice, snapshot).stem)
    icon = NewItemIcon(name, stringinfo_key(name), icon_target_path(name), _fake_dds(), None, None)
    model = ModelFiles(imported_pac(1), {PAC_XML: snapshot.payload(PAC_XML)}) if imported else None
    task = plan_task(choice, snapshot, service=service, model=model, icon=icon, independent=True)
    first = task(lambda _: None, threading.Event())
    package = from_plan(first, uuid4().hex)
    backups.apply(prepare_install([package_bytes(package)], root).preparation)
    before = files_in(root)
    second = task(lambda _: None, threading.Event())
    assert first.spec.item_key == second.spec.item_key and first.spec.stem == second.spec.stem
    assert files_in(root) == before, 'authoring must not change the installation'
    backups.apply(prepare_install([package_bytes(from_plan(second, uuid4().hex))], root).preparation)
    rows = list(load_registry(root)['items'].values())
    assert len(rows) == len({row['values']['iteminfo']['item'] for row in rows}) == 2
    assert len({row['stem'] for row in rows}) == 2
    assert set(rows[0]['paths']).isdisjoint(rows[1]['paths'])
    final = snapshot_of(root)
    for row in rows:
        assert all(final.has_entry(path) for path in row['paths'])
        assert all(final.pathc.find(path) is not None for path in row['paths'] if path.endswith('.dds'))
    assert files_in(root / '0009') == shipped


@pytest.mark.parametrize('variant', [True, False])
def test_import_rejects_invalid_attachment_bindings_even_with_valid_hashes(tmp_path, variant):
    from cdmw.domain.new_item.spec import ModelSource
    from cdmw.services.independent_item_codec import decode, encode
    from cdmw.services.new_item_planning import ModelFiles
    from tests.test_new_item_service import PAC_XML, imported_pac
    from tests.test_new_item_variant_rig import _pac
    service, snapshot = imported_game(tmp_path / 'author')
    choice = replace(shop_spec('ImportedItem'), model_source=ModelSource.IMPORTED)
    model = ModelFiles(imported_pac(1), {PAC_XML: snapshot.payload(PAC_XML)})
    package = from_plan(service.plan(choice, snapshot, model=model, capture_independent=True), uuid4().hex)
    invalid = _pac(attachment_slot=1)
    with pytest.raises(ValueError, match='single attachment slot'):
        service.plan(choice, snapshot, model=replace(model, pac_data=invalid), capture_independent=True)
    recipe, blobs = deepcopy(package.recipe), dict(package.blobs)
    owned = recipe['variants'][0]['model']
    if not variant:
        recipe['model'], recipe['variants'] = owned, []
        recipe['spec'] = encode(replace(decode(recipe['spec']), variants=None))
    del blobs[owned['pac']]
    owned['pac'] = digest(invalid)
    blobs[owned['pac']] = invalid
    tampered = replace(package, recipe=recipe, blobs=blobs)
    imported_game(tmp_path / 'recipient')
    root = tmp_path / 'recipient/game'
    before = files_in(root)
    with pytest.raises(IndependentItemError, match='single attachment slot'):
        prepare_install([package_bytes(tampered)], root)
    assert files_in(root) == before


@pytest.mark.parametrize('directory_name', ['0042', 'dmmgen', 'dmmsa'])
def test_unmounted_external_replacement_does_not_block_install_or_rebuild(tmp_path, directory_name):
    from cdmw.services.archive_overlay_rebuild import prepare_overlay_rebuild
    from tests.test_new_item_service import build_package
    _, package = authored(tmp_path / 'author')
    _, snapshot, _ = setup_game(tmp_path / 'recipient')
    root, backups = tmp_path / 'recipient/game', Backups(tmp_path)
    path = next(iter(package.dependencies))
    pamt = build_package(tmp_path / 'external', {path: snapshot.payload(path)})
    directory = root / directory_name
    directory.mkdir()
    for source in pamt.parent.iterdir():
        if source.is_file():
            (directory / source.name).write_bytes(source.read_bytes())
    before = files_in(directory)
    backups.apply(prepare_install([package_bytes(package)], root).preparation)
    backups.apply(prepare_overlay_rebuild(root))
    assert inventory(root)[0][3] == 'Installed'
    assert files_in(directory) == before
