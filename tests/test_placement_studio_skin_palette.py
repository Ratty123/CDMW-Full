"""A `.pac` says which bone drives each vertex; it does not have to be guessed.

An influence slot indexes the file's own palette of `.pab` bone-name hashes, and that palette
resolves against the rig exactly. The studio used to infer the mapping instead — cluster the
vertices a slot drives, take the nearest bone — which held together only while the "body" was a
coat and a pair of trousers. Put a whole anatomy on the rig and it tears apart the moment a pose
moves: a hand has fifteen bones inside a few centimetres and the guess pairs fingers with the
wrong knuckles.
"""

from __future__ import annotations

import unittest

import numpy as np

from tools.placement_studio.skinning import _bone_column, _resolved_palette


class _Bone:
    def __init__(self, name_hash: int) -> None:
        self.name_hash = name_hash
        self.bind_matrix = (1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0,
                            0.0, 0.0, 1.0, 0.0, float(name_hash % 7), 0.0, 0.0, 1.0)


class _Rig:
    def __init__(self, hashes) -> None:
        self.bones = [_Bone(h) for h in hashes]


def _pac_with_palette(hashes, *, offset: int = 64) -> bytes:
    """A byte run shaped like a palette: a u16 count then that many u32 hashes."""

    import struct

    body = bytearray(b"\x00" * offset)
    body += struct.pack("<H", len(hashes))
    for value in hashes:
        body += struct.pack("<I", value)
    body += b"\x00" * 256
    return bytes(body)


_HASHES = tuple(0x10000 + i * 977 for i in range(24))


class PaletteResolutionTests(unittest.TestCase):
    def test_a_palette_is_read_off_the_file(self) -> None:
        palette = _resolved_palette(_pac_with_palette(_HASHES), _Rig(_HASHES))

        self.assertEqual(palette, tuple(range(len(_HASHES))))

    def test_slots_map_to_the_rig_s_own_ordering(self) -> None:
        """The file's order is its own; what matters is where each hash sits on this rig."""

        rig = _Rig(tuple(reversed(_HASHES)))
        palette = _resolved_palette(_pac_with_palette(_HASHES), rig)

        self.assertEqual(palette, tuple(range(len(_HASHES) - 1, -1, -1)))

    def test_a_palette_beyond_the_first_kilobytes_is_still_found(self) -> None:
        """Bodies keep it near the front; armour keeps it far enough in to have been missed."""

        deep = _pac_with_palette(_HASHES, offset=200_000)

        self.assertEqual(_resolved_palette(deep, _Rig(_HASHES)), tuple(range(len(_HASHES))))

    def test_a_palette_for_another_rig_is_refused(self) -> None:
        """Half-matching is not matching: a wrong bone is worse than falling back."""

        other = _Rig(tuple(h + 1 for h in _HASHES))

        self.assertEqual(_resolved_palette(_pac_with_palette(_HASHES), other), ())

    def test_no_rig_resolves_nothing(self) -> None:
        self.assertEqual(_resolved_palette(_pac_with_palette(_HASHES), _Rig(())), ())


class BoneColumnTests(unittest.TestCase):
    def test_an_exact_palette_reports_itself_as_exact(self) -> None:
        """The caller skips the drift guard on this, so the flag has to be true only here."""

        rest = np.zeros((3, 4))
        rig = _Rig(_HASHES)
        column, exact = _bone_column(
            _resolved_palette(_pac_with_palette(_HASHES), rig), [0, 5, 23], rest, rig
        )

        self.assertTrue(exact)
        self.assertEqual(column.tolist(), [0, 5, 23])

    def test_an_unresolvable_file_falls_back_and_says_so(self) -> None:
        """A slightly wrong body still beats no body — but it must be judged by drift."""

        rest = np.zeros((2, 4))
        rig = _Rig(_HASHES)
        column, exact = _bone_column(
            _resolved_palette(b"\x00" * 512, rig), [0, 1], rest, rig
        )

        self.assertFalse(exact)
        self.assertEqual(len(column), 2)

    def test_a_slot_outside_the_palette_never_indexes_off_the_end(self) -> None:
        rest = np.zeros((2, 4))
        rig = _Rig(_HASHES)
        column, _exact = _bone_column(
            _resolved_palette(_pac_with_palette(_HASHES), rig), [0, 99], rest, rig
        )

        self.assertEqual(column.tolist(), [0, 0])


if __name__ == "__main__":
    unittest.main()


class _Jointed:
    """A rig shaped like an arm: shoulder -> upper -> fore -> hand, plus an unrelated leg."""

    def __init__(self) -> None:
        self.bones = []
        for index, parent in enumerate((-1, 0, 1, 2, 0)):
            bone = _Bone(0x20000 + index)
            bone.parent_index = parent
            self.bones.append(bone)


class BlendAdjacencyTests(unittest.TestCase):
    """A vertex only blends between bones that meet at a joint.

    The second influence is a real bone, but ~20% of the pairs in a file are not adjacent ones.
    Blending towards a bone on the other side of the body stretches a triangle into a sliver —
    it showed up as fresh tearing across a coat's shoulder the first time both influences were
    used, and it looked worse than the rigid skin it replaced.
    """

    def setUp(self) -> None:
        from tools.placement_studio.skinning import _neighbouring

        self.neighbouring = _neighbouring
        self.rig = _Jointed()

    def _pairs(self, pairs):
        first = np.asarray([a for a, _b in pairs], dtype=np.int64)
        second = np.asarray([b for _a, b in pairs], dtype=np.int64)
        return self.neighbouring(self.rig, first, second).tolist()

    def test_a_bone_and_its_parent_blend(self) -> None:
        self.assertEqual(self._pairs([(2, 1), (1, 2)]), [True, True])

    def test_two_bones_on_the_same_parent_blend(self) -> None:
        """Left and right of a joint share it; the crease between them is the one to round."""

        self.assertEqual(self._pairs([(1, 4)]), [True])

    def test_bones_far_apart_and_unrelated_do_not(self) -> None:
        """The rejected pairs sit a median 0.40 m apart, none of them within 20 cm."""

        self.assertEqual(self._pairs([(3, 0)]), [False])

    def test_a_near_neighbour_blends_even_without_a_joint_between_them(self) -> None:
        """434 bones, most of them helpers packed around the ones an animator would name.

        Hierarchy alone kept 15.8% of the vertices the file offers a second bone for and threw
        away 32.2% whose median separation was 0.153 m — real joints, discarded, which is why
        joints still creased after both influences were read. Proximity widens an exact test;
        it never stands alone.
        """

        from tools.placement_studio.skinning import NEAR_BONE

        rig = _Jointed()
        rig.bones[3].bind_matrix = tuple(rig.bones[0].bind_matrix)

        self.assertTrue(self.neighbouring(rig, np.asarray([0]), np.asarray([3]))[0])
        self.assertGreater(NEAR_BONE, 0.15, "the helper bones it exists for sit at 0.15 m")

    def test_an_index_past_the_rig_never_raises(self) -> None:
        self.assertEqual(len(self._pairs([(99, 1), (1, 99)])), 2)

    def test_an_empty_rig_blends_nothing(self) -> None:
        class _Empty:
            bones = ()

        result = self.neighbouring(_Empty(), np.asarray([0]), np.asarray([1]))

        self.assertEqual(result.tolist(), [False])


class SecondInfluenceTests(unittest.TestCase):
    """Byte 24 is the second bone; bytes 28 and 29 are the two weights it shares."""

    def setUp(self) -> None:
        from tools.placement_studio.skinning import _second_influence

        self.second = _second_influence

    @staticmethod
    def _record(slot: int, first: int, other: int) -> bytes:
        rec = bytearray(b"\x00" * 40)
        rec[24] = slot
        rec[28] = first
        rec[29] = other
        return bytes(rec)

    def test_the_share_is_the_second_weight_out_of_the_whole(self) -> None:
        """Out of 255, not out of the two that were decoded.

        Renormalising against the primary hands the second bone the weight the two undecoded
        influences were carrying, which over-rotates the vertex: across six poses on both
        characters it raised the badly-stretched face count on five, worse than the rigid skin
        it replaced. Influences three and four sit near the primary, so leaving their weight
        there is the better approximation.
        """

        slot, share = self.second(self._record(7, 128, 64), 0)

        self.assertEqual(slot, 7)
        self.assertAlmostEqual(share, 64 / 255)

    def test_the_primary_keeps_the_undecoded_weight(self) -> None:
        _slot, share = self.second(self._record(7, 100, 50), 0)

        self.assertLess(share, 50 / 150, "renormalising would inflate the second bone")

    def test_no_second_weight_means_no_second_bone(self) -> None:
        self.assertEqual(self.second(self._record(7, 255, 0), 0), (0, 0.0))

    def test_slot_zero_is_treated_as_absent(self) -> None:
        """It is a real palette entry, but including it drops adjacency from 74% to 50%."""

        self.assertEqual(self.second(self._record(0, 192, 64), 0), (0, 0.0))

    def test_a_truncated_record_is_not_read_off_the_end(self) -> None:
        self.assertEqual(self.second(b"\x00" * 8, 0), (0, 0.0))
        self.assertEqual(self.second(self._record(7, 192, 64), -1), (0, 0.0))
