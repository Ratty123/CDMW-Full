"""Gates for the `meta/0.pathc` texture registry model."""

from __future__ import annotations

import struct
import sys
import unittest
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from cdmw.core.pathc_format import (  # noqa: E402
    PathcEntry,
    PathcError,
    PathcTable,
    dds_shape,
    encode_pathc,
    parse_pathc,
    pathc_checksum,
    register_dds,
    register_texture,
)

ICON = "ui/texture/icon/itemicon_prefab_cd_phm_01_sword_0109.dds"
NEW_ICON = "ui/texture/icon/itemicon_prefab_cd_phm_01_sword_9109.dds"


def dds_header(*, width: int, height: int, fourcc: bytes = b"DXT5", mips: int = 1) -> bytes:
    head = bytearray(128)
    head[:4] = b"DDS "
    struct.pack_into("<7I", head, 4, 124, 0x000A1007, height, width, width * height, 1, mips)
    struct.pack_into("<I", head, 76, 32)
    struct.pack_into("<I", head, 80, 4)
    head[84:88] = fourcc
    return bytes(head)


def build_table(*, headers: list[bytes], entries: list[tuple[str, int, bytes]]) -> PathcTable:
    rows = sorted(
        (PathcEntry(checksum=pathc_checksum(path), header_index=index, collision_start=255, collision_end=255, block_infos=blocks) for path, index, blocks in entries),
        key=lambda row: row.checksum,
    )
    return PathcTable(reserved=0, header_size=148, headers=tuple(h + bytes(20) for h in headers), entries=tuple(rows), collisions=(), filenames=b"")


ICON_HEADER = dds_header(width=256, height=256)
BIG_HEADER = dds_header(width=1024, height=512, fourcc=b"DXT1", mips=11)
ICON_BLOCKS = struct.pack("<4I", 65536, 65536, 0, 0)
BIG_BLOCKS = struct.pack("<4I", 262144, 65536, 16384, 4096)


class PathcTests(unittest.TestCase):
    def test_round_trip_and_lookup(self) -> None:
        table = build_table(headers=[BIG_HEADER, ICON_HEADER], entries=[(ICON, 1, ICON_BLOCKS), ("a/b.dds", 0, BIG_BLOCKS)])
        raw = encode_pathc(table)
        self.assertEqual(parse_pathc(raw), table)
        self.assertEqual(struct.unpack_from("<QIIIII", raw, 0), (0, 148, 2, 2, 0, 0))
        found = table.find(ICON)
        self.assertIsNotNone(found)
        self.assertEqual((found.header_index, found.block_infos), (1, ICON_BLOCKS))
        self.assertEqual(table.dds_header_for(found), ICON_HEADER)
        self.assertIsNone(table.find(NEW_ICON))
        with self.assertRaisesRegex(PathcError, "describe"):
            parse_pathc(raw[:-1])

    def test_register_like_the_template_icon(self) -> None:
        table = build_table(headers=[BIG_HEADER, ICON_HEADER], entries=[(ICON, 1, ICON_BLOCKS), ("a/b.dds", 0, BIG_BLOCKS)])
        new = register_texture(table, NEW_ICON, like=ICON, dds_header=ICON_HEADER + bytes(65536))
        entry = new.find(NEW_ICON)
        self.assertEqual((entry.header_index, entry.block_infos, entry.collision_start, entry.collision_end), (1, ICON_BLOCKS, 255, 255))
        self.assertEqual([e.checksum for e in new.entries], sorted(e.checksum for e in new.entries), "the checksum table stays ascending")
        self.assertEqual(len(encode_pathc(new)), len(encode_pathc(table)) + 24)
        self.assertEqual(parse_pathc(encode_pathc(new)), new)
        self.assertEqual(table.find(NEW_ICON), None, "the source table is untouched")
        with self.assertRaisesRegex(PathcError, "differs"):
            register_texture(table, NEW_ICON, like=ICON, dds_header=BIG_HEADER)
        # engine tags in dwReserved1 / dwReserved2 differ between the archive and registry copies of a header: not a difference
        tagged = bytearray(ICON_HEADER)
        struct.pack_into("<II", tagged, 32, 0xDEADBEEF, 7)
        struct.pack_into("<I", tagged, 124, 0xF)
        self.assertEqual(dds_shape(bytes(tagged)), dds_shape(ICON_HEADER))
        self.assertIsNotNone(register_texture(table, NEW_ICON, like=ICON, dds_header=bytes(tagged)).find(NEW_ICON))
        self.assertIsNotNone(register_dds(table, "ui/texture/icon/other_new.dds", bytes(tagged) + bytes(16)).find("ui/texture/icon/other_new.dds"))
        with self.assertRaisesRegex(PathcError, "not registered"):
            register_texture(table, NEW_ICON, like="nope.dds")
        with self.assertRaisesRegex(PathcError, "already registered"):
            register_texture(new, NEW_ICON, like=ICON)

    def test_register_a_dds_by_its_own_header(self) -> None:
        odd = struct.pack("<4I", 1153, 65536, 16384, 4096)
        table = build_table(headers=[BIG_HEADER, ICON_HEADER], entries=[(ICON, 1, ICON_BLOCKS), ("a/b.dds", 0, BIG_BLOCKS), ("a/c.dds", 0, BIG_BLOCKS), ("a/d.dds", 0, odd)])
        new = register_dds(table, "character/texture/new_d.dds", BIG_HEADER + bytes(16))
        entry = new.find("character/texture/new_d.dds")
        self.assertEqual((entry.header_index, entry.block_infos), (0, BIG_BLOCKS), "the header's usual block infos, not the odd one out")
        with self.assertRaisesRegex(PathcError, "no shipped texture header"):
            register_dds(table, "x.dds", dds_header(width=64, height=64))
        with self.assertRaisesRegex(PathcError, "DDS header"):
            register_dds(table, "x.dds", b"nope")

    def test_encode_refuses_malformed_rows(self) -> None:
        table = build_table(headers=[ICON_HEADER], entries=[(ICON, 0, ICON_BLOCKS)])
        with self.assertRaisesRegex(PathcError, "16 bytes"):
            encode_pathc(PathcTable(0, 148, table.headers, (PathcEntry(1, 0, 255, 255, b"short"),), (), b""))
        with self.assertRaisesRegex(PathcError, "header_size"):
            encode_pathc(PathcTable(0, 148, (b"x",), (), (), b""))


@pytest.mark.real_game
class VanillaPathcTests(unittest.TestCase):
    def test_the_shipped_registry_round_trips_and_takes_an_icon(self) -> None:
        from tools.placement_studio import corpus

        path = corpus.game_root() / "meta" / "0.pathc"
        if not path.is_file():
            self.skipTest("needs the installed game")
        raw = path.read_bytes()
        table = parse_pathc(raw)
        self.assertEqual(encode_pathc(table), raw)
        self.assertGreater(len(table.entries), 280_000)
        checksums = [entry.checksum for entry in table.entries]
        self.assertEqual(checksums, sorted(checksums))
        self.assertEqual(len(set(checksums)), len(checksums))
        icon = table.find(ICON)
        self.assertIsNotNone(icon)
        header = table.dds_header_for(icon)
        self.assertEqual((header[:4], struct.unpack_from("<I", header, 12)[0], struct.unpack_from("<I", header, 16)[0], header[84:88]), (b"DDS ", 256, 256, b"DXT5"))
        probe = "ui/texture/icon/itemicon_prefab_cdmw_gate_probe.dds"
        if table.find(probe) is None:
            new = register_texture(table, probe, like=ICON, dds_header=header)
            self.assertEqual(new.find(probe).header_index, icon.header_index)
            self.assertEqual(len(encode_pathc(new)), len(raw) + 24)


if __name__ == "__main__":
    unittest.main()
