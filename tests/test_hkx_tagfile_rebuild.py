from __future__ import annotations

import struct
import unittest
from typing import Dict, List, Sequence, Tuple

from cdmw.core.archive_hkx_structural_edits import (
    hkx_string_items,
    hkx_structural_edit_gate_document,
    rename_hkx_strings,
    replace_hkx_string_item,
)
from cdmw.core.archive_hkx_tagfile_model import (
    HkxTagfileRefused,
    hkx_tagfile_masked_payloads,
    hkx_tagfile_reference_graph,
    parse_hkx_tagfile_model,
    serialize_hkx_tagfile_model,
)


def _section(tag: str, flags: int, payload: bytes) -> bytes:
    return struct.pack(">I", (flags << 30) | (len(payload) + 8)) + tag.encode("ascii") + payload


def _type_section(names: Sequence[str]) -> bytes:
    strings = b"".join(name.encode("ascii") + b"\0" for name in names)
    strings += b"\xff" * (-len(strings) % 4)
    table = bytes([len(names) + 1]) + b"".join(bytes([index, 0]) for index in range(len(names)))
    table += b"\0" * (-len(table) % 4)
    children = (
        _section("MTTP", 1, bytes(8 * (len(names) + 1)))
        + _section("TST1", 1, strings)
        + _section("TNA1", 1, table)
        + _section("TPAD", 1, b"")
    )
    return _section("TYPE", 0, children)


def _tagfile(
    names: Sequence[str],
    items: Sequence[Tuple[int, int, int, int]],
    data: bytes,
    patches: Dict[int, List[int]] | None = None,
    sdk: bytes = b"20240200",
) -> bytes:
    item_table = bytes(12) + b"".join(struct.pack("<3I", (kind << 24) | type_index, offset, count) for kind, type_index, offset, count in items)
    index = _section("ITEM", 1, item_table)
    if patches is not None:
        table = b"".join(struct.pack("<2I", key, len(words)) + struct.pack(f"<{len(words)}I", *words) for key, words in sorted(patches.items()))
        index += _section("PTCH", 1, table)
    body = _section("SDKV", 1, sdk) + _section("DATA", 1, data) + _type_section(names) + _section("INDX", 0, index)
    return _section("TAG0", 0, body)


CONVEX_TYPES = (
    "hknpConvexShape",
    "hknpShapeMassProperties",
    "hknpShapeProperties::Entry",
    "hkFloat3",
    "hkVector4",
    "hknpConvexHull::Face",
    "hkUint8",
    "hknpConvexHull::Edge",
)


def build_convex_fixture(
    *,
    names: Sequence[str] = CONVEX_TYPES,
    entry_offset: int = 128,
    vertex_slot_bias: int = 0,
    vertex_count_field: int = 4,
    entry_points_at_mass: bool = True,
    padding_byte: int = 0,
    sdk: bytes = b"20240200",
) -> bytes:
    """A tetrahedron hknpConvexShape laid out the way shipped meshphysics files are (no PTCH).

    ITEM order (shape, mass, entry, arrays) differs from DATA order (shape, entry,
    arrays, mass), as in the game files.
    """

    vertices_offset = entry_offset + 16
    layout = {  # item -> (DATA offset, byte size)
        1: (0, 120),
        3: (entry_offset, 8),
        4: (vertices_offset, 48),
        5: (vertices_offset + 48, 64),
        6: (vertices_offset + 112, 16),
        7: (vertices_offset + 128, 12),
        8: (vertices_offset + 144, 48),
        9: (vertices_offset + 192, 16),
        2: (vertices_offset + 208, 64),
    }
    data = bytearray(vertices_offset + 272)
    shape = bytearray(120)
    shape[24:28] = bytes((0x00, 0x01, 0x43, 0x00))
    struct.pack_into("<qI", shape, 32, entry_offset - 32, 1)
    for slot, item, count in ((56, 4, 4), (64, 5, 4), (72, 6, 4), (80, 7, 12), (88, 8, 12), (96, 9, 4)):
        struct.pack_into("<iI", shape, slot, layout[item][0] - slot + (vertex_slot_bias if slot == 56 else 0), vertex_count_field if slot == 56 else count)
    struct.pack_into("<f", shape, 104, 0.01)
    data[0:120] = shape
    if entry_points_at_mass:
        struct.pack_into("<q", data, entry_offset, layout[2][0] - entry_offset)
    vertices = ((0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0))
    for index, vertex in enumerate(vertices):
        struct.pack_into("<3f", data, vertices_offset + 12 * index, *vertex)
    planes = ((0.0, 0.0, -1.0, 0.0), (0.0, -1.0, 0.0, 0.0), (-1.0, 0.0, 0.0, 0.0), (0.577, 0.577, 0.577, -0.577))
    for index, plane in enumerate(planes):
        struct.pack_into("<4f", data, layout[5][0] + 16 * index, *plane)
    for index in range(4):
        struct.pack_into("<HBB", data, layout[6][0] + 4 * index, 3 * index, 3, 54)
    data[layout[7][0] : layout[7][0] + 12] = bytes((0, 2, 1, 0, 1, 3, 0, 3, 2, 1, 2, 3))
    for index in range(12):
        struct.pack_into("<HBB", data, layout[8][0] + 4 * index, (index // 3 + 1) % 4, index % 3, 0)
    for index in range(4):
        struct.pack_into("<HBB", data, layout[9][0] + 4 * index, index, 0, 0)
    mass = layout[2][0]
    data[mass + 16 : mass + 24] = bytes((0, 0xF1, 0, 0, 0, 0, 0, 0))
    struct.pack_into("<2f", data, mass + 56, 10.0, 0.1667)
    data[121] = padding_byte
    kinds = {1: (0x10, 1), 2: (0x10, 2), 3: (0x20, 3), 4: (0x20, 4), 5: (0x20, 5), 6: (0x20, 6), 7: (0x20, 7), 8: (0x20, 8), 9: (0x20, 8)}
    counts = {1: 1, 2: 1, 3: 1, 4: 4, 5: 4, 6: 4, 7: 12, 8: 12, 9: 4}
    items = [(kinds[index][0], kinds[index][1], layout[index][0], counts[index]) for index in range(1, 10)]
    return _tagfile(names, items, bytes(data), sdk=sdk)


ROOT_TYPES = (
    "hkRootLevelContainer",
    "hkArray",
    "hkRootLevelContainer::NamedVariant",
    "hkStringPtr",
    "char",
    "hkRefVariant",
    "hknpShapeMassProperties",
)


def build_root_fixture(name0: str = "Physics Data", class_name: str = "hknpShapeMassProperties", name1: str = "Second") -> bytes:
    """A PTCH-backed root container with two named variants that share one class-name string."""

    def align(value: int, alignment: int) -> int:
        return (value + alignment - 1) // alignment * alignment

    strings = [s.encode("utf-8") + b"\0" for s in (name0, class_name, name1)]
    offsets = [64]
    for text in strings[:-1]:
        offsets.append(align(offsets[-1] + len(text), 2))
    mass_offset = align(offsets[-1] + len(strings[-1]), 8)
    data = bytearray(align(mass_offset + 64, 16))
    struct.pack_into("<Q", data, 0, 2)
    for element, (name_item, class_item) in enumerate(((3, 4), (5, 4))):
        struct.pack_into("<3Q", data, 16 + 24 * element, name_item, class_item, 6)
    for offset, text in zip(offsets, strings):
        data[offset : offset + len(text)] = text
    struct.pack_into("<2f", data, mass_offset + 56, 7.5, 0.0075)
    items = [
        (0x10, 1, 0, 1),
        (0x20, 3, 16, 2),
        (0x20, 5, offsets[0], len(strings[0])),
        (0x20, 5, offsets[1], len(strings[1])),
        (0x20, 5, offsets[2], len(strings[2])),
        (0x10, 7, mass_offset, 1),
    ]
    patches = {2: [0], 4: [16, 24, 40, 48], 6: [32, 56]}
    return _tagfile(ROOT_TYPES, items, bytes(data), patches)


class HkxTagfileRebuildTests(unittest.TestCase):
    def test_relative_fixture_rebuilds_byte_exact(self) -> None:
        data = build_convex_fixture()
        model = parse_hkx_tagfile_model(data)
        self.assertEqual(serialize_hkx_tagfile_model(model), data)
        self.assertFalse(model.has_patch_section)
        self.assertEqual(model.data_order, [1, 3, 4, 5, 6, 7, 8, 9, 2])
        targets = {(ref.source_item, ref.offset): ref.target_item for ref in model.references}
        self.assertEqual(targets[(1, 32)], 3)
        self.assertEqual(targets[(1, 56)], 4)
        self.assertEqual(targets[(1, 96)], 9)
        self.assertEqual(targets[(3, 0)], 2)

    def test_patch_fixture_rebuilds_byte_exact(self) -> None:
        data = build_root_fixture()
        model = parse_hkx_tagfile_model(data)
        self.assertEqual(serialize_hkx_tagfile_model(model), data)
        patch_targets = sorted((ref.source_item, ref.offset, ref.target_item) for ref in model.references if ref.is_patch)
        self.assertEqual(patch_targets, [(1, 0, 2), (2, 0, 3), (2, 8, 4), (2, 16, 6), (2, 24, 5), (2, 32, 4), (2, 40, 6)])

    def test_references_follow_relocation(self) -> None:
        for data in (build_convex_fixture(), build_root_fixture()):
            model = parse_hkx_tagfile_model(data)
            shifted_bytes = serialize_hkx_tagfile_model(model, extra_gap=16)
            self.assertNotEqual(shifted_bytes, data)
            with self.assertRaises(HkxTagfileRefused) as raised:
                parse_hkx_tagfile_model(shifted_bytes)
            self.assertEqual(raised.exception.code, "unproven_layout")
            shifted = parse_hkx_tagfile_model(shifted_bytes, canonical_layout=False)
            self.assertEqual(hkx_tagfile_reference_graph(shifted), hkx_tagfile_reference_graph(model))
            self.assertEqual(hkx_tagfile_masked_payloads(shifted), hkx_tagfile_masked_payloads(model))
            self.assertEqual(serialize_hkx_tagfile_model(shifted), data)

    def test_string_replace_lays_data_out_again(self) -> None:
        model = parse_hkx_tagfile_model(build_root_fixture())
        self.assertEqual(hkx_string_items(model), [(3, "Physics Data"), (4, "hknpShapeMassProperties"), (5, "Second")])
        edited = serialize_hkx_tagfile_model(replace_hkx_string_item(model, 3, "Ragdoll Physics Data, renamed"))
        self.assertEqual(edited, build_root_fixture(name0="Ragdoll Physics Data, renamed"))
        shorter = serialize_hkx_tagfile_model(replace_hkx_string_item(model, 5, ""))
        self.assertEqual(shorter, build_root_fixture(name1=""))

    def test_shared_string_changes_for_every_owner(self) -> None:
        data = build_root_fixture()
        edited = rename_hkx_strings(data, {"hknpShapeMassProperties": "hknpShapeMassProperties_v2"})
        self.assertEqual(edited, build_root_fixture(class_name="hknpShapeMassProperties_v2"))
        reparsed = parse_hkx_tagfile_model(edited)
        owners = [ref for ref in reparsed.references if ref.target_item == 4]
        self.assertEqual(len(owners), 2)

    def test_utf8_strings_round_trip_through_the_edit(self) -> None:
        data = build_root_fixture(name0="C:\\scenes\\교수대로프.max")
        model = parse_hkx_tagfile_model(data)
        index, text = hkx_string_items(model)[0]
        self.assertEqual(serialize_hkx_tagfile_model(replace_hkx_string_item(model, index, text)), data)

    def test_string_edit_refusals(self) -> None:
        model = parse_hkx_tagfile_model(build_root_fixture())
        with self.assertRaises(HkxTagfileRefused) as raised:
            replace_hkx_string_item(model, 6, "x")
        self.assertEqual(raised.exception.code, "unproven_edit")
        with self.assertRaises(HkxTagfileRefused) as raised:
            replace_hkx_string_item(model, 3, "bad\0name")
        self.assertEqual(raised.exception.code, "bad_edit")
        with self.assertRaises(HkxTagfileRefused):
            rename_hkx_strings(build_root_fixture(), {"Not present": "x"})

    def test_unproven_files_are_refused_with_a_reason(self) -> None:
        cases = {
            "unsupported_sdk": build_convex_fixture(sdk=b"20230100"),
            "unproven_type": build_convex_fixture(names=("hknpConvexShapeX",) + CONVEX_TYPES[1:]),
            "unproven_layout": build_convex_fixture(entry_offset=144),
            "nonzero_padding": build_convex_fixture(padding_byte=7),
            "unreached_items": build_convex_fixture(entry_points_at_mass=False),
        }
        for code, data in cases.items():
            with self.subTest(code=code):
                with self.assertRaises(HkxTagfileRefused) as raised:
                    parse_hkx_tagfile_model(data)
                self.assertEqual(raised.exception.code, code)
        for data in (build_convex_fixture(vertex_slot_bias=4), build_convex_fixture(vertex_count_field=5)):
            with self.assertRaises(HkxTagfileRefused) as raised:
                parse_hkx_tagfile_model(data)
            self.assertEqual(raised.exception.code, "bad_reference")

    def test_structural_edit_gate_document(self) -> None:
        strings_gate = hkx_structural_edit_gate_document(build_root_fixture())
        self.assertEqual(strings_gate["codec_status"], "exact")
        self.assertEqual(strings_gate["allowed"], ["string_replace"])
        self.assertEqual(len(strings_gate["strings"]), 3)
        self.assertIn("convex_hull_rebuild", strings_gate["blocked"])
        convex_gate = hkx_structural_edit_gate_document(build_convex_fixture())
        self.assertEqual((convex_gate["codec_status"], convex_gate["allowed"]), ("exact", []))
        refused = hkx_structural_edit_gate_document(build_convex_fixture(entry_points_at_mass=False))
        self.assertEqual((refused["codec_status"], refused["codec_refusal_code"]), ("refused", "unreached_items"))
        self.assertEqual(refused["fallback"], "fixed_size_patch_gate")

    def test_editable_document_reports_the_structural_gate(self) -> None:
        from cdmw.core.archive_hkx import build_hkx_editable_geometry_document

        document = build_hkx_editable_geometry_document(build_convex_fixture(), "character/bin__/meshphysics/fixture.hkx")
        self.assertEqual(document["structural_edit_gate_v1"]["codec_status"], "exact")


if __name__ == "__main__":
    unittest.main()
