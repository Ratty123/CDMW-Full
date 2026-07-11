from __future__ import annotations

import ast
import threading
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from cdmw.core import archive_patching
from cdmw.models import RunCancelled
from cdmw.services.archive_mutation_service import ArchiveMutationService, ArchivePatchRequest
from tests.test_archive_patch_preflight import _write_test_archive


class ArchiveMutationServiceTests(unittest.TestCase):
    def test_confirmed_plan_applies_with_core_preflight_and_backup(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            entry = _write_test_archive(root)
            service = ArchiveMutationService()
            plan = service.prepare_patch(
                ArchivePatchRequest(entry, b"new-payload"),
                confirmed=True,
                description="Test archive patch",
            )

            with patch.object(archive_patching, "ARCHIVE_PATCH_BACKUP_ROOT", root / "backups"):
                result = service.apply_patch(plan)

            self.assertTrue(plan.confirmed)
            self.assertEqual((entry.path,), plan.target_paths)
            self.assertEqual("Test archive patch", plan.safety.description)
            self.assertIn(entry.path.casefold(), result.changed_entries)
            self.assertTrue((result.backup_dir / "backup_manifest.json").is_file())

    def test_unconfirmed_plan_never_reaches_low_level_apply(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            entry = _write_test_archive(Path(temp_dir))
            service = ArchiveMutationService()
            plan = service.prepare_patch(ArchivePatchRequest(entry, b"new"))

            with patch.object(archive_patching, "patch_archive_entries") as low_level_apply:
                with self.assertRaisesRegex(PermissionError, "explicit confirmation"):
                    service.apply_patch(plan)

            low_level_apply.assert_not_called()

    def test_read_only_preflight_rejects_stale_entry_before_backup(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            entry = _write_test_archive(root, "character/model/existing.pac")
            stale_entry = replace(entry, path="character/model/missing.pac")
            plan = ArchiveMutationService().prepare_patch(
                ArchivePatchRequest(stale_entry, b"new"),
                confirmed=True,
            )

            with patch.object(archive_patching, "_create_backup") as create_backup:
                with self.assertRaisesRegex(ValueError, "Could not locate"):
                    ArchiveMutationService().validate_patch(plan)

            create_backup.assert_not_called()

    def test_backup_listing_and_confirmed_restore_use_core_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            entry = _write_test_archive(root)
            original_payload = entry.paz_file.read_bytes()
            service = ArchiveMutationService()
            plan = service.prepare_patch(ArchivePatchRequest(entry, b"unused"), confirmed=True)
            backup_root = root / "backups"

            with patch.object(archive_patching, "ARCHIVE_PATCH_BACKUP_ROOT", backup_root):
                backup_dir = service.create_backup(plan)
                entry.paz_file.write_bytes(b"damaged")
                self.assertEqual([backup_dir], service.list_backups())
                with self.assertRaisesRegex(PermissionError, "explicit confirmation"):
                    service.restore_backup(backup_dir)
                restored_dir = service.restore_backup(backup_dir, confirmed=True)

            self.assertEqual(backup_dir, restored_dir)
            self.assertEqual(original_payload, entry.paz_file.read_bytes())

    def test_cancellation_after_append_rolls_back_complete_backup(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            entry = _write_test_archive(root)
            original_files = {
                path: path.read_bytes()
                for path in (root / "meta" / "0.papgt", entry.pamt_path, entry.paz_file)
            }
            stop_event = threading.Event()
            service = ArchiveMutationService()
            plan = service.prepare_patch(ArchivePatchRequest(entry, b"new-payload"), confirmed=True)
            original_write = archive_patching._write_paz_payload

            def write_then_cancel(request_entry, payload: bytes) -> int:
                offset = original_write(request_entry, payload)
                stop_event.set()
                return offset

            with (
                patch.object(archive_patching, "ARCHIVE_PATCH_BACKUP_ROOT", root / "backups"),
                patch.object(archive_patching, "_write_paz_payload", side_effect=write_then_cancel),
            ):
                with self.assertRaisesRegex(RunCancelled, "restoring the backup"):
                    service.apply_patch(plan, stop_event=stop_event)

            for path, expected in original_files.items():
                self.assertEqual(expected, path.read_bytes(), path)

    def test_post_commit_reporting_failure_restores_backup(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            entry = _write_test_archive(root)
            original_files = {
                path: path.read_bytes()
                for path in (root / "meta" / "0.papgt", entry.pamt_path, entry.paz_file)
            }
            service = ArchiveMutationService()
            plan = service.prepare_patch(ArchivePatchRequest(entry, b"new-payload"), confirmed=True)

            def fail_after_commit(message: str) -> None:
                if message.startswith("Refreshing changed archive entries"):
                    raise RuntimeError("report failed")

            with patch.object(archive_patching, "ARCHIVE_PATCH_BACKUP_ROOT", root / "backups"):
                with self.assertRaisesRegex(RuntimeError, "report failed"):
                    service.apply_patch(plan, on_log=fail_after_commit)

            for path, expected in original_files.items():
                self.assertEqual(expected, path.read_bytes(), path)

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
            "restore_archive_patch_backup",
            "list_archive_patch_backups",
        }
        for path in (
            Path("cdmw/ui/archive_browser/patch_actions.py"),
            Path("cdmw/ui/archive_browser/mesh_patch_flow.py"),
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
