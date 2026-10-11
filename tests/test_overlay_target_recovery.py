"""Recovery reverses only verified mutations attempted by this transaction."""
from pathlib import Path
import json
import threading

import pytest

from cdmw.core.archive_overlay import OverlayFile
from cdmw.core.papgt_format import serialize_papgt
from cdmw.domain.archives.mutation import ArchiveAddRequest
from cdmw.domain.cancellation import RunCancelled
from cdmw.services import archive_overlay_install as legacy
from cdmw.services import archive_overlay_manager as managed
from cdmw.services.archive_overlay_migration import MigrationPlan, migrate_into_overlay, remove_overlay
from tests.test_archive_overlay_manager import Backups
from tests.test_overlay_mutation_boundary import prepared_item


def _backup_snapshots(backups):
    folder = backups.root / "backup-0"
    manifest = folder / "backup_manifest.json"
    paths = [manifest, *(Path(row["backup_path"]) for row in json.loads(manifest.read_text())["files"])]
    return {path.relative_to(folder).as_posix(): path.read_bytes() for path in paths}


@pytest.mark.parametrize("new_target", [False, True])
def test_managed_rollback_preserves_untouched_foreign_target(prepared_item, monkeypatch, new_target):
    root, backups, _, prepared = prepared_item
    relative = prepared.directory_name + "/0.paz" if new_target else "meta/0.papgt"
    target = root / relative
    stop = threading.Event()
    write = managed.atomic_write_bytes
    attempted = []
    saved = {}

    def first_write_then_external_change(path, payload):
        write(path, payload)
        attempted.append(path)
        if len(attempted) == 1:
            assert path != target
            saved.update(_backup_snapshots(backups))
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(b"foreign target was never attempted by this transaction")
            stop.set()

    monkeypatch.setattr(managed, "atomic_write_bytes", first_write_then_external_change)
    with pytest.raises(RunCancelled):
        backups.apply(prepared, stop_event=stop)
    assert target.read_bytes() == b"foreign target was never attempted by this transaction"
    assert len(attempted) == 1
    for relative, payload in saved.items():
        assert (backups.root / "backup-0" / relative).read_bytes() == payload


def test_managed_unknown_postimage_requires_recovery_and_preserves_backup(prepared_item, monkeypatch):
    root, backups, _, prepared = prepared_item
    write = managed.atomic_write_bytes
    changed = []
    saved = {}

    def write_then_foreign_replace(path, payload):
        write(path, payload)
        changed.append(path)
        saved.update(_backup_snapshots(backups))
        path.write_bytes(b"foreign bytes after the attempted write")
        raise OSError("injected failure after foreign replacement")

    monkeypatch.setattr(managed, "atomic_write_bytes", write_then_foreign_replace)
    with pytest.raises(RuntimeError, match="recovery.*backup|backup.*recovery") as caught:
        backups.apply(prepared)
    assert changed[0].read_bytes() == b"foreign bytes after the attempted write"
    assert str(backups.root / "backup-0") in str(caught.value)
    for relative, payload in saved.items():
        assert (backups.root / "backup-0" / relative).read_bytes() == payload
    journals = list((backups.root / "backup-0").rglob("*journal*.json"))
    assert journals, "Uncertain mutation evidence must remain with the immutable backup"
    record = json.loads(journals[0].read_text(encoding="utf-8"))
    assert record["status"] == "recovery_required"
    assert any(row["target"] == str(changed[0]) and row["attempted"]
               and not row["completed"] for row in record["targets"])


@pytest.fixture(params=["install", "migrate", "remove"])
def legacy_operation(tmp_path, request):
    root = tmp_path / "game"
    (root / "meta").mkdir(parents=True)
    mount = root / "meta/0.papgt"
    mount.write_bytes(serialize_papgt([]))
    plan = MigrationPlan((OverlayFile("fixture/item.bin", b"item", 4),), (), ())
    if request.param == "install":
        addition = ArchiveAddRequest(pamt_path=root / "0009/0.pamt", path="fixture/item.bin", payload_data=b"item", flags=0)
        prepared = legacy.prepare_overlay_install((), (addition,), package_root=root)
        invoke = lambda **kwargs: legacy.apply_overlay_install(prepared, confirmed=True, **kwargs)
    elif request.param == "migrate":
        invoke = lambda **kwargs: migrate_into_overlay(root, plan=plan, **kwargs)
    else:
        migrate_into_overlay(root, plan=plan)
        invoke = lambda **kwargs: remove_overlay(root, **kwargs)
    return root, Backups(tmp_path), invoke


def test_legacy_cancel_after_backup_never_recovers_unattempted_targets(legacy_operation, monkeypatch):
    root, backups, invoke = legacy_operation
    stop = threading.Event()
    target = root / "meta/0.papgt"
    restores, writes = [], []
    write = legacy._write_atomic

    def backup(paths, label):
        folder = backups.backup_files(paths, description=label)
        target.write_bytes(b"external change made during backup")
        stop.set()
        return folder

    def restore(folder):
        restores.append(folder)
        backups.restore_backup(folder)

    def record_write(path, payload):
        writes.append(path)
        write(path, payload)

    monkeypatch.setattr(legacy, "_write_atomic", record_write)
    with pytest.raises(RunCancelled):
        invoke(backup=backup, restore_backup=restore, stop_event=stop)
    assert restores == [] and writes == []
    assert target.read_bytes() == b"external change made during backup"


def test_legacy_replace_then_error_recovers_only_owned_write(legacy_operation, monkeypatch):
    root, backups, invoke = legacy_operation
    write = legacy._write_atomic
    original = {path: path.read_bytes() for path in root.rglob("*") if path.is_file()}
    writes = []

    def replace_then_error(path, payload):
        write(path, payload)
        writes.append(path)
        raise OSError("injected replace then error")

    monkeypatch.setattr(legacy, "_write_atomic", replace_then_error)
    with pytest.raises(OSError, match="replace then error"):
        invoke(backup=lambda paths, label: backups.backup_files(paths, description=label),
               restore_backup=backups.restore_backup)
    assert len(writes) == 1
    assert {path: path.read_bytes() for path in root.rglob("*") if path.is_file()} == original


@pytest.mark.parametrize("foreign_after_attempt", [False, True])
def test_legacy_preserves_foreign_target_after_staging(legacy_operation, monkeypatch, foreign_after_attempt):
    root, backups, invoke = legacy_operation
    write = legacy._write_atomic
    stop = threading.Event()
    changed = []
    saved = {}

    def first_write_then_foreign_change(path, payload):
        write(path, payload)
        if not changed:
            target = path if foreign_after_attempt else root / "0036/0.paz"
            assert foreign_after_attempt or path != target
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(b"foreign contents must survive rollback")
            changed.append(target)
            saved.update(_backup_snapshots(backups))
            if foreign_after_attempt:
                raise OSError("injected failure after foreign write")
            stop.set()

    monkeypatch.setattr(legacy, "_write_atomic", first_write_then_foreign_change)
    with pytest.raises(RuntimeError) as caught:
        invoke(backup=lambda paths, label: backups.backup_files(paths, description=label),
               restore_backup=backups.restore_backup, stop_event=stop)
    assert changed[0].read_bytes() == b"foreign contents must survive rollback"
    for relative, payload in saved.items():
        assert (backups.root / "backup-0" / relative).read_bytes() == payload
    if foreign_after_attempt:
        assert "recovery" in str(caught.value).lower()
        assert str(backups.root / "backup-0") in str(caught.value)


def test_legacy_removal_unlink_then_error_recovers_removed_file(tmp_path, monkeypatch):
    root = tmp_path / "game"
    (root / "meta").mkdir(parents=True)
    (root / "meta/0.papgt").write_bytes(serialize_papgt([]))
    plan = MigrationPlan((OverlayFile("fixture/item.bin", b"item", 4),), (), ())
    migrated = migrate_into_overlay(root, plan=plan)
    backups = Backups(tmp_path)
    before = {path: path.read_bytes() for path in root.rglob("*") if path.is_file()}
    target, unlink = migrated.directory / "0.pamt", Path.unlink
    attempts = []

    def unlink_then_error(path, *args, **kwargs):
        result = unlink(path, *args, **kwargs)
        if path == target:
            attempts.append(path)
            raise OSError("injected unlink then error")
        return result

    monkeypatch.setattr(Path, "unlink", unlink_then_error)
    with pytest.raises(OSError, match="unlink then error"):
        remove_overlay(root, backup=lambda paths, label: backups.backup_files(paths, description=label),
                       restore_backup=backups.restore_backup)
    assert attempts == [target]
    assert {path: path.read_bytes() for path in root.rglob("*") if path.is_file()} == before


def test_legacy_removal_preserves_unowned_files_added_during_backup(tmp_path):
    root = tmp_path / "game"
    (root / "meta").mkdir(parents=True)
    (root / "meta/0.papgt").write_bytes(serialize_papgt([]))
    plan = MigrationPlan((OverlayFile("fixture/item.bin", b"item", 4),), (), ())
    migrated = migrate_into_overlay(root, plan=plan)
    backups = Backups(tmp_path)
    foreign = migrated.directory / "external-manager.txt"

    def backup(paths, label):
        folder = backups.backup_files(paths, description=label)
        foreign.write_bytes(b"another manager owns this file")
        return folder

    result = remove_overlay(root, backup=backup, restore_backup=backups.restore_backup)
    assert result.unmounted and result.removed_files == 2
    assert foreign.read_bytes() == b"another manager owns this file"
    assert not (migrated.directory / legacy.OVERLAY_OWNER_MARKER).exists()


@pytest.mark.parametrize("foreign_inventory", [False, True])
def test_retirement_rename_then_error_recovers_only_verified_targets(prepared_item, monkeypatch, foreign_inventory):
    from cdmw.core.papgt_format import parse_papgt

    root, backups, _, installed = prepared_item
    backups.apply(installed)
    mount = root / "meta/0.papgt"
    mount_before = mount.read_bytes()
    mount.write_bytes(serialize_papgt([row for row in parse_papgt(mount_before)
                                      if row.name != installed.directory_name], header=mount_before[:12]))
    prepared = managed.prepare_overlay_retirement(root)
    inventory = root / managed.INDEX_PATH
    retired = root / ".cdmw/retired-overlays" / (prepared.retirement_id + ".json")
    original = inventory.read_bytes()
    rename = Path.rename

    def rename_then_error(path, target):
        result = rename(path, target)
        if path == inventory:
            if foreign_inventory:
                inventory.write_bytes(b"external manager replaced the inventory")
            raise OSError("injected rename then error")
        return result

    monkeypatch.setattr(Path, "rename", rename_then_error)
    error_type = RuntimeError if foreign_inventory else OSError
    with pytest.raises(error_type, match="recovery requires backup" if foreign_inventory else "rename then error"):
        managed.apply_overlay_retirement(prepared, confirmed=True,
            backup=lambda paths, label: backups.backup_files(paths, description=label),
            restore_backup=backups.restore_backup, game_running=lambda: False)
    if foreign_inventory:
        assert inventory.read_bytes() == b"external manager replaced the inventory"
        assert retired.read_bytes() == original
    else:
        assert inventory.read_bytes() == original
        assert not retired.exists()


def test_legacy_operations_share_the_installation_lane(legacy_operation):
    from concurrent.futures import ThreadPoolExecutor
    from cdmw.domain.virtual_loader import VirtualLoaderError
    from cdmw.services.installation_lane import installation_lane

    root, _, invoke = legacy_operation
    before = {path: path.read_bytes() for path in root.rglob("*") if path.is_file()}
    with installation_lane(root), ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(invoke)
        with pytest.raises(VirtualLoaderError, match="in use by another CDMW operation"):
            future.result(timeout=5)
    assert {path: path.read_bytes() for path in root.rglob("*") if path.is_file()} == before


def test_committed_cleanup_preserves_unknown_artifact_without_rollback(tmp_path):
    from cdmw.core.atomic_file import atomic_write_bytes
    from cdmw.services.overlay_target_recovery import OverlayTargetRecovery, payload_digest

    root = tmp_path / "game"
    root.mkdir()
    target = root / "owned-state.bin"
    target.write_bytes(b"before")
    recovery = OverlayTargetRecovery(root, {target: payload_digest(b"before")})
    recovery.write(target, b"committed", atomic_write_bytes)
    copied_original = recovery.sources[target]
    copied_original.unlink()
    copied_original.mkdir()  # Another writer replaces a disposable artifact with a directory.
    recovery.committed()
    assert target.read_bytes() == b"committed"
    assert copied_original.is_dir()
