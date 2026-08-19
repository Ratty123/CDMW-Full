"""An archive directory built from scratch, and the PAPGT entry that mounts it.

A mod written this way leaves every shipped archive alone: the files it changes go in a
directory of its own, and `meta/0.papgt` names that directory before the shipped ones, so
the game takes it first. These check that what the builder writes is what the reader in
this same repository reads.
"""

from __future__ import annotations

import struct
import tempfile
import unittest
from pathlib import Path

import lz4.block as lz4_block

from cdmw.core.archive_entry_addition import parse_pamt_document
from cdmw.core.archive_extraction import read_archive_entry_data
from cdmw.core.archive_format import calculate_pa_checksum, hashlittle, parse_archive_pamt
from cdmw.core.archive_overlay import (
    FOLDER_HASH_SEED,
    PAZ_ALIGNMENT,
    OverlayFile,
    build_overlay_archive,
)
from cdmw.core.papgt_format import (
    PAPGT_DEFAULT_FLAGS,
    PapgtDirectory,
    papgt_with_directory,
    parse_papgt,
    serialize_papgt,
)

BIN = "gamedata/binary__/client/bin"
MODEL = "character/model/1_pc/1_phm/weapon/1_onehandweapon"


def _files() -> list[OverlayFile]:
    table = b"the item table" * 20
    return [
        OverlayFile(path=f"{BIN}/iteminfo.pabgb", payload=lz4_block.compress(table, store_size=False), orig_size=len(table), flags=2),
        OverlayFile(path=f"{BIN}/iteminfo.pabgh", payload=b"HEAD", orig_size=4, flags=0),
        OverlayFile(path=f"{MODEL}/cd_phm_01_sword_9109.pac", payload=b"PAC!" * 3, orig_size=12, flags=0),
    ]


class OverlayArchiveTests(unittest.TestCase):
    def test_the_built_table_is_the_one_this_repository_reads(self) -> None:
        built = build_overlay_archive(_files())
        document = parse_pamt_document(built.pamt_bytes, name="overlay")
        self.assertEqual(len(document.files), 3)
        self.assertEqual(
            sorted(record.full_path for record in document.files),
            sorted(item.path for item in _files()),
        )
        self.assertEqual(document.serialize(), built.pamt_bytes, "the reader writes back what the builder wrote")
        self.assertEqual(len(document.paz_records), 1)
        index, checksum, size = document.paz_records[0]
        self.assertEqual((index, size), (0, len(built.paz_bytes)))
        self.assertEqual(checksum, calculate_pa_checksum(built.paz_bytes))
        stored = struct.unpack_from("<I", built.pamt_bytes, 0)[0]
        self.assertEqual(stored, calculate_pa_checksum(built.pamt_bytes[12:]), "the PAMT signs itself")
        self.assertEqual(built.pamt_checksum, stored)

    def test_folders_carry_their_hash_and_tile_the_file_table(self) -> None:
        built = build_overlay_archive(_files())
        document = parse_pamt_document(built.pamt_bytes, name="overlay")
        self.assertEqual([folder.path for folder in document.folders], sorted({BIN, MODEL}))
        for folder in document.folders:
            self.assertEqual(folder.folder_hash, hashlittle(folder.path.encode("utf-8"), FOLDER_HASH_SEED))
        covered = sum(folder.count for folder in document.folders)
        self.assertEqual(covered, len(document.files))

    def test_payloads_sit_where_the_records_say_and_stay_aligned(self) -> None:
        built = build_overlay_archive(_files())
        document = parse_pamt_document(built.pamt_bytes, name="overlay")
        by_path = {item.path: item for item in _files()}
        for record in document.files:
            self.assertEqual(record.paz_offset % PAZ_ALIGNMENT, 0, f"{record.full_path} is off the alignment")
            payload = built.paz_bytes[record.paz_offset : record.paz_offset + record.comp_size]
            self.assertEqual(payload, by_path[record.full_path].payload)
            self.assertEqual(record.orig_size, by_path[record.full_path].orig_size)
        # every shipped .paz is a whole number of sixteen-byte blocks, tail included, and
        # the pamt's own paz table carries that length and the checksum of it
        self.assertEqual(len(built.paz_bytes) % PAZ_ALIGNMENT, 0, "the payload file is padded out like the shipped ones")
        last = max(record.paz_offset + record.comp_size for record in document.files)
        self.assertLess(len(built.paz_bytes) - last, PAZ_ALIGNMENT, "the padding is the tail of the last payload, no more")

    def test_the_app_reads_a_written_overlay_directory(self) -> None:
        built = build_overlay_archive(_files())
        with tempfile.TemporaryDirectory() as folder:
            group = Path(folder) / "0036"
            group.mkdir()
            (group / "0.pamt").write_bytes(built.pamt_bytes)
            (group / "0.paz").write_bytes(built.paz_bytes)
            entries = {entry.path: entry for entry in parse_archive_pamt(group / "0.pamt")}
            self.assertEqual(sorted(entries), sorted(item.path for item in _files()))
            table = read_archive_entry_data(entries[f"{BIN}/iteminfo.pabgb"])
            table = table[0] if isinstance(table, tuple) else table
            self.assertEqual(table, b"the item table" * 20, "an LZ4 entry decodes to what went in")
            head = read_archive_entry_data(entries[f"{BIN}/iteminfo.pabgh"])
            head = head[0] if isinstance(head, tuple) else head
            self.assertEqual(head, b"HEAD")

    def test_refusals(self) -> None:
        with self.assertRaises(ValueError):
            build_overlay_archive([])
        with self.assertRaises(ValueError):
            build_overlay_archive([OverlayFile(path="   ", payload=b"x", orig_size=1)])


class PapgtTests(unittest.TestCase):
    def _papgt(self, names: tuple[str, ...] = ("0000", "0001", "0008")) -> bytes:
        entries = tuple(
            PapgtDirectory(name=name, flags=PAPGT_DEFAULT_FLAGS, pamt_checksum=0x1000 + index)
            for index, name in enumerate(names)
        )
        return serialize_papgt(entries, header=b"\x01\x02\x03\x04" + b"\x00" * 8)

    def test_the_list_round_trips(self) -> None:
        data = self._papgt()
        directories = parse_papgt(data)
        self.assertEqual([item.name for item in directories], ["0000", "0001", "0008"])
        self.assertEqual(directories[0].flags, PAPGT_DEFAULT_FLAGS)
        self.assertEqual(serialize_papgt(directories, header=data[:12]), data)
        self.assertEqual(data[:4], b"\x01\x02\x03\x04", "the header bytes this module does not read are kept")

    def test_a_mod_directory_is_mounted_first(self) -> None:
        """The game takes the first directory that holds a path, so an overlay that is to
        win over a shipped archive has to be named before it."""

        grown = papgt_with_directory(self._papgt(), "0036", 0xABCDEF01)
        directories = parse_papgt(grown)
        self.assertEqual([item.name for item in directories], ["0036", "0000", "0001", "0008"])
        self.assertEqual(directories[0].pamt_checksum, 0xABCDEF01)
        self.assertEqual(directories[0].flags, PAPGT_DEFAULT_FLAGS)

    def test_mounting_the_same_directory_again_updates_it_in_place(self) -> None:
        once = papgt_with_directory(self._papgt(), "0036", 0x11111111)
        twice = papgt_with_directory(once, "0036", 0x22222222)
        directories = parse_papgt(twice)
        self.assertEqual([item.name for item in directories], ["0036", "0000", "0001", "0008"])
        self.assertEqual(directories[0].pamt_checksum, 0x22222222)

    def test_a_broken_checksum_is_refused(self) -> None:
        data = bytearray(self._papgt())
        data[-1] ^= 0xFF
        with self.assertRaisesRegex(ValueError, "checksum"):
            parse_papgt(bytes(data))


if __name__ == "__main__":
    unittest.main()
