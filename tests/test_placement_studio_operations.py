"""Operation isolation, linked-part atomicity, clone-on-write, and exact animation scope.

Synthetic fixtures only — no game install, no Qt. Every case here is one of the confirmed
failure modes from the placement/animation safety plan, written so that a regression fails
here rather than in a shipped package:

* an earlier shield move and an earlier one-handed swap bleeding into a two-handed package
* a selected row and a selected asset diverging into a mixed operation
* a placement no-op presented as a move
* the weapon case staying behind while the weapon moves
* a shared child socket edited in place for one item
* a one-handed target path written by a two-handed operation
"""

from __future__ import annotations

import unittest
from dataclasses import dataclass, replace

from tools.placement_studio import carry
from tools.placement_studio.editing import (
    OP_MOVE_EQUIPMENT,
    EditSession,
    OperationScope,
    ScopeError,
)
from tools.placement_studio.model import Quat, Vec3
from tools.placement_studio.move_operation import (
    MoveBlocked,
    MoveRequest,
    apply_move,
    plan_move,
)
from tools.placement_studio.orientation import (
    SOURCE_BORROWED_ZONE,
    decide_socket_edit,
    diagnose_inversion,
    half_turn_about_y,
    operation_socket_name,
)
from tools.placement_studio.resolver import PlacementResolver
from tools.placement_studio.session import EquipmentResolutionError, PlacementSession

MODEL = "1_phm"
BODY = "character/descriptors/socketbonedata/1_pc/1_phm/phm_01.pab.sockets.xml"
DESC = "character/descriptors/characterdescription/phm_description_player_kliff.xml"
ALIAS = "character/phm_description_player_kliff.xml"
W2H = ("character/descriptors/socketbonedata/1_pc/1_phm/weapon/2_twohandweapon/"
       "cd_phm_02_sword_0001.sockets.xml")
W2H_CASE = ("character/descriptors/socketbonedata/1_pc/1_phm/weapon/2_twohandweapon/"
            "cd_phm_02_sword_0001_in.sockets.xml")
W1H = ("character/descriptors/socketbonedata/1_pc/1_phm/weapon/1_onehandweapon/"
       "cd_phm_01_sword_0001_r.sockets.xml")
SHIELD = ("character/descriptors/socketbonedata/1_pc/1_phm/weapon/3_shield/"
          "cd_phm_03_shield_0001.sockets.xml")

CLIPS = "character/animation/1_pc/1_phm"


def _sockets(*rows: str) -> bytes:
    body = "".join(
        f'\t\t<Socket Name="{name}" Parent="{parent}" Rotation="{rotation}"'
        f' Translation="{translation}"/>\r\n'
        for name, parent, rotation, translation in (row.split("|") for row in rows)
    )
    return (
        f'﻿<SocketBoneData>\r\n\t<SocketList Count="{len(rows)}">\r\n'
        f"{body}\t</SocketList>\r\n</SocketBoneData>\r\n"
    ).encode("utf-8")


IDENT = "0.000000 0.000000 0.000000 1.000000"
FLIPPED = "0.000000 1.000000 0.000000 0.000000"
ZERO = "0.000000 0.000000 0.000000"

BODY_BYTES = _sockets(
    f"Pelvis_R_Socket|Bip01 Pelvis|{IDENT}|0.100000 0.000000 0.000000",
    f"Pelvis_L_Socket|Bip01 Pelvis|{IDENT}|-0.100000 0.000000 0.000000",
    f"Spine2_B_MainWeapon_Socket|Bip01 Spine2|{IDENT}|0.000000 0.200000 -0.100000",
    f"Spine2_B_Shield_Socket|Bip01 Spine2|{IDENT}|0.000000 0.250000 -0.100000",
    f"RHand_Socket|Bip01 R Hand|{IDENT}|{ZERO}",
)

# The two-hand sword: aimed for the back, with no hip child socket of its own. That absence is
# the case the plan is about — the aim has to come from somewhere, and it must not come from
# quietly editing the hip socket another weapon uses.
W2H_BYTES = _sockets(
    f"Basic_ChildSocket|{'' }|{IDENT}|{ZERO}",
    f"Spine2_B_SubWeapon_ChildSocket||{FLIPPED}|0.000000 -0.470000 0.000000",
)
W2H_CASE_BYTES = _sockets(
    f"Basic_ChildSocket||{IDENT}|{ZERO}",
    f"Spine2_B_SubWeapon_ChildSocket||{FLIPPED}|0.000000 -0.430000 0.000000",
)
# The one-hand sword owns both hip child sockets, so it is the borrow source for a hip aim.
W1H_BYTES = _sockets(
    f"Basic_ChildSocket||{IDENT}|{ZERO}",
    f"Pelvis_L_ChildSocket||{IDENT}|0.000000 -0.200000 0.000000",
    f"Pelvis_R_ChildSocket||{IDENT}|0.000000 -0.200000 0.000000",
)
SHIELD_BYTES = _sockets(
    f"Basic_ChildSocket||{IDENT}|{ZERO}",
    f"Spine2_B_SubWeapon_ChildSocket||{IDENT}|{ZERO}",
)

DESC_BYTES = (
    "<CharacterDescription>\r\n"
    '\t<Part PartName="CD_TwoHandWeapon_Sword" InSocketBone="Spine2_B_MainWeapon_Socket"'
    ' OutSocketBone="RHand_Socket" InChildSocketBone="Spine2_B_SubWeapon_ChildSocket"'
    ' OutChildSocketBone="Basic_ChildSocket"'
    ' WeaponCasePart="CD_TwoHandWeapon_Sword_IN"/>\r\n'
    '\t<Part PartName="CD_TwoHandWeapon_Sword_IN" InSocketBone="Spine2_B_MainWeapon_Socket"'
    ' OutSocketBone="" InChildSocketBone="Spine2_B_SubWeapon_ChildSocket"'
    ' OutChildSocketBone=""/>\r\n'
    '\t<Part PartName="CD_MainWeapon_Sword_R" InSocketBone="Pelvis_L_Socket"'
    ' OutSocketBone="RHand_Socket" InChildSocketBone="Pelvis_L_ChildSocket"'
    ' OutChildSocketBone="Basic_ChildSocket"/>\r\n'
    '\t<Part PartName="CD_MainWeapon_Shield_L" InSocketBone="Spine2_B_Shield_Socket"'
    ' OutSocketBone="RHand_Socket" InChildSocketBone="Spine2_B_SubWeapon_ChildSocket"'
    ' OutChildSocketBone="Basic_ChildSocket"/>\r\n'
    "</CharacterDescription>\r\n"
).encode("utf-8")


FILES = {
    BODY: BODY_BYTES,
    DESC: DESC_BYTES,
    ALIAS: DESC_BYTES,
    W2H: W2H_BYTES,
    W2H_CASE: W2H_CASE_BYTES,
    W1H: W1H_BYTES,
    SHIELD: SHIELD_BYTES,
}


@dataclass(frozen=True, slots=True)
class FakeClip:
    """A clip index entry: a game path and the stem the family is parsed out of."""

    name: str
    path: str

    @property
    def is_lod(self) -> bool:
        return self.name.endswith("_lod")


def _clip(stem: str, model: str = MODEL) -> FakeClip:
    return FakeClip(stem, f"character/animation/1_pc/{model}/{stem}.paa")


#: Target and donor clips for a two-handed move, plus the traps the plan names: a boss clip, a
#: `00_mon` copy, a swarm clip, and the other character's folder.
CLIP_INDEX = [
    _clip("cd_phm_longsword_00_01_normal_stand_weapon_out_000"),
    _clip("cd_phm_longsword_00_01_normal_stand_weapon_in_000"),
    _clip("cd_phm_longsword_00_01_normal_move_run_f_000"),
    _clip("cd_phm_lswd_00_01_nor_std_weapon_out_000"),
    _clip("cd_phm_sword_00_01_normal_stand_weapon_out_000"),
    _clip("cd_phm_sword_00_01_normal_stand_weapon_in_000"),
    _clip("cd_phm_sword_00_01_normal_move_run_f_000"),
    _clip("cd_phm_dlsd_00_01_nor_std_weapon_out_000"),
    _clip("cd_phm_dualsword_00_01_normal_stand_weapon_out_000"),
    FakeClip(
        "cd_darkguide_longsword_00_01_normal_stand_weapon_out_000",
        f"{CLIPS}/cd_darkguide_longsword_00_01_normal_stand_weapon_out_000.paa",
    ),
    FakeClip(
        "cd_phm_longsword_00_01_normal_stand_weapon_out_001",
        "character/animation/1_pc/1_phm/00_mon/"
        "cd_phm_longsword_00_01_normal_stand_weapon_out_001.paa",
    ),
    _clip("cd_phm_longsword_00_01_swarm_stand_weapon_out_000"),
    _clip("cd_phw_longsword_00_01_normal_stand_weapon_out_000", model="2_phw"),
    _clip("cd_prh_lswd_00_01_normal_stand_weaponout_000"),
]


class _Baseline:
    """Just enough of `corpus.Baseline` for the package inspector to diff against vanilla."""

    def __init__(self, files) -> None:
        self._files = dict(files)

    def __contains__(self, game_path: str) -> bool:
        return game_path in self._files

    def read(self, game_path: str) -> bytes:
        return self._files[game_path]

    def paths(self):
        return sorted(self._files)


def _session() -> PlacementSession:
    resolver = PlacementResolver()
    resolver.add_files(FILES)
    return PlacementSession(MODEL, None, resolver)


def _weapon(session: PlacementSession, weapon_id: str):
    return next(w for w in session.weapons() if w.weapon_id == weapon_id)


def _edits() -> EditSession:
    return EditSession(FILES)


def _two_hand_unit(session: PlacementSession):
    session.select_weapon(_weapon(session, "cd_phm_02_sword_0001"))
    return session.resolve_equipment_unit(
        "CD_TwoHandWeapon_Sword",
        available_families={carry.family_of(c.name) for c in CLIP_INDEX},
    )


def _shared_users(session: PlacementSession) -> dict:
    """Every child socket mapped to the descriptor rows that reference it, from vanilla."""

    return {
        name: usage.child_offset
        for name, usage in session.usage_map().items()
        if usage.child_offset
    }


# ── Workstream B: equipment unit resolution ──────────────────────────


class EquipmentUnitTests(unittest.TestCase):
    def test_selected_part_resolves_to_the_selected_asset(self) -> None:
        session = _session()
        unit = _two_hand_unit(session)
        self.assertEqual(unit.primary_part, "CD_TwoHandWeapon_Sword")
        self.assertEqual(unit.weapon_id, "cd_phm_02_sword_0001")
        self.assertEqual(unit.handedness, "2h")
        self.assertEqual(unit.unit_id, "1_phm/cd_phm_02_sword_0001/CD_TwoHandWeapon_Sword")

    def test_a_mismatched_part_and_asset_is_rejected(self) -> None:
        session = _session()
        session.select_weapon(_weapon(session, "cd_phm_01_sword_0001_r"))
        with self.assertRaises(EquipmentResolutionError) as caught:
            session.resolve_equipment_unit("CD_TwoHandWeapon_Sword")
        self.assertIn("2h row", str(caught.exception))
        self.assertIn("cd_phm_01_sword_0001_r is a 1h asset", str(caught.exception))

    def test_a_row_the_character_does_not_have_is_rejected(self) -> None:
        session = _session()
        session.select_weapon(_weapon(session, "cd_phm_02_sword_0001"))
        with self.assertRaises(EquipmentResolutionError):
            session.resolve_equipment_unit("CD_MainWeapon_Nonexistent")

    def test_weapon_case_part_resolves_to_the_linked_row(self) -> None:
        session = _session()
        unit = _two_hand_unit(session)
        self.assertEqual([l.part_name for l in unit.linked_parts],
                         ["CD_TwoHandWeapon_Sword_IN"])
        link = unit.linked_parts[0]
        self.assertEqual(link.role, "sheath")
        self.assertTrue(link.required_for_stow)
        self.assertEqual(link.source_file, DESC)

    def test_allowed_files_cover_the_weapon_and_its_case_and_nothing_else(self) -> None:
        session = _session()
        unit = _two_hand_unit(session)
        self.assertEqual(set(unit.allowed_socket_files), {W2H, W2H_CASE})
        self.assertEqual(unit.allowed_descriptor_files, (DESC,))
        self.assertNotIn(W1H, unit.allowed_socket_files)
        self.assertNotIn(BODY, unit.allowed_socket_files)

    def test_target_families_are_this_handedness_and_donors_are_the_other(self) -> None:
        session = _session()
        unit = _two_hand_unit(session)
        self.assertEqual(unit.target_animation_families, ("longsword", "lswd"))
        self.assertIn("sword", unit.donor_animation_families)
        self.assertNotIn("longsword", unit.donor_animation_families)


# ── Workstream A: operation transactions ─────────────────────────────


class OperationTransactionTests(unittest.TestCase):
    def _scope(self) -> OperationScope:
        return OperationScope(
            kind=OP_MOVE_EQUIPMENT,
            equipment_unit_id="unit-1",
            model=MODEL,
            destination_socket="Pelvis_R_Socket",
            allowed_descriptor_parts=("CD_TwoHandWeapon_Sword",),
            allowed_descriptor_files=(DESC,),
            allowed_socket_files=(W2H,),
        )

    def test_one_accepted_dialog_is_one_operation(self) -> None:
        edits = _edits()
        with edits.begin_operation(self._scope(), label="move") as handle:
            handle.set_route(DESC, "CD_TwoHandWeapon_Sword", "in_socket", "Pelvis_R_Socket")
        operations = edits.operations()
        self.assertEqual(len(operations), 1)
        self.assertEqual(operations[0].routed_parts(), ("CD_TwoHandWeapon_Sword",))
        self.assertEqual(operations[0].kind, OP_MOVE_EQUIPMENT)

    def test_rollback_leaves_the_session_untouched(self) -> None:
        edits = _edits()
        handle = edits.begin_operation(self._scope())
        handle.set_route(DESC, "CD_TwoHandWeapon_Sword", "in_socket", "Pelvis_R_Socket")
        self.assertTrue(edits.modified_paths())
        handle.rollback()
        self.assertEqual(edits.modified_paths(), [])
        self.assertEqual(edits.operations(), [])

    def test_undo_removes_the_whole_operation_in_one_action(self) -> None:
        edits = _edits()
        with edits.begin_operation(self._scope()) as handle:
            handle.set_route(DESC, "CD_TwoHandWeapon_Sword", "in_socket", "Pelvis_R_Socket")
            handle.set_route(DESC, "CD_TwoHandWeapon_Sword", "in_child_socket", "Basic_ChildSocket")
        self.assertEqual(len(edits.commands()), 2)
        self.assertTrue(edits.undo_operation())
        self.assertEqual(edits.operations(), [])
        self.assertEqual(edits.modified_paths(), [])

    def test_redo_restores_the_whole_operation(self) -> None:
        edits = _edits()
        with edits.begin_operation(self._scope()) as handle:
            handle.set_route(DESC, "CD_TwoHandWeapon_Sword", "in_socket", "Pelvis_R_Socket")
            handle.set_route(DESC, "CD_TwoHandWeapon_Sword", "in_child_socket", "Basic_ChildSocket")
        operation_id = edits.operations()[0].operation_id
        edits.undo_operation()
        self.assertEqual(edits.redo_operation(), operation_id)
        self.assertEqual(len(edits.operations()), 1)
        self.assertEqual(len(edits.commands()), 2)

    def test_an_operation_cannot_be_opened_inside_another(self) -> None:
        edits = _edits()
        edits.begin_operation(self._scope())
        with self.assertRaises(Exception):
            edits.begin_operation(self._scope())

    def test_a_free_form_edit_belongs_to_no_operation(self) -> None:
        edits = _edits()
        edits.nudge(BODY, "Pelvis_R_Socket", dy=0.02)
        self.assertEqual(edits.operations(), [])
        self.assertEqual(len(edits.loose_commands()), 1)

    def test_start_clean_drops_free_form_edits_and_keeps_operations(self) -> None:
        edits = _edits()
        edits.nudge(BODY, "Pelvis_R_Socket", dy=0.02)
        with edits.begin_operation(self._scope()) as handle:
            handle.set_route(DESC, "CD_TwoHandWeapon_Sword", "in_socket", "Pelvis_R_Socket")
        self.assertEqual(len(edits.loose_commands()), 1)
        self.assertEqual(edits.start_clean_operation(), 1)
        self.assertEqual(edits.loose_commands(), [])
        self.assertEqual(len(edits.operations()), 1)
        self.assertNotIn(BODY, edits.modified_paths())
        self.assertIn(DESC, edits.modified_paths())

    def test_start_clean_refuses_while_an_operation_is_open(self) -> None:
        edits = _edits()
        edits.begin_operation(self._scope())
        with self.assertRaises(Exception):
            edits.start_clean_operation()

    def test_reset_clears_operations_too(self) -> None:
        edits = _edits()
        with edits.begin_operation(self._scope()) as handle:
            handle.set_route(DESC, "CD_TwoHandWeapon_Sword", "in_socket", "Pelvis_R_Socket")
        edits.reset()
        self.assertEqual(edits.operations(), [])
        self.assertEqual(edits.modified_paths(), [])

    def test_discarding_a_middle_operation_leaves_the_others_intact(self) -> None:
        edits = _edits()
        with edits.begin_operation(self._scope()) as first:
            first.set_route(DESC, "CD_TwoHandWeapon_Sword", "in_socket", "Pelvis_R_Socket")
        shield_scope = OperationScope(
            kind=OP_MOVE_EQUIPMENT,
            equipment_unit_id="unit-2",
            model=MODEL,
            allowed_descriptor_parts=("CD_MainWeapon_Shield_L",),
            allowed_descriptor_files=(DESC,),
            allowed_socket_files=(SHIELD,),
        )
        with edits.begin_operation(shield_scope) as second:
            second.set_route(DESC, "CD_MainWeapon_Shield_L", "in_socket", "Pelvis_L_Socket")
        first_id = edits.operations()[0].operation_id
        self.assertTrue(edits.discard_operation(first_id))
        remaining = edits.operations()
        self.assertEqual(len(remaining), 1)
        self.assertEqual(remaining[0].routed_parts(), ("CD_MainWeapon_Shield_L",))
        # And the discarded route is genuinely gone from the emitted bytes.
        self.assertNotIn(b'PartName="CD_TwoHandWeapon_Sword" InSocketBone="Pelvis_R_Socket"',
                         edits.preview()[DESC])


class ScopeEnforcementTests(unittest.TestCase):
    def _scope(self, **overrides) -> OperationScope:
        fields = dict(
            kind=OP_MOVE_EQUIPMENT,
            equipment_unit_id="unit-1",
            model=MODEL,
            allowed_descriptor_parts=("CD_TwoHandWeapon_Sword",),
            allowed_descriptor_files=(DESC,),
            allowed_socket_files=(W2H,),
        )
        fields.update(overrides)
        return OperationScope(**fields)

    def test_a_descriptor_row_outside_the_allowlist_is_refused(self) -> None:
        edits = _edits()
        handle = edits.begin_operation(self._scope())
        with self.assertRaises(ScopeError):
            handle.set_route(DESC, "CD_MainWeapon_Shield_L", "in_socket", "Pelvis_L_Socket")
        handle.rollback()

    def test_a_socket_file_outside_the_allowlist_is_refused(self) -> None:
        edits = _edits()
        handle = edits.begin_operation(self._scope())
        with self.assertRaises(ScopeError):
            handle.set_rotation_euler(W1H, "Pelvis_L_ChildSocket", 0.0, 0.0, 90.0)
        handle.rollback()

    def test_an_animation_path_outside_the_allowlist_is_refused(self) -> None:
        edits = _edits()
        allowed = f"{CLIPS}/cd_phm_longsword_00_01_normal_stand_weapon_out_000.paa"
        handle = edits.begin_operation(self._scope(allowed_animation_targets=(allowed,)))
        handle.replace_clip(allowed, b"payload", "donor")
        with self.assertRaises(ScopeError):
            handle.replace_clip(
                f"{CLIPS}/cd_phm_sword_00_01_normal_stand_weapon_out_000.paa",
                b"payload",
                "donor",
            )
        handle.rollback()

    def test_free_form_editing_is_not_scope_checked(self) -> None:
        edits = _edits()
        edits.set_rotation_euler(W1H, "Pelvis_L_ChildSocket", 0.0, 0.0, 90.0)
        self.assertIn(W1H, edits.modified_paths())


# ── Workstream C: orientation safety ─────────────────────────────────


class OrientationSafetyTests(unittest.TestCase):
    def test_the_inversion_check_only_reports(self) -> None:
        anchor = Vec3(0.0, 1.0, 0.0)
        upside_down = diagnose_inversion(anchor, [Vec3(0.0, 1.6, 0.0)])
        self.assertTrue(upside_down.inverted)
        self.assertIn("Review orientation", upside_down.message)
        hanging = diagnose_inversion(anchor, [Vec3(0.0, 0.4, 0.0)])
        self.assertFalse(hanging.inverted)
        self.assertEqual(hanging.message, "")

    def test_the_half_turn_is_offered_not_applied(self) -> None:
        turned = half_turn_about_y(Quat())
        self.assertAlmostEqual(turned.y, 1.0, places=6)
        self.assertAlmostEqual(turned.w, 0.0, places=6)

    def test_a_shared_child_socket_requires_a_clone(self) -> None:
        decision = decide_socket_edit(
            "Pelvis_L_ChildSocket",
            ["CD_MainWeapon_Sword_R", "CD_Tool_Torch"],
            ["CD_MainWeapon_Sword_R"],
        )
        self.assertTrue(decision.clone_required)
        self.assertIn("CD_Tool_Torch", decision.reason)

    def test_a_socket_only_this_unit_uses_may_be_edited_with_confirmation(self) -> None:
        decision = decide_socket_edit(
            "CDMW_Sword_hip_ChildSocket", ["CD_TwoHandWeapon_Sword"],
            ["CD_TwoHandWeapon_Sword", "CD_TwoHandWeapon_Sword_IN"],
        )
        self.assertFalse(decision.clone_required)
        self.assertTrue(decision.needs_confirmation)

    def test_operation_socket_names_are_deterministic_and_fit_the_chart_prefix(self) -> None:
        first = operation_socket_name("CD_TwoHandWeapon_Sword", "hip")
        self.assertEqual(first, operation_socket_name("CD_TwoHandWeapon_Sword", "hip"))
        self.assertEqual(first, "CDMW_Sword_hip_ChildSocket")
        long_name = operation_socket_name("CD_MainWeapon_" + "Verbose" * 12, "back")
        self.assertLessEqual(len(long_name), 62)
        self.assertTrue(long_name.startswith("CDMW_"))

    def test_a_borrowed_aim_keeps_this_items_own_translation(self) -> None:
        session = _session()
        unit = _two_hand_unit(session)
        template = session.orientation_template(
            "Pelvis_R_Socket", current_child=unit.in_child_socket
        )
        self.assertEqual(template.source, SOURCE_BORROWED_ZONE)
        self.assertTrue(template.creates_socket)
        # The rotation comes from the one-hand sword's hip socket; the -0.470 grip offset is
        # the two-hand sword's own and must not be replaced by the shorter weapon's -0.200.
        self.assertAlmostEqual(template.translation.y, -0.470, places=6)
        self.assertAlmostEqual(template.rotation.w, 1.0, places=6)


# ── Workstream D: animation target isolation ─────────────────────────


class AnimationScopeTests(unittest.TestCase):
    def _unit(self):
        return _two_hand_unit(_session())

    def test_placement_only_replaces_nothing(self) -> None:
        rows = carry.swappable_pairs(
            self._unit(), CLIP_INDEX, carry.AnimationScope(carry.SCOPE_PLACEMENT_ONLY)
        )
        self.assertEqual(rows, ())

    def test_draw_and_stow_only_selects_draws_and_sheathes(self) -> None:
        rows = carry.swappable_pairs(
            self._unit(), CLIP_INDEX, carry.AnimationScope(carry.SCOPE_DRAW_STOW)
        )
        self.assertTrue(rows)
        for row in rows:
            self.assertTrue(carry.is_draw(row.target.name), row.target.name)

    def test_two_handed_targets_never_include_a_one_handed_path(self) -> None:
        rows = carry.swappable_pairs(
            self._unit(), CLIP_INDEX, carry.AnimationScope(carry.SCOPE_FULL_BODY)
        )
        self.assertTrue(rows)
        for row in rows:
            self.assertIn(row.target_family, ("longsword", "lswd"))
            self.assertNotIn(row.target_family, ("sword", "dualsword", "dlsd"))

    def test_one_handed_families_are_reported_as_donors(self) -> None:
        rows = carry.swappable_pairs(
            self._unit(), CLIP_INDEX, carry.AnimationScope(carry.SCOPE_FULL_BODY)
        )
        targets, donors = carry.family_counts(rows)
        self.assertEqual(set(targets), {"longsword", "lswd"})
        self.assertTrue(set(donors) <= {"sword", "dualsword", "dlsd", "swd", "swds", "rpr",
                                        "2rpr"})

    def test_npc_swarm_other_model_and_00_mon_paths_are_excluded(self) -> None:
        rows = carry.swappable_pairs(
            self._unit(), CLIP_INDEX, carry.AnimationScope(carry.SCOPE_FULL_BODY)
        )
        paths = {row.target_path for row in rows}
        for forbidden in ("cd_darkguide", "/00_mon/", "_swarm_", "/2_phw/"):
            self.assertFalse(
                any(forbidden in path for path in paths),
                f"{forbidden} leaked into the target set",
            )

    def test_mounted_clips_need_opt_in(self) -> None:
        unit = self._unit()
        off = carry.swappable_pairs(unit, CLIP_INDEX,
                                    carry.AnimationScope(carry.SCOPE_FULL_BODY))
        self.assertFalse(any(row.mounted for row in off))
        on = carry.swappable_pairs(
            unit, CLIP_INDEX,
            carry.AnimationScope(carry.SCOPE_FULL_BODY, include_mounted=True),
        )
        self.assertGreaterEqual(len(on), len(off))

    def test_borrowed_clips_need_opt_in(self) -> None:
        unit = self._unit()
        off = carry.swappable_pairs(unit, CLIP_INDEX,
                                    carry.AnimationScope(carry.SCOPE_FULL_BODY))
        self.assertFalse(any(row.borrowed for row in off))

    def test_same_zone_move_recommends_placement_only(self) -> None:
        self.assertEqual(
            carry.recommended_scope("Pelvis_R_Socket", "Pelvis_L_Socket"),
            carry.SCOPE_PLACEMENT_ONLY,
        )

    def test_hip_to_back_recommends_draw_and_stow(self) -> None:
        self.assertEqual(
            carry.recommended_scope("Pelvis_R_Socket", "Spine2_B_MainWeapon_Socket"),
            carry.SCOPE_DRAW_STOW,
        )

    def test_full_body_is_never_recommended(self) -> None:
        for source in ("Pelvis_R_Socket", "Spine2_B_MainWeapon_Socket", ""):
            for destination in ("Pelvis_L_Socket", "Spine2_B_MainWeapon_Socket"):
                self.assertNotEqual(
                    carry.recommended_scope(source, destination), carry.SCOPE_FULL_BODY
                )

    def test_dual_wield_donors_are_flagged(self) -> None:
        rows = carry.swappable_pairs(
            self._unit(), CLIP_INDEX, carry.AnimationScope(carry.SCOPE_FULL_BODY)
        )
        if any(row.dual_wield_donor for row in rows):
            self.assertTrue(
                any("off-hand" in message for message in carry.risk_warnings(rows))
            )


# ── the move, planned and applied ────────────────────────────────────


class MovePlanTests(unittest.TestCase):
    def _plan(self, destination="Pelvis_R_Socket", **overrides):
        session = _session()
        edits = _edits()
        unit = _two_hand_unit(session)
        fields = dict(
            unit=unit,
            destination_socket=destination,
            scope=carry.AnimationScope(carry.SCOPE_DRAW_STOW),
            orientation_reviewed=True,
        )
        fields.update(overrides)
        request = MoveRequest(**fields)
        return session, edits, plan_move(session, edits, request)

    def test_the_case_row_follows_the_weapon(self) -> None:
        _session_, _edits_, plan = self._plan()
        moved = {route.part_name for route in plan.routes}
        self.assertEqual(moved, {"CD_TwoHandWeapon_Sword", "CD_TwoHandWeapon_Sword_IN"})
        for route in plan.routes:
            self.assertEqual(route.destination_socket, "Pelvis_R_Socket")

    def test_weapon_and_case_get_separate_child_sockets_in_separate_files(self) -> None:
        _session_, _edits_, plan = self._plan()
        by_part = {route.part_name: route for route in plan.routes}
        weapon = by_part["CD_TwoHandWeapon_Sword"]
        case = by_part["CD_TwoHandWeapon_Sword_IN"]
        self.assertNotEqual(weapon.proposed_child, case.proposed_child)
        self.assertEqual(weapon.socket_file, W2H)
        self.assertEqual(case.socket_file, W2H_CASE)
        self.assertTrue(weapon.creates_socket)
        self.assertTrue(case.creates_socket)

    def test_the_shared_back_child_socket_is_not_touched(self) -> None:
        session, edits, plan = self._plan()
        operation = apply_move(session, edits, plan)
        self.assertNotIn("Spine2_B_SubWeapon_ChildSocket", operation.modified_sockets())
        # The back child socket is referenced by the weapon and the case both, so a local hip
        # correction that edited it would move whichever of them stayed behind. Its own row has
        # to come out of the replay byte-identical.
        for path, vanilla in ((W2H, W2H_BYTES), (W2H_CASE, W2H_CASE_BYTES)):
            produced = edits.preview().get(path, vanilla)
            for source in (vanilla, produced):
                row = source.split(b'Name="Spine2_B_SubWeapon_ChildSocket"')[1].split(b"/>")[0]
                self.assertIn(b'Rotation="0.000000 1.000000 0.000000 0.000000"', row)
            self.assertEqual(
                vanilla.split(b'Name="Spine2_B_SubWeapon_ChildSocket"')[1].split(b"/>")[0],
                produced.split(b'Name="Spine2_B_SubWeapon_ChildSocket"')[1].split(b"/>")[0],
            )

    def test_a_second_move_into_the_same_zone_gets_its_own_socket(self) -> None:
        """Two operations must not share an operation-owned socket.

        The name is derived from the row and the destination zone, so a second move of the same
        row to the other hip would land on the first operation's socket — `add_socket` would
        refuse it, and if it did not, packaging either operation alone would leave a route
        pointing at a definition the other one shipped.
        """

        session = _session()
        edits = _edits()
        unit = _two_hand_unit(session)
        first = plan_move(
            session, edits,
            MoveRequest(unit=unit, destination_socket="Pelvis_R_Socket",
                        orientation_reviewed=True),
        )
        apply_move(session, edits, first)
        second = plan_move(
            session, edits,
            MoveRequest(unit=unit, destination_socket="Pelvis_L_Socket",
                        orientation_reviewed=True),
        )
        apply_move(session, edits, second)

        operations = edits.operations()
        self.assertEqual(len(operations), 2)
        created_first = set(operations[0].created_sockets())
        created_second = set(operations[1].created_sockets())
        self.assertTrue(created_first)
        self.assertTrue(created_second)
        self.assertEqual(created_first & created_second, set())
        # The two do conflict, and rightly: they send the same row to different hips, so
        # packaging both together has no single answer. What must *not* appear is a conflict
        # over a socket one created and the other reused.
        conflicts = edits.operation_conflicts([op.operation_id for op in operations])
        self.assertTrue(conflicts)
        self.assertEqual(
            [c.reason for c in conflicts], ["different final value"] * len(conflicts)
        )
        self.assertTrue(all(c.field_name.endswith("socket") for c in conflicts))

    def test_three_state_comparison_separates_vanilla_from_pending(self) -> None:
        session = _session()
        edits = _edits()
        unit = _two_hand_unit(session)
        # An earlier experiment already moved the weapon to the left hip.
        earlier = edits.begin_operation(
            OperationScope(
                kind=OP_MOVE_EQUIPMENT,
                equipment_unit_id=unit.unit_id,
                model=MODEL,
                allowed_descriptor_parts=(unit.primary_part,),
                allowed_descriptor_files=(DESC,),
                allowed_socket_files=(W2H,),
            )
        )
        earlier.set_route(DESC, unit.primary_part, "in_socket", "Pelvis_L_Socket")
        earlier.commit()

        plan = plan_move(
            session,
            edits,
            MoveRequest(unit=unit, destination_socket="Pelvis_R_Socket",
                        orientation_reviewed=True),
        )
        body = next(row for row in plan.states if row.field_label == "Weapon body socket")
        self.assertEqual(body.vanilla, "Spine2_B_MainWeapon_Socket")
        self.assertEqual(body.pending, "Pelvis_L_Socket")
        self.assertEqual(body.proposed, "Pelvis_R_Socket")
        self.assertTrue(body.already_changed)
        self.assertEqual(plan.earlier_operations, (edits.operations()[0].operation_id,))

    def test_a_no_op_placement_is_not_presented_as_a_move(self) -> None:
        session = _session()
        edits = _edits()
        unit = _two_hand_unit(session)
        rows = carry.swappable_pairs(unit, CLIP_INDEX,
                                     carry.AnimationScope(carry.SCOPE_DRAW_STOW))
        plan = plan_move(
            session,
            edits,
            MoveRequest(
                unit=unit,
                destination_socket="Spine2_B_MainWeapon_Socket",
                scope=carry.AnimationScope(carry.SCOPE_DRAW_STOW),
                replacements=rows,
                orientation_reviewed=True,
            ),
        )
        self.assertFalse(plan.placement_changes)
        self.assertTrue(plan.action_label().startswith("Replace "))
        self.assertNotIn("Move", plan.action_label())

    def test_nothing_at_all_disables_the_action(self) -> None:
        session = _session()
        edits = _edits()
        unit = _two_hand_unit(session)
        plan = plan_move(
            session,
            edits,
            MoveRequest(unit=unit, destination_socket="Spine2_B_MainWeapon_Socket",
                        orientation_reviewed=True),
        )
        self.assertEqual(plan.action_label(), "No changes")
        with self.assertRaises(MoveBlocked):
            apply_move(session, edits, plan)

    def test_a_move_with_animations_says_both(self) -> None:
        session = _session()
        edits = _edits()
        unit = _two_hand_unit(session)
        rows = carry.swappable_pairs(unit, CLIP_INDEX,
                                     carry.AnimationScope(carry.SCOPE_DRAW_STOW))
        plan = plan_move(
            session,
            edits,
            MoveRequest(
                unit=unit,
                destination_socket="Pelvis_R_Socket",
                scope=carry.AnimationScope(carry.SCOPE_DRAW_STOW),
                replacements=rows,
                orientation_reviewed=True,
            ),
        )
        label = plan.action_label()
        self.assertIn("Move weapon and case", label)
        self.assertIn(f"replace {len(rows)} animations", label)

    def test_leaving_the_case_behind_is_recorded_as_an_accepted_warning(self) -> None:
        session = _session()
        edits = _edits()
        unit = _two_hand_unit(session)
        plan = plan_move(
            session,
            edits,
            MoveRequest(
                unit=unit,
                destination_socket="Pelvis_R_Socket",
                leave_behind=("CD_TwoHandWeapon_Sword_IN",),
                orientation_reviewed=True,
            ),
        )
        self.assertIn("leave CD_TwoHandWeapon_Sword_IN behind", plan.confirmations)
        self.assertEqual({r.part_name for r in plan.routes}, {"CD_TwoHandWeapon_Sword"})
        operation = apply_move(session, edits, plan)
        self.assertIn("leave CD_TwoHandWeapon_Sword_IN behind", operation.warnings_accepted)

    def test_full_body_scope_is_blocked_until_confirmed(self) -> None:
        session = _session()
        edits = _edits()
        unit = _two_hand_unit(session)
        rows = carry.swappable_pairs(unit, CLIP_INDEX,
                                     carry.AnimationScope(carry.SCOPE_FULL_BODY))
        request = MoveRequest(
            unit=unit,
            destination_socket="Pelvis_R_Socket",
            scope=carry.AnimationScope(carry.SCOPE_FULL_BODY),
            replacements=rows,
            orientation_reviewed=True,
        )
        plan = plan_move(session, edits, request)
        self.assertTrue(plan.blocked)
        confirmed = plan_move(session, edits, replace(request, advanced_confirmed=True))
        self.assertFalse(confirmed.blocked)

    def test_an_unreviewed_borrowed_aim_is_a_confirmation(self) -> None:
        session = _session()
        edits = _edits()
        unit = _two_hand_unit(session)
        plan = plan_move(
            session, edits,
            MoveRequest(unit=unit, destination_socket="Pelvis_R_Socket"),
        )
        self.assertTrue(any("borrows its aim" in item for item in plan.confirmations))

    def test_apply_is_atomic(self) -> None:
        session = _session()
        edits = _edits()
        unit = _two_hand_unit(session)
        plan = plan_move(
            session, edits,
            MoveRequest(unit=unit, destination_socket="Pelvis_R_Socket",
                        orientation_reviewed=True),
        )
        # Make the second route impossible by pointing the case row at a file nothing loaded,
        # the way a resolution bug would. The weapon's own route and its new socket land first,
        # so a non-atomic apply would leave the weapon on the hip with its sheath on the back.
        poisoned = replace(
            plan,
            routes=(plan.routes[0], replace(plan.routes[1], source_file="character/other.xml")),
        )
        with self.assertRaises(Exception):
            apply_move(session, edits, poisoned)
        self.assertEqual(edits.operations(), [])
        self.assertEqual(edits.modified_paths(), [])



if __name__ == "__main__":  # pragma: no cover
    unittest.main()
