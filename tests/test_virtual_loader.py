from dataclasses import replace
import json
from pathlib import Path
import threading
from uuid import uuid4

import pytest

from cdmw.domain.virtual_loader import VirtualProfile, VirtualLoaderError
from cdmw.services.independent_item_package import from_plan, package_bytes, canonical, digest
from cdmw.services.independent_item_install import load_registry, prepare_install, inventory, export_profile
from cdmw.services.virtual_loader_composition import prepare_profile
from cdmw.services.virtual_loader_state import publish_profile, load_profile, recover_profile, PROFILE_PATH, JOURNAL_PATH, _journal_value
from tests.test_independent_items import setup_game
from tests.test_archive_overlay_manager import shop_spec, Backups


def packages(tmp_path, count=2):
    service, snapshot, _ = setup_game(tmp_path)
    result = []
    for i in range(count):
        plan = service.plan(shop_spec('SameSourceName'), snapshot, capture_independent=True)
        item = from_plan(plan, uuid4().hex)
        file = tmp_path / f'item-{i}.cditem'
        file.write_bytes(package_bytes(item))
        result.append(file)
    return tmp_path / 'game', tuple(result)


def game_bytes(root):
    return {p.relative_to(root).as_posix(): p.read_bytes() for p in root.rglob('*') if p.is_file() and '.cdmw' not in p.parts}


@pytest.mark.parametrize('reverse', [False, True])
def test_virtual_collision_composition_is_private_and_identity_survives_reinstall(tmp_path, reverse):
    root, files = packages(tmp_path)
    if reverse:
        files = tuple(reversed(files))
    before = game_bytes(root)
    plan = prepare_profile(VirtualProfile(files), root)
    assert game_bytes(root) == before and not (root / '.cdmw').exists()
    publish_profile(plan)
    registry = load_registry(root)
    rows = list(registry['items'].values())
    assert len({r['values']['iteminfo']['item'] for r in rows}) == 2
    assert all(r['layer'] is None for r in rows)
    assert {r[3] for r in inventory(root)} == {'Virtual profile'}
    assert game_bytes(root) == before
    with pytest.raises(ValueError, match='virtual profile'):
        prepare_install(files, root)
    publish_profile(prepare_profile(VirtualProfile(), root))
    assert not load_profile(root)['items']
    publish_profile(prepare_profile(VirtualProfile(files), root))
    assert load_registry(root) == registry
    export_profile(root, tmp_path / 'saved.cdprofile')
    assert json.loads((tmp_path / 'saved.cdprofile').read_text()) == registry
    assert game_bytes(root) == before


def test_dual_activation_and_stale_publication_refused(tmp_path):
    root, files = packages(tmp_path)
    plan = prepare_profile(VirtualProfile(files), root)
    Backups(tmp_path).apply(prepare_install(files[:1], root).preparation)
    with pytest.raises(ValueError, match='changed'):
        publish_profile(plan)
    with pytest.raises(ValueError, match='remove the installed contribution'):
        prepare_profile(VirtualProfile(files), root)


def test_selected_loose_files_are_carried_and_unknown_mod_refuses(tmp_path):
    root, files = packages(tmp_path, 1)
    mod = tmp_path / 'external'
    (mod / 'files/character').mkdir(parents=True)
    (mod / 'files/character/example.txt').write_bytes(b'foreign data')
    prepared = prepare_profile(VirtualProfile(files, (mod,)), root)
    from cdmw.core.archive_format import parse_archive_pamt
    from cdmw.core.archive_extraction import read_archive_entry_data
    publish_profile(prepared)
    generation = root / '.cdmw/virtual-loader/generations' / prepared.generation / 'files'
    pamt = next(generation.glob('*/0.pamt'))
    entries = {entry.path: entry for entry in parse_archive_pamt(pamt)}
    assert read_archive_entry_data(entries['character/example.txt'])[0] == b'foreign data'
    (mod / 'unknown.asi').write_bytes(b'not supported')
    with pytest.raises(ValueError, match='runtime code'):
        prepare_profile(VirtualProfile(files, (mod,)), root)


def test_cancel_and_recover_interrupted_ledger_publication(tmp_path, monkeypatch):
    root, files = packages(tmp_path, 1)
    prepared = prepare_profile(VirtualProfile(files), root)
    stop = threading.Event(); stop.set()
    from cdmw.models import RunCancelled
    with pytest.raises(RunCancelled):
        publish_profile(prepared, stop_event=stop)
    assert not (root / PROFILE_PATH).exists()
    publish_profile(prepared)
    original = (root / PROFILE_PATH).read_bytes()
    registry = (root / '.cdmw/independent-items.json').read_bytes()
    before = {'.cdmw/independent-items.json': registry.decode(), PROFILE_PATH: original.decode()}
    after = {'.cdmw/independent-items.json': registry.decode(), PROFILE_PATH: None}
    (root / JOURNAL_PATH).write_bytes(_journal_value(before, after))
    with pytest.raises(ValueError, match='Recover'):
        load_registry(root)
    assert recover_profile(root) == 'before'
    assert (root / PROFILE_PATH).read_bytes() == original
    assert load_registry(root)


def test_corrupt_virtual_ownership_and_map_refused(tmp_path):
    root, files = packages(tmp_path, 1)
    plan = prepare_profile(VirtualProfile(files), root)
    corrupt = json.loads(plan.profile)
    corrupt['files']['bin64/CrimsonDesert.exe'] = 'a' * 64
    with pytest.raises(ValueError, match='redirection'):
        publish_profile(replace(plan, profile=canonical(corrupt)))
    assert not (root / PROFILE_PATH).exists()


def test_failed_second_ledger_write_restores_previous_profile(tmp_path, monkeypatch):
    from cdmw.services import virtual_loader_state as state
    root, files = packages(tmp_path, 1)
    publish_profile(prepare_profile(VirtualProfile(files), root))
    before = {name: (root / name).read_bytes() for name in (PROFILE_PATH, state.REGISTRY)}
    changed = prepare_profile(VirtualProfile(), root)
    write = state.atomic_write_bytes
    def fail_active_profile(path, data):
        if path == root / PROFILE_PATH:
            raise OSError('injected active profile failure')
        write(path, data)
    monkeypatch.setattr(state, 'atomic_write_bytes', fail_active_profile)
    with pytest.raises(OSError, match='injected'):
        publish_profile(changed)
    assert not (root / JOURNAL_PATH).exists()
    assert all((root / path).read_bytes() == data for path, data in before.items())
    assert len(load_profile(root)['items']) == 1
    assert load_registry(root)


def test_virtual_update_and_identity_transfer_reuse_bindings(tmp_path):
    from cdmw.services.independent_item_install import prepare_profile_import
    from cdmw.services.independent_item_package import read_package
    from tests.test_independent_items import authored
    root, files = packages(tmp_path, 1)
    publish_profile(prepare_profile(VirtualProfile(files), root))
    identity = read_package(files[0]).identity
    before = load_registry(root)['items'][identity]
    _, update = authored(tmp_path / 'update', identity, 'UpdatedName')
    files[0].write_bytes(package_bytes(update))
    publish_profile(prepare_profile(VirtualProfile(files), root))
    after = load_registry(root)['items'][identity]
    assert after['values'] == before['values'] and after['digest'] != before['digest']
    transfer = export_profile(root, tmp_path / 'transfer.cdprofile')
    setup_game(tmp_path / 'recipient')
    recipient = tmp_path / 'recipient/game'
    Backups(tmp_path).apply(prepare_profile_import(transfer, recipient))
    publish_profile(prepare_profile(VirtualProfile(files), recipient))
    assert load_registry(recipient) == load_registry(root)


@pytest.mark.parametrize('archive_mod', [False, True])
def test_virtual_update_partial_removal_and_reverse_reinstall_preserve_external_edit(tmp_path, archive_mod, monkeypatch):
    monkeypatch.setattr('cdmw.services.new_item_service.game_is_running', lambda: False)
    import copy
    import shutil
    from cdmw.services.independent_item_package import read_package
    from tests.test_archive_overlay_manager import snapshot_of
    from tests.test_independent_item_compatibility import table_change
    from tests.test_new_item_service import build_package, OTHER, TEMPLATE

    root, files = packages(tmp_path)
    stock = snapshot_of(root)
    external = tmp_path / 'external'
    changes = table_change(stock)
    if archive_mod:
        external = build_package(external, changes).parent
    else:
        for path, data in changes.items():
            target = external / 'files' / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
    original_game, original_mod = game_bytes(root), game_bytes(external)
    originals = tuple(read_package(path) for path in files)
    publish_profile(prepare_profile(VirtualProfile(files, (external,)), root))
    reservations = load_registry(root)
    first_generation = root / '.cdmw/virtual-loader/generations' / load_profile(root)['generation']
    first_files = game_bytes(first_generation / 'files')

    recipe = copy.deepcopy(originals[0].recipe)
    recipe['spec']['fields']['display_names']['map']['eng'] = 'Updated sword'
    updated_path = tmp_path / 'updated.cditem'
    updated_path.write_bytes(package_bytes(replace(originals[0], recipe=recipe)))
    selections = ((updated_path, files[1]), (updated_path,), tuple(reversed(files)))
    for index, selected in enumerate(selections):
        prepared = prepare_profile(VirtualProfile(selected, (external,)), root)
        publish_profile(prepared)
        active = {read_package(path).identity for path in selected}
        assert set(load_profile(root)['items']) == active
        registry = load_registry(root)
        assert set(registry['items']) == set(reservations['items'])
        for identity, original in reservations['items'].items():
            for field in ('values', 'stem', 'paths', 'binding_hash'):
                assert registry['items'][identity][field] == original[field]

        view = tmp_path / f'view-{index}'
        shutil.copytree(root, view, ignore=shutil.ignore_patterns('.cdmw'))
        for relative, data in prepared.files:
            target = view / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
        snapshot = snapshot_of(view)
        camp = next(store for store in snapshot.stores if store.name == 'Store_Camp_Equipment')
        names = snapshot.english.index()
        assert snapshot.rows[OTHER].max_stack_count == stock.rows[OTHER].max_stack_count + 1
        for package in originals:
            key = reservations['items'][package.identity]['values']['iteminfo']['item']
            assert (key in snapshot.rows) == (package.identity in active)
            assert bool(camp.entries_for(key)) == (package.identity in active)
            if package.identity in active:
                expected_name = ('Updated sword' if index < 2 and package == originals[0]
                                 else package.recipe['spec']['fields']['display_names']['map']['eng'])
                assert names[snapshot.rows[key].name_key].text == expected_name
            else:
                assert all(key not in group.members for group in snapshot.item_groups)
        assert game_bytes(root) == original_game
        assert game_bytes(external) == original_mod
        assert game_bytes(first_generation / 'files') == first_files

    assert load_registry(root) == reservations
    # An edit to a borrowed perk must refuse without replacing the usable profile.
    conflicting = tmp_path / 'conflicting'
    for path, data in table_change(stock, key=stock.rows[TEMPLATE].socket_items[0]).items():
        target = conflicting / 'files' / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    before = (root / PROFILE_PATH).read_bytes()
    with pytest.raises(ValueError, match='record'):
        prepare_profile(VirtualProfile(files, (conflicting,)), root)
    assert (root / PROFILE_PATH).read_bytes() == before
    assert load_registry(root) == reservations
    assert game_bytes(root) == original_game


@pytest.mark.parametrize('reverse', [False, True])
def test_virtual_imported_models_auxiliaries_and_recipes_resolve_in_complete_view(tmp_path, reverse, monkeypatch):
    import shutil
    from cdmw.core.item_icon_addition import NewItemIcon, icon_string_for_stem, icon_target_path
    from cdmw.core.stringinfo_table import stringinfo_key
    from cdmw.core.prefab_binary import decode_prefab_binary
    from cdmw.domain.new_item.spec import ModelSource, IconSource, EffectLook
    from cdmw.services.new_item_planning import ModelFiles
    from cdmw.services.new_item_acquisition_index import load_acquisition_index
    from tests.test_new_item_service import PAC_XML, imported_pac, _fake_dds
    from tests.test_independent_items import imported_game
    from tests.test_archive_overlay_manager import snapshot_of
    from tests.test_effect_edit import EFFECT
    # This installation consists only of owned temporary fixtures; a real game
    # running on the developer's machine cannot observe this synthetic profile.
    monkeypatch.setattr('cdmw.services.new_item_service.game_is_running', lambda: False)
    files, source_ids = [], []
    for i in range(2):
        service, snapshot = imported_game(tmp_path / f'author-{i}', auxiliaries=True)
        spec = replace(shop_spec('SameImportedItem'), model_source=ModelSource.IMPORTED,
            icon=IconSource.GENERATED, include_perk_prices=False, effect=EFFECT.stem + '.level.effect',
            effect_look=EffectLook(color=(1, 0, 0), emitter_order=(0,)))
        allocated = service.allocate(spec, snapshot)
        name = icon_string_for_stem(allocated.stem)
        icon = NewItemIcon(name, stringinfo_key(name), icon_target_path(name), _fake_dds(), None, None)
        plan = service.plan(spec, snapshot, model=ModelFiles(imported_pac(100), {PAC_XML: snapshot.payload(PAC_XML)}),
                            icon=icon, capture_independent=True)
        source_ids.append((plan.spec.item_key, plan.spec.internal_name, plan.spec.stem))
        file = tmp_path / f'imported-{i}.cditem'
        file.write_bytes(package_bytes(from_plan(plan, uuid4().hex)))
        files.append(file)
    assert source_ids[0] == source_ids[1]
    imported_game(tmp_path / 'recipient', auxiliaries=True)
    root = tmp_path / 'recipient/game'
    before = game_bytes(root)
    prepared = prepare_profile(VirtualProfile(tuple(reversed(files)) if reverse else tuple(files)), root)
    publish_profile(prepared)
    assert game_bytes(root) == before
    owned = list(load_registry(root)['items'].values())
    assert owned[0]['stem'] != owned[1]['stem']
    assert set(owned[0]['paths']).isdisjoint(owned[1]['paths'])
    for namespace in ('iteminfo', 'effect', 'multichangeinfo', 'dropsetinfo'):
        assert set(owned[0]['values'][namespace].values()).isdisjoint(owned[1]['values'][namespace].values())
    # Materialize only this synthetic fixture's virtual view for the real readers.
    view = tmp_path / 'inspected-view'
    shutil.copytree(root, view, ignore=shutil.ignore_patterns('.cdmw'))
    for path, data in prepared.files:
        out = view / path
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(data)
    snapshot = snapshot_of(view)
    acquisition = load_acquisition_index(snapshot)
    for row in owned:
        key, perk = row['values']['iteminfo']['item'], row['values']['iteminfo']['perk:1002791']
        assert perk in snapshot.rows[key].socket_items
        assert all(price.price == 0 for price in snapshot.rows[perk].price_list)
        assert snapshot.rows[key].name_key in snapshot.english.index()
        for recipe_key in row['values']['multichangeinfo'].values():
            recipe = acquisition.recipes[recipe_key]
            assert key in [entry.item_key for reward in recipe.reward_keys + recipe.additional_reward_keys
                           for entry in acquisition.rewards[reward].entries]
        for path in row['paths']:
            assert snapshot.has_entry(path)
            if path.endswith('.prefab'):
                assert any(row['stem'] in ref.text and ref.text in row['paths']
                           for ref in decode_prefab_binary(snapshot.payload(path)).resource_strings())
            if path.endswith('.dds'):
                assert snapshot.pathc.find(path) is not None
            if path.endswith('.pae'):
                from cdmw.core.effect_binary import decode_effect_binary
                from cdmw.core.effect_edit import emitter_paths_of
                document = decode_effect_binary(snapshot.payload(path))
                assert set(emitter_paths_of(document)) <= set(row['paths'])
                assert {node.type_name.lstrip('/') for node in document.root.walk()
                        if node.type_name.endswith('.paem')} <= set(row['paths'])
