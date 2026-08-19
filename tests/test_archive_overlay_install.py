"""Installing a plan as an overlay directory rather than as a rewrite of the archives.

The point of the route is what it does *not* touch: the shipped `.paz` files stay byte for
byte as they were, and what changes is a new directory beside them plus the mount list that
names it first. These check both halves -- that the overlay wins where the game reads, and
that the archives it overrides were left alone.
"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT / "tests") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "tests"))

from cdmw.core.archive_extraction import read_archive_entry_data  # noqa: E402
from cdmw.core.archive_format import parse_archive_pamt  # noqa: E402
from cdmw.core.archive_scan_cache import discover_pamt_files  # noqa: E402
from cdmw.core.papgt_format import parse_papgt  # noqa: E402
from cdmw.domain.archives.mutation import ArchiveAddRequest, ArchivePatchRequest  # noqa: E402
from cdmw.services.archive_overlay_install import install_overlay, overlay_directory_name  # noqa: E402
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
        self.assertEqual(overlay_directory_name(self.root, existing="0036"), "0036")


if __name__ == "__main__":
    unittest.main()
