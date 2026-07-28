"""Tests for re-routing from the viewport and for the part dropdown.

`EditSession.set_route` is covered by the Phase 3 tests; what is new here is the *window wiring*
— that a click means "select" in every mode but `route`, that the guards refuse the cases which
would produce a broken mod, and that the dropdown reports where each row currently points.

The window mixins are exercised directly against a real `EditSession` built from synthetic
bytes, so these need no game install and no pinned baseline. Qt is needed only for the combo box.
"""

from __future__ import annotations

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEvent, QPointF, Qt  # noqa: E402
from PySide6.QtGui import QMouseEvent  # noqa: E402
from PySide6.QtWidgets import QApplication, QComboBox  # noqa: E402

from tools.placement_studio.editing import EditSession  # noqa: E402
from tools.placement_studio.model import (  # noqa: E402
    DescriptorPart,
    PlacementBinding,
    Socket,
    Vec3,
)
from tools.placement_studio.session import PlacementSession  # noqa: E402
from tools.placement_studio.skeleton import BoneHierarchy, BoneNode  # noqa: E402
from tools.placement_studio.viewport import SkeletonViewport  # noqa: E402
from tools.placement_studio.window import PlacementStudioWindow  # noqa: E402
from tools.placement_studio.window_editing import EditPanelMixin  # noqa: E402

_APP = QApplication.instance() or QApplication([])

_BODY_PATH = "character/descriptors/socketbonedata/1_pc/1_phm/phm_01.pab.sockets.xml"
_DESC_PATH = "character/descriptors/characterdescription/phm_description_player_kliff.xml"

_WEAPON_PATH = (
    "character/descriptors/socketbonedata/1_pc/1_phm/weapon/1_onehandweapon/"
    "cd_phm_01_sword_0001_r.sockets.xml"
)

_SOCKETS = (
    b"\xef\xbb\xbf<SocketBoneData>\r\n\t<SocketList Count=\"4\">\r\n"
    b'\t\t<Socket Name="Pelvis_L_Socket" Parent="B_WeaponIn_R_00"'
    b' Rotation="0.000000 0.000000 0.000000 1.000000"'
    b' Translation="0.000000 0.000000 0.150000"/>\r\n'
    b'\t\t<Socket Name="Pelvis_R_Socket" Parent="B_WeaponIn_L_00"'
    b' Rotation="0.000000 0.000000 0.000000 1.000000"'
    b' Translation="0.000000 0.000000 -0.150000"/>\r\n'
    b'\t\t<Socket Name="Spine2_B_MainWeapon_Socket" Parent="Bip_Spine2"'
    b' Rotation="0.000000 0.000000 0.000000 1.000000"'
    b' Translation="0.000000 0.100000 0.000000"/>\r\n'
    b'\t\t<Socket Name="RHand_Socket" Parent="Bip_Weapon_R"'
    b' Rotation="0.000000 0.000000 0.000000 1.000000"'
    b' Translation="0.000000 0.000000 0.000000"/>\r\n'
    b"\t</SocketList>\r\n</SocketBoneData>\r\n"
)

# The item's own child sockets. These live in the weapon file, not the body file, which is why a
# route to a child socket can only be validated with both files loaded.
_WEAPON_SOCKETS = (
    b"\xef\xbb\xbf<SocketBoneData>\r\n\t<SocketList Count=\"3\">\r\n"
    b'\t\t<Socket Name="Pelvis_L_ChildSocket" Parent=""'
    b' Rotation="0.000000 0.000000 0.000000 1.000000"'
    b' Translation="0.000000 0.000000 0.000000"/>\r\n'
    b'\t\t<Socket Name="Pelvis_R_ChildSocket" Parent=""'
    b' Rotation="0.000000 0.000000 0.000000 1.000000"'
    b' Translation="0.000000 0.000000 0.000000"/>\r\n'
    b'\t\t<Socket Name="Basic_ChildSocket" Parent=""'
    b' Rotation="0.000000 0.707107 0.000000 0.707107"'
    b' Translation="0.000000 0.000000 0.000000"/>\r\n'
    b"\t</SocketList>\r\n</SocketBoneData>\r\n"
)

_DESCRIPTOR = (
    b"<CharacterDescription>\r\n"
    b'\t<Part PartName="CD_MainWeapon_Sword_R" InSocketBone="Pelvis_L_Socket"'
    b' OutSocketBone="RHand_Socket" InChildSocketBone="Pelvis_L_ChildSocket"'
    b' OutChildSocketBone="Basic_ChildSocket"/>\r\n'
    b"</CharacterDescription>\r\n"
)


def _part(**overrides) -> DescriptorPart:
    values = dict(
        part_name="CD_MainWeapon_Sword_R",
        in_socket="Pelvis_L_Socket",
        out_socket="RHand_Socket",
        in_child_socket="Pelvis_L_ChildSocket",
        out_child_socket="Basic_ChildSocket",
        source_file=_DESC_PATH,
    )
    values.update(overrides)
    return DescriptorPart(**values)


def _mouse(kind, x: float, y: float, button=Qt.LeftButton, buttons=Qt.LeftButton) -> QMouseEvent:
    """Build a mouse event via the overload that takes a global position.

    The shorter (type, pos, button, buttons, modifiers) form is deprecated in Qt 6.
    """

    point = QPointF(x, y)
    return QMouseEvent(kind, point, point, button, buttons, Qt.NoModifier)


class _StubWeapon:
    def __init__(self, socket_names) -> None:
        self.sockets = {name: object() for name in socket_names}
        self.weapon_id = "cd_phm_01_sword_0001_r"


class _StubSession:
    """Only what the routing and dropdown code actually reads off a session."""

    conventional_child_socket = PlacementSession.conventional_child_socket

    def __init__(self, parts, weapon_sockets=("Pelvis_L_ChildSocket",)) -> None:
        self._bindings = [PlacementBinding(part=part) for part in parts]
        self.model = "1_phm"
        self.weapon = _StubWeapon(weapon_sockets)

    def bindings(self):
        return list(self._bindings)


class _StubBox:
    """A combo box stand-in for the role selector."""

    def __init__(self, value: str) -> None:
        self._value = value

    def currentData(self):
        return self._value


class _StubStatusBar:
    def __init__(self) -> None:
        self.message = ""

    def showMessage(self, text: str) -> None:
        self.message = text


class _RouteHarness(EditPanelMixin):
    """The edit mixin over stubs, so routing can be driven without a game install."""

    def __init__(
        self,
        parts=None,
        mode: str = "route",
        role: str = "stowed",
        weapon_sockets=("Pelvis_L_ChildSocket",),
    ) -> None:
        self._session = _StubSession(parts or [_part()], weapon_sockets=weapon_sockets)
        self._edits = EditSession(
            {
                _BODY_PATH: _SOCKETS,
                _WEAPON_PATH: _WEAPON_SOCKETS,
                _DESC_PATH: _DESCRIPTOR,
            }
        )
        self._mode_box = _StubBox(mode)
        self._mesh_role_box = _StubBox(role)
        self._selected_part = "CD_MainWeapon_Sword_R"
        self._status = _StubStatusBar()
        self.selected_sockets = []
        self.edits_applied = 0
        self.parts_repopulated = 0

    def statusBar(self):
        return self._status

    def _select_socket(self, socket_name: str) -> None:
        self.selected_sockets.append(socket_name)

    def _after_edit(self) -> None:
        self.edits_applied += 1

    def _populate_parts(self) -> None:
        self.parts_repopulated += 1


class RouteDispatchTests(unittest.TestCase):
    def test_a_click_routes_in_route_mode(self) -> None:
        harness = _RouteHarness(mode="route")
        harness._on_socket_clicked("Spine2_B_MainWeapon_Socket")
        self.assertEqual(harness.selected_sockets, [])
        self.assertEqual(harness.edits_applied, 1)
        socket = harness._edits.socket(_BODY_PATH, "Pelvis_L_Socket")
        self.assertIsNotNone(socket)  # the socket definition itself is untouched

    def test_a_click_only_selects_in_every_other_mode(self) -> None:
        for mode in ("off", "move", "rotate", "tilt"):
            harness = _RouteHarness(mode=mode)
            harness._on_socket_clicked("Spine2_B_MainWeapon_Socket")
            self.assertEqual(harness.selected_sockets, ["Spine2_B_MainWeapon_Socket"], mode)
            self.assertEqual(harness.edits_applied, 0, mode)

    def test_routing_is_one_tier_b_operation_on_the_descriptor_only(self) -> None:
        """The whole safety claim for this gesture: routing changes routing, nothing else."""

        harness = _RouteHarness()
        harness._on_socket_clicked("Spine2_B_MainWeapon_Socket")
        plan = harness._edits.to_plan()
        self.assertEqual(plan.tier_counts(), {"B": 1})
        self.assertEqual(harness._edits.modified_paths(), [_DESC_PATH])
        self.assertNotIn(_BODY_PATH, harness._edits.modified_paths())

    def test_stowed_and_held_write_different_attributes(self) -> None:
        stowed = _RouteHarness(role="stowed")
        stowed._on_socket_clicked("Spine2_B_MainWeapon_Socket")
        self.assertIn(b'InSocketBone="Spine2_B_MainWeapon_Socket"', stowed._edits.preview()[_DESC_PATH])
        self.assertIn(b'OutSocketBone="RHand_Socket"', stowed._edits.preview()[_DESC_PATH])

        held = _RouteHarness(role="held")
        held._on_socket_clicked("Spine2_B_MainWeapon_Socket")
        self.assertIn(b'OutSocketBone="Spine2_B_MainWeapon_Socket"', held._edits.preview()[_DESC_PATH])
        self.assertIn(b'InSocketBone="Pelvis_L_Socket"', held._edits.preview()[_DESC_PATH])

    def test_the_dropdown_is_relabelled_after_a_route(self) -> None:
        harness = _RouteHarness()
        harness._on_socket_clicked("Spine2_B_MainWeapon_Socket")
        self.assertEqual(harness.parts_repopulated, 1)

    def test_the_status_line_names_both_ends_of_the_move(self) -> None:
        harness = _RouteHarness()
        harness._on_socket_clicked("Spine2_B_MainWeapon_Socket")
        message = harness._status.message
        self.assertIn("Pelvis_L_Socket", message)
        self.assertIn("Spine2_B_MainWeapon_Socket", message)


class RouteGuardTests(unittest.TestCase):
    """Each guard covers a way to produce a mod that misbehaves in game."""

    def test_an_undefined_socket_is_refused(self) -> None:
        harness = _RouteHarness()
        harness._on_socket_clicked("Not_A_Real_Socket")
        self.assertEqual(harness._edits.modified_paths(), [])
        self.assertIn("not defined", harness._status.message)

    def test_routing_with_no_part_selected_does_nothing(self) -> None:
        harness = _RouteHarness()
        harness._selected_part = ""
        harness._on_socket_clicked("Spine2_B_MainWeapon_Socket")
        self.assertEqual(harness._edits.modified_paths(), [])
        self.assertIn("Select a part first", harness._status.message)

    def test_routing_to_the_current_socket_records_nothing(self) -> None:
        """Re-clicking the socket a part already uses must not add a no-op operation."""

        harness = _RouteHarness()
        harness._on_socket_clicked("Pelvis_L_Socket")
        self.assertEqual(harness._edits.modified_paths(), [])
        self.assertEqual(harness.edits_applied, 0)
        self.assertIn("already uses", harness._status.message)

    def test_a_row_with_no_descriptor_file_is_refused(self) -> None:
        harness = _RouteHarness(parts=[_part(source_file="")])
        harness._on_socket_clicked("Spine2_B_MainWeapon_Socket")
        self.assertEqual(harness._edits.modified_paths(), [])
        self.assertIn("No descriptor row", harness._status.message)

    def test_an_unknown_part_name_is_refused(self) -> None:
        harness = _RouteHarness()
        harness._selected_part = "CD_MainWeapon_Nonexistent"
        harness._on_socket_clicked("Spine2_B_MainWeapon_Socket")
        self.assertEqual(harness._edits.modified_paths(), [])
        self.assertIn("No descriptor row", harness._status.message)


class _PartsHarness:
    """`_populate_parts` over a real combo box and a stub session."""

    _populate_parts = PlacementStudioWindow._populate_parts
    _sync_part_box = PlacementStudioWindow._sync_part_box
    # Picking the row that matches the weapon's hand is part of populating the list, so the
    # harness has to carry it too.
    _default_part_name = PlacementStudioWindow._default_part_name
    _part_suits_weapon = PlacementStudioWindow._part_suits_weapon
    _weapon_hand = PlacementStudioWindow._weapon_hand

    def __init__(self, parts) -> None:
        self._session = _StubSession(parts)
        self._part_box = QComboBox()
        self._weapon_box = QComboBox()
        self._bindings = list(self._session.bindings())
        self._selected_part = ""


class PartDropdownTests(unittest.TestCase):
    def test_every_descriptor_row_is_listed(self) -> None:
        harness = _PartsHarness([_part(), _part(part_name="CD_Tool_Torch")])
        harness._populate_parts()
        self.assertEqual(harness._part_box.count(), 2)

    def test_the_label_carries_the_current_route(self) -> None:
        harness = _PartsHarness([_part()])
        harness._populate_parts()
        label = harness._part_box.itemText(0)
        # Rows are named the way a person would say them; the game's own identifiers are one
        # hover away, because a modder comparing against a chart still needs them verbatim.
        self.assertIn("Sword", label)
        self.assertIn("Left hip", label)
        self.assertIn("Right hand", label)
        from PySide6.QtCore import Qt as _Qt

        hover = harness._part_box.itemData(0, _Qt.ToolTipRole) or ""
        self.assertIn("CD_MainWeapon_Sword_R", hover)
        self.assertIn("RHand_Socket", hover)

    def test_weapon_rows_sort_ahead_of_uncategorised_rows(self) -> None:
        harness = _PartsHarness(
            [_part(part_name="AAA_Something_Else"), _part(part_name="CD_MainWeapon_Axe_R")]
        )
        harness._populate_parts()
        self.assertEqual(harness._part_box.itemData(0), "CD_MainWeapon_Axe_R")
        self.assertEqual(harness._part_box.itemData(1), "AAA_Something_Else")

    def test_a_single_route_is_not_printed_twice(self) -> None:
        """When stowed and held share a socket the label must not repeat it."""

        harness = _PartsHarness([_part(in_socket="RHand_Socket", out_socket="RHand_Socket")])
        harness._populate_parts()
        self.assertEqual(harness._part_box.itemText(0).count("Right hand"), 1)

    def test_an_unrouted_row_reads_as_none_rather_than_blank(self) -> None:
        harness = _PartsHarness([_part(in_socket="", out_socket="")])
        harness._populate_parts()
        self.assertIn("(nowhere)", harness._part_box.itemText(0))

    def test_the_selection_survives_a_repopulate(self) -> None:
        parts = [_part(), _part(part_name="CD_MainWeapon_Axe_R")]
        harness = _PartsHarness(parts)
        harness._populate_parts()
        harness._part_box.setCurrentIndex(harness._part_box.findData("CD_MainWeapon_Axe_R"))
        harness._populate_parts()
        self.assertEqual(harness._part_box.currentData(), "CD_MainWeapon_Axe_R")

    def test_the_sword_row_is_the_default_pick(self) -> None:
        harness = _PartsHarness([_part(part_name="CD_MainWeapon_Axe_R"), _part()])
        harness._populate_parts()
        self.assertEqual(harness._selected_part, "CD_MainWeapon_Sword_R")

    def test_syncing_an_unknown_part_leaves_the_box_alone(self) -> None:
        harness = _PartsHarness([_part()])
        harness._populate_parts()
        harness._sync_part_box("CD_MainWeapon_Nonexistent")
        self.assertEqual(harness._part_box.currentData(), "CD_MainWeapon_Sword_R")


class RouteModeViewportTests(unittest.TestCase):
    """Route mode must be a pure pick: no drag, no gizmo, no weapon click."""

    def _viewport(self) -> SkeletonViewport:
        """A scene with one selected socket — so an absent gizmo means something."""

        identity = (1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 1.0, 0.0, 1.0)
        hierarchy = BoneHierarchy(
            [BoneNode(0, "Root", -1, identity, Vec3(0.0, 1.0, 0.0))], "test"
        )
        view = SkeletonViewport()
        view.resize(800, 600)
        placed = hierarchy.place(Socket(name="Pelvis_L_Socket", parent_bone="Root"))
        view.set_scene(hierarchy, [placed], {"Pelvis_L_Socket": 1})
        view.set_selected("Pelvis_L_Socket")
        return view

    def test_route_is_an_accepted_mode(self) -> None:
        view = self._viewport()
        view.set_edit_mode("route")
        self.assertEqual(view.edit_mode, "route")

    def test_rotate_mode_really_does_cache_rings_in_this_scene(self) -> None:
        """Guards the two tests below: without this, an empty `_rings` proves nothing."""

        view = self._viewport()
        view.set_edit_mode("rotate")
        view.grab()
        self.assertEqual(sorted(view._rings), ["X", "Y", "Z"])

    def test_route_mode_paints_no_gizmo(self) -> None:
        view = self._viewport()
        view.set_edit_mode("rotate")
        view.grab()
        view.set_edit_mode("route")
        view.grab()
        self.assertEqual(view._rings, {})

    def test_route_mode_grabs_nothing_to_drag(self) -> None:
        """A drag in route mode must not nudge the socket the user is aiming at."""

        view = self._viewport()
        view.set_edit_mode("route")
        moved: list = []
        view.socket_dragged.connect(lambda *args: moved.append(args))
        view.mousePressEvent(_mouse(QEvent.MouseButtonPress, 400.0, 300.0))
        self.assertEqual(view._dragging_socket, "")
        view.mouseMoveEvent(
            _mouse(QEvent.MouseMove, 460.0, 340.0, button=Qt.NoButton)
        )
        self.assertEqual(moved, [])

    def test_clicking_the_weapon_does_not_hijack_a_route_click(self) -> None:
        view = self._viewport()
        view.set_edit_mode("route")
        view._weapon_screen = [(380.0, 280.0, 430.0, 280.0, 405.0, 330.0)]
        clicks: list = []
        view.weapon_clicked.connect(lambda: clicks.append(True))
        view.mousePressEvent(_mouse(QEvent.MouseButtonPress, 405.0, 300.0))
        self.assertEqual(clicks, [])


class ChildSocketPairingTests(unittest.TestCase):
    """Body and child sockets are matched pairs; the pairing is read off vanilla, not guessed."""

    def _session(self) -> _StubSession:
        return _StubSession(
            [
                _part(part_name="A", in_socket="Pelvis_L_Socket",
                      in_child_socket="Pelvis_L_ChildSocket"),
                _part(part_name="B", in_socket="Pelvis_R_Socket",
                      in_child_socket="Pelvis_R_ChildSocket"),
                # The back sockets pair with a *SubWeapon* child: proof the names follow no
                # single rule, which is why this is derived from the data.
                _part(part_name="C", in_socket="Spine2_B_MainWeapon_Socket",
                      in_child_socket="Spine2_B_SubWeapon_ChildSocket"),
            ]
        )

    def test_the_pairing_comes_from_the_descriptor_rows(self) -> None:
        session = self._session()
        self.assertEqual(
            session.conventional_child_socket("Pelvis_R_Socket"), "Pelvis_R_ChildSocket"
        )

    def test_a_pairing_that_defies_the_naming_pattern_is_still_found(self) -> None:
        session = self._session()
        self.assertEqual(
            session.conventional_child_socket("Spine2_B_MainWeapon_Socket"),
            "Spine2_B_SubWeapon_ChildSocket",
        )

    def test_an_unpaired_socket_yields_nothing(self) -> None:
        self.assertEqual(self._session().conventional_child_socket("Nobody_Uses_This"), "")

    def test_the_stowed_and_held_pairings_are_read_separately(self) -> None:
        session = _StubSession(
            [_part(in_socket="Pelvis_L_Socket", in_child_socket="Pelvis_L_ChildSocket",
                   out_socket="RHand_Socket", out_child_socket="Basic_ChildSocket")]
        )
        self.assertEqual(
            session.conventional_child_socket("Pelvis_L_Socket"), "Pelvis_L_ChildSocket"
        )
        self.assertEqual(
            session.conventional_child_socket("RHand_Socket", held=True), "Basic_ChildSocket"
        )
        # The stowed lookup must not see the held pairing.
        self.assertEqual(session.conventional_child_socket("RHand_Socket"), "")

    def test_the_most_used_pairing_wins_a_disagreement(self) -> None:
        session = _StubSession(
            [
                _part(part_name="A", in_socket="S", in_child_socket="Common_ChildSocket"),
                _part(part_name="B", in_socket="S", in_child_socket="Common_ChildSocket"),
                _part(part_name="C", in_socket="S", in_child_socket="Odd_ChildSocket"),
            ]
        )
        self.assertEqual(session.conventional_child_socket("S"), "Common_ChildSocket")


class ChildSocketFollowTests(unittest.TestCase):
    """Re-routing must carry the orientation with it, or say plainly that it could not."""

    def _parts(self):
        return [
            _part(),  # Sword_R: Pelvis_L_Socket / Pelvis_L_ChildSocket
            _part(part_name="CD_MainWeapon_Axe_R", in_socket="Pelvis_R_Socket",
                  in_child_socket="Pelvis_R_ChildSocket"),
        ]

    def test_the_child_socket_follows_when_the_item_defines_it(self) -> None:
        harness = _RouteHarness(
            parts=self._parts(),
            weapon_sockets=("Pelvis_L_ChildSocket", "Pelvis_R_ChildSocket"),
        )
        harness._on_socket_clicked("Pelvis_R_Socket")
        payload = harness._edits.preview()[_DESC_PATH]
        self.assertIn(b'InSocketBone="Pelvis_R_Socket"', payload)
        self.assertIn(b'InChildSocketBone="Pelvis_R_ChildSocket"', payload)
        self.assertEqual(harness._edits.to_plan().tier_counts(), {"B": 2})
        self.assertIn("orientation", harness._status.message)

    def test_an_item_with_no_borrowable_child_socket_is_told_to_rotate(self) -> None:
        """When nothing anywhere defines the angle, say so rather than invent one.

        Where another item *does* define it the angle is borrowed instead — covered in
        `test_placement_studio_orientation`.
        """

        harness = _RouteHarness(
            parts=self._parts() + [
                _part(part_name="CD_TwoHandWeapon_Axe", in_socket="Spine2_B_MainWeapon_Socket",
                      in_child_socket="Spine2_B_SubWeapon_ChildSocket"),
            ],
            weapon_sockets=("Pelvis_L_ChildSocket",),
        )
        harness._on_socket_clicked("Spine2_B_MainWeapon_Socket")
        payload = harness._edits.preview()[_DESC_PATH]
        # The body route still lands; only the orientation is left alone.
        self.assertIn(b'InSocketBone="Spine2_B_MainWeapon_Socket"', payload)
        self.assertIn(b'InChildSocketBone="Pelvis_L_ChildSocket"', payload)
        self.assertEqual(harness._edits.to_plan().tier_counts(), {"B": 1})
        self.assertIn("Rotate or Tilt", harness._status.message)

    def test_a_target_no_row_pairs_still_gets_the_conventional_angle(self) -> None:
        """Silence here is what left a back-slung sword hanging upside down.

        The descriptor rows resolve against the selected weapon, so with a one-hand sword in
        hand nothing in view pairs `Spine2_B_MainWeapon_Socket` with a child socket. The
        lookup came back empty, the orientation was left on the hip's identity rotation, and
        the move reported success. There is a known pairing for that socket, so it is used.
        """

        harness = _RouteHarness(parts=self._parts())
        harness._on_socket_clicked("Spine2_B_MainWeapon_Socket")
        self.assertEqual(harness._edits.to_plan().tier_counts(), {"B": 1})
        # The pairing is now known even though no row in view mentions it...
        self.assertIn("Spine2_B_SubWeapon_ChildSocket", harness._status.message)
        # ...and when it cannot be applied, the user is told rather than left to notice.
        self.assertIn("Rotate or Tilt", harness._status.message)

    def test_an_already_correct_child_socket_adds_no_operation(self) -> None:
        harness = _RouteHarness(
            parts=[
                _part(),
                _part(part_name="CD_MainWeapon_Other", in_socket="Spine2_B_MainWeapon_Socket",
                      in_child_socket="Pelvis_L_ChildSocket"),
            ],
            weapon_sockets=("Pelvis_L_ChildSocket",),
        )
        harness._on_socket_clicked("Spine2_B_MainWeapon_Socket")
        self.assertEqual(harness._edits.to_plan().tier_counts(), {"B": 1})


class UseAsOrientationTests(unittest.TestCase):
    """A socket the user just created has no vanilla pairing, so aiming with it is explicit."""

    def _harness(self, selected: str = "Basic_ChildSocket") -> _RouteHarness:
        harness = _RouteHarness(
            weapon_sockets=("Pelvis_L_ChildSocket", "Basic_ChildSocket", "New_Back_ChildSocket")
        )
        harness._selected_socket = selected
        return harness

    def test_it_routes_the_child_socket_not_the_body_socket(self) -> None:
        harness = self._harness("New_Back_ChildSocket")
        harness._edits.add_socket(_WEAPON_PATH, Socket(name="New_Back_ChildSocket"))
        harness._use_selected_as_orientation()
        payload = harness._edits.preview()[_DESC_PATH]
        self.assertIn(b'InChildSocketBone="New_Back_ChildSocket"', payload)
        # The body socket is untouched: this aims the item, it does not move it.
        self.assertIn(b'InSocketBone="Pelvis_L_Socket"', payload)

    def test_held_aims_the_out_child_socket(self) -> None:
        harness = _RouteHarness(
            role="held", weapon_sockets=("Basic_ChildSocket", "Pelvis_L_ChildSocket")
        )
        harness._selected_socket = "Pelvis_L_ChildSocket"
        harness._use_selected_as_orientation()
        payload = harness._edits.preview()[_DESC_PATH]
        self.assertIn(b'OutChildSocketBone="Pelvis_L_ChildSocket"', payload)
        self.assertIn(b'InChildSocketBone="Pelvis_L_ChildSocket"', payload)

    def test_a_body_socket_cannot_aim_an_item(self) -> None:
        harness = self._harness("Pelvis_L_Socket")
        harness._use_selected_as_orientation()
        self.assertEqual(harness._edits.modified_paths(), [])
        self.assertIn("child socket on the item", harness._status.message)

    def test_it_needs_a_selected_part(self) -> None:
        harness = self._harness()
        harness._selected_part = ""
        harness._use_selected_as_orientation()
        self.assertEqual(harness._edits.modified_paths(), [])
        self.assertIn("Select a part", harness._status.message)

    def test_re_aiming_with_the_same_socket_records_nothing(self) -> None:
        harness = self._harness("Pelvis_L_ChildSocket")
        harness._use_selected_as_orientation()
        self.assertEqual(harness._edits.modified_paths(), [])
        self.assertIn("already uses", harness._status.message)

    def test_aiming_with_an_undefined_socket_is_refused(self) -> None:
        """The item may list a socket no loaded file defines; routing to it would dangle."""

        harness = self._harness("Basic_ChildSocket")
        harness._session.weapon.sockets["Ghost_ChildSocket"] = object()
        harness._selected_socket = "Ghost_ChildSocket"
        harness._use_selected_as_orientation()
        self.assertEqual(harness._edits.modified_paths(), [])
        self.assertIn("not defined", harness._status.message)

    def test_the_status_line_names_both_ends(self) -> None:
        harness = self._harness("Basic_ChildSocket")
        harness._use_selected_as_orientation()
        self.assertIn("Basic_ChildSocket", harness._status.message)
        self.assertIn("Pelvis_L_ChildSocket", harness._status.message)

    def test_it_is_one_tier_b_operation(self) -> None:
        harness = self._harness("Basic_ChildSocket")
        harness._use_selected_as_orientation()
        self.assertEqual(harness._edits.to_plan().tier_counts(), {"B": 1})


class WeaponHandTests(unittest.TestCase):
    """The part being edited must be held in the hand the chosen weapon is authored for.

    Kliff's swords are all `_r`, so the default row — `CD_MainWeapon_Sword_R`, hard-coded —
    agreed with them by luck. Damian has a left-handed set as well, and choosing one left the
    right-hand row selected: the left-hand sword on screen while the animation drove the right
    arm, a hand reaching for nothing. That reads as the swap being broken rather than as the
    wrong row being edited.
    """

    def _harness(self, weapon_id: str, parts):
        harness = _PartsHarness(parts)

        class _Weapon:
            pass

        weapon = _Weapon()
        weapon.weapon_id = weapon_id
        harness._weapon_box.addItem(weapon_id, weapon)
        harness._weapon_box.setCurrentIndex(harness._weapon_box.count() - 1)
        harness._bindings = list(harness._session.bindings())
        return harness

    def test_a_left_handed_weapon_selects_the_left_hand_row(self) -> None:
        harness = self._harness(
            "cd_phw_01_sword_0001_l",
            [_part(part_name="CD_MainWeapon_Sword_R", out_socket="RHand_Socket"),
             _part(part_name="CD_MainWeapon_Sword_L", out_socket="LHand_Socket")],
        )

        self.assertEqual(harness._default_part_name(), "CD_MainWeapon_Sword_L")

    def test_a_right_handed_weapon_selects_the_right_hand_row(self) -> None:
        harness = self._harness(
            "cd_phm_01_sword_0001_r",
            [_part(part_name="CD_MainWeapon_Sword_R", out_socket="RHand_Socket"),
             _part(part_name="CD_MainWeapon_Sword_L", out_socket="LHand_Socket")],
        )

        self.assertEqual(harness._default_part_name(), "CD_MainWeapon_Sword_R")

    def test_the_kind_matters_as_well_as_the_hand(self) -> None:
        """Matching on the hand alone picks the first right-handed row, which is the arrow."""

        harness = self._harness(
            "cd_phm_01_sword_0001_r",
            [_part(part_name="CD_MainWeapon_Arw", out_socket="RHand_Socket"),
             _part(part_name="CD_MainWeapon_Sword_R", out_socket="RHand_Socket")],
        )

        self.assertEqual(harness._default_part_name(), "CD_MainWeapon_Sword_R")

    def test_a_stale_selection_gives_way_when_the_hand_changes(self) -> None:
        """Both characters have a `CD_MainWeapon_Sword_R`, so it would otherwise survive."""

        harness = self._harness(
            "cd_phw_01_sword_0001_l",
            [_part(part_name="CD_MainWeapon_Sword_R", out_socket="RHand_Socket"),
             _part(part_name="CD_MainWeapon_Sword_L", out_socket="LHand_Socket")],
        )

        self.assertFalse(harness._part_suits_weapon("CD_MainWeapon_Sword_R"))
        self.assertTrue(harness._part_suits_weapon("CD_MainWeapon_Sword_L"))

    def test_a_weapon_with_no_side_keeps_whatever_was_chosen(self) -> None:
        harness = self._harness(
            "cd_phm_02_sword_0001",
            [_part(part_name="CD_MainWeapon_Sword_R", out_socket="RHand_Socket")],
        )

        self.assertTrue(harness._part_suits_weapon("CD_MainWeapon_Sword_R"))
