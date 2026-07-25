"""Pins the PAC skin-influence byte layout against real vanilla bodies.

The reader and writer previously used offsets 28 (indices) and 32 (weights).
They agreed with each other, so round-trip tests passed while the bytes were
wrong: 44-98% of every real body decoded as unweighted, and authoring could
only ever emit bone indices 0-3.

These assertions are structural, not sampled — they hold for every vertex of
every submesh — so they fail loudly if the offsets regress.

Bodies live outside source control; the suite skips when they are absent.
"""

from __future__ import annotations

import struct
import unittest
from pathlib import Path

from cdmw.domain.mesh.body_regions import build_body_region_map
from cdmw.modding.mesh_parser import (
    PAC_SKIN_INDEX_OFFSET,
    PAC_SKIN_MAX_BONE_INDEX,
    PAC_SKIN_UNUSED_SLOT,
    PAC_SKIN_WEIGHT_OFFSET,
    parse_mesh,
    resolve_pac_bone_palette,
)
from cdmw.modding.mesh_skinning import pack_pac_skin_weights
from tools.dump_body_region_map import _resolve_skeleton


EXTRACTS_ROOT = Path(__file__).resolve().parent / "Extracts"
# u8 weights across four influences lose a little to rounding, and how much
# varies by body. Measured over 92 vanilla submeshes the worst case still keeps
# 95.6% of its vertices inside this band, while a wrong offset lands nowhere
# near it, so the band is wide and the bar sits below the observed floor.
WEIGHT_SUM_FLOOR = 200
WEIGHT_SUM_CEILING = 260
WEIGHT_SUM_MINIMUM_RATE = 0.90


def _body_paths() -> tuple[Path, ...]:
    if not EXTRACTS_ROOT.is_dir():
        return ()
    return tuple(sorted(EXTRACTS_ROOT.rglob("*.pac")))


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

    def test_live_weights_never_land_on_an_unused_slot(self) -> None:
        """0xFF marks an empty influence, so no live weight may pair with it.

        This is the load-bearing check: it is a property of the format itself,
        and reading the index lane one byte off breaks it immediately.
        """

        for path in self.paths:
            data = path.read_bytes()
            mesh = parse_mesh(data, path.name)
            for index, submesh in enumerate(mesh.submeshes):
                if submesh.source_vertex_stride != 40:
                    continue
                with self.subTest(body=path.name, submesh=index):
                    for offset in submesh.source_vertex_offsets:
                        slots = struct.unpack_from("<BBBB", data, offset + PAC_SKIN_INDEX_OFFSET)
                        weights = struct.unpack_from("<BBBB", data, offset + PAC_SKIN_WEIGHT_OFFSET)
                        for slot, weight in zip(slots, weights):
                            if weight > 0:
                                self.assertNotEqual(slot, PAC_SKIN_UNUSED_SLOT)

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
                    if WEIGHT_SUM_FLOOR
                    <= sum(struct.unpack_from("<BBBB", data, offset + PAC_SKIN_WEIGHT_OFFSET))
                    <= WEIGHT_SUM_CEILING
                )
                with self.subTest(body=path.name, submesh=index):
                    self.assertGreater(in_band / len(offsets), WEIGHT_SUM_MINIMUM_RATE)

    def test_slots_exceed_any_descriptor_palette(self) -> None:
        """Slots are per-mesh tokens, not indices into the descriptor field.

        The descriptor's bone field is only ever the identity sequence
        (0,1,2,3), while live slots reach past 200, so that field cannot be the
        palette. The real palette is a bone-hash table elsewhere in the .pac;
        the slot -> entry mapping is still unsolved, so this only pins the
        range, not any bone identity.
        """

        highest = -1
        for path in self.paths:
            mesh = parse_mesh(path.read_bytes(), path.name)
            for submesh in mesh.submeshes:
                palette = tuple(submesh.source_bone_palette or ())
                for row in submesh.bone_indices:
                    for bone in row:
                        highest = max(highest, int(bone))
                        self.assertLessEqual(int(bone), PAC_SKIN_MAX_BONE_INDEX)
                if palette:
                    self.assertEqual(palette, tuple(range(len(palette))))
        self.assertGreater(highest, 200, "no body referenced a high skeleton bone index")


class PacSkinEncodeTests(unittest.TestCase):
    def test_encoder_writes_the_measured_lanes(self) -> None:
        record = bytearray(40)
        pack_pac_skin_weights(record, (7, 200), (0.5, 0.5), context="test vertex")

        slots = tuple(record[PAC_SKIN_INDEX_OFFSET:PAC_SKIN_INDEX_OFFSET + 4])
        weights = tuple(record[PAC_SKIN_WEIGHT_OFFSET:PAC_SKIN_WEIGHT_OFFSET + 4])
        self.assertEqual(slots, (7, 200, PAC_SKIN_UNUSED_SLOT, PAC_SKIN_UNUSED_SLOT))
        self.assertEqual(sum(weights), 255)
        self.assertEqual(weights[2:], (0, 0))
        # Bytes outside the two influence lanes must be left alone.
        untouched = [
            position
            for position in range(40)
            if not (
                PAC_SKIN_INDEX_OFFSET <= position < PAC_SKIN_INDEX_OFFSET + 4
                or PAC_SKIN_WEIGHT_OFFSET <= position < PAC_SKIN_WEIGHT_OFFSET + 4
            )
        ]
        self.assertTrue(all(record[position] == 0 for position in untouched))


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
                highest = max(
                    (slot for submesh in mesh.submeshes for row in submesh.bone_indices for slot in row),
                    default=-1,
                )
                # Slots run past the palette because only the primary decodes;
                # what matters is that the primary slot is always addressable.
                primaries = [
                    row[0]
                    for submesh in mesh.submeshes
                    for row in submesh.bone_indices
                    if row
                ]
                self.assertTrue(primaries)
                self.assertLess(max(primaries), len(palette), f"primary slot outran the palette (max slot {highest})")

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
