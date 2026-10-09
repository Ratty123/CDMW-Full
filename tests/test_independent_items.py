from dataclasses import replace
import io
import json
import threading
from uuid import uuid4
import zipfile

import pytest

from cdmw.domain.new_item.independent import IndependentItemError
from cdmw.services.independent_item_package import from_plan, package_bytes, read_package, write_package
from cdmw.services.independent_item_install import (
    REGISTRY_PATH, export_profile, inventory, load_registry, prepare_install, prepare_profile_import, prepare_remove,
)
from tests.test_new_item_provenance import spec
from tests.test_archive_overlay_manager import Backups, snapshot_of, shop_spec


def imported_game(path, *, auxiliaries=False):
    from cdmw.core.archive_format import parse_archive_pamt
    from cdmw.core.pathc_format import PathcTable, encode_pathc, register_dds
    from cdmw.services.new_item_service import NewItemService
    from tests.test_new_item_provenance import current_files
    from tests.test_new_item_service import build_package, PAC_XML, STEM, ICON, _read, _fake_dds
    from tests.test_pac_xml_standard_material import HEAD, TAIL, wrapper, texture, STANDARD_SHADER
    files = current_files()
    from cdmw.core.pappt_format import parse_pappt, encode_pappt
    pappt_path = 'character/bin__/partprefabtable.pappt'
    pappt = parse_pappt(files[pappt_path])
    socket_path = 'character/sockets/independent_test.sockets.xml'
    files[pappt_path] = encode_pappt(replace(pappt, records=tuple(replace(record, sockets_path=socket_path) for record in pappt.records)))
    files[socket_path] = b'<Sockets/>'
    texture_path = f'character/texture/1_pc/{STEM}_d.dds'
    files[PAC_XML] = (HEAD + wrapper(STEM, STANDARD_SHADER, texture('_baseColorTexture', '0', texture_path, 0)) + TAIL).encode()
    if auxiliaries:
        from cdmw.core.effect_binary import decode_effect_binary
        from cdmw.core.effect_edit import preset_path
        from cdmw.core.iteminfo_row import parse_iteminfo_row, rebuild_stat_block
        from cdmw.core.structured_binary_editor import parse_pabgh_table
        from tests.test_effect_edit import EFFECT, TRAIL, PRESET
        from tests.test_new_item_service import _table4
        from tests.test_iteminfo_row import build_row
        for source, target in ((EFFECT, 'effect/binary__/releasebin/' + EFFECT.name),
                               (TRAIL, 'effect/binary__/emitter/' + TRAIL.name),
                               (PRESET, preset_path('render', PRESET.stem))):
            files[target] = source.read_bytes()
            for resource in decode_effect_binary(files[target]).resources():
                files[resource] = _fake_dds()
        body_path = 'gamedata/binarystaticinfo__/bin/iteminfo.staticinfobody'
        header_path = body_path.replace('staticinfobody', 'staticinfoheader')
        body, header = files[body_path], files[header_path]
        rows = []
        for directory, start, end in parse_pabgh_table(header, payload=body).row_spans(len(body)):
            raw = body[start:end]
            if directory.row_id == 1002791:
                perk = parse_iteminfo_row(build_row(key=directory.row_id, string_key='Socket_Gem', item_type=2501,
                    equip='', stems=(), levels=[([], [])], prices=((1, 55),), socket_items=(), adds=()))
                raw = rebuild_stat_block(replace(perk, stat_block_marker=0x12))
            rows.append((directory.row_id, raw))
        files[body_path], files[header_path] = _table4(rows)
    entries = parse_archive_pamt(build_package(path / 'game', files))
    registry = PathcTable(0, 148, (), (), (), b'')
    for resource in (ICON, texture_path):
        registry = register_dds(registry, resource, files[resource])
    (path / 'game/meta/0.pathc').write_bytes(encode_pathc(registry))
    service = NewItemService()
    return service, service.build_snapshot(entries, read_entry=_read)


def setup_game(path):
    service, snapshot = imported_game(path)
    return service, snapshot, tuple(snapshot.entries.values())


@pytest.mark.parametrize('auxiliaries', [False, True])
@pytest.mark.parametrize('order', [(0, 1), (1, 0)])
def test_imported_mesh_icon_and_material_references_remap_together(tmp_path, auxiliaries, order):
    from cdmw.core.item_icon_addition import NewItemIcon, icon_string_for_stem, icon_target_path
    from cdmw.core.stringinfo_table import stringinfo_key
    from cdmw.core.prefab_binary import decode_prefab_binary
    from cdmw.domain.new_item.spec import ModelSource, IconSource
    from cdmw.services.new_item_planning import ModelFiles
    from tests.test_new_item_service import PAC, PAC_XML, imported_pac, _fake_dds
    packages = []
    for i in range(2):
        service, snapshot = imported_game(tmp_path / f'author-{i}', auxiliaries=auxiliaries)
        choice = replace(shop_spec('SameImportedItem'), model_source=ModelSource.IMPORTED, icon=IconSource.GENERATED)
        if auxiliaries:
            from cdmw.domain.new_item.spec import EffectLook
            from tests.test_effect_edit import EFFECT
            choice = replace(choice, include_perk_prices=False, effect=EFFECT.stem + '.level.effect',
                             effect_look=EffectLook(color=(1, 0, 0), emitter_order=(0,)))
        allocated = service.allocate(choice, snapshot)
        name = icon_string_for_stem(allocated.stem)
        icon = NewItemIcon(name, stringinfo_key(name), icon_target_path(name), _fake_dds(), None, None)
        model = ModelFiles(imported_pac(100), {PAC_XML: snapshot.payload(PAC_XML)})
        plan = service.plan(choice, snapshot, model=model, icon=icon, capture_independent=True)
        packages.append(from_plan(plan, uuid4().hex))
    imported_game(tmp_path / 'recipient', auxiliaries=auxiliaries)
    root = tmp_path / 'recipient/game'
    backups = Backups(tmp_path)
    backups.apply(prepare_install([package_bytes(packages[i]) for i in order], root).preparation)
    registry = load_registry(root)
    first, second = (registry['items'][package.identity] for package in packages)
    assert first['stem'] != second['stem']
    assert set(first['paths']).isdisjoint(second['paths'])
    if auxiliaries:
        assert first['values']['effect'] and second['values']['effect']
        assert set(first['values']['effect'].values()).isdisjoint(second['values']['effect'].values())
        assert 'perk:1002791' in first['values']['iteminfo']
        assert first['values']['iteminfo']['perk:1002791'] != second['values']['iteminfo']['perk:1002791']
    snapshot = snapshot_of(root)
    for owned in (first, second):
        for path in owned['paths']:
            assert snapshot.has_entry(path)
            if path.endswith('.prefab'):
                refs = decode_prefab_binary(snapshot.payload(path)).resource_strings()
                assert any(owned['stem'] in ref.text and ref.text in owned['paths'] for ref in refs)
            if path.endswith('.dds'):
                assert snapshot.pathc.find(path) is not None
            if path.endswith('.pae'):
                from cdmw.core.effect_binary import decode_effect_binary
                from cdmw.core.effect_edit import emitter_paths_of
                document = decode_effect_binary(snapshot.payload(path))
                assert set(emitter_paths_of(document)) <= set(owned['paths'])
                assert {node.type_name.lstrip('/') for node in document.root.walk()
                        if node.type_name.endswith('.paem')} <= set(owned['paths'])
        if auxiliaries:
            main = snapshot.rows[owned['values']['iteminfo']['item']]
            perk_key = owned['values']['iteminfo']['perk:1002791']
            assert perk_key in main.socket_items
            assert all(price.price == 0 for price in snapshot.rows[perk_key].price_list)
            assert snapshot.rows[perk_key].name_key in snapshot.english.index()
    backups.apply(prepare_remove(packages[0].identity, root))
    assert all(snapshot_of(root).has_entry(path) for path in second['paths'])
    backups.apply(prepare_install([package_bytes(packages[0])], root).preparation)
    assert load_registry(root)['items'][packages[0].identity]['values'] == first['values']


def authored(root, identity=None, name='SameSourceName'):
    service, snapshot, _ = setup_game(root)
    plan = service.plan(shop_spec(name), snapshot, capture_independent=True)
    return plan, from_plan(plan, identity or uuid4().hex)


@pytest.mark.parametrize('order', [(0, 1), (1, 0)])
def test_independent_authors_collide_at_source_but_not_at_destination(tmp_path, order):
    plans, packages = zip(*(authored(tmp_path / str(i)) for i in range(2)))
    assert plans[0].spec.item_key == plans[1].spec.item_key
    assert plans[0].spec.internal_name == plans[1].spec.internal_name
    setup_game(tmp_path / 'recipient')
    root = tmp_path / 'recipient/game'
    backups = Backups(tmp_path)
    sources = [package_bytes(packages[i]) for i in order]
    prepared = prepare_install(sources, root)
    assert not (root / REGISTRY_PATH).exists()
    backups.apply(prepared.preparation)
    registry = load_registry(root)
    keys = [row['values']['iteminfo']['item'] for row in registry['items'].values()]
    assert len(set(keys)) == 2
    for namespace in ('multichangeinfo', 'dropsetinfo'):
        groups = [set(row['values'][namespace].values()) for row in registry['items'].values()]
        assert groups[0] and groups[1] and groups[0].isdisjoint(groups[1])
    snapshot = snapshot_of(root)
    assert len({snapshot.rows[key].string_key for key in keys}) == 2
    assert all(snapshot.rows[key].name_key in snapshot.english.index() for key in keys)
    from cdmw.services.new_item_acquisition_index import load_acquisition_index
    from cdmw.core.multichangeinfo_table import find_multichange_keys
    index = load_acquisition_index(snapshot)
    for record in registry['items'].values():
        key = record['values']['iteminfo']['item']
        owned_recipes = set(record['values']['multichangeinfo'].values())
        assert set(find_multichange_keys(snapshot.rows[key], snapshot.multichange_rows)) == owned_recipes
        for recipe_key in owned_recipes:
            recipe = index.recipes[recipe_key]
            outputs = [entry.item_key for reward in recipe.reward_keys + recipe.additional_reward_keys
                       for entry in index.rewards[reward].entries]
            assert key in outputs and not (set(outputs) & (set(keys) - {key}))
    assert prepare_install(sources, root).preparation is None
    first = packages[order[0]]
    old = registry['items'][first.identity]
    _, update = authored(tmp_path / 'updated', first.identity, 'UpdatedName')
    backups.apply(prepare_install([package_bytes(update)], root).preparation)
    assert load_registry(root)['items'][first.identity]['values'] == old['values']
    backups.apply(prepare_remove(first.identity, root))
    assert old['values']['iteminfo']['item'] not in snapshot_of(root).rows
    assert load_registry(root)['items'][first.identity]['values'] == old['values']
    backups.apply(prepare_install([package_bytes(update)], root).preparation)
    assert load_registry(root)['items'][first.identity]['values'] == old['values']
    profile = export_profile(root, tmp_path / 'save.cdprofile')
    setup_game(tmp_path / 'transfer')
    transfer = tmp_path / 'transfer/game'
    backups.apply(prepare_profile_import(profile, transfer))
    backups.apply(prepare_install(list(reversed(sources)), transfer).preparation)
    assert {i: r['values'] for i, r in load_registry(transfer)['items'].items()} == {i: r['values'] for i, r in registry['items'].items()}


def test_portable_package_is_data_only_and_update_requires_explicit_selection(tmp_path):
    _, package = authored(tmp_path / 'source')
    data = package_bytes(package)
    assert read_package(data) == package
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        metadata = archive.read('item.json')
        assert b'source_archive' not in metadata and b'new-item.json' not in metadata
        assert str(tmp_path).encode() not in metadata
        assert all(name == 'item.json' or name.startswith('assets/') for name in archive.namelist())
    output = tmp_path / 'test.cditem'
    write_package(package, output)
    with pytest.raises(IndependentItemError, match='explicitly'):
        write_package(package, output)
    write_package(package, output, expected_digest=package.digest)


@pytest.mark.parametrize('malformation', ['traversal', 'duplicate', 'unknown_version', 'missing_dependency'])
def test_corrupt_and_incomplete_packages_are_refused(tmp_path, malformation):
    _, package = authored(tmp_path / 'source')
    source = zipfile.ZipFile(io.BytesIO(package_bytes(package)))
    meta = json.loads(source.read('item.json'))
    target = io.BytesIO()
    if malformation == 'unknown_version':
        meta['version'] = 99
    if malformation == 'missing_dependency':
        meta['dependencies'].pop(next(iter(meta['dependencies'])))
    with zipfile.ZipFile(target, 'w') as archive:
        archive.writestr('item.json', json.dumps(meta))
        if malformation == 'traversal':
            archive.writestr('../escape', b'data')
        if malformation == 'duplicate':
            with pytest.warns(UserWarning):
                archive.writestr('item.json', json.dumps(meta))
    setup_game(tmp_path / 'recipient')
    with pytest.raises(IndependentItemError):
        prepare_install([target.getvalue()], tmp_path / 'recipient/game')
    assert not (tmp_path / 'recipient/game' / REGISTRY_PATH).exists()


def test_cancel_and_publication_failure_preserve_previous_installation(tmp_path, monkeypatch):
    _, package = authored(tmp_path / 'source')
    setup_game(tmp_path / 'recipient')
    root = tmp_path / 'recipient/game'
    backups = Backups(tmp_path)
    preparation = prepare_install([package_bytes(package)], root).preparation
    stop = threading.Event()
    stop.set()
    with pytest.raises(RuntimeError):
        backups.apply(preparation, stop_event=stop)
    from cdmw.services import archive_overlay_manager as manager
    write = manager.atomic_write_bytes
    def fail(path, data):
        write(path, data)
        if path.name == 'independent-items.json':
            raise OSError('injected publication failure')
    monkeypatch.setattr(manager, 'atomic_write_bytes', fail)
    with pytest.raises(OSError, match='injected'):
        backups.apply(preparation)
    assert not (root / REGISTRY_PATH).exists()
    assert not inventory(root)
    assert not list((root / '.cdmw').glob('independent-items/*.cditem'))


def test_exhaustion_and_retired_keys_cannot_silently_rebind(tmp_path):
    from cdmw.domain.new_item.allocation import DEFAULT_ITEM_KEY_RANGE
    from cdmw.domain.new_item.independent import IdentityBindings
    bindings = IdentityBindings(uuid4().hex, reserved={'iteminfo': set(DEFAULT_ITEM_KEY_RANGE)})
    with pytest.raises(ValueError):
        bindings.allocate('iteminfo', 'item', ())
    bindings = IdentityBindings(uuid4().hex, {'iteminfo': {'item': 1990000}})
    with pytest.raises(IndependentItemError, match='cannot be renumbered'):
        bindings.allocate('iteminfo', 'item', {1990000})
    _, package = authored(tmp_path / 'source')
    service, snapshot, _ = setup_game(tmp_path / 'recipient')
    root = tmp_path / 'recipient/game'
    backups = Backups(tmp_path)
    backups.apply(prepare_install([package_bytes(package)], root).preparation)
    backups.apply(prepare_remove(package.identity, root))
    from cdmw.services.archive_overlay_manager import prepare_item_overlay
    with pytest.raises(ValueError, match='reserved by an independent package'):
        prepare_item_overlay(service.plan(spec('OrdinaryItem'), snapshot_of(root)), root)


def test_stale_registry_and_external_change_refuse_before_publication(tmp_path):
    _, first = authored(tmp_path / 'source')
    _, second = authored(tmp_path / 'source2')
    setup_game(tmp_path / 'recipient')
    root = tmp_path / 'recipient/game'
    backups = Backups(tmp_path)
    backups.apply(prepare_install([package_bytes(first)], root).preparation)
    prepared = prepare_install([package_bytes(second)], root).preparation
    registry_path = root / REGISTRY_PATH
    original = registry_path.read_bytes()
    registry_path.write_bytes(original + b' ')
    with pytest.raises(ValueError, match='changed after preparation'):
        backups.apply(prepared)
    registry_path.write_bytes(original)
    target = root / prepared.directory_name / '0.pamt'
    target.write_bytes(target.read_bytes() + b'changed')
    with pytest.raises(ValueError, match='changed outside'):
        prepare_install([package_bytes(second)], root)
    assert backups.count == 1


def test_unverified_shared_changes_and_bad_types_are_refused(tmp_path):
    from cdmw.domain.new_item.spec import PlacementKind
    service, snapshot, _ = setup_game(tmp_path)
    choice = shop_spec('Owned')
    with pytest.raises(IndependentItemError, match='replacing existing stock'):
        service.plan(replace(choice, placement=replace(choice.placement, kind=PlacementKind.SWAP,
                                                     old_item_name='Cigar_OneHandSword')), snapshot, capture_independent=True)
    _, package = authored(tmp_path / 'source')
    raw = dict(package.recipe)
    raw['spec'] = dict(raw['spec'], fields=dict(raw['spec']['fields'], template_key='wrong type'))
    bad = replace(package, recipe=raw)
    with pytest.raises(IndependentItemError, match='Invalid value type'):
        read_package(package_bytes(bad))


def test_dependency_version_and_hash_collisions_fail_without_writing(tmp_path, monkeypatch):
    _, package = authored(tmp_path / 'source')
    setup_game(tmp_path / 'recipient')
    root = tmp_path / 'recipient/game'
    dependencies = dict(package.dependencies)
    dependencies[next(iter(dependencies))] = 'f' * 64
    with pytest.raises(IndependentItemError, match='incompatible game dependency'):
        prepare_install([package_bytes(replace(package, dependencies=dependencies))], root)
    from cdmw.services import independent_item_install as install
    from cdmw.services.new_item_planning import build_plan
    def collide(allocated, snapshot, **kwargs):
        # A real StringInfo collision at a verified record boundary must abort;
        # do not use broad binary replacement in the reproducer either.
        from cdmw.core.stringinfo_table import append_stringinfo_strings
        from unittest.mock import patch
        with patch('cdmw.core.stringinfo_table.stringinfo_key', return_value=next(iter(snapshot.stringinfo_texts))):
            append_stringinfo_strings(snapshot.stringinfo.payload, snapshot.stringinfo.header, ['DifferentOwnedName'])
        return build_plan(allocated, snapshot, **kwargs)
    monkeypatch.setattr(install, 'build_plan', collide)
    with pytest.raises(ValueError):
        prepare_install([package_bytes(package)], root)
    assert not (root / REGISTRY_PATH).exists()


@pytest.mark.parametrize('first', [False, True])
@pytest.mark.parametrize('directory_name', ['0042', 'dmmgen', 'dmmsa'])
def test_identical_external_dependency_does_not_block_installation(tmp_path, first, directory_name):
    from cdmw.core.papgt_format import papgt_with_directory
    from tests.test_new_item_service import build_package
    _, package = authored(tmp_path / 'source')
    _, snapshot, _ = setup_game(tmp_path / 'recipient')
    root = tmp_path / 'recipient/game'
    path = next(iter(package.dependencies))
    pamt = build_package(tmp_path / 'foreign', {path: snapshot.payload(path)})
    directory = root / directory_name
    directory.mkdir()
    for source in pamt.parent.iterdir():
        if source.is_file():
            (directory / source.name).write_bytes(source.read_bytes())
    mount = root / 'meta/0.papgt'
    checksum = int.from_bytes((directory / '0.pamt').read_bytes()[:4], 'little')
    mount.write_bytes(papgt_with_directory(mount.read_bytes(), directory_name, checksum, first=first))
    before = mount.read_bytes()
    assert prepare_install([package_bytes(package)], root).preparation is not None
    assert mount.read_bytes() == before and not (root / REGISTRY_PATH).exists()


def test_identity_profile_conflict_cancel_and_stale_composition(tmp_path, monkeypatch):
    from cdmw.services import archive_overlay_manager as manager
    _, package = authored(tmp_path / 'source')
    setup_game(tmp_path / 'recipient')
    root = tmp_path / 'recipient/game'
    Backups(tmp_path).apply(prepare_install([package_bytes(package)], root).preparation)
    profile = export_profile(root, tmp_path / 'save.cdprofile')
    before = profile.read_bytes()
    stop = threading.Event()
    stop.set()
    with pytest.raises(RuntimeError):
        export_profile(root, profile, stop_event=stop)
    assert profile.read_bytes() == before
    changed = json.loads(before)
    changed['items'][package.identity]['values']['iteminfo']['item'] += 1
    from cdmw.services.independent_item_install import _binding_hash
    changed['items'][package.identity]['binding_hash'] = _binding_hash(package.identity, changed['items'][package.identity])
    profile.write_text(json.dumps(changed), encoding='utf-8')
    with pytest.raises(IndependentItemError, match='cannot be renumbered'):
        prepare_profile_import(profile, root)
    profile.write_bytes(before)
    compose = manager._compose
    def changing_compose(*args, **kwargs):
        path = root / manager.INDEX_PATH
        path.write_bytes(path.read_bytes() + b' ')
        return compose(*args, **kwargs)
    monkeypatch.setattr(manager, '_compose', changing_compose)
    with pytest.raises(IndependentItemError, match='changed during preparation'):
        prepare_profile_import(profile, root)


def test_private_file_inputs_and_unrepresentable_numbers_are_refused(tmp_path):
    from cdmw.domain.new_item.authoring import DyeAssignment, VariantAppearance
    from cdmw.services.independent_item_codec import encode
    from cdmw.services.independent_item_package import unpack_recipe
    from tests.test_new_item_service import PAC
    _, package = authored(tmp_path / 'source')
    original, _, _, _ = unpack_recipe(package)
    variant = VariantAppearance('character/prefab/source.prefab', PAC,
                                dyes=(DyeAssignment('part', 'part', (0, 1, 2), 'C:/private.dds'),))
    recipe = dict(package.recipe, spec=encode(replace(original, variants=(variant,))))
    with pytest.raises(IndependentItemError, match='Local dye mask'):
        read_package(package_bytes(replace(package, recipe=recipe)))
    recipe['spec'] = dict(package.recipe['spec'], fields=dict(package.recipe['spec']['fields'], effect_scale=10 ** 400))
    with pytest.raises(IndependentItemError, match='Invalid value type'):
        read_package(package_bytes(replace(package, recipe=recipe)))


def test_batch_version_conflict_and_corrupted_owned_blob_are_refused(tmp_path):
    import hashlib
    _, package = authored(tmp_path / 'source')
    setup_game(tmp_path / 'recipient')
    root = tmp_path / 'recipient/game'
    with pytest.raises(IndependentItemError, match='two different versions'):
        prepare_install([package_bytes(package), package_bytes(replace(package, title='Updated title'))], root)
    with zipfile.ZipFile(io.BytesIO(package_bytes(package))) as archive:
        metadata = json.loads(archive.read('item.json'))
    key = hashlib.sha256(b'owned').hexdigest()
    metadata['blobs'] = {key: 5}
    metadata['recipe']['icon'] = key
    output = io.BytesIO()
    with zipfile.ZipFile(output, 'w') as archive:
        archive.writestr('item.json', json.dumps(metadata))
        archive.writestr('assets/' + key, b'wrong')
    with pytest.raises(IndependentItemError, match='checksum or size'):
        prepare_install([output.getvalue()], root)
    assert not (root / REGISTRY_PATH).exists()


def test_equal_shape_texture_hash_collision_between_packages_is_refused(tmp_path, monkeypatch):
    from cdmw.core import pathc_format
    from cdmw.core.item_icon_addition import NewItemIcon, icon_string_for_stem, icon_target_path
    from cdmw.core.stringinfo_table import stringinfo_key
    from cdmw.domain.new_item.spec import IconSource
    from cdmw.services import independent_item_install as install
    from tests.test_new_item_service import _fake_dds
    packages = []
    for i in range(2):
        service, snapshot, _ = setup_game(tmp_path / f'author{i}')
        choice = replace(shop_spec('SameIcon'), icon=IconSource.GENERATED)
        allocated = service.allocate(choice, snapshot)
        name = icon_string_for_stem(allocated.stem)
        icon = NewItemIcon(name, stringinfo_key(name), icon_target_path(name), _fake_dds(), None, None)
        packages.append(from_plan(service.plan(choice, snapshot, icon=icon, capture_independent=True), uuid4().hex))
    setup_game(tmp_path / 'recipient')
    root = tmp_path / 'recipient/game'
    owned = set()
    checksum, build = pathc_format.pathc_checksum, install.build_plan
    def capture(*args, **kwargs):
        result = build(*args, **kwargs)
        owned.update(addition.path for addition in result.additions if addition.path.endswith('.dds'))
        return result
    monkeypatch.setattr(install, 'build_plan', capture)
    monkeypatch.setattr(pathc_format, 'pathc_checksum', lambda path: 0x12345678 if path in owned else checksum(path))
    with pytest.raises(IndependentItemError, match='asset hash collides'):
        prepare_install([package_bytes(package) for package in packages], root)
    assert len(owned) == 2 and not (root / REGISTRY_PATH).exists()


def test_generic_recovery_preserves_package_ownership_and_checks_dependencies(tmp_path):
    from cdmw.services.archive_overlay_rebuild import prepare_overlay_rebuild
    from tests.test_new_item_service import build_package, ICON
    _, package = authored(tmp_path / 'source')
    _, snapshot, _ = setup_game(tmp_path / 'recipient')
    files = {path: snapshot.payload(path) for path in snapshot.entries}
    root = tmp_path / 'recipient/game'
    backups = Backups(tmp_path)
    backups.apply(prepare_install([package_bytes(package)], root).preparation)
    before = load_registry(root)
    rebuild = prepare_overlay_rebuild(root)
    assert REGISTRY_PATH in dict(rebuild.writes)
    assert any(path.endswith('.cditem') for path, _ in rebuild.writes)
    backups.apply(rebuild)
    assert load_registry(root) == before
    assert prepare_install([package_bytes(package)], root).preparation is None
    # A generic rebase must not silently waive the portable package's pinned
    # borrowed assets, even when all shared table records can still be merged.
    files[ICON] += b'changed game resource'
    build_package(root, files)
    with pytest.raises(IndependentItemError, match='incompatible game dependency'):
        prepare_overlay_rebuild(root)
    assert load_registry(root) == before


def test_changed_retained_mapping_is_refused_after_removal(tmp_path):
    _, package = authored(tmp_path / 'source')
    setup_game(tmp_path / 'recipient')
    root = tmp_path / 'recipient/game'
    backups = Backups(tmp_path)
    backups.apply(prepare_install([package_bytes(package)], root).preparation)
    backups.apply(prepare_remove(package.identity, root))
    path = root / REGISTRY_PATH
    changed = json.loads(path.read_bytes())
    changed['items'][package.identity]['values']['iteminfo']['item'] += 1
    path.write_text(json.dumps(changed), encoding='utf-8')
    with pytest.raises(IndependentItemError, match='mapping failed its checksum'):
        prepare_install([package_bytes(package)], root)


def test_install_cannot_publish_an_identity_profile_too_large_to_reopen(tmp_path, monkeypatch):
    from cdmw.services import independent_item_install as install
    _, package = authored(tmp_path / 'source')
    setup_game(tmp_path / 'recipient')
    root = tmp_path / 'recipient/game'
    monkeypatch.setattr(install, 'MAX_MANIFEST', 192)
    with pytest.raises(IndependentItemError, match='profile exceeds'):
        prepare_install([package_bytes(package)], root)
    assert not (root / REGISTRY_PATH).exists()
