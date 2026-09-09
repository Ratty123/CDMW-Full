from dataclasses import replace
import json
from pathlib import Path
import threading

import pytest

from cdmw.core.archive_format import parse_archive_pamt
from cdmw.core.archive_scan_cache import discover_pamt_files
from cdmw.core.papgt_format import parse_papgt
from cdmw.domain.new_item.spec import Placement, PlacementKind, UNLIMITED_STOCK
from cdmw.services.archive_overlay_manager import (
    INDEX_PATH, list_installed_overlays, prepare_item_overlay, prepare_overlay_removal, apply_overlay_change,
)
from cdmw.services.new_item_service import NewItemService
from tests import test_archive_overlay_install as backup_fixture
from tests.test_new_item_provenance import setup_game, spec
from tests.test_new_item_service import _read


class Backups:
    def __init__(self, root):
        self.root, self.count = root, 0

    def backup_files(self, paths, *, description='', on_log=None):
        path = self.root / f'backup-{self.count}'
        self.count += 1
        backup_fixture.OverlayInstallTests._write_backup_manifest(path, paths)
        return path

    def restore_backup(self, path, *, confirmed=True, on_log=None):
        for item in json.loads((path / 'backup_manifest.json').read_text())['files']:
            target = Path(item['original_path'])
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(Path(item['backup_path']).read_bytes())

    def apply(self, preparation, **kwargs):
        return apply_overlay_change(preparation, confirmed=True,
            backup=lambda paths, label: self.backup_files(paths, description=label),
            restore_backup=self.restore_backup, game_running=lambda: False, **kwargs)


def snapshot_of(root):
    entries = [entry for pamt in discover_pamt_files(root) for entry in parse_archive_pamt(pamt)]
    return NewItemService().build_snapshot(entries, read_entry=_read)


def shop_spec(name):
    return replace(spec(name), placement=Placement(kind=PlacementKind.INSERT, store_name='Store_Camp_Equipment', stock_count=UNLIMITED_STOCK))


@pytest.mark.parametrize('order', [(0, 1), (1, 0)])
def test_two_items_share_tables_and_either_one_can_be_removed(tmp_path, order):
    service, snapshot, _ = setup_game(tmp_path)
    root, backups = tmp_path / 'game', Backups(tmp_path)
    shipped = {path: path.read_bytes() for path in (root / '0009').glob('*') if path.is_file()}
    original_mount = (root / 'meta/0.papgt').read_bytes()
    plans = []
    for label in ('Alpha', 'Beta'):
        plan = service.plan(shop_spec(label), snapshot)
        plans.append(plan)
        service.install_overlay(plan, mutation_service=backups, confirmed=True, game_running=lambda: False)
        snapshot = snapshot_of(root)
    catalog = list_installed_overlays(root)
    assert [entry.label for entry in catalog] == ['Alpha', 'Beta']
    assert len({entry.directory for entry in catalog}) == 1
    assert all(plan.spec.item_key in snapshot.rows for plan in plans)
    selected, remaining = order
    prepared = prepare_overlay_removal(root, catalog[selected].id)
    assert len(list_installed_overlays(root)) == 2, 'preparation must be read-only'
    result = backups.apply(prepared)
    assert result.remaining == 1
    snapshot = snapshot_of(root)
    removed_key, kept_key = plans[selected].spec.item_key, plans[remaining].spec.item_key
    assert removed_key not in snapshot.rows and kept_key in snapshot.rows
    camp = next(store for store in snapshot.stores if store.name == 'Store_Camp_Equipment')
    assert not camp.entries_for(removed_key)
    assert camp.entries_for(kept_key)[0].count == UNLIMITED_STOCK
    assert [e.stock_index for e in camp.entries] == list(range(len(camp.entries)))
    assert all(removed_key not in group.members for group in snapshot.item_groups)
    assert any(kept_key in group.members for group in snapshot.item_groups)
    for language in snapshot.languages:
        index = snapshot.paloc_table(language).index()
        assert plans[selected].spec.name_key not in index
        assert index[plans[remaining].spec.name_key].text in ('Alpha', 'Beta', 'سيف جديد')
    backups.apply(prepare_overlay_removal(root, catalog[remaining].id))
    assert list_installed_overlays(root) == ()
    assert parse_papgt((root / 'meta/0.papgt').read_bytes()) == parse_papgt(original_mount)
    assert not (root / catalog[0].directory).exists()
    assert all(path.read_bytes() == data for path, data in shipped.items())
    # Removed history does not prevent another independent install.
    snapshot = snapshot_of(root)
    again = service.plan(shop_spec('Gamma'), snapshot)
    service.install_overlay(again, mutation_service=backups, confirmed=True, game_running=lambda: False)
    assert [entry.label for entry in list_installed_overlays(root)] == ['Gamma']


def test_preparation_rejects_reused_identity_and_removing_a_template_dependency(tmp_path):
    service, snapshot, _ = setup_game(tmp_path)
    root, backups = tmp_path / 'game', Backups(tmp_path)
    first = service.plan(replace(shop_spec('Alpha'), recipes=()), snapshot)
    service.install_overlay(first, mutation_service=backups, confirmed=True, game_running=lambda: False)
    with pytest.raises(ValueError):
        prepare_item_overlay(first, root)
    snapshot = snapshot_of(root)
    second = service.plan(replace(shop_spec('Beta'), template_key=first.spec.item_key), snapshot)
    service.install_overlay(second, mutation_service=backups, confirmed=True, game_running=lambda: False)
    first_id = list_installed_overlays(root)[0].id
    with pytest.raises(ValueError, match='dependent overlay'):
        prepare_overlay_removal(root, first_id)
    assert len(list_installed_overlays(root)) == 2


def test_missing_confirmation_stale_preparation_and_external_changes_fail_before_write(tmp_path):
    service, snapshot, _ = setup_game(tmp_path)
    root, backups = tmp_path / 'game', Backups(tmp_path)
    plan = service.plan(shop_spec('Alpha'), snapshot)
    prepared = prepare_item_overlay(plan, root)
    with pytest.raises(PermissionError):
        apply_overlay_change(prepared, confirmed=False, backup=None, restore_backup=None)
    backups.apply(prepared)
    with pytest.raises(ValueError, match='changed after preparation'):
        backups.apply(prepared)
    inventory = list_installed_overlays(root)
    pamt = root / inventory[0].directory / '0.pamt'
    pamt.write_bytes(pamt.read_bytes() + b'changed')
    with pytest.raises(ValueError, match='changed outside'):
        prepare_overlay_removal(root, inventory[0].id)
    assert backups.count == 1


def test_failure_and_cancellation_restore_files_and_do_not_publish_ownership(tmp_path, monkeypatch):
    import cdmw.services.archive_overlay_manager as manager
    service, snapshot, _ = setup_game(tmp_path)
    root, backups = tmp_path / 'game', Backups(tmp_path)
    prepared = prepare_item_overlay(service.plan(shop_spec('Alpha'), snapshot), root)
    original = (root / 'meta/0.papgt').read_bytes()
    write = manager.atomic_write_bytes
    for cancelled in (False, True):
        stop = threading.Event()
        def fail(path, payload):
            write(path, payload)
            if path.name == '0.paz':
                if cancelled:
                    stop.set()
                else:
                    raise OSError('injected payload failure')
        monkeypatch.setattr(manager, 'atomic_write_bytes', fail)
        with pytest.raises((OSError, RuntimeError)):
            backups.apply(prepared, stop_event=stop)
        assert (root / 'meta/0.papgt').read_bytes() == original
        assert not (root / INDEX_PATH).exists()
        assert not (root / prepared.directory_name / '0.paz').exists()
        assert not list((root / '.cdmw').glob('overlays/*.zip'))


def test_earlier_installer_is_listed_and_adopted_as_one_removable_bundle(tmp_path):
    from cdmw.services.archive_overlay_install import install_overlay
    from cdmw.core.papgt_format import papgt_with_directory
    service, snapshot, _ = setup_game(tmp_path)
    root, backups = tmp_path / 'game', Backups(tmp_path)
    mount = root / 'meta/0.papgt'
    mount.write_bytes(papgt_with_directory(mount.read_bytes(), '0036', 0, first=True))
    snapshot = snapshot_of(root)
    old = service.plan(shop_spec('Old'), snapshot)
    install_overlay(old.patches, old.additions, package_root=root, game_running=lambda: False)
    legacy = list_installed_overlays(root)
    assert len(legacy) == 1 and legacy[0].legacy
    snapshot = snapshot_of(root)
    new = service.plan(shop_spec('New'), snapshot)
    service.install_overlay(new, mutation_service=backups, confirmed=True, game_running=lambda: False)
    catalog = list_installed_overlays(root)
    assert len(catalog) == 2 and catalog[0].legacy
    backups.apply(prepare_overlay_removal(root, catalog[0].id))
    snapshot = snapshot_of(root)
    assert old.spec.item_key not in snapshot.rows and new.spec.item_key in snapshot.rows


def test_borrowed_effect_prevents_removing_its_owner(tmp_path):
    from cdmw.domain.archives.mutation import ArchiveAddRequest

    service, snapshot, _ = setup_game(tmp_path)
    root, backups = tmp_path / 'game', Backups(tmp_path)
    first = service.plan(shop_spec('Alpha'), snapshot)
    effect = ArchiveAddRequest.from_template(first.patches[0].entry,
        'effect/binary__/releasebin/fx_owned_alpha.pae', b'owned effect fixture')
    first = replace(first, additions=first.additions + (effect,))
    service.install_overlay(first, mutation_service=backups, confirmed=True, game_running=lambda: False)
    second = service.plan(shop_spec('Beta'), snapshot_of(root))
    second = replace(second, manifest=dict(second.manifest, effects=[{'path': 'fx_owned_alpha.level.effect'}]))
    service.install_overlay(second, mutation_service=backups, confirmed=True, game_running=lambda: False)
    with pytest.raises(ValueError, match='dependent overlay'):
        prepare_overlay_removal(root, list_installed_overlays(root)[0].id)


def test_an_external_mod_shadowing_shared_tables_is_not_silently_overridden(tmp_path):
    from cdmw.core.papgt_format import papgt_with_directory
    from tests.test_new_item_service import build_package

    service, snapshot, _ = setup_game(tmp_path)
    root, backups = tmp_path / 'game', Backups(tmp_path)
    first = service.plan(shop_spec('Alpha'), snapshot)
    service.install_overlay(first, mutation_service=backups, confirmed=True, game_running=lambda: False)
    foreign = service.plan(shop_spec('Foreign'), snapshot_of(root))
    pamt = build_package(tmp_path / 'foreign', dict(foreign.loose_files))
    directory = root / '0042'
    directory.mkdir()
    for source in pamt.parent.iterdir():
        if source.is_file():
            (directory / source.name).write_bytes(source.read_bytes())
    mount = root / 'meta/0.papgt'
    checksum = int.from_bytes((directory / '0.pamt').read_bytes()[:4], 'little')
    mount.write_bytes(papgt_with_directory(mount.read_bytes(), '0042', checksum, first=True))
    next_plan = service.plan(shop_spec('Beta'), snapshot_of(root))
    with pytest.raises(ValueError, match='overlapping file edits'):
        prepare_item_overlay(next_plan, root)
    with pytest.raises(ValueError, match='overlapping file edits'):
        prepare_overlay_removal(root, list_installed_overlays(root)[0].id)
    assert backups.count == 1


def test_a_change_during_backup_is_preserved_and_publication_is_refused(tmp_path):
    service, snapshot, _ = setup_game(tmp_path)
    root, backups = tmp_path / 'game', Backups(tmp_path)
    prepared = prepare_item_overlay(service.plan(shop_spec('Alpha'), snapshot), root)
    mount = root / 'meta/0.papgt'
    external = mount.read_bytes() + b'external update during backup'
    def backup(paths, label):
        saved = backups.backup_files(paths, description=label)
        mount.write_bytes(external)
        return saved
    with pytest.raises(ValueError, match='changed after preparation'):
        apply_overlay_change(prepared, confirmed=True, backup=backup,
            restore_backup=backups.restore_backup, game_running=lambda: False)
    assert mount.read_bytes() == external
    assert not (root / INDEX_PATH).exists()
    assert not (root / prepared.directory_name / '0.pamt').exists()


@pytest.mark.parametrize('old_inventory', [False, True])
def test_recipe_ingredients_prevent_removing_their_owner(tmp_path, old_inventory):
    from cdmw.domain.new_item.authoring import RecipeInput, RecipeOverride
    from tests.test_new_item_service import MC_ROW_0

    service, snapshot, _ = setup_game(tmp_path)
    root, backups = tmp_path / 'game', Backups(tmp_path)
    first = service.plan(replace(shop_spec('Alpha'), recipes=()), snapshot)
    service.install_overlay(first, mutation_service=backups, confirmed=True, game_running=lambda: False)
    second = service.plan(replace(shop_spec('Beta'), recipes=(RecipeOverride(MC_ROW_0,
        inputs=(RecipeInput(first.spec.item_key, 1),)),)), snapshot_of(root))
    assert any(i['item_key'] == first.spec.item_key for r in second.manifest['recipes'] for i in r['inputs'])
    service.install_overlay(second, mutation_service=backups, confirmed=True, game_running=lambda: False)
    catalog = list_installed_overlays(root)
    inventory = json.loads((root / INDEX_PATH).read_bytes())
    assert inventory['layers'][1]['dependencies'] == [catalog[0].id]
    if old_inventory:
        # Earlier inventories omitted recipe dependencies; journal rows still
        # prove the dependency and must protect an already installed item.
        inventory['layers'][1]['dependencies'] = []
        (root / INDEX_PATH).write_text(json.dumps(inventory), encoding='utf-8')
    before = {path: path.read_bytes() for path in (root / catalog[0].directory).iterdir()}
    with pytest.raises(ValueError, match='dependent overlay'):
        prepare_overlay_removal(root, catalog[0].id)
    assert all(path.read_bytes() == value for path, value in before.items())
    assert backups.count == 2
    backups.apply(prepare_overlay_removal(root, catalog[1].id))
    backups.apply(prepare_overlay_removal(root, catalog[0].id))
    assert list_installed_overlays(root) == ()


def test_recipe_output_dependencies_are_read_from_the_generated_rows(tmp_path):
    from cdmw.core.item_reward_table import parse_item_reward_set, encode_item_reward_set
    from cdmw.core.structured_binary_editor import parse_pabgh_table, replace_table_row

    service, snapshot, _ = setup_game(tmp_path)
    root, backups = tmp_path / 'game', Backups(tmp_path)
    first = service.plan(replace(shop_spec('Alpha'), recipes=()), snapshot)
    service.install_overlay(first, mutation_service=backups, confirmed=True, game_running=lambda: False)
    second = service.plan(shop_spec('Beta'), snapshot_of(root))
    body_request = next(p for p in second.patches if p.entry.path.endswith('dropsetinfo.staticinfobody'))
    head_request = next(p for p in second.patches if p.entry.path.endswith('dropsetinfo.staticinfoheader'))
    body, head = body_request.payload_data, head_request.payload_data
    reward_key = second.manifest['recipes'][0]['reward_keys'][0]
    reward = next(parse_item_reward_set(body[start:end]) for entry, start, end in
        parse_pabgh_table(head, payload=body).row_spans(len(body)) if entry.row_id == reward_key)
    reward = replace(reward, entries=reward.entries + (replace(reward.entries[0], item_key=first.spec.item_key),))
    body, head = replace_table_row(body, head, reward_key, encode_item_reward_set(reward))
    # The summary intentionally does not advertise this additional product:
    # dependency protection must inspect the actual rows being installed.
    second = replace(second, patches=tuple(replace(p, payload_data=body) if p is body_request else
        replace(p, payload_data=head) if p is head_request else p for p in second.patches))
    service.install_overlay(second, mutation_service=backups, confirmed=True, game_running=lambda: False)
    catalog = list_installed_overlays(root)
    with pytest.raises(ValueError, match='dependent overlay'):
        prepare_overlay_removal(root, catalog[0].id)
    backups.apply(prepare_overlay_removal(root, catalog[1].id))
    assert first.spec.item_key in snapshot_of(root).rows


def test_empty_inventory_starts_a_fresh_baseline_after_a_game_update(tmp_path):
    from cdmw.core.iteminfo_row import parse_iteminfo_row, rebuild_stat_block, price_list_with
    from cdmw.core.structured_binary_editor import parse_pabgh_table, replace_table_row
    from cdmw.core.pathc_format import encode_pathc, register_dds
    from tests.test_pathc_format import build_table, ICON_HEADER, ICON_BLOCKS
    from tests.test_new_item_provenance import current_files
    from tests.test_new_item_service import build_package, TEMPLATE

    service, snapshot, _ = setup_game(tmp_path)
    root, backups = tmp_path / 'game', Backups(tmp_path)
    registry = root / 'meta/0.pathc'
    baseline = build_table(headers=[ICON_HEADER], entries=[('ui/texture/base.dds', 0, ICON_BLOCKS)])
    registry.write_bytes(encode_pathc(baseline))
    first = service.plan(shop_spec('Alpha'), snapshot_of(root))
    service.install_overlay(first, mutation_service=backups, confirmed=True, game_running=lambda: False)
    backups.apply(prepare_overlay_removal(root, list_installed_overlays(root)[0].id))
    old_journals = {path: path.read_bytes() for path in (root / '.cdmw/overlays').glob('*.zip')}
    assert list_installed_overlays(root) == ()

    updated = current_files()
    body_path = 'gamedata/binarystaticinfo__/bin/iteminfo.staticinfobody'
    head_path = body_path.replace('body', 'header')
    body, head = updated[body_path], updated[head_path]
    row = next(parse_iteminfo_row(body[start:end]) for entry, start, end in
        parse_pabgh_table(head, payload=body).row_spans(len(body)) if entry.row_id == TEMPLATE)
    row_bytes = rebuild_stat_block(row, price_list=price_list_with(row.price_list, 1, 12345))
    updated[body_path], updated[head_path] = replace_table_row(body, head, TEMPLATE, row_bytes)
    build_package(root, updated)
    registry.write_bytes(encode_pathc(register_dds(baseline, 'ui/texture/game_update.dds', ICON_HEADER)))
    shipped = {path: path.read_bytes() for path in (root / '0009').iterdir() if path.is_file()}
    registry_before = registry.read_bytes()
    next_plan = service.plan(shop_spec('AfterUpdate'), snapshot_of(root))
    service.install_overlay(next_plan, mutation_service=backups, confirmed=True, game_running=lambda: False)
    assert snapshot_of(root).rows[TEMPLATE].raw == row_bytes
    assert len(json.loads((root / INDEX_PATH).read_bytes())['layers']) == 1
    backups.apply(prepare_overlay_removal(root, list_installed_overlays(root)[0].id))
    assert snapshot_of(root).rows[TEMPLATE].raw == row_bytes
    assert registry.read_bytes() == registry_before
    assert all(path.read_bytes() == value for path, value in shipped.items())
    assert all(path.read_bytes() == value for path, value in old_journals.items())


def test_empty_history_cannot_overwrite_a_still_mounted_managed_archive(tmp_path):
    service, snapshot, _ = setup_game(tmp_path)
    root, backups = tmp_path / 'game', Backups(tmp_path)
    service.install_overlay(service.plan(shop_spec('Alpha'), snapshot),
        mutation_service=backups, confirmed=True, game_running=lambda: False)
    inventory = json.loads((root / INDEX_PATH).read_bytes())
    inventory['layers'][0]['active'] = False
    (root / INDEX_PATH).write_text(json.dumps(inventory), encoding='utf-8')
    next_plan = service.plan(shop_spec('Beta'), snapshot_of(root))
    with pytest.raises(ValueError, match='changed outside'):
        prepare_item_overlay(next_plan, root)
    assert backups.count == 1


def test_legacy_removal_preserves_later_foreign_texture_registrations(tmp_path, monkeypatch):
    import cdmw.core.archive_patching as patching
    from cdmw.domain.archives.mutation import ArchiveAddRequest
    from cdmw.services.archive_overlay_install import install_overlay
    from cdmw.core.pathc_format import encode_pathc, parse_pathc, register_dds
    from tests.test_pathc_format import build_table, ICON_HEADER, ICON_BLOCKS, BIG_HEADER

    monkeypatch.setattr(patching, 'ARCHIVE_PATCH_BACKUP_ROOT', tmp_path / 'backups')
    service, _snapshot, _ = setup_game(tmp_path)
    root, backups = tmp_path / 'game', Backups(tmp_path)
    base = build_table(headers=[ICON_HEADER], entries=[('ui/texture/base.dds', 0, ICON_BLOCKS)])
    registry = root / 'meta/0.pathc'
    registry.write_bytes(encode_pathc(base))
    legacy_path, foreign_path = 'ui/texture/legacy.dds', 'ui/texture/foreign_mod.dds'
    owned = register_dds(base, legacy_path, BIG_HEADER, tag=4)
    old = service.plan(shop_spec('Legacy'), snapshot_of(root))
    texture = ArchiveAddRequest.from_template(old.patches[0].entry, legacy_path, BIG_HEADER)
    install_overlay(old.patches, old.additions + (texture,), package_root=root, game_running=lambda: False,
        meta_files=[('meta/0.pathc', encode_pathc(owned))])
    # This mod shares the header introduced by the older overlay.
    live = register_dds(owned, foreign_path, BIG_HEADER, tag=4)
    registry.write_bytes(encode_pathc(live))
    before = registry.read_bytes()
    prepared = prepare_overlay_removal(root, list_installed_overlays(root)[0].id)
    assert registry.read_bytes() == before
    backups.apply(prepared)
    after = parse_pathc(registry.read_bytes())
    assert after.find(legacy_path) is None
    assert after.find(foreign_path) == live.find(foreign_path)
    assert after.dds_header_for(after.find(foreign_path)) == BIG_HEADER
    assert after.find('ui/texture/base.dds') == base.find('ui/texture/base.dds')
    assert list_installed_overlays(root) == ()
