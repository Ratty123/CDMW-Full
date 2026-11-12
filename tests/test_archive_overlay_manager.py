from dataclasses import replace
import json
from pathlib import Path
import threading

import pytest

from cdmw.core.archive_format import parse_archive_pamt
from cdmw.core.archive_scan_cache import discover_pamt_files
from cdmw.core.papgt_format import parse_papgt
from cdmw.domain.new_item.spec import Placement, PlacementKind, UNLIMITED_STOCK
from tests.support.overlay_manager import (
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
    with pytest.raises(ValueError, match='changed after an older CDMW installed overlays'):
        prepare_overlay_removal(root, inventory[0].id)
    assert backups.count == 1


def test_failure_and_cancellation_restore_files_and_do_not_publish_ownership(tmp_path, monkeypatch):
    import tests.support.overlay_manager as manager
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


def test_legacy_removal_preserves_later_foreign_texture_registrations(tmp_path, monkeypatch):
    import cdmw.core.archive_patching as patching
    from cdmw.domain.archives.mutation import ArchiveAddRequest
    from tests.support.overlay_install import install_overlay
    from cdmw.core.pathc_format import encode_pathc, parse_pathc, register_dds
    from tests.test_pathc_format import build_table, ICON_HEADER, ICON_BLOCKS, BIG_HEADER, dds_payload

    monkeypatch.setattr(patching, 'ARCHIVE_PATCH_BACKUP_ROOT', tmp_path / 'backups')
    service, _snapshot, _ = setup_game(tmp_path)
    root, backups = tmp_path / 'game', Backups(tmp_path)
    base = build_table(headers=[ICON_HEADER], entries=[('ui/texture/base.dds', 0, ICON_BLOCKS)])
    registry = root / 'meta/0.pathc'
    registry.write_bytes(encode_pathc(base))
    legacy_path, foreign_path = 'ui/texture/legacy.dds', 'ui/texture/foreign_mod.dds'
    owned = register_dds(base, legacy_path, dds_payload(BIG_HEADER), tag=4)
    old = service.plan(shop_spec('Legacy'), snapshot_of(root))
    texture = ArchiveAddRequest.from_template(old.patches[0].entry, legacy_path, dds_payload(BIG_HEADER))
    install_overlay(old.patches, old.additions + (texture,), package_root=root, game_running=lambda: False,
        meta_files=[('meta/0.pathc', encode_pathc(owned))])
    # This mod shares the header introduced by the older overlay.
    live = register_dds(owned, foreign_path, dds_payload(BIG_HEADER), tag=4)
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
