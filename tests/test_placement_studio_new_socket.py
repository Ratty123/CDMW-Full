"""Tests for creating a new attach point (Tier A2) and using it to aim an item.

Creating a socket definition is safe on its own — nothing references it, so nothing moves. The
value is in what it unblocks, and both are covered here:

* aiming an item somewhere vanilla never put it, by giving the placement a child socket of its
  own (a one-hand sword defines no back child socket at all);
* retargeting a draw animation, where the `.paac` length rule means only a name of *exactly* the
  right length will do, and some chart sockets have no same-length alternative in vanilla.

No game install: synthetic socket and descriptor bytes. Qt is needed for the dialog.
"""

from __future__ import annotations

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QDialogButtonBox  # noqa: E402

from tools.placement_studio.editing import (  # noqa: E402
    MAX_SOCKET_NAME,
    EditError,
    EditSession,
    socket_name_problem,
)
from tools.placement_studio.model import Quat, Socket, Vec3  # noqa: E402
from tools.placement_studio.new_socket import NewSocketDialog  # noqa: E402

_APP = QApplication.instance() or QApplication([])

_BODY_PATH = "character/descriptors/socketbonedata/1_pc/1_phm/phm_01.pab.sockets.xml"
_ITEM_PATH = (
    "character/descriptors/socketbonedata/1_pc/1_phm/weapon/1_onehandweapon/"
    "cd_phm_01_sword_0001_r.sockets.xml"
)

_BODY = (
    b"\xef\xbb\xbf<SocketBoneData>\r\n\t<SocketList Count=\"2\">\r\n"
    b'\t\t<Socket Name="Pelvis_L_Socket" Parent="B_WeaponIn_R_00"'
    b' Rotation="0.000000 0.000000 0.000000 1.000000"'
    b' Translation="0.000000 0.000000 0.150000"/>\r\n'
    b'\t\t<Socket Name="Spine2_B_MainWeapon_Socket" Parent="Bip_Spine2"'
    b' Rotation="0.000000 0.000000 0.000000 1.000000"'
    b' Translation="0.000000 0.100000 0.000000"/>\r\n'
    b"\t</SocketList>\r\n</SocketBoneData>\r\n"
)

# Real child sockets are parented to a bone on the *item* (`B_Weapon_0001`), which is not part of
# the character rig at all — the reason the parent field has to accept a name not in the rig list.
_ITEM = (
    b"\xef\xbb\xbf<SocketBoneData>\r\n\t<SocketList Count=\"2\">\r\n"
    b'\t\t<Socket Name="Basic_ChildSocket" Parent="B_Weapon_0001"'
    b' Rotation="0.000000 0.707107 0.000000 0.707107"'
    b' Translation="0.000000 0.000000 -0.030000"/>\r\n'
    b'\t\t<Socket Name="Pelvis_L_ChildSocket" Parent="B_Weapon_0001"'
    b' Rotation="0.000000 0.000000 0.000000 1.000000"'
    b' Translation="0.000000 0.000000 0.000000"/>\r\n'
    b"\t</SocketList>\r\n</SocketBoneData>\r\n"
)


def _session() -> EditSession:
    return EditSession({_BODY_PATH: _BODY, _ITEM_PATH: _ITEM})


def _sockets_by_file():
    session = _session()
    return {
        _BODY_PATH: dict(session._documents[_BODY_PATH].socket_map()),
        _ITEM_PATH: dict(session._documents[_ITEM_PATH].socket_map()),
    }


def _dialog(**overrides) -> NewSocketDialog:
    kwargs = dict(
        files=[("Kliff body sockets", _BODY_PATH), ("sword child sockets", _ITEM_PATH)],
        sockets_by_file=_sockets_by_file(),
        bones=["Bip_Spine2", "B_WeaponIn_R_00", "Bip01"],
    )
    kwargs.update(overrides)
    return NewSocketDialog(None, **kwargs)


class SocketNameTests(unittest.TestCase):
    def test_a_vanilla_style_name_is_accepted(self) -> None:
        self.assertEqual(socket_name_problem("Spine2_B_Back_ChildSocket"), "")

    def test_an_empty_name_is_refused(self) -> None:
        self.assertIn("name", socket_name_problem(""))

    def test_characters_outside_the_safe_set_are_refused(self) -> None:
        """The safe set is the intersection of an XML attribute and ASCII `.paac` bytes."""

        for name in ("has space", 'quote"x', "Ünicode", "semi;colon", "tab\tname"):
            self.assertNotEqual(socket_name_problem(name), "", name)

    def test_a_name_too_long_for_the_chart_prefix_is_refused(self) -> None:
        self.assertEqual(socket_name_problem("A" * MAX_SOCKET_NAME), "")
        self.assertIn("too long", socket_name_problem("A" * (MAX_SOCKET_NAME + 1)))


class AddSocketTests(unittest.TestCase):
    def test_creating_a_socket_is_one_tier_a2_operation(self) -> None:
        session = _session()
        session.add_socket(_ITEM_PATH, Socket(name="Spine2_B_Back_ChildSocket"))
        self.assertEqual(session.to_plan().tier_counts(), {"A2": 1})
        self.assertEqual(session.modified_paths(), [_ITEM_PATH])

    def test_the_new_socket_becomes_defined_and_routable(self) -> None:
        session = _session()
        self.assertNotIn("Spine2_B_Back_ChildSocket", session.defined_sockets())
        session.add_socket(_ITEM_PATH, Socket(name="Spine2_B_Back_ChildSocket"))
        self.assertIn("Spine2_B_Back_ChildSocket", session.defined_sockets())

    def test_the_socket_list_count_is_bumped(self) -> None:
        session = _session()
        session.add_socket(_ITEM_PATH, Socket(name="Spine2_B_Back_ChildSocket"))
        self.assertIn(b'Count="3"', session.preview()[_ITEM_PATH])

    def test_a_bad_name_is_refused_at_the_domain_level(self) -> None:
        """Not only in the dialog — the file is what a chart would have to carry."""

        for name in ("", "has space", 'quote"x'):
            with self.assertRaises(EditError):
                _session().add_socket(_ITEM_PATH, Socket(name=name))

    def test_a_duplicate_name_is_refused(self) -> None:
        with self.assertRaises(EditError):
            _session().add_socket(_ITEM_PATH, Socket(name="Basic_ChildSocket"))

    def test_a_descriptor_file_is_not_a_socket_file(self) -> None:
        with self.assertRaises(EditError):
            _session().add_socket("nope.xml", Socket(name="Whatever_Socket"))

    def test_creating_then_undoing_restores_the_original_bytes(self) -> None:
        session = _session()
        session.add_socket(_ITEM_PATH, Socket(name="Spine2_B_Back_ChildSocket"))
        self.assertTrue(session.undo())
        self.assertEqual(session.modified_paths(), [])

    def test_the_copied_transform_is_written_out(self) -> None:
        session = _session()
        session.add_socket(
            _ITEM_PATH,
            Socket(
                name="Spine2_B_Back_ChildSocket",
                parent_bone="B_Weapon_0001",
                rotation=Quat(0.0, 0.707107, 0.0, 0.707107),
                translation=Vec3(0.0, 0.0, -0.03),
            ),
        )
        payload = session.preview()[_ITEM_PATH]
        self.assertIn(b'Name="Spine2_B_Back_ChildSocket"', payload)
        self.assertIn(b'Parent="B_Weapon_0001"', payload)
        self.assertIn(b'Translation="0.000000 0.000000 -0.030000"', payload)


class NewSocketDialogTests(unittest.TestCase):
    def _ok(self, dialog) -> bool:
        return dialog._buttons.button(QDialogButtonBox.Ok).isEnabled()

    def test_create_is_disabled_until_the_name_is_valid(self) -> None:
        dialog = _dialog()
        self.assertFalse(self._ok(dialog))
        dialog._name_edit.setText("Spine2_B_Back_ChildSocket")
        self.assertTrue(self._ok(dialog))

    def test_a_duplicate_name_in_the_chosen_file_is_refused(self) -> None:
        dialog = _dialog(preferred_file=_ITEM_PATH)
        dialog._name_edit.setText("Basic_ChildSocket")
        self.assertFalse(self._ok(dialog))
        self.assertIn("already defined", dialog._problem.text())

    def test_a_name_used_in_another_file_is_allowed(self) -> None:
        """Sockets are scoped per file; the same name in a different file is not a clash."""

        dialog = _dialog(preferred_file=_BODY_PATH)
        dialog._name_edit.setText("Basic_ChildSocket")
        self.assertTrue(self._ok(dialog))

    def test_the_length_readout_tracks_a_retarget_target(self) -> None:
        dialog = _dialog(target_length=25, target_length_reason="because")
        dialog._name_edit.setText("Spine2_B_Back_ChildSocket")  # 25
        self.assertIn("matches", dialog._length_label.text())
        dialog._name_edit.setText("Too_Short")
        self.assertIn("does not match", dialog._length_label.text())

    def test_the_length_readout_is_plain_without_a_target(self) -> None:
        dialog = _dialog()
        dialog._name_edit.setText("Anything")
        self.assertIn("8 of", dialog._length_label.text())
        self.assertNotIn("match", dialog._length_label.text())

    def test_copying_a_socket_takes_its_transform_and_its_parent(self) -> None:
        """A transform without its frame of reference lands nowhere near the source."""

        dialog = _dialog(preferred_file=_ITEM_PATH, copy_from="Basic_ChildSocket")
        dialog._name_edit.setText("Spine2_B_Back_ChildSocket")
        created = dialog.socket()
        self.assertEqual(created.parent_bone, "B_Weapon_0001")
        self.assertAlmostEqual(created.translation.z, -0.03, places=6)
        self.assertAlmostEqual(created.rotation.y, 0.707107, places=6)

    def test_identity_is_offered_and_produces_no_transform(self) -> None:
        dialog = _dialog(preferred_file=_ITEM_PATH)
        dialog._copy_box.setCurrentIndex(0)  # "(identity ...)"
        dialog._name_edit.setText("Fresh_Socket")
        created = dialog.socket()
        self.assertEqual(created.translation, Vec3())
        self.assertEqual(created.rotation, Quat())

    def test_the_item_file_offers_its_own_bone_first(self) -> None:
        """`B_Weapon_0001` is on the item and absent from the character rig."""

        dialog = _dialog(preferred_file=_ITEM_PATH)
        self.assertEqual(dialog._bone_box.itemText(0), "B_Weapon_0001")

    def test_switching_file_reoffers_that_file_s_sockets(self) -> None:
        dialog = _dialog(preferred_file=_BODY_PATH)
        body_options = {dialog._copy_box.itemData(i) for i in range(dialog._copy_box.count())}
        self.assertIn("Pelvis_L_Socket", body_options)
        self.assertNotIn("Basic_ChildSocket", body_options)

        dialog._file_box.setCurrentIndex(dialog._file_box.findData(_ITEM_PATH))
        item_options = {dialog._copy_box.itemData(i) for i in range(dialog._copy_box.count())}
        self.assertIn("Basic_ChildSocket", item_options)
        self.assertNotIn("Pelvis_L_Socket", item_options)

    def test_the_dialog_reports_the_file_it_will_write_to(self) -> None:
        dialog = _dialog(preferred_file=_ITEM_PATH)
        self.assertEqual(dialog.game_path, _ITEM_PATH)
