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
    block_infos_for,
    dds_shape,
    encode_pathc,
    header_tag,
    header_tag_for,
    parse_pathc,
    pathc_checksum,
    register_dds,
    register_texture,
    validate_dds_payload,
)

ICON = "ui/texture/icon/itemicon_prefab_cd_phm_01_sword_0109.dds"
NEW_ICON = "ui/texture/icon/itemicon_prefab_cd_phm_01_sword_9109.dds"


def dds_header(*, width: int, height: int, fourcc: bytes = b"DXT5", mips: int = 1, tag: int = 4) -> bytes:
    head = bytearray(128)
    head[:4] = b"DDS "
    struct.pack_into("<7I", head, 4, 124, 0x000A1007, height, width, width * height, 1, mips)
    struct.pack_into("<I", head, 76, 32)
    struct.pack_into("<I", head, 80, 4)
    head[84:88] = fourcc
    struct.pack_into("<I", head, 124, tag)
    return bytes(head)


def dds_payload(header: bytes) -> bytes:
    """Complete synthetic BC payload, without using the registration implementation."""
    height, width = struct.unpack_from("<II", header, 12)
    mips = max(1, struct.unpack_from("<I", header, 28)[0])
    block = 8 if header[84:88] in (b"DXT1", b"BC4U") else 16
    return header + bytes(sum(max(1, ((width >> level) + 3) // 4)
                              * max(1, ((height >> level) + 3) // 4) * block
                              for level in range(mips)))


def build_table(*, headers: list[bytes], entries: list[tuple[str, int, bytes]]) -> PathcTable:
    rows = sorted(
        (PathcEntry(checksum=pathc_checksum(path), header_index=index, collision_start=255, collision_end=255, block_infos=blocks) for path, index, blocks in entries),
        key=lambda row: row.checksum,
    )
    return PathcTable(reserved=0, header_size=148, headers=tuple(h.ljust(148, b"\0") for h in headers), entries=tuple(rows), collisions=(), filenames=b"")


ICON_HEADER = dds_header(width=256, height=256)
BIG_HEADER = dds_header(width=1024, height=512, fourcc=b"DXT1", mips=11)
ICON_BLOCKS = struct.pack("<4I", 65536, 65536, 0, 0)
BIG_BLOCKS = struct.pack("<4I", 262144, 65536, 16384, 4096)


class PathcTests(unittest.TestCase):
    def test_dx10_formats_never_share_a_descriptor(self) -> None:
        base = dds_header(width=4, height=4, fourcc=b"DX10")
        bc3 = base + struct.pack("<5I", 77, 3, 0, 1, 0)
        bc7 = base + struct.pack("<5I", 98, 3, 0, 1, 0)
        table = register_dds(build_table(headers=[], entries=[]), "x/first_n.dds", dds_payload(bc3))
        changed = register_dds(table, "x/second_n.dds", dds_payload(bc7))
        self.assertEqual(len(changed.headers), 2)
        self.assertEqual(changed.dds_header_for(changed.find("x/second_n.dds")), bc7)
        with self.assertRaisesRegex(PathcError, "differs"):
            register_texture(table, "x/second_n.dds", like="x/first_n.dds", dds_header=dds_payload(bc7))

    def test_incomplete_dds_refuses_before_header_reuse_or_creation(self) -> None:
        header = dds_header(width=4, height=4)
        table = build_table(headers=[header], entries=[("x/old_n.dds", 0, struct.pack("<4I", 16, 16, 0, 0))])
        for target in (table, build_table(headers=[], entries=[])):
            for data in (header, header + bytes(15)):
                with self.subTest(reuse=bool(target.entries), size=len(data)):
                    with self.assertRaisesRegex(PathcError, "payload"):
                        register_dds(target, "x/new_n.dds", data)
        with self.assertRaisesRegex(PathcError, "payload"):
            register_texture(table, "x/new_n.dds", like="x/old_n.dds", dds_header=header)

    def test_dx10_extension_is_required_even_when_base_header_matches(self) -> None:
        base = dds_header(width=4, height=4, fourcc=b"DX10")
        header = base + struct.pack("<5I", 77, 3, 0, 1, 0)
        table = register_dds(build_table(headers=[], entries=[]), "x/old_n.dds", dds_payload(header))
        for data in (base, base + bytes(19)):
            with self.assertRaisesRegex(PathcError, "DX10"):
                register_dds(table, "x/new_n.dds", data)

    def test_raw_registration_does_not_copy_per_file_storage_sizes(self) -> None:
        header = dds_header(width=4, height=4)
        table = build_table(headers=[header], entries=[("x/old_n.dds", 0, bytes(16))])
        for result in (register_dds(table, "x/new_n.dds", dds_payload(header)),
                       register_texture(table, "x/new_n.dds", like="x/old_n.dds", dds_header=dds_payload(header))):
            self.assertEqual(result.find("x/new_n.dds").block_infos, struct.pack("<4I", 16, 16, 0, 0))

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
            register_texture(table, NEW_ICON, like=ICON, dds_header=dds_payload(BIG_HEADER))
        # engine tags in dwReserved1 / dwReserved2 differ between the archive and registry copies of a header: not a difference
        tagged = bytearray(ICON_HEADER)
        struct.pack_into("<II", tagged, 32, 0xDEADBEEF, 7)
        struct.pack_into("<I", tagged, 124, 0xF)
        self.assertEqual(dds_shape(bytes(tagged)), dds_shape(ICON_HEADER))
        self.assertIsNotNone(register_texture(table, NEW_ICON, like=ICON, dds_header=dds_payload(bytes(tagged))).find(NEW_ICON))
        self.assertIsNotNone(register_dds(table, "ui/texture/icon/other_new.dds", dds_payload(bytes(tagged))).find("ui/texture/icon/other_new.dds"))
        with self.assertRaisesRegex(PathcError, "not registered"):
            register_texture(table, NEW_ICON, like="nope.dds")
        with self.assertRaisesRegex(PathcError, "already registered"):
            register_texture(new, NEW_ICON, like=ICON)

    def test_register_a_dds_by_its_own_header(self) -> None:
        odd = struct.pack("<4I", 1153, 65536, 16384, 4096)
        table = build_table(headers=[BIG_HEADER, ICON_HEADER], entries=[(ICON, 1, ICON_BLOCKS), ("a/b.dds", 0, BIG_BLOCKS), ("a/c.dds", 0, BIG_BLOCKS), ("a/d.dds", 0, odd)])
        new = register_dds(table, "character/texture/new_mg.dds", dds_payload(BIG_HEADER))
        entry = new.find("character/texture/new_mg.dds")
        self.assertEqual((entry.header_index, entry.block_infos), (0, BIG_BLOCKS), "the header's usual block infos, not the odd one out")
        # the tag is part of the match: a base colour (tag 12) does not land on a mask's header (tag 4)
        colour = register_dds(table, "character/texture/new_d.dds", dds_payload(BIG_HEADER))
        self.assertEqual(colour.find("character/texture/new_d.dds").header_index, 2, "a new header row, tagged 12")
        self.assertEqual(header_tag(colour.headers[2]), 12)
        self.assertEqual(colour.find("character/texture/new_d.dds").block_infos, BIG_BLOCKS)
        self.assertEqual(register_dds(table, "character/texture/new_d.dds", dds_payload(BIG_HEADER), tag=4).find("character/texture/new_d.dds").header_index, 0, "an explicit tag overrides the role")
        with self.assertRaisesRegex(PathcError, "DDS header"):
            register_dds(table, "x.dds", b"nope")
        # a shape the registry has never seen gets a header row of its own, with computed mip sizes
        odd_shape = dds_header(width=64, height=64, mips=7)  # DXT5
        grown = register_dds(table, "x/new_64.dds", dds_payload(odd_shape))
        self.assertEqual(len(grown.headers), 3)
        entry = grown.find("x/new_64.dds")
        self.assertEqual(entry.header_index, 2)
        self.assertEqual(struct.unpack("<4I", entry.block_infos), (4096, 1024, 256, 64), "DXT5 64x64 mips 0..3")
        self.assertEqual(grown.headers[2][:32], odd_shape[:32])
        self.assertEqual(grown.headers[2][32:76], bytes(44), "dwReserved1 zeroed")
        self.assertEqual(struct.unpack_from("<I", grown.headers[2], 124)[0], 13, "the tag of a colour texture with alpha")
        self.assertEqual(grown.headers[2][128:], bytes(20))
        self.assertEqual(parse_pathc(encode_pathc(grown)), grown)
        one_mip = register_dds(table, "x/one.dds", dds_header(width=64, height=64, mips=1) + bytes(4096))
        self.assertEqual(struct.unpack("<4I", one_mip.find("x/one.dds").block_infos), (4096, 4096, 0, 0), "a one-mip texture repeats the top size, like the icons")
        bc5 = register_dds(table, "x/n.dds", dds_payload(dds_header(width=32, height=32, fourcc=b"BC5U", mips=6)))
        self.assertEqual(struct.unpack("<4I", bc5.find("x/n.dds").block_infos), (1024, 256, 64, 16))
        self.assertEqual(block_infos_for(dds_header(width=256, height=256, fourcc=b"DXT5", mips=1)), struct.pack("<4I", 65536, 65536, 0, 0))
        with self.assertRaisesRegex(PathcError, "not one whose mip sizes"):
            register_dds(table, "x/rgba.dds", dds_header(width=8, height=8, fourcc=bytes(4)))

    def test_header_tags_follow_the_texture_kind(self) -> None:
        dxt1 = dds_header(width=64, height=64, fourcc=b"DXT1", mips=7)
        dxt5 = dds_header(width=64, height=64, fourcc=b"DXT5", mips=7)
        self.assertEqual(header_tag_for("character/texture/cd_phm_02_sword_9003_blade_basecolor.dds", dxt1), 12)
        self.assertEqual(header_tag_for("character/texture/cd_phm_02_sword_9003_blade.dds", dxt5), 13, "a colour with alpha")
        self.assertEqual(header_tag_for("character/texture/x_sp.dds", dxt1), 12, "_sp ships tagged like a colour")
        for suffix in ("n", "disp", "ma", "mg", "emi", "o"):
            self.assertEqual(header_tag_for(f"character/texture/x_{suffix}.dds", dxt1), 4, suffix)
        self.assertEqual(header_tag_for("character/texture/x_m.dds", dxt5), 5)
        self.assertEqual(header_tag_for("ui/texture/icon/x.dds", dxt5), 13)
        self.assertEqual(header_tag(dds_header(width=8, height=8, tag=15)), 15)

    def test_encode_refuses_malformed_rows(self) -> None:
        table = build_table(headers=[ICON_HEADER], entries=[(ICON, 0, ICON_BLOCKS)])
        with self.assertRaisesRegex(PathcError, "16 bytes"):
            encode_pathc(PathcTable(0, 148, table.headers, (PathcEntry(1, 0, 255, 255, b"short"),), (), b""))
        with self.assertRaisesRegex(PathcError, "header_size"):
            encode_pathc(PathcTable(0, 148, (b"x",), (), (), b""))


@pytest.mark.parametrize('offset,value', [(4, 0), (76, 0), (12, 0), (16, 32768), (28, 99),
                                         (24, 2), (112, 0x200), (8, 0x800000), (80, 0)])
def test_invalid_dds_layouts_cannot_enter_a_registry(offset, value):
    data = bytearray(dds_payload(dds_header(width=4, height=4)))
    struct.pack_into('<I', data, offset, value)
    with pytest.raises(PathcError):
        register_dds(build_table(headers=[], entries=[]), 'x/new.dds', bytes(data))


@pytest.mark.parametrize('dimension,misc,array,alpha', [(2, 0, 1, 0), (4, 0, 1, 0), (3, 4, 1, 0),
                                                       (3, 0, 0, 0), (3, 0, 2, 0), (3, 0, 1, 5)])
def test_unsupported_dx10_shapes_refuse(dimension, misc, array, alpha):
    header = dds_header(width=4, height=4, fourcc=b'DX10') + struct.pack('<5I', 98, dimension, misc, array, alpha)
    with pytest.raises(PathcError, match='DX10'):
        validate_dds_payload(dds_payload(header))


@pytest.mark.parametrize('delta', [-1, 1])
def test_all_mips_and_only_the_declared_payload_are_required(delta):
    header = dds_header(width=8, height=8, mips=4)
    valid = dds_payload(header)
    assert validate_dds_payload(valid).mip_bytes == (64, 16, 16, 16)
    with pytest.raises(PathcError, match='payload'):
        validate_dds_payload(valid[:delta] if delta < 0 else valid + bytes(delta))


def test_supported_dx10_alpha_semantics_remain_distinct():
    base = dds_header(width=4, height=4, fourcc=b'DX10')
    table = build_table(headers=[], entries=[])
    for alpha in (0, 1, 2, 3, 4):
        data = dds_payload(base + struct.pack('<5I', 98, 3, 0, 1, alpha))
        table = register_dds(table, f'x/alpha_{alpha}_n.dds', data)
    assert len(table.headers) == 5


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
            new = register_texture(table, probe, like=ICON)
            self.assertEqual(new.find(probe).header_index, icon.header_index)
            self.assertEqual(len(encode_pathc(new)), len(raw) + 24)


if __name__ == "__main__":
    unittest.main()
