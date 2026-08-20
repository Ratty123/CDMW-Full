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
        """Every folder on the way down is in the table, in path order, and the ones with
        no file of their own carry a count of zero.

        The shipped archives are built that way: 123 of archive 0000's 1,370 folder
        records hold no file. An overlay that listed only the folders holding files read
        back correctly through this repository's own reader and made the game refuse to
        start with "There may be a problem with the game installation", so the tree the
        game walks has to be whole.
        """

        built = build_overlay_archive(_files())
        document = parse_pamt_document(built.pamt_bytes, name="overlay")
        expected = sorted({
            "character", "character/model", "character/model/1_pc", "character/model/1_pc/1_phm",
            "character/model/1_pc/1_phm/weapon", MODEL,
            "gamedata", "gamedata/binary__", "gamedata/binary__/client", BIN,
        })
        self.assertEqual([folder.path for folder in document.folders], expected)
        for folder in document.folders:
            self.assertEqual(folder.folder_hash, hashlittle(folder.path.encode("utf-8"), FOLDER_HASH_SEED))
        by_path = {folder.path: folder for folder in document.folders}
        self.assertEqual(by_path[BIN].count, 2)
        self.assertEqual(by_path[MODEL].count, 1)
        self.assertEqual(by_path["character"].count, 0, "a folder on the way down holds no file of its own")
        covered = sum(folder.count for folder in document.folders)
        self.assertEqual(covered, len(document.files))
        # the ranges tile the file table in order, empty folders included
        cursor = 0
        for folder in document.folders:
            self.assertEqual(folder.start, cursor, f"{folder.path} does not start where the last folder ended")
            cursor += folder.count

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

    def test_the_header_counts_the_directories_it_lists(self) -> None:
        """The low byte of the header's third field is how many directories the file
        holds, and the game reads that rather than counting the records.

        Preserving the header verbatim, as this module first did, left every mounted
        overlay claiming one directory fewer than it listed. The game starts on a list
        that counts itself and refuses one that does not, with "There may be a problem
        with the game installation"; the shipped file says 33 with its 33 directories,
        and the game itself wrote 34 when it had 34.
        """

        data = self._papgt(("0000", "0001", "0008"))
        self.assertEqual(data[8], 3, "three directories, three in the header")
        mounted = papgt_with_directory(data, "0036", 0x22222222)
        self.assertEqual(len(parse_papgt(mounted)), 4)
        self.assertEqual(mounted[8], 4, "the mounted file counts itself")
        self.assertEqual(mounted[9:12], data[9:12], "the rest of the field is left alone")

        unmounted = serialize_papgt([item for item in parse_papgt(mounted) if item.name != "0036"], header=mounted[:12])
        self.assertEqual(unmounted[8], 3)
        self.assertEqual(unmounted, data, "and taking it out again gives back the file it started as")

        # re-mounting an already listed directory changes no count
        again = papgt_with_directory(mounted, "0036", 0x33333333)
        self.assertEqual(again[8], 4)
        self.assertEqual(len(parse_papgt(again)), 4)

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


import pytest  # noqa: E402


def _tables(data: bytes):
    """The folder and file tables of a PAMT, as the reader walks them."""

    _crc, paz_count, _konst = struct.unpack_from("<III", data, 0)
    off = 12 + paz_count * 12
    dir_size = struct.unpack_from("<I", data, off)[0]; off += 4
    dir_block = data[off:off + dir_size]; off += dir_size
    name_size = struct.unpack_from("<I", data, off)[0]; off += 4
    name_block = data[off:off + name_size]; off += name_size
    folder_count = struct.unpack_from("<I", data, off)[0]; off += 4
    folders = [struct.unpack_from("<IIII", data, off + index * 16) for index in range(folder_count)]
    off += folder_count * 16
    file_count = struct.unpack_from("<I", data, off)[0]; off += 4
    files = [struct.unpack_from("<IIIIHH", data, off + index * 20) for index in range(file_count)]

    def resolve(block: bytes, offset: int) -> str:
        parts, seen = [], set()
        while offset != 0xFFFFFFFF and offset not in seen:
            seen.add(offset)
            parent = struct.unpack_from("<I", block, offset)[0]
            length = block[offset + 4]
            parts.append(block[offset + 5: offset + 5 + length].decode("utf-8", "replace"))
            offset = parent
        return "".join(reversed(parts))

    return (
        [(resolve(dir_block, record[1]) if record[1] != 0xFFFFFFFF else "", record[0], record[2], record[3]) for record in folders],
        [(resolve(name_block, record[0]), record[2], record[3], record[5]) for record in files],
    )


@pytest.mark.real_game
@pytest.mark.parametrize("directory", ["0013", "0011", "0002"])
def test_the_writer_lays_a_shipped_archive_out_the_way_the_game_ships_it(directory: str) -> None:
    """A shipped archive's own files, back through the overlay writer, come out with the
    same tables the game shipped.

    This is the gate that would have caught the folder table: an overlay listed only the
    folders that held files, which read back correctly through this repository's own
    reader and made the game refuse to start. The game walks that table as a tree, and
    every shipped archive carries every folder on the way down -- 123 of archive 0000's
    1,370 folder records hold no file of their own.
    """

    from cdmw.core.archive_format import parse_archive_pamt
    from tools.placement_studio import corpus


    game = Path(corpus.game_root())
    pamt = game / directory / "0.pamt"
    if not pamt.is_file():
        pytest.skip(f"{directory} is not in this install")
    payloads = (game / directory / "0.paz").read_bytes()
    shipped_folders, shipped_files = _tables(pamt.read_bytes())

    built = build_overlay_archive([
        OverlayFile(
            path=str(entry.path).replace("\\", "/").strip("/"),
            payload=payloads[int(entry.offset): int(entry.offset) + int(entry.comp_size)],
            orig_size=int(entry.orig_size),
            flags=int(entry.flags),
        )
        for entry in parse_archive_pamt(pamt)
    ])
    ours_folders, ours_files = _tables(built.pamt_bytes)

    assert [row[0] for row in ours_folders] == [row[0] for row in shipped_folders], "folder paths and their order"
    assert [row[1] for row in ours_folders] == [row[1] for row in shipped_folders], "folder hashes"
    assert [(row[2], row[3]) for row in ours_folders] == [(row[2], row[3]) for row in shipped_folders], "folder file ranges"
    assert [row[0] for row in ours_files] == [row[0] for row in shipped_files], "file names and their order"
    assert [(row[1], row[2], row[3]) for row in ours_files] == [(row[1], row[2], row[3]) for row in shipped_files], "sizes and flags"
    assert len(built.paz_bytes) % PAZ_ALIGNMENT == 0
    if directory in {"0013", "0016"}:
        # these two carry no file names sharing a prefix, so the whole table comes back
        # byte for byte: the same trie, the same tables, the same header checksum
        assert built.pamt_bytes == pamt.read_bytes(), "the PAMT is the one the game shipped"
        assert built.paz_bytes == payloads, "the PAZ is the one the game shipped"
