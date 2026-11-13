"""Recompilation bindings and exact wrapper guards on the real composition routes."""
import os
from uuid import uuid4

import pytest

from cdmw.core.mod_compatibility import SEMANTIC_EXPORT_FILE
from cdmw.domain.new_item.independent import IndependentItemError
from tests.support.virtual_domain import VirtualLoaderError, VirtualProfile
from cdmw.services.independent_item_compatibility import prepare_independent_mod_merge
from tests.support.item_install import prepare_install
from cdmw.services.independent_item_package import from_plan, package_bytes
from cdmw.services.mod_merge_service import export_merged_mod
from tests.support.virtual_state import publish_profile, load_profile
from tests.test_archive_overlay_manager import Backups, shop_spec
from tests.test_independent_item_fields import field_package
from tests.test_independent_item_regressions import files_in
from tests.test_independent_items import setup_game
from tests.test_semantic_merge_admission import exported_fields


@pytest.mark.parametrize('virtual', [False, True])
def test_same_size_wrapper_change_after_review_never_publishes(tmp_path, virtual):
    from tests.support.virtual_composition import prepare_profile
    folder, _, _ = exported_fields(tmp_path / 'producer', value=1)
    setup_game(tmp_path / 'recipient')
    root = tmp_path / 'recipient/game'
    wrapper = folder / SEMANTIC_EXPORT_FILE
    if virtual:
        prepared = prepare_profile(VirtualProfile((), (folder,)), root)
    else:
        prepared = prepare_install([wrapper], root).preparation
    before = files_in(root)
    stamp = wrapper.stat()
    data = bytearray(wrapper.read_bytes())
    data[-1] ^= 1
    wrapper.write_bytes(data)
    os.utime(wrapper, ns=(stamp.st_atime_ns, stamp.st_mtime_ns))
    with pytest.raises(ValueError, match='[Cc]hanged|[Mm]ismatch'):
        publish_profile(prepared) if virtual else Backups(tmp_path / 'recipient').apply(prepared)
    assert files_in(root) == before


def test_semantic_item_binding_collision_does_not_renumber_retired_or_live_ids(tmp_path):
    service, snapshot, _ = setup_game(tmp_path / 'producer')
    legacy = from_plan(service.plan(shop_spec('ExportedLegacy'), snapshot, capture_independent=True), uuid4().hex)
    keep = field_package(snapshot, value=1)
    root = tmp_path / 'producer/game'
    Backups(tmp_path / 'producer').apply(prepare_install([package_bytes(legacy), package_bytes(keep)], root).preparation)
    folder = export_merged_mod(prepare_independent_mod_merge(root), tmp_path / 'export').package_root
    other_service, other_snapshot, _ = setup_game(tmp_path / 'recipient')
    other = from_plan(other_service.plan(shop_spec('ReservedElsewhere'), other_snapshot, capture_independent=True), uuid4().hex)
    recipient = tmp_path / 'recipient/game'
    Backups(tmp_path / 'recipient').apply(prepare_install([package_bytes(other)], recipient).preparation)
    before = files_in(recipient)
    with pytest.raises(IndependentItemError, match='Conflicting|relocation'):
        prepare_install([folder], recipient)
    assert files_in(recipient) == before


def test_installed_export_recompiles_legacy_intent_before_publishing(tmp_path):
    from cdmw.core.iteminfo_row import parse_iteminfo_row, set_max_stack_count
    from cdmw.domain.archives.iteminfo_composition import replace_rows, rows_of
    import tests.support.overlay_manager as overlays
    from cdmw.services.independent_item_install import load_registry
    from cdmw.services.independent_item_package import digest
    service, snapshot, _ = setup_game(tmp_path)
    legacy = from_plan(service.plan(shop_spec('WitnessedLegacy'), snapshot, capture_independent=True), uuid4().hex)
    keep = field_package(snapshot, value=1)
    root = tmp_path / 'game'
    Backups(tmp_path).apply(prepare_install([package_bytes(legacy), package_bytes(keep)], root).preparation)
    registry = load_registry(root)
    state = overlays._load_index(root)
    layer = next(row for row in state['layers'] if row.get('independent_identity') == legacy.identity)
    changes = overlays._unpack_changes(root, layer, {}, None)
    body, head = snapshot.iteminfo.payload_entry.path, snapshot.iteminfo.header_entry.path
    key = registry['items'][legacy.identity]['values']['iteminfo']['item']
    row = parse_iteminfo_row(rows_of(changes[body]['after'], changes[head]['after'])[key])
    changes[body]['after'] = replace_rows(changes[body]['after'], changes[head]['after'],
                                          {key: set_max_stack_count(row, 9)})
    journal = overlays._pack_changes(changes)
    (root / overlays.overlay_journal_path(layer)).write_bytes(journal)
    layer['sha256'] = digest(journal)
    (root / overlays.INDEX_PATH).write_bytes(overlays._inventory_bytes(state))
    before = files_in(root)
    with pytest.raises(ValueError, match='recompilation'):
        prepare_independent_mod_merge(root)
    assert files_in(root) == before


