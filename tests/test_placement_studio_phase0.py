"""Unit tests for the Placement Studio Phase 0 harness.

These cover the operation vocabulary and its invariants on synthetic fixtures, so they run
without the 134 GB game install or the golden mod corpus. The corpus gates live behind the
`placement_studio` CLI (`phase0`), which needs both.
"""

from __future__ import annotations

import unittest

from tools.placement_studio import ops, paac


def _prefixed(name: str) -> bytes:
    """Encode a name the way `.paac` stores it: <len+1> <ascii> <NUL>."""

    return bytes([len(name) + 1]) + name.encode("ascii") + b"\x00"


class PaacLengthPrefixTests(unittest.TestCase):
    def test_indexes_only_length_prefixed_strings(self) -> None:
        data = b"\x00\x00" + _prefixed("Spine2_R_Socket") + b"RawSocket" + b"\x00"
        found = paac.index_sockets(data)
        self.assertEqual([s.value for s in found], ["Spine2_R_Socket"])

    def test_same_length_retarget_preserves_length_and_prefix(self) -> None:
        data = b"\x11\x22" + _prefixed("Spine2_R_Socket") + b"\x33"
        patched = paac.retarget(data, "Spine2_R_Socket", "Pelvis_R_Socket")
        self.assertEqual(len(patched), len(data))
        self.assertEqual([s.value for s in paac.index_sockets(patched)], ["Pelvis_R_Socket"])
        # The prefix byte is untouched, which is exactly why same-length swaps are safe.
        offset = paac.index_sockets(patched)[0].offset
        self.assertEqual(patched[offset - 1], len("Pelvis_R_Socket") + 1)

    def test_different_length_is_refused(self) -> None:
        data = _prefixed("Spine2_R_Socket")
        with self.assertRaises(paac.PaacPatchError):
            paac.retarget(data, "Spine2_R_Socket", "Pelvis_Socket")

    def test_coincidental_match_without_prefix_is_refused(self) -> None:
        # Same bytes, but no length prefix and no terminator: must not be patched.
        data = b"\xff\xffSpine2_R_Socket\xff"
        with self.assertRaises(paac.PaacPatchError):
            paac.retarget(data, "Spine2_R_Socket", "Pelvis_R_Socket")

    def test_diff_recovers_same_length_rename(self) -> None:
        before = b"\x01" + _prefixed("Spine2_B_SubWeapon_Socket")
        after = paac.retarget(before, "Spine2_B_SubWeapon_Socket", "Pelvis_L_SubWeapon_Socket")
        self.assertEqual(
            [(old, new) for old, new, _offset in paac.diff_socket_renames(before, after)],
            [("Spine2_B_SubWeapon_Socket", "Pelvis_L_SubWeapon_Socket")],
        )


_SOCKETS = (
    '<SocketBoneData>\r\n\t<SocketList Count="2">\r\n'
    '\t\t<Socket Name="A_Socket" Parent="Bip01" Rotation="0.000000 0.000000 0.000000 1.000000"'
    ' Translation="0.000000 0.000000 0.000000"/>\r\n'
    '\t\t<Socket Name="B_Socket" Parent="Bip02" Rotation="0.000000 0.000000 0.000000 1.000000"'
    ' Translation="1.000000 0.000000 0.000000"/>\r\n'
    "\t</SocketList>\r\n\t<StackEquipInfo Count=\"1\">\r\n"
    '\t\t<Socket Name="A_Socket"/>\r\n'
    "\t</StackEquipInfo>\r\n</SocketBoneData>\r\n"
)


class XmlSurgeryTests(unittest.TestCase):
    def test_attribute_edit_changes_only_the_target_bytes(self) -> None:
        updated = ops.apply_xml_attr(
            _SOCKETS, "Name", "B_Socket", "Translation",
            "1.000000 0.000000 0.000000", "1.000000 0.020000 0.000000",
            container="SocketList",
        )
        self.assertEqual(len(updated), len(_SOCKETS))
        self.assertIn('Translation="1.000000 0.020000 0.000000"', updated)
        self.assertEqual(updated.count("\r\n"), _SOCKETS.count("\r\n"))

    def test_container_scoping_ignores_reference_entries(self) -> None:
        # A_Socket appears in both SocketList and StackEquipInfo; only the definition
        # carries a transform, and edits must never land on the reference.
        spans = ops._element_spans(_SOCKETS, "Name", container="StackEquipInfo")
        self.assertEqual(sorted(spans), ["A_Socket"])
        with self.assertRaises(ops.DeriveError):
            ops.apply_xml_attr(
                _SOCKETS, "Name", "B_Socket", "Translation", "x", "y", container="StackEquipInfo"
            )

    def test_element_add_bumps_count_and_keeps_line_endings(self) -> None:
        raw = (
            '\r\n\t\t<Socket Name="C_Socket" Parent="Bip03"'
            ' Rotation="0.000000 0.000000 0.000000 1.000000"'
            ' Translation="0.000000 0.000000 0.000000"/>'
        )
        updated = ops.apply_xml_element_add(
            _SOCKETS, "Name", "C_Socket", raw, after="B_Socket", container="SocketList"
        )
        self.assertIn('<SocketList Count="3">', updated)
        self.assertIn('Name="C_Socket"', updated)
        self.assertNotIn("\n\n", updated.replace("\r\n", "\n").replace("\n\t", "\t"))

    def test_attribute_add_places_after_named_sibling(self) -> None:
        descriptor = '<Part PartName="X" InSocketBone="A" OutSocketBone="B"/>'
        updated = ops.apply_xml_attr_add(
            descriptor, "PartName", "X", "VehicleBagSocketBone", "Pelvis_L_Socket",
            after_attr="InSocketBone",
        )
        self.assertEqual(
            updated,
            '<Part PartName="X" InSocketBone="A" VehicleBagSocketBone="Pelvis_L_Socket"'
            ' OutSocketBone="B"/>',
        )


class CompositionTests(unittest.TestCase):
    def _attr_op(self, path: str, target: str, attr: str, old: str, new: str) -> ops.Operation:
        return ops.Operation("A", "xml_attr", path, target, {"attr": attr, "old": old, "new": new})

    def test_same_file_different_sockets_compose(self) -> None:
        left = ops.Plan("1H", (self._attr_op("f.xml", "A_Socket", "Translation", "0", "1"),))
        right = ops.Plan("2H", (self._attr_op("f.xml", "B_Socket", "Translation", "0", "2"),))
        merged = ops.merge([left, right])
        self.assertEqual(len(merged.operations), 2)

    def test_same_socket_different_attributes_compose(self) -> None:
        left = ops.Plan("1H", (self._attr_op("f.xml", "A_Socket", "Translation", "0", "1"),))
        right = ops.Plan("2H", (self._attr_op("f.xml", "A_Socket", "Rotation", "0", "1"),))
        self.assertEqual(len(ops.merge([left, right]).operations), 2)

    def test_same_field_different_values_conflicts(self) -> None:
        left = ops.Plan("1H", (self._attr_op("f.xml", "A_Socket", "Translation", "0", "1"),))
        right = ops.Plan("2H", (self._attr_op("f.xml", "A_Socket", "Translation", "0", "2"),))
        with self.assertRaises(ops.ConflictError):
            ops.merge([left, right])

    def test_descriptor_alias_shares_a_key_with_its_canonical_twin(self) -> None:
        canonical = "character/descriptors/characterdescription/phm_description_player_kliff.xml"
        alias = "character/phm_description_player_kliff.xml"
        self.assertEqual(ops.descriptor_alias_source(alias), canonical)
        left = ops.Plan("alias", (self._attr_op(alias, "P", "InSocketBone", "A", "B"),))
        right = ops.Plan("canon", (self._attr_op(canonical, "P", "InSocketBone", "A", "B"),))
        # Identical intent recorded on the two required-identical paths must dedupe,
        # not collide.
        self.assertEqual(len(ops.merge([left, right]).operations), 1)


class CanonicalComparisonTests(unittest.TestCase):
    def test_bom_and_trailing_whitespace_are_incidental(self) -> None:
        left = b"\xef\xbb\xbf<A/>\t\t\r\n<B/>\r\n"
        right = b"<A/>\r\n<B/>\r\n"
        self.assertEqual(ops.canonical_text(left), ops.canonical_text(right))

    def test_structural_view_ignores_comment_encoding_damage(self) -> None:
        path = "character/descriptors/characterdescription/phm_description_player_kliff.xml"
        clean = '<!-- 한글 --><Part PartName="X" InSocketBone="A"/>'.encode("utf-8")
        mojibake = (
            '<!-- íê¸ --><Part PartName="X" InSocketBone="A"/>'
        ).encode("utf-8")
        self.assertNotEqual(clean, mojibake)
        self.assertEqual(ops.structural_view(clean, path), ops.structural_view(mojibake, path))


if __name__ == "__main__":
    unittest.main()
