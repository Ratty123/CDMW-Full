"""Pins the PAC skin-influence byte layout against real vanilla bodies.

A vertex carries six influences, not four: two u32 of three 10-bit palette
slots, then six u8 weights. An earlier reading took bytes 20-23 as four u8
slots. Reader and writer agreed with each other, so round-trip tests passed
while the bytes were wrong -- 3,672 of one body's slots landed outside its
206-entry palette, and secondary bones sat a median 0.532 from their own
vertices where the packed reading puts them at 0.088.

These assertions are structural, not sampled -- they hold for every vertex of
every submesh -- so they fail loudly if the layout regresses.

Bodies live outside source control; the suite skips when they are absent.
"""

from __future__ import annotations

import struct
import unittest
from pathlib import Path

from cdmw.domain.mesh.body_regions import build_body_region_map
from cdmw.modding.mesh_parser import (
    PAC_SKIN_INFLUENCES,
    PAC_SKIN_MAX_BONE_INDEX,
    PAC_SKIN_SLOT_BITS,
    PAC_SKIN_SLOT_GROUPS,
    PAC_SKIN_SLOT_MASK,
    PAC_SKIN_SLOTS_PER_GROUP,
    PAC_SKIN_WEIGHT_LAYOUT,
    PAC_SKIN_WEIGHT_OFFSET,
    parse_mesh,
    resolve_pac_bone_palette,
)
from cdmw.modding.mesh_skinning import pack_pac_skin_weights, patch_pac_vertex_skin
from tools.dump_body_region_map import _resolve_skeleton


EXTRACTS_ROOT = Path(__file__).resolve().parent / "Extracts"
# Six u8 weights sum to 255 give or take rounding. Measured over the whole
# extracted corpus the worst body still keeps 90.2% of its vertices in this
# band, and the four-u8 reading lands nowhere near it.
WEIGHT_SUM_FLOOR = 200
WEIGHT_SUM_CEILING = 260
WEIGHT_SUM_MINIMUM_RATE = 0.90


def _body_paths() -> tuple[Path, ...]:
    if not EXTRACTS_ROOT.is_dir():
        return ()
    return tuple(sorted(EXTRACTS_ROOT.rglob("*.pac")))


def _raw_influences(data: bytes, offset: int) -> tuple[tuple[int, ...], tuple[int, ...]]:
    """The six slots and six raw u8 weights at a vertex record, straight from bytes."""

    slots: list[int] = []
    for group_offset in PAC_SKIN_SLOT_GROUPS:
        group = struct.unpack_from("<I", data, offset + group_offset)[0]
        slots.extend(
            (group >> (PAC_SKIN_SLOT_BITS * position)) & PAC_SKIN_SLOT_MASK
            for position in range(PAC_SKIN_SLOTS_PER_GROUP)
        )
    weights = struct.unpack_from(f"<{PAC_SKIN_INFLUENCES}B", data, offset + PAC_SKIN_WEIGHT_OFFSET)
    return tuple(slots), tuple(weights)


class PacSkinLayoutTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.paths = _body_paths()
        if not cls.paths:
            raise unittest.SkipTest(f"No extracted bodies under {EXTRACTS_ROOT}")

    def test_every_body_vertex_carries_skin_weights(self) -> None:
        for path in self.paths:
            mesh = parse_mesh(path.read_bytes(), path.name)
            with self.subTest(body=path.name):
                self.assertTrue(mesh.submeshes, "body parsed with no submeshes")
                for index, submesh in enumerate(mesh.submeshes):
                    unweighted = sum(1 for row in submesh.bone_weights if not row)
                    self.assertEqual(
                        unweighted,
                        0,
                        f"submesh {index} ({submesh.name}) decoded {unweighted} unweighted vertices",
                    )

    def test_every_record_declares_the_packed_layout(self) -> None:
        for path in self.paths:
            mesh = parse_mesh(path.read_bytes(), path.name)
            for index, submesh in enumerate(mesh.submeshes):
                if submesh.source_vertex_stride != 40:
                    continue
                with self.subTest(body=path.name, submesh=index):
                    self.assertEqual(submesh.source_skin_weight_layout, PAC_SKIN_WEIGHT_LAYOUT)

    def test_weights_descend_across_all_six_lanes(self) -> None:
        """The load-bearing check: reading the weight lane as four bytes breaks it.

        Descending order holds on every record of every extracted body across
        all six bytes, which is what distinguishes the real lane from a lane
        that happens to look plausible for the first few.
        """

        for path in self.paths:
            data = path.read_bytes()
            mesh = parse_mesh(data, path.name)
            for index, submesh in enumerate(mesh.submeshes):
                if submesh.source_vertex_stride != 40:
                    continue
                with self.subTest(body=path.name, submesh=index):
                    for offset in submesh.source_vertex_offsets:
                        _slots, weights = _raw_influences(data, offset)
                        self.assertEqual(
                            list(weights),
                            sorted(weights, reverse=True),
                            f"weights out of order at record {offset}",
                        )

    def test_slot_group_top_bits_are_unused(self) -> None:
        """Each u32 carries three 10-bit slots; the top two bits are always clear."""

        for path in self.paths:
            data = path.read_bytes()
            mesh = parse_mesh(data, path.name)
            for index, submesh in enumerate(mesh.submeshes):
                if submesh.source_vertex_stride != 40:
                    continue
                with self.subTest(body=path.name, submesh=index):
                    for offset in submesh.source_vertex_offsets:
                        for group_offset in PAC_SKIN_SLOT_GROUPS:
                            group = struct.unpack_from("<I", data, offset + group_offset)[0]
                            self.assertEqual(group >> 30, 0, f"top bits set at record {offset}")

    def test_weights_sum_to_full_influence(self) -> None:
        for path in self.paths:
            data = path.read_bytes()
            mesh = parse_mesh(data, path.name)
            for index, submesh in enumerate(mesh.submeshes):
                if submesh.source_vertex_stride != 40:
                    continue
                offsets = submesh.source_vertex_offsets
                in_band = sum(
                    1
                    for offset in offsets
                    if WEIGHT_SUM_FLOOR <= sum(_raw_influences(data, offset)[1]) <= WEIGHT_SUM_CEILING
                )
                with self.subTest(body=path.name, submesh=index):
                    self.assertGreater(in_band / len(offsets), WEIGHT_SUM_MINIMUM_RATE)

    def test_a_zero_weight_ends_the_influences(self) -> None:
        """A zero weight marks an influence unused, whatever its slot holds.

        Real records leave stale slot values behind a zero weight, so a decoder
        that keyed on the slot instead of the weight would invent influences.
        """

        stale_slots = 0
        for path in self.paths:
            data = path.read_bytes()
            mesh = parse_mesh(data, path.name)
            for index, submesh in enumerate(mesh.submeshes):
                if submesh.source_vertex_stride != 40:
                    continue
                with self.subTest(body=path.name, submesh=index):
                    for offset, decoded in zip(submesh.source_vertex_offsets, submesh.bone_weights):
                        _slots, weights = _raw_influences(data, offset)
                        live = [weight for weight in weights if weight > 0]
                        # Weights descend, so the live ones are a prefix.
                        self.assertEqual(live, list(weights[:len(live)]))
                        self.assertEqual(len(decoded), len(live))
                    for offset in submesh.source_vertex_offsets:
                        slots, weights = _raw_influences(data, offset)
                        stale_slots += sum(
                            1 for slot, weight in zip(slots, weights) if weight == 0 and slot != 0
                        )
        self.assertGreater(stale_slots, 0, "no body exercised a stale slot behind a zero weight")

    def test_every_decoded_slot_lands_inside_the_palette(self) -> None:
        """The four-u8 reading put 3,672 of one body's slots outside its palette."""

        checked = 0
        for path in self.paths:
            raw = path.read_bytes()
            skeleton, palette = _resolve_skeleton(path, raw, None)
            if not palette:
                continue  # rigid binding, or no rig on disk: nothing to name
            checked += 1
            mesh = parse_mesh(raw, path.name)
            with self.subTest(body=path.name):
                for submesh in mesh.submeshes:
                    for row in submesh.bone_indices:
                        for slot in row:
                            self.assertLessEqual(int(slot), PAC_SKIN_MAX_BONE_INDEX)
                            self.assertLess(
                                int(slot),
                                len(palette),
                                f"slot {slot} outran the {len(palette)}-entry palette",
                            )
        self.assertGreater(checked, 5, "no bodies resolved a palette to check against")

    def test_bodies_use_every_influence_count(self) -> None:
        """Smooth-skinned bodies spread one to six influences, not one to four."""

        counts: dict[int, int] = {}
        for path in self.paths:
            mesh = parse_mesh(path.read_bytes(), path.name)
            for submesh in mesh.submeshes:
                for row in submesh.bone_indices:
                    counts[len(row)] = counts.get(len(row), 0) + 1
        self.assertEqual(max(counts), PAC_SKIN_INFLUENCES, f"influence histogram {counts}")
        for influence_count in range(1, PAC_SKIN_INFLUENCES + 1):
            self.assertGreater(counts.get(influence_count, 0), 0, f"no vertex used {influence_count}")


class PacSkinRoundTripTests(unittest.TestCase):
    """The replacement path patches donor records, so an untouched row must not move."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.paths = _body_paths()
        if not cls.paths:
            raise unittest.SkipTest(f"No extracted bodies under {EXTRACTS_ROOT}")

    def test_unchanged_rows_survive_a_patch_byte_for_byte(self) -> None:
        checked = 0
        for path in self.paths:
            data = path.read_bytes()
            mesh = parse_mesh(data, path.name)
            for index, submesh in enumerate(mesh.submeshes):
                if submesh.source_vertex_stride != 40:
                    continue
                if len(submesh.source_vertex_offsets) != len(submesh.bone_indices):
                    continue
                with self.subTest(body=path.name, submesh=index):
                    for vertex_index, offset in enumerate(submesh.source_vertex_offsets):
                        if not submesh.bone_indices[vertex_index]:
                            continue
                        original = data[offset:offset + 40]
                        record = bytearray(original)
                        patch_pac_vertex_skin(record, submesh, vertex_index, index)
                        self.assertEqual(bytes(record), original, f"record {offset} moved")
                        checked += 1
        self.assertGreater(checked, 100_000, "corpus too small to prove the round trip")


class PacSkinEncodeTests(unittest.TestCase):
    def test_encoder_writes_the_packed_lanes(self) -> None:
        record = bytearray(40)
        pack_pac_skin_weights(record, (7, 1000), (0.5, 0.5), context="test vertex")

        slots, weights = _raw_influences(bytes(record), 0)
        # Sorted by descending weight, ties broken by the lower slot.
        self.assertEqual(slots, (7, 1000, 0, 0, 0, 0))
        self.assertEqual(sum(weights), 255)
        self.assertEqual(weights[2:], (0, 0, 0, 0))
        # Bytes outside the two influence lanes must be left alone.
        lanes = set(range(PAC_SKIN_SLOT_GROUPS[0], PAC_SKIN_SLOT_GROUPS[-1] + 4))
        lanes |= set(range(PAC_SKIN_WEIGHT_OFFSET, PAC_SKIN_WEIGHT_OFFSET + PAC_SKIN_INFLUENCES))
        self.assertTrue(all(record[position] == 0 for position in range(40) if position not in lanes))

    def test_encoder_round_trips_all_six_influences(self) -> None:
        from cdmw.modding.mesh_parser import _decode_pac_skin_influences

        bones = (205, 187, 40, 3, PAC_SKIN_MAX_BONE_INDEX, 7)
        record = bytearray(40)
        pack_pac_skin_weights(record, bones, (0.4, 0.25, 0.15, 0.1, 0.06, 0.04), context="test vertex")

        decoded_bones, decoded_weights = _decode_pac_skin_influences(bytes(record), 0)
        self.assertEqual(decoded_bones, bones)
        self.assertAlmostEqual(sum(decoded_weights), 1.0, places=6)
        self.assertEqual(list(decoded_weights), sorted(decoded_weights, reverse=True))

    def test_encoder_keeps_slot_zero_as_a_real_entry(self) -> None:
        """Slot 0 is a palette entry, not a sentinel: a rigid prop rides on it."""

        from cdmw.modding.mesh_parser import _decode_pac_skin_influences

        record = bytearray(40)
        pack_pac_skin_weights(record, (0,), (1.0,), context="test vertex")

        self.assertEqual(_decode_pac_skin_influences(bytes(record), 0)[0], (0,))
        self.assertEqual(record[PAC_SKIN_WEIGHT_OFFSET], 255)


class PacBonePaletteTests(unittest.TestCase):
    """The palette that turns an influence slot into a named skeleton bone."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.paths = tuple(p for p in _body_paths() if "/nude/" in p.as_posix() and "lod" not in p.name)
        if not cls.paths:
            raise unittest.SkipTest(f"No extracted nude bodies under {EXTRACTS_ROOT}")

    def test_every_body_resolves_a_palette(self) -> None:
        for path in self.paths:
            raw = path.read_bytes()
            skeleton, palette = _resolve_skeleton(path, raw, None)
            with self.subTest(body=path.name):
                self.assertIsNotNone(skeleton, "no skeleton candidate parsed")
                self.assertTrue(palette, "no candidate palette resolved against any skeleton")
                mesh = parse_mesh(raw, path.name)
                # Every influence is addressable now, not only the primary.
                slots = [
                    slot
                    for submesh in mesh.submeshes
                    for row in submesh.bone_indices
                    for slot in row
                ]
                self.assertTrue(slots)
                self.assertLess(max(slots), len(palette), "a slot outran the palette")

    def test_an_unresolved_palette_is_not_an_error(self) -> None:
        """A rigidly bound mesh carries no bone hash, so nothing resolves.

        The resolver must answer with an empty palette rather than raising, and
        the region map must degrade to a diagnostic rather than a failure.
        """

        path = self.paths[0]
        raw = path.read_bytes()

        class _NoBones:
            bones = ()

        self.assertEqual(resolve_pac_bone_palette(raw, _NoBones()), ())

        skeleton, _palette = _resolve_skeleton(path, raw, None)
        region_map = build_body_region_map(parse_mesh(raw, path.name), skeleton, bone_palette=())
        self.assertEqual(region_map.populated_regions, ())
        self.assertTrue(
            any("no bone palette" in note.lower() for note in region_map.diagnostics),
            region_map.diagnostics,
        )

    def test_regions_are_bilaterally_symmetric(self) -> None:
        """The strongest evidence the naming is right: a body is symmetric.

        A wrong palette scatters vertices across unrelated bones, which shows up
        immediately as left and right regions of different sizes. Only the
        Torso/Arms/Legs groups are checked: face rigs differ per head, so the
        sided head and ear regions legitimately vary.
        """

        checked = 0
        for path in self.paths:
            raw = path.read_bytes()
            skeleton, palette = _resolve_skeleton(path, raw, None)
            region_map = build_body_region_map(
                parse_mesh(raw, path.name), skeleton, bone_palette=palette or None
            )
            regions = region_map.populated_regions
            if len(regions) < 20:
                continue  # partial asset (hands/hair only), not a whole body
            checked += 1
            sizes = {region.region_id: region.vertex_count for region in regions}
            body = {
                region.region_id
                for region in regions
                if region.group in ("Torso", "Arms", "Legs")
            }
            with self.subTest(body=path.name):
                self.assertLess(region_map.unmapped_weight_fraction, 0.02)
                for region_id in sorted(body):
                    if not region_id.endswith("_l"):
                        continue
                    left = sizes[region_id]
                    right = sizes.get(f"{region_id[:-2]}_r", 0)
                    self.assertGreater(
                        min(left, right) / max(left, right, 1),
                        0.90,
                        f"{region_id} is lopsided: {left} vs {right}",
                    )
        self.assertGreater(checked, 5, "no whole bodies were available to check")
