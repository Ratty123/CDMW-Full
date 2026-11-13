"""ArchiveMutationService after the direct patch route was removed (decision 35).

What remains is Restore Backup (putting back what an older CDMW patched into the
game) and the backup/restore pair the switched-off overlay installs use. Every
test works on an owned archive written into a temporary folder.
"""

from __future__ import annotations

import ast
import os
import threading
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pytest

from cdmw.app.app_folder import SYSTEM_TEMP_ENV
from cdmw.core import archive_patching
from cdmw.models import RunCancelled
from cdmw.services.archive_mutation_service import ArchiveMutationService
from tests.test_archive_patch_preflight import _write_test_archive


def _archive_files(root: Path, entry) -> tuple[Path, ...]:
    return (root / "meta" / "0.papgt", entry.pamt_path, entry.paz_file)


def test_the_patch_plan_entry_points_are_gone():
    service = ArchiveMutationService()
    for name in ("prepare_patch", "validate_patch", "create_backup", "apply_patch"):
        assert not hasattr(service, name), name


def test_restore_holds_archive_write_ownership_and_refuses_while_closing(tmp_path, monkeypatch):
    from cdmw.services import application_shutdown_service as shutdown

    monkeypatch.setattr(shutdown, "_shutdown_started_at", None)
    monkeypatch.setattr(archive_patching, "ARCHIVE_PATCH_BACKUP_ROOT", tmp_path / "backups")
    entry = _write_test_archive(tmp_path)
    originals = {path: path.read_bytes() for path in _archive_files(tmp_path, entry)}
    service = ArchiveMutationService()
    backup_dir = service.backup_files(_archive_files(tmp_path, entry), description="Test backup")
    entry.paz_file.write_bytes(b"damaged by an older CDMW")
    restore = archive_patching.restore_archive_patch_backup
    owned = []

    def restore_and_check(backup, **kwargs):
        owned.append(shutdown.archive_write_in_progress())
        return restore(backup, **kwargs)

    monkeypatch.setattr(archive_patching, "restore_archive_patch_backup", restore_and_check)
    assert service.restore_backup(backup_dir, confirmed=True, game_root=tmp_path) == backup_dir
    assert owned == [True] and not shutdown.archive_write_in_progress()
    assert {path: path.read_bytes() for path in originals} == originals
    entry.paz_file.write_bytes(b"damaged again")
    shutdown._shutdown_started_at = 0.0
    with pytest.raises(RunCancelled, match="CDMW is closing"):
        service.restore_backup(backup_dir, confirmed=True, game_root=tmp_path)
    assert entry.paz_file.read_bytes() == b"damaged again"


def test_restore_lists_the_backups_an_older_cdmw_made_in_the_system_temp_folder(tmp_path, monkeypatch):
    from cdmw.constants import APP_NAME

    monkeypatch.setattr(archive_patching, "ARCHIVE_PATCH_BACKUP_ROOT", tmp_path / "workspace" / "temp" / "backups")
    monkeypatch.setenv(SYSTEM_TEMP_ENV, str(tmp_path / "system-temp"))
    older = tmp_path / "system-temp" / APP_NAME / "archive_patch_backups" / "20260901_120000"
    older.mkdir(parents=True)
    (older / "backup_manifest.json").write_text('{"files": []}', encoding="utf-8")
    (older.parent / "not-a-backup").mkdir()
    entry = _write_test_archive(tmp_path / "game")
    service = ArchiveMutationService()
    newer = service.backup_files((entry.paz_file,), description="Made now")

    assert service.backup_roots() == (tmp_path / "workspace" / "temp" / "backups", older.parent)
    assert service.list_backups() == [newer, older]
    assert service.list_backups(limit=1) == [newer]


class ArchiveMutationServiceTests(unittest.TestCase):
    def test_backup_listing_and_confirmed_restore_use_core_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            entry = _write_test_archive(root)
            original_payload = entry.paz_file.read_bytes()
            service = ArchiveMutationService()
            backup_root = root / "backups"
            (root / "system-temp").mkdir()

            with (
                patch.object(archive_patching, "ARCHIVE_PATCH_BACKUP_ROOT", backup_root),
                patch.dict(os.environ, {SYSTEM_TEMP_ENV: str(root / "system-temp")}),
            ):
                backup_dir = service.backup_files(_archive_files(root, entry), description="Test backup")
                self.assertTrue((backup_dir / "backup_manifest.json").is_file())
                entry.paz_file.write_bytes(b"damaged")
                self.assertEqual([backup_dir], service.list_backups())
                with self.assertRaisesRegex(PermissionError, "explicit confirmation"):
                    service.restore_backup(backup_dir)
                restored_dir = service.restore_backup(backup_dir, confirmed=True, game_root=root)

            self.assertEqual(backup_dir, restored_dir)
            self.assertEqual(original_payload, entry.paz_file.read_bytes())

    def test_a_backup_needs_files(self) -> None:
        with self.assertRaisesRegex(ValueError, "at least one file"):
            ArchiveMutationService().backup_files(())

    def test_cancelled_restore_stops_before_writing(self) -> None:
        service = ArchiveMutationService()
        stop_event = threading.Event()
        stop_event.set()

        with patch.object(archive_patching, "restore_archive_patch_backup") as restore:
            with self.assertRaisesRegex(RunCancelled, "before writing"):
                service.restore_backup("unused", confirmed=True, stop_event=stop_event)

        restore.assert_not_called()

    def test_destructive_ui_modules_have_no_direct_low_level_patch_calls(self) -> None:
        forbidden = {
            "patch_archive_entries",
            "apply_archive_mutations",
            "add_archive_entries",
            "restore_archive_patch_backup",
            "list_archive_patch_backups",
        }
        for path in (
            Path("cdmw/ui/archive_browser/patch_actions.py"),
            Path("cdmw/ui/archive_browser/mesh_patch_flow.py"),
            Path("cdmw/ui/new_item/tab.py"),
            Path("cdmw/ui/new_item/controller.py"),
        ):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            called = {
                node.func.id
                for node in ast.walk(tree)
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
            }
            imported = {
                alias.name
                for node in ast.walk(tree)
                if isinstance(node, ast.ImportFrom)
                for alias in node.names
            }
            self.assertTrue(forbidden.isdisjoint(called), path)
            self.assertTrue(forbidden.isdisjoint(imported), path)


if __name__ == "__main__":
    unittest.main()
