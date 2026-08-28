"""Installing a plan as an overlay directory rather than as a rewrite of the archives.

The point of the route is what it does *not* touch: the shipped `.paz` files stay byte for
byte as they were, and what changes is a new directory beside them plus the mount list that
names it first. These check both halves -- that the overlay wins where the game reads, and
that the archives it overrides were left alone.
"""

from __future__ import annotations

import json
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT / "tests") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "tests"))

from cdmw.core.archive_extraction import read_archive_entry_data  # noqa: E402
from cdmw.core.archive_format import parse_archive_pamt  # noqa: E402
from cdmw.core.archive_scan_cache import discover_pamt_files  # noqa: E402
from cdmw.core.papgt_format import parse_papgt  # noqa: E402
from cdmw.domain.archives.mutation import ArchiveAddRequest, ArchivePatchRequest  # noqa: E402
from cdmw.services.archive_overlay_install import (  # noqa: E402
    OVERLAY_OWNER_MARKER,
    apply_overlay_install,
    install_overlay,
    overlay_directory_name,
    prepare_overlay_install,
    restore_last_overlay_install,
)
from test_new_item_service import build_package, synthetic_files  # noqa: E402

BIN = "gamedata/binary__/client/bin"


class OverlayInstallTests(unittest.TestCase):
    def setUp(self) -> None:
        self._temp = tempfile.TemporaryDirectory()
        self.root = Path(self._temp.name)
        self.pamt = build_package(self.root, synthetic_files())
        self.entries = {entry.path: entry for entry in parse_archive_pamt(self.pamt)}
        self.shipped = {path: path.read_bytes() for path in sorted(self.root.glob("0009/*.paz"))}

    def tearDown(self) -> None:
        self._temp.cleanup()

    def _first_entry(self, path: str):
        """The entry a reader that keeps the first hit would use, in mount order."""

        for pamt in discover_pamt_files(self.root):
            for entry in parse_archive_pamt(pamt):
                if entry.path == path:
                    return entry
        return None

    @staticmethod
    def _write_backup_manifest(backup_dir: Path, paths) -> dict[Path, bytes]:
        backup_dir.mkdir(exist_ok=True)
        snapshots: dict[Path, bytes] = {}
        files: list[dict[str, str]] = []
        for index, raw_path in enumerate(paths):
            path = Path(raw_path).resolve()
            if not path.is_file():
                continue
            payload = path.read_bytes()
            snapshots[path] = payload
            backup_path = backup_dir / f"{index:03d}-{path.name}"
            backup_path.write_bytes(payload)
            files.append({"original_path": str(path), "backup_path": str(backup_path.resolve())})
        (backup_dir / "backup_manifest.json").write_text(
            json.dumps({"description": "test overlay backup", "files": files}),
            encoding="utf-8",
        )
        return snapshots

    def test_the_overlay_wins_where_the_game_reads_and_the_archives_are_untouched(self) -> None:
        target = self.entries[f"{BIN}/iteminfo.pabgb"]
        replacement = b"the patched item table" * 8
        added = f"{BIN}/cdmw_overlay_marker.pabgb"
        result = install_overlay(
            [ArchivePatchRequest(target, replacement)],
            [ArchiveAddRequest(pamt_path=Path(target.pamt_path), path=added, payload_data=b"a new file", flags=int(target.flags))],
            package_root=self.root,
        )

        self.assertTrue((result.directory / "0.pamt").is_file())
        self.assertTrue((result.directory / "0.paz").is_file())
        self.assertTrue((result.directory / OVERLAY_OWNER_MARKER).is_file())
        self.assertEqual(result.file_count, 2)
        self.assertEqual(result.carried_forward, 0)

        mounted = parse_papgt((self.root / "meta" / "0.papgt").read_bytes())
        self.assertEqual(mounted[0].name, result.directory.name, "the overlay is mounted first")
        self.assertEqual(mounted[0].pamt_checksum, result.pamt_checksum)
        self.assertIn("0009", [item.name for item in mounted], "the shipped directory stays mounted")

        found = discover_pamt_files(self.root)
        self.assertEqual(found[0].parent.name, result.directory.name, "and is read first")

        entry = self._first_entry(f"{BIN}/iteminfo.pabgb")
        self.assertIsNotNone(entry)
        self.assertEqual(entry.pamt_path.parent.name, result.directory.name)
        payload = read_archive_entry_data(entry)
        payload = payload[0] if isinstance(payload, tuple) else payload
        self.assertEqual(payload, replacement, "the overlay's version is the one a reader gets")

        new_entry = self._first_entry(added)
        self.assertIsNotNone(new_entry, "the added path exists")
        new_payload = read_archive_entry_data(new_entry)
        new_payload = new_payload[0] if isinstance(new_payload, tuple) else new_payload
        self.assertEqual(new_payload, b"a new file")

        for path, before in self.shipped.items():
            self.assertEqual(path.read_bytes(), before, f"{path.name} was rewritten")

    def test_a_second_install_carries_the_first_one_forward(self) -> None:
        first_target = self.entries[f"{BIN}/iteminfo.pabgb"]
        second_target = self.entries[f"{BIN}/stringinfo.pabgb"]
        first = install_overlay([ArchivePatchRequest(first_target, b"first item table")], package_root=self.root)
        second = install_overlay([ArchivePatchRequest(second_target, b"second string table")], package_root=self.root)

        self.assertEqual(second.directory, first.directory, "the workbench keeps one overlay")
        self.assertEqual(second.carried_forward, 1)
        self.assertEqual(second.file_count, 2)
        self.assertEqual(set(second.paths), {f"{BIN}/iteminfo.pabgb", f"{BIN}/stringinfo.pabgb"})

        for path, expected in ((f"{BIN}/iteminfo.pabgb", b"first item table"), (f"{BIN}/stringinfo.pabgb", b"second string table")):
            entry = self._first_entry(path)
            payload = read_archive_entry_data(entry)
            payload = payload[0] if isinstance(payload, tuple) else payload
            self.assertEqual(payload, expected, f"{path} lost its overlay")

        mounted = parse_papgt((self.root / "meta" / "0.papgt").read_bytes())
        self.assertEqual([item.name for item in mounted].count(first.directory.name), 1, "mounted once, not twice")

    def test_the_backup_is_the_mount_list_and_the_meta_files_only(self) -> None:
        target = self.entries[f"{BIN}/iteminfo.pabgb"]
        seen: list[Path] = []

        def backup(paths, description):
            seen.extend(paths)
            folder = self.root / "backup"
            folder.mkdir(exist_ok=True)
            return folder

        result = install_overlay(
            [ArchivePatchRequest(target, b"payload")],
            package_root=self.root,
            meta_files=[("meta/0.pathc", b"registry bytes")],
            backup=backup,
        )
        self.assertEqual(result.backup_dir, self.root / "backup")
        names = sorted(path.name for path in seen)
        self.assertEqual(names, ["0.papgt", "0.pathc"], "no shipped archive is in the backup set")
        self.assertEqual((self.root / "meta" / "0.pathc").read_bytes(), b"registry bytes")

    def test_the_directory_name_is_free_and_reused(self) -> None:
        name = overlay_directory_name(self.root)
        self.assertEqual(name, "0036")
        (self.root / "0036").mkdir()
        self.assertEqual(overlay_directory_name(self.root), "0037")
        self.assertEqual(overlay_directory_name(self.root, existing="0036"), "0037", "an unmarked folder is foreign")
        target = self.entries[f"{BIN}/iteminfo.pabgb"]
        installed = install_overlay([ArchivePatchRequest(target, b"payload")], package_root=self.root)
        self.assertEqual(overlay_directory_name(self.root, existing=installed.directory.name), installed.directory.name)

    def test_a_foreign_numeric_mount_is_never_reused(self) -> None:
        from cdmw.core.papgt_format import papgt_with_directory

        foreign = self.root / "0036"
        foreign.mkdir()
        (foreign / "keep.txt").write_bytes(b"belongs to another mod")
        mount = self.root / "meta" / "0.papgt"
        mount.write_bytes(papgt_with_directory(mount.read_bytes(), "0036", 0, first=True))
        target = self.entries[f"{BIN}/iteminfo.pabgb"]

        result = install_overlay([ArchivePatchRequest(target, b"payload")], package_root=self.root)

        self.assertEqual(result.directory.name, "0037")
        self.assertEqual((foreign / "keep.txt").read_bytes(), b"belongs to another mod")

    def test_a_write_failure_rolls_back_without_a_restore_service(self) -> None:
        import cdmw.services.archive_overlay_install as overlay

        target = self.entries[f"{BIN}/iteminfo.pabgb"]
        mount = self.root / "meta" / "0.papgt"
        before = mount.read_bytes()
        original = overlay._write_atomic

        def fail_on_index(path: Path, payload: bytes) -> None:
            if path.name == "0.pamt" and path.parent.name == "0036":
                raise OSError("index write failed")
            original(path, payload)

        with patch.object(overlay, "_write_atomic", fail_on_index):
            with self.assertRaisesRegex(OSError, "index write failed"):
                install_overlay([ArchivePatchRequest(target, b"payload")], package_root=self.root)

        self.assertEqual(mount.read_bytes(), before)
        self.assertFalse((self.root / "0036").exists(), "the unpublished overlay is removed")

    def test_cancellation_after_backup_restores_before_any_overlay_is_published(self) -> None:
        target = self.entries[f"{BIN}/iteminfo.pabgb"]
        mount = self.root / "meta" / "0.papgt"
        before = mount.read_bytes()
        preparation = prepare_overlay_install(
            [ArchivePatchRequest(target, b"payload")],
            package_root=self.root,
        )
        stop_event = threading.Event()
        restored: list[Path] = []

        def backup(_paths, _description):
            folder = self.root / "backup"
            folder.mkdir()
            stop_event.set()
            return folder

        with self.assertRaisesRegex(Exception, "cancelled after backup"):
            apply_overlay_install(
                preparation,
                confirmed=True,
                backup=backup,
                restore_backup=lambda path: restored.append(path),
                stop_event=stop_event,
            )

        self.assertEqual(restored, [self.root / "backup"])
        self.assertEqual(mount.read_bytes(), before)
        self.assertFalse(preparation.directory.exists())
        self.assertFalse(preparation.receipt_path.exists())

    def test_explicit_restore_uses_the_receipt_and_removes_only_install_created_files(self) -> None:
        target = self.entries[f"{BIN}/iteminfo.pabgb"]
        mount = self.root / "meta" / "0.papgt"
        before = mount.read_bytes()
        backup_dir = self.root / "backup"
        snapshots: dict[Path, bytes] = {}

        def backup(paths, _description):
            snapshots.update(self._write_backup_manifest(backup_dir, paths))
            return backup_dir

        def restore(_path):
            for path, payload in snapshots.items():
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(payload)

        result = install_overlay(
            [ArchivePatchRequest(target, b"payload")],
            package_root=self.root,
            backup=backup,
            restore_backup=restore,
        )
        unrelated = result.directory / "kept-by-another-operation.txt"
        unrelated.write_bytes(b"keep")

        restored_root = restore_last_overlay_install(
            result.receipt_path,
            confirmed=True,
            restore_backup=restore,
        )

        self.assertEqual(restored_root, self.root)
        self.assertEqual(mount.read_bytes(), before)
        self.assertEqual(unrelated.read_bytes(), b"keep")
        self.assertFalse((result.directory / "0.pamt").exists())
        self.assertFalse((result.directory / "0.paz").exists())
        self.assertFalse((result.directory / OVERLAY_OWNER_MARKER).exists())
        self.assertFalse(result.receipt_path.exists())

    def test_restore_rejects_a_tampered_receipt_before_restoring_any_backup(self) -> None:
        target = self.entries[f"{BIN}/iteminfo.pabgb"]
        backup_dir = self.root / "backup"
        backup_dir.mkdir()
        result = install_overlay(
            [ArchivePatchRequest(target, b"payload")],
            package_root=self.root,
            backup=lambda _paths, _description: backup_dir,
        )
        payload = json.loads(result.receipt_path.read_text(encoding="utf-8"))
        payload["created_files"].append(str(self.root.parent / "outside.txt"))
        result.receipt_path.write_text(json.dumps(payload), encoding="utf-8")
        restored: list[Path] = []

        with self.assertRaisesRegex(ValueError, "outside the package root"):
            restore_last_overlay_install(
                result.receipt_path,
                confirmed=True,
                restore_backup=lambda path: restored.append(path),
            )

        self.assertEqual(restored, [])

    def test_restore_rejects_a_tampered_same_root_created_path_before_restore_or_delete(self) -> None:
        target = self.entries[f"{BIN}/iteminfo.pabgb"]
        backup_dir = self.root / "backup"

        def backup(paths, _description):
            self._write_backup_manifest(backup_dir, paths)
            return backup_dir

        result = install_overlay(
            [ArchivePatchRequest(target, b"payload")],
            package_root=self.root,
            backup=backup,
        )
        unrelated = self.root / "meta" / "unrelated-user-file.bin"
        unrelated.write_bytes(b"keep")
        payload = json.loads(result.receipt_path.read_text(encoding="utf-8"))
        payload["created_files"].append(str(unrelated))
        result.receipt_path.write_text(json.dumps(payload), encoding="utf-8")
        restored: list[Path] = []

        with self.assertRaisesRegex(ValueError, "not owned by the overlay install"):
            restore_last_overlay_install(
                result.receipt_path,
                confirmed=True,
                restore_backup=lambda path: restored.append(path),
            )

        self.assertEqual(restored, [])
        self.assertEqual(unrelated.read_bytes(), b"keep")

    def test_restore_rejects_a_receipt_whose_targets_do_not_match_the_backup_manifest(self) -> None:
        target = self.entries[f"{BIN}/iteminfo.pabgb"]
        backup_dir = self.root / "backup"

        def backup(paths, _description):
            self._write_backup_manifest(backup_dir, paths)
            return backup_dir

        result = install_overlay(
            [ArchivePatchRequest(target, b"payload")],
            package_root=self.root,
            backup=backup,
        )
        unrelated = self.root / "meta" / "unrelated-user-file.bin"
        unrelated.write_bytes(b"keep")
        payload = json.loads(result.receipt_path.read_text(encoding="utf-8"))
        payload["backup_targets"].append(str(unrelated))
        result.receipt_path.write_text(json.dumps(payload), encoding="utf-8")
        restored: list[Path] = []

        with self.assertRaisesRegex(ValueError, "do not match the install backup manifest"):
            restore_last_overlay_install(
                result.receipt_path,
                confirmed=True,
                restore_backup=lambda path: restored.append(path),
            )

        self.assertEqual(restored, [])
        self.assertEqual(unrelated.read_bytes(), b"keep")

    def test_restore_rejects_a_receipt_that_omits_an_install_created_overlay_file(self) -> None:
        target = self.entries[f"{BIN}/iteminfo.pabgb"]
        backup_dir = self.root / "backup"

        def backup(paths, _description):
            self._write_backup_manifest(backup_dir, paths)
            return backup_dir

        result = install_overlay(
            [ArchivePatchRequest(target, b"payload")],
            package_root=self.root,
            backup=backup,
        )
        payload = json.loads(result.receipt_path.read_text(encoding="utf-8"))
        payload["created_files"].remove(str((result.directory / "0.pamt").resolve()))
        result.receipt_path.write_text(json.dumps(payload), encoding="utf-8")
        restored: list[Path] = []

        with self.assertRaisesRegex(ValueError, "do not match the install backup manifest"):
            restore_last_overlay_install(
                result.receipt_path,
                confirmed=True,
                restore_backup=lambda path: restored.append(path),
            )

        self.assertEqual(restored, [])
        self.assertTrue((result.directory / "0.pamt").is_file())

    def test_restore_rejects_an_overlay_that_lost_its_owner_marker(self) -> None:
        target = self.entries[f"{BIN}/iteminfo.pabgb"]
        backup_dir = self.root / "backup"

        def backup(paths, _description):
            self._write_backup_manifest(backup_dir, paths)
            return backup_dir

        result = install_overlay(
            [ArchivePatchRequest(target, b"payload")],
            package_root=self.root,
            backup=backup,
        )
        (result.directory / OVERLAY_OWNER_MARKER).write_bytes(b"foreign owner\n")
        restored: list[Path] = []

        with self.assertRaisesRegex(ValueError, "CDMW-owned overlay directory"):
            restore_last_overlay_install(
                result.receipt_path,
                confirmed=True,
                restore_backup=lambda path: restored.append(path),
            )

        self.assertEqual(restored, [])


if __name__ == "__main__":
    unittest.main()
