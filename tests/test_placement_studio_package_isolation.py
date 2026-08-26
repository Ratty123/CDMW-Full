"""Package isolation, preflight, manifest, and reporting tests for Placement Studio."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from tools.placement_studio import carry, inspect_package, packaging, preflight
from tools.placement_studio.editing import (
    OP_MOVE_EQUIPMENT,
    OP_REPLACE_ANIMATIONS,
    OperationScope,
    ScopeError,
)
from tools.placement_studio.model import Socket
from tools.placement_studio.move_operation import MoveRequest, apply_move, plan_move
from tests.test_placement_studio_operations import (
    BODY,
    CLIPS,
    CLIP_INDEX,
    DESC,
    FILES,
    MODEL,
    SHIELD,
    W1H,
    W2H,
    W2H_CASE,
    _Baseline,
    _edits,
    _session,
    _shared_users,
    _two_hand_unit,
    _weapon,
)

# ── Workstream F: package isolation and preflight ────────────────────


class PackageIsolationTests(unittest.TestCase):
    def _three_operations(self):
        """The reported reproduction: a one-handed swap, a shield move, then the sword."""

        session = _session()
        edits = _edits()

        # 1. an earlier one-handed animation operation
        one_hand_path = f"{CLIPS}/cd_phm_sword_00_01_normal_stand_weapon_out_000.paa"
        animation_scope = OperationScope(
            kind=OP_REPLACE_ANIMATIONS,
            equipment_unit_id="1_phm/cd_phm_01_sword_0001_r/CD_MainWeapon_Sword_R",
            model=MODEL,
            allowed_animation_targets=(one_hand_path,),
            allowed_animation_families=("sword", "dualsword", "dlsd"),
        )
        with edits.begin_operation(animation_scope, label="one-handed swap") as handle:
            handle.replace_clip(one_hand_path, b"one-hand bytes", "donor")

        # 2. an earlier shield placement operation
        session.select_weapon(_weapon(session, "cd_phm_03_shield_0001"))
        shield_unit = session.resolve_equipment_unit("CD_MainWeapon_Shield_L")
        shield_plan = plan_move(
            session, edits,
            MoveRequest(unit=shield_unit, destination_socket="Pelvis_L_Socket",
                        orientation_reviewed=True),
        )
        apply_move(session, edits, shield_plan, label="shield move")

        # 3. the two-handed sword move the user actually wants to ship
        unit = _two_hand_unit(session)
        rows = carry.swappable_pairs(unit, CLIP_INDEX,
                                     carry.AnimationScope(carry.SCOPE_DRAW_STOW))
        clip_bytes = {row.target_path: b"two-hand bytes" for row in rows}
        sword_plan = plan_move(
            session, edits,
            MoveRequest(
                unit=unit,
                destination_socket="Pelvis_R_Socket",
                scope=carry.AnimationScope(carry.SCOPE_DRAW_STOW),
                replacements=rows,
                orientation_reviewed=True,
            ),
        )
        sword = apply_move(session, edits, sword_plan, clip_bytes=clip_bytes,
                           label="two-handed sword move")
        return session, edits, unit, shield_unit, sword, rows

    def test_three_operations_stand_apart_in_history(self) -> None:
        _session_, edits, _unit, _shield, _sword, _rows = self._three_operations()
        self.assertEqual(len(edits.operations()), 3)
        labels = [op.label for op in edits.operations()]
        self.assertEqual(labels,
                         ["one-handed swap", "shield move", "two-handed sword move"])

    def test_latest_operation_excludes_every_earlier_file(self) -> None:
        _session_, edits, _unit, _shield, sword, _rows = self._three_operations()
        ids = packaging.operation_ids_for(edits, packaging.SELECTION_LATEST)
        self.assertEqual(ids, [sword.operation_id])
        files = edits.preview_for_operations(ids)
        # The one-handed clip and the shield's socket file are in the *session* preview and
        # must not be in this one.
        whole = edits.preview()
        self.assertIn(f"{CLIPS}/cd_phm_sword_00_01_normal_stand_weapon_out_000.paa", whole)
        self.assertNotIn(
            f"{CLIPS}/cd_phm_sword_00_01_normal_stand_weapon_out_000.paa", files
        )
        self.assertIn(SHIELD, whole)
        self.assertNotIn(SHIELD, files)
        self.assertIn(W2H, files)
        self.assertIn(W2H_CASE, files)

    def test_the_isolated_descriptor_carries_only_this_operations_rows(self) -> None:
        _session_, edits, _unit, _shield, sword, _rows = self._three_operations()
        isolated = edits.preview_for_operations([sword.operation_id])[DESC]
        self.assertIn(b'PartName="CD_TwoHandWeapon_Sword" InSocketBone="Pelvis_R_Socket"',
                      isolated)
        # The shield stays where vanilla put it.
        self.assertIn(b'PartName="CD_MainWeapon_Shield_L" InSocketBone="Spine2_B_Shield_Socket"',
                      isolated)

    def test_preflight_passes_for_the_clean_two_handed_operation(self) -> None:
        session, edits, unit, _shield, sword, rows = self._three_operations()
        verdict = preflight.run_preflight(
            edits,
            [sword.operation_id],
            units={unit.unit_id: unit},
            shared_socket_users=_shared_users(session),
            replacements=rows,
        )
        self.assertEqual([f.describe() for f in verdict.errors], [])
        self.assertEqual(set(verdict.summary.descriptor_parts),
                         {"CD_TwoHandWeapon_Sword", "CD_TwoHandWeapon_Sword_IN"})
        self.assertEqual(verdict.summary.shared_sockets_modified, ())
        self.assertEqual(set(verdict.summary.animation_targets), {"longsword", "lswd"})
        self.assertEqual(len(verdict.summary.excluded_operations), 2)

    def test_selecting_two_operations_packages_exactly_those_two(self) -> None:
        session, edits, unit, shield_unit, sword, rows = self._three_operations()
        shield_id = edits.operations()[1].operation_id
        verdict = preflight.run_preflight(
            edits,
            [sword.operation_id, shield_id],
            units={unit.unit_id: unit, shield_unit.unit_id: shield_unit},
            shared_socket_users=_shared_users(session),
            replacements=rows,
        )
        # Two operations chosen on purpose is a legitimate package; the one the user did not
        # choose is still absent, and the summary says so.
        self.assertEqual([f.describe() for f in verdict.errors], [])
        self.assertIn("CD_MainWeapon_Shield_L", verdict.summary.descriptor_parts)
        self.assertEqual(len(verdict.summary.excluded_operations), 1)
        files = edits.preview_for_operations([sword.operation_id, shield_id])
        self.assertNotIn(
            f"{CLIPS}/cd_phm_sword_00_01_normal_stand_weapon_out_000.paa", files
        )

    def test_preflight_blocks_a_row_an_operation_never_declared(self) -> None:
        """An operation committed without a scope cannot be packaged.

        This is the shape a legacy or free-form edit takes once it is grouped: it changed a
        real descriptor row and declared nothing, so no allowlist covers it.
        """

        edits = _edits()
        with edits.begin_operation(OperationScope.unrestricted(kind=OP_MOVE_EQUIPMENT)) as h:
            h.set_route(DESC, "CD_MainWeapon_Shield_L", "in_socket", "Pelvis_L_Socket")
        ids = [op.operation_id for op in edits.operations()]
        verdict = preflight.run_preflight(edits, ids)
        self.assertIn("descriptor_out_of_scope", {f.code for f in verdict.errors})

    def test_preflight_blocks_a_one_handed_target_on_a_two_handed_unit(self) -> None:
        session = _session()
        edits = _edits()
        unit = _two_hand_unit(session)
        one_hand_path = f"{CLIPS}/cd_phm_sword_00_01_normal_stand_weapon_out_000.paa"
        # The scope a buggy pair generator would produce: the two-handed unit, but a one-handed
        # target path in its allowlist. Recording is allowed — the allowlist says so — and the
        # family check is the layer that catches it.
        scope = OperationScope(
            kind=OP_REPLACE_ANIMATIONS,
            equipment_unit_id=unit.unit_id,
            model=MODEL,
            allowed_animation_targets=(one_hand_path,),
            allowed_animation_families=unit.target_animation_families,
        )
        with edits.begin_operation(scope, label="leaky swap") as handle:
            handle.replace_clip(one_hand_path, b"bytes", "donor")
        verdict = preflight.run_preflight(
            edits,
            [edits.operations()[0].operation_id],
            units={unit.unit_id: unit},
            shared_socket_users=_shared_users(session),
        )
        codes = {f.code for f in verdict.errors}
        self.assertIn("animation_family_mismatch", codes)
        self.assertTrue(
            any("sword family" in f.message for f in verdict.errors),
            [f.describe() for f in verdict.errors],
        )

    def test_a_target_path_the_operation_never_declared_is_blocked(self) -> None:
        session = _session()
        edits = _edits()
        unit = _two_hand_unit(session)
        declared = f"{CLIPS}/cd_phm_longsword_00_01_normal_stand_weapon_out_000.paa"
        scope = OperationScope(
            kind=OP_REPLACE_ANIMATIONS,
            equipment_unit_id=unit.unit_id,
            model=MODEL,
            allowed_animation_targets=(declared,),
            allowed_animation_families=unit.target_animation_families,
        )
        handle = edits.begin_operation(scope)
        handle.replace_clip(declared, b"bytes", "donor")
        handle.commit()
        # Widen the recorded operation the way a stale replay would, by re-recording the same
        # command against a path the scope never named. `replace_clip` refuses it outright,
        # which is the enforcement layer D8 asks for.
        with self.assertRaises(ScopeError):
            handle2 = edits.begin_operation(scope)
            handle2.replace_clip(
                f"{CLIPS}/cd_phm_longsword_00_01_normal_move_run_f_000.paa", b"bytes", "donor"
            )
        edits.active_operation.rollback()

    def test_the_package_contains_only_the_selected_operation(self) -> None:
        session, edits, unit, _shield, sword, rows = self._three_operations()
        metadata = packaging.PackageMetadata(name="Two-Hand Right Hip", version="1.0.0")
        with tempfile.TemporaryDirectory() as directory:
            results, verdict = packaging.build_for_operations(
                edits,
                [sword.operation_id],
                metadata,
                out_root=Path(directory),
                units={unit.unit_id: unit},
                shared_socket_users=_shared_users(session),
                replacements=rows,
                managers=("DMM",),
                accept_warnings=True,
            )
            self.assertFalse(verdict.blocked, verdict.render())
            self.assertEqual(len(results), 1)
            payload = set(results[0].payload_paths)
            self.assertNotIn(SHIELD, payload)
            self.assertNotIn(
                f"{CLIPS}/cd_phm_sword_00_01_normal_stand_weapon_out_000.paa", payload
            )
            self.assertIn(W2H, payload)

            manifest = json.loads(
                (results[0].root / preflight.MANIFEST_NAME).read_text(encoding="utf-8")
            )
            self.assertEqual(manifest["format"], preflight.MANIFEST_FORMAT)
            self.assertEqual([op["operation_id"] for op in manifest["operations"]],
                             [sword.operation_id])
            self.assertEqual(sorted(manifest["descriptor_parts"]),
                             ["CD_TwoHandWeapon_Sword", "CD_TwoHandWeapon_Sword_IN"])
            self.assertEqual(len(manifest["excluded_operations"]), 2)
            self.assertEqual(set(manifest["animation_targets"]), {"longsword", "lswd"})

            readme = (results[0].root / "README.txt").read_text(encoding="utf-8")
            self.assertIn("Operation scope", readme)
            self.assertIn("animation substitutions", readme)
            self.assertIn("CD_TwoHandWeapon_Sword_IN", readme)

    def test_readme_and_manifest_counts_match_the_actual_files(self) -> None:
        session, edits, unit, _shield, sword, rows = self._three_operations()
        metadata = packaging.PackageMetadata(name="Counts", version="1.0.0")
        with tempfile.TemporaryDirectory() as directory:
            results, _verdict = packaging.build_for_operations(
                edits,
                [sword.operation_id],
                metadata,
                out_root=Path(directory),
                units={unit.unit_id: unit},
                shared_socket_users=_shared_users(session),
                replacements=rows,
                managers=("DMM",),
                accept_warnings=True,
            )
            manifest = json.loads(
                (results[0].root / preflight.MANIFEST_NAME).read_text(encoding="utf-8")
            )
            self.assertEqual(sorted(manifest["payload_paths"]),
                             sorted(results[0].payload_paths))
            clips = [p for p in results[0].payload_paths if p.endswith(".paa")]
            self.assertEqual(manifest["animation_files"], len(clips))
            self.assertEqual(sum(manifest["animation_targets"].values()), len(rows))

    def test_output_is_deterministic_from_the_same_baseline_and_selection(self) -> None:
        session, edits, unit, _shield, sword, _rows = self._three_operations()
        first = edits.preview_for_operations([sword.operation_id])
        second = edits.preview_for_operations([sword.operation_id])
        self.assertEqual(first, second)

    def test_conflicting_operations_are_reported(self) -> None:
        edits = _edits()
        scope = OperationScope(
            kind=OP_MOVE_EQUIPMENT,
            equipment_unit_id="unit-1",
            model=MODEL,
            allowed_descriptor_parts=("CD_TwoHandWeapon_Sword",),
            allowed_descriptor_files=(DESC,),
            allowed_socket_files=(W2H,),
        )
        with edits.begin_operation(scope, label="left") as first:
            first.set_route(DESC, "CD_TwoHandWeapon_Sword", "in_socket", "Pelvis_L_Socket")
        with edits.begin_operation(scope, label="right") as second:
            second.set_route(DESC, "CD_TwoHandWeapon_Sword", "in_socket", "Pelvis_R_Socket")
        ids = [op.operation_id for op in edits.operations()]
        conflicts = edits.operation_conflicts(ids)
        self.assertEqual(len(conflicts), 1)
        self.assertIn("in_socket", conflicts[0].describe())
        verdict = preflight.run_preflight(edits, ids)
        self.assertIn("operation_conflict", {f.code for f in verdict.errors})

    def test_preflight_blocks_a_shared_socket_changed_in_place(self) -> None:
        """The fourth blocker in Workstream F's definition of done.

        `Spine2_B_SubWeapon_ChildSocket` aims the two-hand sword and its sheath both, so
        re-aiming it for a hip move would swing whichever of them stayed on the back. The
        operation may still record the edit — the socket is in its own asset file, which its
        scope allows — so preflight is what refuses to ship it.
        """

        session = _session()
        edits = _edits()
        unit = _two_hand_unit(session)
        scope = OperationScope(
            kind=OP_MOVE_EQUIPMENT,
            equipment_unit_id=unit.unit_id,
            model=MODEL,
            destination_socket="Pelvis_R_Socket",
            allowed_descriptor_parts=unit.part_names,
            allowed_descriptor_files=unit.allowed_descriptor_files,
            allowed_socket_files=unit.allowed_socket_files,
        )
        with edits.begin_operation(scope, label="re-aim in place") as handle:
            handle.set_route(DESC, unit.primary_part, "in_socket", "Pelvis_R_Socket")
            handle.set_rotation_euler(W2H, "Spine2_B_SubWeapon_ChildSocket", 0.0, 0.0, 90.0)

        shared = _shared_users(session)
        self.assertGreater(len(shared["Spine2_B_SubWeapon_ChildSocket"]), 1)
        verdict = preflight.run_preflight(
            edits,
            [edits.operations()[0].operation_id],
            units={unit.unit_id: unit},
            shared_socket_users=shared,
        )
        self.assertIn("shared_socket_modified", {f.code for f in verdict.errors})
        self.assertTrue(
            any("clone it and reroute" in f.message for f in verdict.errors),
            [f.describe() for f in verdict.errors],
        )
        self.assertEqual(
            verdict.summary.shared_sockets_modified, ("Spine2_B_SubWeapon_ChildSocket",)
        )

    def test_preflight_blocks_a_socket_file_the_operation_never_declared(self) -> None:
        """The third blocker: a socket created in a file outside the operation's allowlist."""

        session = _session()
        edits = _edits()
        unit = _two_hand_unit(session)
        # An operation scoped to the two-hand asset that nonetheless created a socket in the
        # one-hand asset — what a resolution bug that picked the wrong file would leave behind.
        with edits.begin_operation(OperationScope.unrestricted(kind=OP_MOVE_EQUIPMENT)) as h:
            h.set_route(DESC, unit.primary_part, "in_socket", "Pelvis_R_Socket")
            h.add_socket(
                W1H,
                Socket(name="CDMW_Stray_hip_ChildSocket", source_file=W1H),
            )
        verdict = preflight.run_preflight(
            edits,
            [edits.operations()[0].operation_id],
            units={unit.unit_id: unit},
            shared_socket_users=_shared_users(session),
        )
        codes = {f.code for f in verdict.errors}
        self.assertIn("socket_file_out_of_scope", codes)

    def test_the_inspection_command_confirms_a_clean_package(self) -> None:
        session, edits, unit, _shield, sword, rows = self._three_operations()
        metadata = packaging.PackageMetadata(name="Inspect Me", version="1.0.0")
        with tempfile.TemporaryDirectory() as directory:
            results, _verdict = packaging.build_for_operations(
                edits,
                [sword.operation_id],
                metadata,
                out_root=Path(directory),
                units={unit.unit_id: unit},
                shared_socket_users=_shared_users(session),
                replacements=rows,
                managers=("DMM",),
                accept_warnings=True,
            )
            result = inspect_package.inspect(results[0].root, _Baseline(FILES))
            self.assertEqual(result.mismatches, ())
            self.assertTrue(result.ok)
            self.assertEqual(
                set(result.contents.all_parts()),
                {"CD_TwoHandWeapon_Sword", "CD_TwoHandWeapon_Sword_IN"},
            )
            self.assertEqual(set(result.contents.animation_targets), {"longsword", "lswd"})
            # The new child sockets are additions, and the shared back socket is untouched.
            self.assertEqual(len(result.contents.all_socket_additions()), 2)
            self.assertEqual(result.contents.all_socket_changes(), ())

    def test_the_inspection_command_catches_a_file_the_manifest_does_not_claim(self) -> None:
        session, edits, unit, _shield, sword, rows = self._three_operations()
        metadata = packaging.PackageMetadata(name="Leaky", version="1.0.0")
        with tempfile.TemporaryDirectory() as directory:
            results, _verdict = packaging.build_for_operations(
                edits,
                [sword.operation_id],
                metadata,
                out_root=Path(directory),
                units={unit.unit_id: unit},
                shared_socket_users=_shared_users(session),
                replacements=rows,
                managers=("DMM",),
                accept_warnings=True,
            )
            # Slip a one-handed clip into the built package, the way a builder bug would.
            smuggled = (
                results[0].root
                / "character/animation/1_pc/1_phm"
                / "cd_phm_sword_00_01_normal_stand_weapon_out_000.paa"
            )
            smuggled.parent.mkdir(parents=True, exist_ok=True)
            smuggled.write_bytes(b"one-hand bytes")
            result = inspect_package.inspect(results[0].root, _Baseline(FILES))
            self.assertFalse(result.ok)
            self.assertTrue(
                any("sword" in item and "manifest" in item for item in result.mismatches),
                result.mismatches,
            )

    def test_identical_operations_deduplicate_rather_than_conflict(self) -> None:
        edits = _edits()
        scope = OperationScope(
            kind=OP_MOVE_EQUIPMENT,
            equipment_unit_id="unit-1",
            model=MODEL,
            allowed_descriptor_parts=("CD_TwoHandWeapon_Sword",),
            allowed_descriptor_files=(DESC,),
            allowed_socket_files=(W2H,),
        )
        for _ in range(2):
            with edits.begin_operation(scope) as handle:
                handle.set_route(DESC, "CD_TwoHandWeapon_Sword", "in_socket", "Pelvis_R_Socket")
        ids = [op.operation_id for op in edits.operations()]
        self.assertEqual(edits.operation_conflicts(ids), [])


class ReportingTests(unittest.TestCase):
    """The panels have to say which operation a change belongs to, not just which file."""

    def test_the_pending_panel_names_each_operation_and_its_counts(self) -> None:
        from tools.placement_studio.report_style import operation_scope_html

        session = _session()
        edits = _edits()
        unit = _two_hand_unit(session)
        plan = plan_move(
            session, edits,
            MoveRequest(unit=unit, destination_socket="Pelvis_R_Socket",
                        orientation_reviewed=True),
        )
        apply_move(session, edits, plan, label="Move the sword to the right hip")
        edits.nudge(BODY, "Pelvis_R_Socket", dy=0.02)

        html = operation_scope_html(edits.operations(), len(edits.loose_commands()))
        self.assertIn("Move the sword to the right hip", html)
        self.assertIn("descriptor changes", html)
        self.assertIn("sockets created", html)
        # And the free-form edit is called out rather than folded in with the operation.
        self.assertIn("free-form edit(s) outside any operation", html)
        self.assertIn("never packaged", html)

    def test_an_empty_session_renders_nothing(self) -> None:
        from tools.placement_studio.report_style import operation_scope_html

        self.assertEqual(operation_scope_html([], 0), "")

    def test_the_package_block_leads_with_its_blockers(self) -> None:
        from tools.placement_studio.report_style import package_scope_html

        session, edits, unit, _shield, sword, rows = PackageIsolationTests()._three_operations()
        verdict = preflight.run_preflight(
            edits,
            [sword.operation_id],
            units={unit.unit_id: unit},
            shared_socket_users=_shared_users(session),
            replacements=rows,
        )
        html = package_scope_html(verdict.summary, verdict.errors, verdict.warnings)
        self.assertIn("Package scope", html)
        self.assertIn("CD_TwoHandWeapon_Sword", html)
        self.assertIn("Animation target families", html)
        self.assertIn("longsword", html)
        self.assertIn("Excluded earlier operations", html)

    def test_the_readme_checklist_covers_the_in_game_matrix(self) -> None:
        checklist = " ".join(packaging.IN_GAME_CHECKLIST).lower()
        criteria = " ".join(packaging.PASS_CRITERIA).lower()
        for expected in ("idle", "draw", "stow", "walk and run", "crouch", "sit",
                         "mount", "shield", "camera angles", "reload"):
            self.assertIn(expected, checklist, expected)
        for expected in ("stay together", "side", "inverted", "reaches close enough",
                         "off-hand", "no other weapon", "snaps back"):
            self.assertIn(expected, criteria, expected)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
