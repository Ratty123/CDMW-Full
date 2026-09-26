"""Reversible overlay controls and rebasing on owned game fixtures."""
from dataclasses import replace
import json
import threading

import pytest

from cdmw.core.structured_binary_editor import parse_pabgh_table, replace_table_row
from cdmw.domain.cancellation import RunCancelled
from cdmw.services.archive_overlay_manager import (
    INDEX_PATH, list_installed_overlays, overlay_journal_path, prepare_overlay_enabled,
    prepare_overlay_removal,
)
from cdmw.services.archive_overlay_rebuild import prepare_overlay_rebuild
from tests.test_archive_overlay_manager import Backups, shop_spec, snapshot_of
from tests.test_mod_merge import fingerprint
from tests.test_new_item_provenance import current_files, setup_game
from tests.test_new_item_service import build_package, TEMPLATE


def install_pair(tmp_path, *, dependent=False):
    service, snapshot, _ = setup_game(tmp_path)
    root, backups = tmp_path / 'game', Backups(tmp_path)
    plans = []
    for name in ('Alpha', 'Beta'):
        choice = replace(shop_spec(name), recipes=())
        if plans and dependent:
            choice = replace(choice, template_key=plans[0].spec.item_key)
        plan = service.plan(choice, snapshot)
        service.install_overlay(plan, mutation_service=backups, confirmed=True, game_running=lambda: False)
        plans.append(plan)
        snapshot = snapshot_of(root)
    return root, backups, plans


def test_disable_enable_last_and_individual_keep_identity_and_removal_distinct(tmp_path):
    root, backups, plans = install_pair(tmp_path)
    original = list_installed_overlays(root)
    shipped = fingerprint(root / '0009')
    backups.apply(prepare_overlay_enabled(root, original[0].id, False))
    entries = list_installed_overlays(root)
    assert [e.enabled for e in entries] == [False, True]
    assert entries[0].health == 'disabled'
    assert plans[0].spec.item_key not in snapshot_of(root).rows
    assert plans[1].spec.item_key in snapshot_of(root).rows
    backups.apply(prepare_overlay_enabled(root, original[1].id, False))
    assert not (root / original[0].directory).exists()
    assert [e.id for e in list_installed_overlays(root)] == [e.id for e in original]
    backups.apply(prepare_overlay_enabled(root, original[0].id, True))
    assert plans[0].spec.item_key in snapshot_of(root).rows
    backups.apply(prepare_overlay_removal(root, original[1].id))
    assert [e.id for e in list_installed_overlays(root)] == [original[0].id]
    with pytest.raises(ValueError, match='no longer installed'):
        prepare_overlay_enabled(root, original[1].id, True)
    assert fingerprint(root / '0009') == shipped


def test_disable_dependency_is_blocked_and_disabled_identity_is_reserved(tmp_path):
    root, backups, plans = install_pair(tmp_path, dependent=True)
    entries = list_installed_overlays(root)
    before = fingerprint(root)
    with pytest.raises(ValueError, match='dependent overlay'):
        prepare_overlay_enabled(root, entries[0].id, False)
    assert fingerprint(root) == before
    backups.apply(prepare_overlay_enabled(root, entries[1].id, False))
    backups.apply(prepare_overlay_enabled(root, entries[0].id, False))
    from cdmw.services.new_item_service import NewItemService
    from cdmw.services.archive_overlay_manager import prepare_item_overlay
    duplicate = NewItemService().plan(replace(shop_spec('Duplicate'), item_key=plans[1].spec.item_key, recipes=()),
                                     snapshot_of(root))
    with pytest.raises(ValueError, match='identity conflicts'):
        prepare_item_overlay(duplicate, root)
    with pytest.raises(ValueError, match='dependent overlay'):
        prepare_overlay_enabled(root, entries[1].id, True)
    backups.apply(prepare_overlay_enabled(root, entries[0].id, True))
    backups.apply(prepare_overlay_enabled(root, entries[1].id, True))
    assert all(e.enabled for e in list_installed_overlays(root))


def test_rebuild_after_game_update_preserves_new_game_row_and_individual_history(tmp_path):
    root, backups, plans = install_pair(tmp_path)
    original = list_installed_overlays(root)
    snapshot = snapshot_of(root)
    old_state = json.loads((root / INDEX_PATH).read_text())
    old_journals = {root / overlay_journal_path(layer): (root / overlay_journal_path(layer)).read_bytes()
                    for layer in old_state['layers']}
    files = current_files()
    body_path, head_path = snapshot.iteminfo.payload_entry.path, snapshot.iteminfo.header_entry.path
    body, head = files[body_path], files[head_path]
    row = next(body[start:end] for item, start, end in parse_pabgh_table(head, payload=body).row_spans(len(body))
               if item.row_id == TEMPLATE)
    from cdmw.core.iteminfo_row import parse_iteminfo_row, price_list_with, rebuild_stat_block
    parsed = parse_iteminfo_row(row)
    replacement = rebuild_stat_block(parsed, price_list=price_list_with(parsed.price_list, 1, 9876))
    files[body_path], files[head_path] = replace_table_row(body, head, TEMPLATE, replacement)
    build_package(root, files)  # A game update restores its mount list too.
    (root / 'meta/0.paver').write_text('2.00.01')
    assert all(e.health == 'unmounted' for e in list_installed_overlays(root))
    before = fingerprint(root)
    shipped = fingerprint(root / '0009')
    prepared = prepare_overlay_rebuild(root)
    assert fingerprint(root) == before, 'Comparison is read-only.'
    assert prepared.action == 'rebuild'
    result = backups.apply(prepared)
    assert result.action == 'rebuild'
    entries = list_installed_overlays(root)
    assert [e.id for e in entries] == [e.id for e in original]
    assert all(e.health == 'mounted' and e.game_build == '2.00.01' for e in entries)
    current = snapshot_of(root)
    assert all(plan.spec.item_key in current.rows for plan in plans)
    rows = {item.row_id: current.iteminfo.payload[start:end] for item, start, end in
            parse_pabgh_table(current.iteminfo.header, payload=current.iteminfo.payload).row_spans(len(current.iteminfo.payload))}
    assert rows[TEMPLATE] == replacement
    assert all(path.read_bytes() == payload for path, payload in old_journals.items())
    assert list((root / '.cdmw/retired-overlays').glob('*.json'))
    # Removal after rebasing keeps the game update and the other logical install.
    backups.apply(prepare_overlay_removal(root, entries[0].id))
    current = snapshot_of(root)
    assert plans[0].spec.item_key not in current.rows and plans[1].spec.item_key in current.rows
    assert fingerprint(root / '0009') == shipped


def test_rebuild_refuses_changed_owned_bytes_and_stale_comparison(tmp_path):
    root, backups, _ = install_pair(tmp_path)
    prepared = prepare_overlay_rebuild(root)
    index = root / INDEX_PATH
    index.write_bytes(index.read_bytes() + b' ')
    with pytest.raises(ValueError, match='changed after preparation'):
        backups.apply(prepared)
    group = list_installed_overlays(root)[0].directory
    payload = root / group / '0.paz'
    payload.write_bytes(payload.read_bytes() + b'foreign edit')
    before = fingerprint(root)
    with pytest.raises(ValueError, match='changed outside'):
        prepare_overlay_rebuild(root)
    assert fingerprint(root) == before
    entry = list_installed_overlays(root)[0]
    assert entry.health == 'changed' and entry.issue


def test_rebuild_cancellation_and_write_failure_restore_fixture(tmp_path, monkeypatch):
    from cdmw.services import archive_overlay_manager as owner
    root, backups, _ = install_pair(tmp_path)
    prepared = prepare_overlay_rebuild(root)
    before = fingerprint(root)
    stop = threading.Event()
    stop.set()
    with pytest.raises(RunCancelled):
        backups.apply(prepared, stop_event=stop)
    assert fingerprint(root) == before
    write = owner.atomic_write_bytes
    def fail(path, data):
        if path.name == '0.pamt':
            raise OSError('simulated write failure')
        return write(path, data)
    monkeypatch.setattr(owner, 'atomic_write_bytes', fail)
    with pytest.raises(OSError, match='simulated'):
        backups.apply(prepared)
    assert fingerprint(root) == before


@pytest.mark.parametrize('copies_owned_id', [False, True])
def test_rebuild_preserves_foreign_shared_tables_and_rejects_owned_id_collision(tmp_path, copies_owned_id):
    from cdmw.core.archive_format import parse_archive_pamt
    from cdmw.core.papgt_format import papgt_with_directory, parse_papgt
    from cdmw.services.new_item_service import NewItemService
    from tests.test_new_item_service import _read
    root, backups, plans = install_pair(tmp_path)
    service = NewItemService()
    baseline = service.build_snapshot(parse_archive_pamt(root / '0009/0.pamt'), read_entry=_read)
    key = plans[0].spec.item_key if copies_owned_id else plans[-1].spec.item_key + 100
    foreign = service.plan(replace(shop_spec('Foreign'), item_key=key, recipes=()), baseline)
    pamt = build_package(tmp_path / 'foreign', dict(foreign.loose_files))
    directory = root / '0042'
    directory.mkdir()
    for source in pamt.parent.iterdir():
        if source.is_file():
            (directory / source.name).write_bytes(source.read_bytes())
    mount = root / 'meta/0.papgt'
    mount.write_bytes(papgt_with_directory(mount.read_bytes(), directory.name,
        int.from_bytes((directory / '0.pamt').read_bytes()[:4], 'little'), first=True))
    before = fingerprint(root)
    foreign_before = fingerprint(directory)
    if copies_owned_id:
        with pytest.raises(ValueError, match='already supplies owned item IDs'):
            prepare_overlay_rebuild(root)
        assert fingerprint(root) == before
        return
    backups.apply(prepare_overlay_rebuild(root))
    assert key in snapshot_of(root).rows
    entries = list_installed_overlays(root)
    backups.apply(prepare_overlay_removal(root, entries[0].id))
    current = snapshot_of(root)
    assert key in current.rows and plans[1].spec.item_key in current.rows
    assert plans[0].spec.item_key not in current.rows
    assert fingerprint(directory) == foreign_before
    assert any(record.name == '0042' for record in parse_papgt(mount.read_bytes()))


def test_rebuild_retains_disabled_installs_and_updated_journals_can_still_export(tmp_path):
    from cdmw.workers.mod_update_workers import mod_update_scan_task
    root, backups, plans = install_pair(tmp_path)
    entries = list_installed_overlays(root)
    backups.apply(prepare_overlay_enabled(root, entries[1].id, False))
    backups.apply(prepare_overlay_rebuild(root))
    assert [e.enabled for e in list_installed_overlays(root)] == [True, False]
    assert plans[1].spec.item_key not in snapshot_of(root).rows
    checked = mod_update_scan_task('', root, installed=True)(lambda *_: None, lambda *_: None, threading.Event())
    assert checked.can_update, checked.conflicts
    backups.apply(prepare_overlay_enabled(root, entries[1].id, True))
    assert plans[1].spec.item_key in snapshot_of(root).rows


def test_health_is_independent_of_the_game_build_label(tmp_path):
    root, _, _ = install_pair(tmp_path)
    entry = list_installed_overlays(root)[0]
    (root / entry.directory / '0.paz').unlink()
    changed = list_installed_overlays(root)[0]
    assert changed.game_build == entry.game_build
    assert changed.health == 'missing' and changed.issue


def test_rebuild_and_remove_preserve_foreign_texture_registry_entries(tmp_path):
    from cdmw.core.pathc_format import encode_pathc, parse_pathc, register_dds
    from cdmw.domain.archives.mutation import ArchiveAddRequest, MetaFileWrite
    from tests.test_pathc_format import build_table, ICON_HEADER, ICON_BLOCKS, BIG_HEADER
    service, _, _ = setup_game(tmp_path)
    root, backups = tmp_path / 'game', Backups(tmp_path)
    registry = root / 'meta/0.pathc'
    base = build_table(headers=[ICON_HEADER], entries=[('ui/texture/base.dds', 0, ICON_BLOCKS)])
    registry.write_bytes(encode_pathc(base))
    own_path, foreign_path = 'ui/texture/ours.dds', 'ui/texture/foreign.dds'
    plan = service.plan(shop_spec('TextureOwner'), snapshot_of(root))
    ours = register_dds(base, own_path, BIG_HEADER, tag=4)
    plan = replace(plan,
        additions=plan.additions + (ArchiveAddRequest.from_template(plan.patches[0].entry, own_path, BIG_HEADER),),
        meta_files=(MetaFileWrite('meta/0.pathc', encode_pathc(ours)),))
    service.install_overlay(plan, mutation_service=backups, confirmed=True, game_running=lambda: False)
    live = register_dds(ours, foreign_path, BIG_HEADER, tag=4)
    registry.write_bytes(encode_pathc(live))
    backups.apply(prepare_overlay_rebuild(root))
    assert parse_pathc(registry.read_bytes()).find(own_path) is not None
    backups.apply(prepare_overlay_removal(root, list_installed_overlays(root)[0].id))
    after = parse_pathc(registry.read_bytes())
    assert after.find(own_path) is None
    assert after.find(foreign_path) is not None
    assert after.dds_header_for(after.find(foreign_path)) == live.dds_header_for(live.find(foreign_path))
