"""Unit tests for Placement Studio Phase 4: Tier C retarget, Tier D substitution.

Synthetic action charts only — no game install, no Qt. The corpus gate (`cli retarget`)
verifies the mechanism against every golden action chart.
"""

from __future__ import annotations

import unittest

from tools.placement_studio import paac
from tools.placement_studio.animation import (
    ChartIndex,
    RetargetError,
    actionchart_group,
    actionchart_model,
    apply_retarget,
    clip_archetype,
    clip_stem,
    index_chart,
    is_actionchart,
    is_motion_clip,
    plan_retarget,
    retarget_candidates,
    substitution_candidates,
    verify_retarget,
)
from tools.placement_studio.editing import EditError, EditSession
from tools.placement_studio.model import Socket

_CHART_A = "actionchart/bin__/upperaction/1_pc/1_phm/ride_upper.paac"
_CHART_B = "actionchart/bin__/upperaction/1_pc/1_phm/basic_upper_weaponin.paac"
_BODY = "character/descriptors/socketbonedata/1_pc/1_phm/phm_01.pab.sockets.xml"

_OLD = "Spine2_B_SubWeapon_Socket"
_NEW = "Pelvis_L_SubWeapon_Socket"


def _prefixed(name: str) -> bytes:
    """Encode a name the way action charts store strings: <len+1><ascii><NUL>."""

    return bytes([len(name) + 1]) + name.encode("ascii") + b"\x00"


def _chart(*names: str, filler: bytes = b"\x7f\x00\x11\x22") -> bytes:
    body = b"".join(filler + _prefixed(name) for name in names)
    return b"PAAC" + filler * 4 + body + filler * 4


_SOCKETS = (
    b'<SocketBoneData>\r\n\t<SocketList Count="1">\r\n'
    b'\t\t<Socket Name="Pelvis_R_Socket" Parent="B_WeaponIn_L_00"'
    b' Rotation="0.000000 0.000000 0.000000 1.000000"'
    b' Translation="0.000000 0.000000 0.150000"/>\r\n'
    b"\t</SocketList>\r\n</SocketBoneData>\r\n"
)


class EncodingTests(unittest.TestCase):
    def test_fixture_matches_the_real_length_prefix_layout(self) -> None:
        data = _chart(_OLD)
        found = paac.index_sockets(data)
        self.assertEqual([item.value for item in found], [_OLD])
        self.assertTrue(paac.is_length_prefixed(data, found[0].offset, len(_OLD)))

    def test_path_classification(self) -> None:
        self.assertTrue(is_actionchart(_CHART_A))
        self.assertFalse(is_actionchart(_BODY))
        self.assertEqual(actionchart_model(_CHART_A), "1_phm")
        self.assertEqual(actionchart_group(_CHART_A), "upperaction")


class IndexTests(unittest.TestCase):
    def _index(self) -> ChartIndex:
        index = ChartIndex()
        index.add(index_chart(_CHART_A, _chart("RHand_Socket", _OLD)))
        index.add(index_chart(_CHART_B, _chart(_OLD)))
        return index

    def test_offsets_are_recorded_per_socket(self) -> None:
        chart = index_chart(_CHART_A, _chart("RHand_Socket", _OLD))
        self.assertEqual(chart.names, ("RHand_Socket", _OLD))
        self.assertEqual(len(chart.offsets(_OLD)), 1)
        self.assertTrue(chart.references(_OLD))
        self.assertFalse(chart.references("Nope_Socket"))

    def test_charts_referencing_finds_every_affected_file(self) -> None:
        index = self._index()
        self.assertEqual(len(index.charts_referencing(_OLD)), 2)
        self.assertEqual(len(index.charts_referencing("RHand_Socket")), 1)

    def test_socket_counts_are_ranked(self) -> None:
        self.assertEqual(self._index().sockets_for()[_OLD], 2)

    def test_model_filter_applies(self) -> None:
        self.assertEqual(len(self._index().charts_referencing(_OLD, model="2_phw")), 0)


class CandidateTests(unittest.TestCase):
    """The length rule is a filter, not an error message."""

    def test_only_same_length_names_are_offered(self) -> None:
        defined = {_NEW, "RHand_Socket", "Pelvis_R_Socket", "A" * len(_OLD)}
        candidates = retarget_candidates(_OLD, defined_sockets=defined)
        self.assertIn(_NEW, candidates)
        self.assertNotIn("RHand_Socket", candidates)
        self.assertTrue(all(len(name) == len(_OLD) for name in candidates))

    def test_the_socket_itself_is_excluded(self) -> None:
        self.assertNotIn(_OLD, retarget_candidates(_OLD, defined_sockets={_OLD, _NEW}))

    def test_undefined_names_are_never_offered(self) -> None:
        self.assertEqual(retarget_candidates(_OLD, defined_sockets=set()), [])


class PlanTests(unittest.TestCase):
    def _index(self) -> ChartIndex:
        index = ChartIndex()
        index.add(index_chart(_CHART_A, _chart("RHand_Socket", _OLD)))
        index.add(index_chart(_CHART_B, _chart(_OLD)))
        return index

    def test_plan_covers_every_referencing_chart(self) -> None:
        plan = plan_retarget(self._index(), _OLD, _NEW)
        self.assertTrue(plan.valid)
        self.assertEqual(plan.file_count, 2)
        self.assertEqual(plan.patch_count, 2)
        self.assertEqual(sorted(plan.paths()), sorted([_CHART_A, _CHART_B]))

    def test_plan_emits_tier_c_operations_with_offsets(self) -> None:
        operations = plan_retarget(self._index(), _OLD, _NEW).operations()
        self.assertTrue(all(op.tier == "C" for op in operations))
        self.assertTrue(all(op.detail["offsets"] for op in operations))

    def test_different_length_is_refused_at_planning_time(self) -> None:
        with self.assertRaises(RetargetError):
            plan_retarget(self._index(), _OLD, "Pelvis_R_Socket")

    def test_no_op_retarget_is_refused(self) -> None:
        with self.assertRaises(RetargetError):
            plan_retarget(self._index(), _OLD, _OLD)

    def test_path_filter_narrows_the_plan(self) -> None:
        plan = plan_retarget(self._index(), _OLD, _NEW, paths=[_CHART_B])
        self.assertEqual(plan.paths(), [_CHART_B])


class ApplyTests(unittest.TestCase):
    def _fixture(self):
        source = {_CHART_A: _chart("RHand_Socket", _OLD), _CHART_B: _chart(_OLD)}
        index = ChartIndex(index_chart(path, data) for path, data in source.items())
        return source, plan_retarget(index, _OLD, _NEW)

    def test_patch_preserves_length_and_renames_the_socket(self) -> None:
        source, plan = self._fixture()
        produced = apply_retarget(plan, source)
        for path, data in produced.items():
            self.assertEqual(len(data), len(source[path]))
            names = set(paac.socket_histogram(data))
            self.assertIn(_NEW, names)
            self.assertNotIn(_OLD, names)

    def test_bytes_outside_the_patched_span_are_untouched(self) -> None:
        source, plan = self._fixture()
        produced = apply_retarget(plan, source)
        self.assertEqual(verify_retarget(plan, source, produced), [])

    def test_other_sockets_survive(self) -> None:
        source, plan = self._fixture()
        produced = apply_retarget(plan, source)
        self.assertIn("RHand_Socket", paac.socket_histogram(produced[_CHART_A]))

    def test_retarget_is_exactly_reversible(self) -> None:
        source, plan = self._fixture()
        produced = apply_retarget(plan, source)
        for path, data in produced.items():
            self.assertEqual(paac.retarget(data, _NEW, _OLD), source[path])

    def test_missing_source_bytes_abort_the_whole_apply(self) -> None:
        source, plan = self._fixture()
        with self.assertRaises(RetargetError):
            apply_retarget(plan, {_CHART_A: source[_CHART_A]})

    def test_a_coincidental_byte_match_is_not_patched(self) -> None:
        """The length prefix rejects matches that are not real strings."""

        raw = b"PAAC" + _OLD.encode("ascii") + b"\x00" * 8
        self.assertEqual(paac.index_sockets(raw), [])
        with self.assertRaises(paac.PaacPatchError):
            paac.retarget(raw, _OLD, _NEW)


class SessionIntegrationTests(unittest.TestCase):
    """Tier C shares the Phase 3 undo/redo model, and depends on Tier A2."""

    def _session(self) -> EditSession:
        return EditSession({_BODY: _SOCKETS, _CHART_A: _chart("RHand_Socket", _OLD)})

    def test_retarget_is_refused_before_the_target_is_defined(self) -> None:
        session = self._session()
        with self.assertRaises(EditError):
            session.retarget(_CHART_A, _OLD, _NEW)
        self.assertEqual(session.modified_paths(), [])

    def test_retarget_succeeds_after_creating_the_definition(self) -> None:
        session = self._session()
        session.add_socket(_BODY, Socket(name=_NEW, parent_bone="B_WeaponIn_R_00"))
        session.retarget(_CHART_A, _OLD, _NEW)
        self.assertEqual(sorted(session.modified_paths()), sorted([_BODY, _CHART_A]))
        self.assertEqual(session.to_plan().tier_counts(), {"A2": 1, "C": 1})

    def test_undo_reverts_the_retarget_only(self) -> None:
        session = self._session()
        session.add_socket(_BODY, Socket(name=_NEW, parent_bone="B_WeaponIn_R_00"))
        session.retarget(_CHART_A, _OLD, _NEW)
        session.undo()
        self.assertEqual(session.modified_paths(), [_BODY])
        self.assertIn(_OLD, paac.socket_histogram(session.chart_bytes(_CHART_A)))

    def test_wrong_length_retarget_is_refused(self) -> None:
        session = self._session()
        session.add_socket(_BODY, Socket(name="Short_Socket", parent_bone="Bip01"))
        with self.assertRaises(EditError):
            session.retarget(_CHART_A, _OLD, "Short_Socket")


class ClipTests(unittest.TestCase):
    def test_clip_classification(self) -> None:
        self.assertTrue(is_motion_clip("character/motion/1_pc/1_phm/cd_phm_longsword_00.paa"))
        self.assertTrue(is_motion_clip("character/binary/motionblending/phm/x.motionblending"))
        self.assertFalse(is_motion_clip(_CHART_A))

    def test_archetype_is_recovered_from_the_clip_name(self) -> None:
        path = "character/motion/1_pc/1_phm/cd_phm_longsword_00_01_normal_move_run_f_ing_000.paa"
        self.assertEqual(clip_archetype(path), "longsword")
        self.assertTrue(clip_stem(path).startswith("cd_phm_longsword"))

    def test_candidates_exclude_the_target_and_other_file_kinds(self) -> None:
        target = "character/motion/1_pc/1_phm/cd_phm_longsword_a.paa"
        available = [
            target,
            "character/motion/1_pc/1_phm/cd_phm_greatsword_b.paa",
            "character/binary/motionblending/phm/x.motionblending",
        ]
        candidates = substitution_candidates(target, available)
        self.assertEqual(candidates, ["character/motion/1_pc/1_phm/cd_phm_greatsword_b.paa"])

    def test_same_archetype_filter(self) -> None:
        target = "character/motion/1_pc/1_phm/cd_phm_longsword_a.paa"
        available = [
            "character/motion/1_pc/1_phm/cd_phm_longsword_b.paa",
            "character/motion/1_pc/1_phm/cd_phm_greatsword_b.paa",
        ]
        self.assertEqual(
            substitution_candidates(target, available, same_archetype=True),
            ["character/motion/1_pc/1_phm/cd_phm_longsword_b.paa"],
        )


if __name__ == "__main__":
    unittest.main()
