"""Reading the game as the October 2026 DLC update ships it.

The update changed three things Placement & Animations depended on: the mount list moved to a
compact layout the strict parser rejects, a DLC root under `dlc/` reuses the base folder
names, and most of the files the tool keeps a private copy of changed. Each used to fail
quietly: the armour list and clip search came up empty, moves failed, and packages were
built on the pre-update files.
"""

from __future__ import annotations

import json
import struct
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from tools.placement_studio import corpus, relationships


def _compact_papgt(names, flags=None) -> bytes:
    """The post-update layout: 4-byte header, records, string table, 64-byte trailer."""

    table = bytearray()
    records = bytearray()
    for index, name in enumerate(names):
        offset = len(table)
        table += name.encode("ascii") + b"\0"
        records += struct.pack("<III", (flags or {}).get(name, 0x007FFF00), offset, 0)
    header = bytes((0, 0, len(names), 2))
    return header + bytes(records) + struct.pack("<I", len(table)) + bytes(table) + b"\x07" * 64


def _install(root: Path, base, dlc, *, base_flags=None) -> None:
    for name in base:
        (root / name).mkdir(parents=True)
        (root / name / "0.pamt").write_bytes(b"")
    (root / "meta").mkdir()
    # As the game ships it: the base list also names the DLC's own groups, marked optional.
    flags = {name: 0x8001 for name in dlc if name not in base}
    flags.update(base_flags or {})
    (root / "meta/0.papgt").write_bytes(_compact_papgt(base + [n for n in dlc if n not in base],
                                                       flags))
    if not dlc:
        return
    dlc_root = root / "dlc/dlc_01"
    for name in dlc:
        (dlc_root / name).mkdir(parents=True)
        (dlc_root / name / "0.pamt").write_bytes(b"")
    (dlc_root / "meta").mkdir()
    (dlc_root / "meta/0.papgt").write_bytes(_compact_papgt(dlc))


class MountListTests(unittest.TestCase):
    def test_compact_mount_lists_and_the_dlc_root_are_read(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            _install(root, ["0000", "0009"], ["0009", "0036"],
                     base_flags={"0036": 0x8001})
            labels = [label for label, _table in relationships.active_tables(root)]
        # Every mounted table, the DLC's 0009 told apart from the base 0009 and read first.
        self.assertEqual(sorted(labels), ["0000", "0009", "dlc/dlc_01/0009", "dlc/dlc_01/0036"])
        self.assertLess(labels.index("dlc/dlc_01/0009"), labels.index("0009"))

    def test_a_folder_the_game_does_not_mount_is_left_out(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            _install(root, ["0000"], ["0036"])
            (root / "0041").mkdir()
            (root / "0041/0.pamt").write_bytes(b"")
            labels = [label for label, _table in relationships.active_tables(root)]
        self.assertNotIn("0041", labels)

    def test_a_missing_base_folder_is_not_excused_by_the_dlc_copy_of_its_name(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            _install(root, ["0000", "0009"], ["0009"])
            (root / "0009/0.pamt").unlink()
            (root / "0009").rmdir()
            with self.assertRaisesRegex(ValueError, "Mounted archive is missing: 0009"):
                relationships.active_tables(root)

    def test_a_missing_required_folder_still_fails(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            _install(root, ["0000"], [])
            papgt = root / "meta/0.papgt"
            papgt.write_bytes(_compact_papgt(["0000", "0007"]))
            with self.assertRaisesRegex(ValueError, "Mounted archive is missing: 0007"):
                relationships.active_tables(root)

    def test_an_unreadable_mount_list_fails_rather_than_guessing(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            _install(root, ["0000"], [])
            (root / "meta/0.papgt").write_bytes(b"\x00\x00\x01\x02garbage")
            with self.assertRaises(ValueError):
                relationships.active_tables(root)

    def test_dlc_tables_are_labelled_by_their_root(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            self.assertEqual(corpus._package_label(root, root / "0009/0.pamt"), "0009")
            self.assertEqual(corpus._package_label(root, root / "dlc/dlc_01/0009/0.pamt"),
                             "dlc/dlc_01/0009")

    def test_the_dlc_mount_list_is_part_of_the_signature(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            _install(root, ["0000"], ["0036"])
            before = corpus.package_signature(root)
            signed = {Path(row[0]).relative_to(root).as_posix() for row in before}
            self.assertIn("dlc/dlc_01/meta/0.papgt", signed)


class _Catalogue:
    def __init__(self, root, files) -> None:
        self.source = SimpleNamespace(package_root=str(root))
        self._files = files

    def active_entry(self, key):
        if key not in self._files:
            return None
        return SimpleNamespace(path=key, pamt_path=Path(self.source.package_root) / "0009/0.pamt",
                               data=self._files[key])

    def validate_sources(self) -> None:
        return None


def _read(entry):
    return entry.data, False, ""


class BaselineRefreshTests(unittest.TestCase):
    def _pinned(self, folder: Path, files) -> corpus.Baseline:
        base = folder / "vanilla"
        records = {path: corpus._pin(base, path, data, "0009") for path, data in files.items()}
        corpus._write_manifest(base, records, root=folder, signature=[["old", 1, 1]],
                               requested=len(files) + 1, missing=["c.xml"], failed=[])
        return corpus.Baseline.load(base)

    def test_changed_removed_and_newly_found_files_are_brought_up_to_date(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            folder = Path(folder)
            baseline = self._pinned(folder, {"a.xml": b"old a", "b.xml": b"gone"})
            game = {"a.xml": b"new a", "c.xml": b"found"}
            with mock.patch.object(corpus, "package_signature", return_value=[["new", 2, 2]]), \
                 mock.patch("cdmw.core.archive_extraction.read_archive_entry_data", _read):
                result = corpus.refresh_baseline(baseline,
                                                 resident_catalogue=_Catalogue(folder, game))
                self.assertTrue(result.updated)
                self.assertEqual(result.changed, ("a.xml",))
                self.assertEqual(result.removed, ("b.xml",))
                self.assertEqual(result.added, ("c.xml",))
                refreshed = corpus.Baseline.load(folder / "vanilla")
                self.assertEqual(refreshed.read("a.xml"), b"new a")
                self.assertEqual(refreshed.read("c.xml"), b"found")
                self.assertNotIn("b.xml", refreshed)
                self.assertFalse((folder / "vanilla/b.xml").exists())
                self.assertTrue(corpus.baseline_is_current(refreshed, folder))
                self.assertIn("1 file(s) updated", result.describe())

                again = corpus.refresh_baseline(refreshed,
                                                resident_catalogue=_Catalogue(folder, game))
                self.assertFalse(again.checked)
                self.assertFalse(again.updated)

    def test_a_copy_that_cannot_be_read_again_is_retried_next_time(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            folder = Path(folder)
            baseline = self._pinned(folder, {"a.xml": b"old a", "b.xml": b"old b"})

            def flaky(entry):
                if entry.path == "b.xml":
                    raise OSError("locked")
                return entry.data, False, ""

            game = {"a.xml": b"new a", "b.xml": b"new b"}
            with mock.patch.object(corpus, "package_signature", return_value=[["new", 2, 2]]), \
                 mock.patch("cdmw.core.archive_extraction.read_archive_entry_data", flaky):
                result = corpus.refresh_baseline(baseline,
                                                 resident_catalogue=_Catalogue(folder, game))
            manifest = json.loads((folder / "vanilla/baseline.json").read_text(encoding="utf-8"))
            self.assertIn("b.xml", result.removed)
            self.assertIn("b.xml", manifest["missing"])
            self.assertIsNone(manifest["signature"])  # so the next open checks again
            self.assertFalse((folder / "vanilla/b.xml").exists())
            self.assertEqual(corpus.Baseline.load(folder / "vanilla").read("a.xml"), b"new a")

    def test_a_baseline_from_before_signatures_is_checked_once(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            folder = Path(folder)
            baseline = self._pinned(folder, {"a.xml": b"same"})
            manifest = folder / "vanilla/baseline.json"
            payload = json.loads(manifest.read_text(encoding="utf-8"))
            del payload["signature"]
            manifest.write_text(json.dumps(payload), encoding="utf-8")
            self.assertFalse(corpus.baseline_is_current(baseline, folder))
            with mock.patch.object(corpus, "package_signature", return_value=[["now", 1, 1]]), \
                 mock.patch("cdmw.core.archive_extraction.read_archive_entry_data", _read):
                result = corpus.refresh_baseline(
                    baseline, resident_catalogue=_Catalogue(folder, {"a.xml": b"same"}))
            self.assertTrue(result.checked)
            self.assertFalse(result.updated)
            self.assertEqual(json.loads(manifest.read_text(encoding="utf-8"))["signature"],
                             [["now", 1, 1]])


if __name__ == "__main__":
    unittest.main()


class ReleaseReviewTests(unittest.TestCase):
    """Findings from the alpha.32 release review."""

    def test_a_dlc_copy_wins_over_the_base_copy_like_the_resident_index(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            # As shipped: the DLC lists its own copy of each base folder in the same order.
            _install(root, ["0000", "0009"], ["0000", "0009", "0036"],
                     base_flags={"0036": 0x8001})
            labels = [label for label, _table in relationships.active_tables(root)]
        self.assertEqual(labels, ["dlc/dlc_01/0000", "0000", "dlc/dlc_01/0009", "0009",
                                  "dlc/dlc_01/0036"])

    def test_a_dmm_mount_does_not_change_the_game_signature(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            _install(root, ["0000"], [])
            (root / "0000/0.paz").write_bytes(b"game")
            before = corpus.package_signature(root)
            for mounted in ("dmmsa", "dmmgen"):
                (root / mounted / "0001").mkdir(parents=True)
                (root / mounted / "0001/0.paz").write_bytes(b"mod")
                (root / mounted / "0001/0.pamt").write_bytes(b"")
            self.assertEqual(corpus.package_signature(root), before)
            (root / "0000/0.paz").write_bytes(b"game, updated")
            self.assertNotEqual(corpus.package_signature(root), before)
