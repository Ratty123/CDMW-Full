"""Moving an install that already went into the shipped archives out into the overlay, and
taking the overlay away again.

The move is only as good as its two halves: what the game reads has to be the same
afterwards, and the archives the game shipped have to be back the way the oldest backup has
them. Both are checked here against a package that was patched the old way first.
"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT / "tests") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "tests"))

from cdmw.core import archive_patching  # noqa: E402
from cdmw.core.archive_extraction import read_archive_entry_data  # noqa: E402
from cdmw.core.archive_format import parse_archive_pamt  # noqa: E402
from cdmw.core.archive_scan_cache import discover_pamt_files  # noqa: E402
from cdmw.core.papgt_format import parse_papgt  # noqa: E402
from cdmw.domain.archives.mutation import ArchivePatchRequest  # noqa: E402
from cdmw.services.archive_overlay_migration import (  # noqa: E402
    migrate_into_overlay,
    plan_migration,
    remove_overlay,
)
from test_new_item_service import build_package, synthetic_files  # noqa: E402

BIN = "gamedata/binary__/client/bin"


class MigrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self._temp = tempfile.TemporaryDirectory()
        self.root = Path(self._temp.name)
        self.pamt = build_package(self.root, synthetic_files())
        self._backup_root = Path(self._temp.name) / "backups"
        self._patch = patch.object(archive_patching, "ARCHIVE_PATCH_BACKUP_ROOT", self._backup_root)
        self._patch.start()
        self.vanilla = {path: path.read_bytes() for path in sorted(self.root.glob("0009/*"))}

    def tearDown(self) -> None:
        self._patch.stop()
        self._temp.cleanup()

    def _entries(self) -> dict:
        found: dict = {}
        for pamt in discover_pamt_files(self.root):
            for entry in parse_archive_pamt(pamt):
                found.setdefault(entry.path, entry)
        return found

    def _payload(self, path: str) -> bytes:
        entry = self._entries()[path]
        data = read_archive_entry_data(entry)
        return data[0] if isinstance(data, tuple) else data

    def _patch_the_old_way(self, payload: bytes = b"the patched item table") -> None:
        entry = {item.path: item for item in parse_archive_pamt(self.pamt)}[f"{BIN}/iteminfo.pabgb"]
        archive_patching.patch_archive_entries((ArchivePatchRequest(entry, payload),))

    def test_a_patched_archive_moves_into_the_overlay_and_the_original_comes_back(self) -> None:
        self._patch_the_old_way()
        self.assertEqual(self._payload(f"{BIN}/iteminfo.pabgb"), b"the patched item table")
        self.assertNotEqual((self.root / "0009" / "0.paz").read_bytes(), self.vanilla[self.root / "0009" / "0.paz"])

        found = plan_migration(self.root)
        self.assertFalse(found.is_empty)
        self.assertIn(f"{BIN}/iteminfo.pabgb", [item.path for item in found.entries])
        self.assertTrue(found.restore, "the archives have somewhere to go back to")

        result = migrate_into_overlay(self.root, plan=found)
        self.assertGreaterEqual(result.moved, 1)

        for path, before in self.vanilla.items():
            self.assertEqual(path.read_bytes(), before, f"{path.name} did not go back to what it was")

        mounted = parse_papgt((self.root / "meta" / "0.papgt").read_bytes())
        self.assertEqual(mounted[0].name, result.directory.name)
        entry = self._entries()[f"{BIN}/iteminfo.pabgb"]
        self.assertEqual(entry.pamt_path.parent.name, result.directory.name, "the overlay answers for it now")
        self.assertEqual(self._payload(f"{BIN}/iteminfo.pabgb"), b"the patched item table", "and with the same bytes")

    def test_nothing_to_move_is_said_rather_than_written(self) -> None:
        found = plan_migration(self.root)
        self.assertTrue(found.is_empty)
        with self.assertRaisesRegex(ValueError, "Nothing"):
            migrate_into_overlay(self.root, plan=found)

    def test_removing_the_overlay_unmounts_and_deletes_it(self) -> None:
        self._patch_the_old_way(b"a patched table")
        result = migrate_into_overlay(self.root, plan=plan_migration(self.root))
        directory = result.directory
        self.assertTrue((directory / "0.pamt").is_file())

        removal = remove_overlay(self.root)
        self.assertTrue(removal.unmounted)
        self.assertEqual(removal.directory, directory)
        self.assertFalse(directory.exists(), "the directory is gone")
        mounted = [item.name for item in parse_papgt((self.root / "meta" / "0.papgt").read_bytes())]
        self.assertNotIn(directory.name, mounted)
        self.assertIn("0009", mounted, "the shipped directory stays mounted")
        self.assertEqual(self._payload(f"{BIN}/iteminfo.pabgb"), synthetic_files()[f"{BIN}/iteminfo.pabgb"], "the shipped table answers again")

    def test_removing_when_there_is_no_overlay_says_so(self) -> None:
        removal = remove_overlay(self.root)
        self.assertFalse(removal.unmounted)
        self.assertIsNone(removal.directory)

    def test_the_move_backs_up_what_it_is_about_to_overwrite(self) -> None:
        self._patch_the_old_way()
        seen: list[Path] = []

        def backup(paths, description):
            seen.extend(paths)
            folder = self.root / "move_backup"
            folder.mkdir(exist_ok=True)
            return folder

        result = migrate_into_overlay(self.root, plan=plan_migration(self.root), backup=backup)
        self.assertEqual(result.backup_dir, self.root / "move_backup")
        names = {path.name for path in seen}
        self.assertIn("0.papgt", names)
        self.assertIn("0.pamt", names)
        self.assertIn("0.paz", names, "the archives it restores over are copied first")


if __name__ == "__main__":
    unittest.main()
