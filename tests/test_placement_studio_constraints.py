"""Gates for the Secondary motion panel and the chain model behind it."""

from __future__ import annotations

import os
from pathlib import Path
import struct
import sys
import unittest

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from cdmw.core.papr_format import (  # noqa: E402
    PAPR_VERSION,
    ConstraintEntry,
    PaprDocument,
    PaprHeader,
    encode_papr,
)
from tools.placement_studio.constraints import (  # noqa: E402
    ChainEdit,
    apply_chain_edits,
    build_chains,
    changed_files,
    constraint_path_for_model,
    describe_changes,
    freeze_chain,
    load_constraints,
    set_chain_strength,
)


def _block(*pairs: tuple[str, float]) -> bytes:
    out = bytearray(b"\x05\x03\x00\x03\x04\x00")
    out.append(len(pairs))
    for name, weight in pairs:
        raw = name.encode("ascii")
        out += struct.pack("<H", len(raw)) + raw + struct.pack("<f", weight)
    out += b"\x07\x05\x00"
    return bytes(out)


def _entry(name, parent, *, kind=0, block=b""):
    return ConstraintEntry(name=name, parent=parent, counters=(0, 1),
                           transform=None, kind=kind, block=block)


def _rig_bytes(*entries: ConstraintEntry) -> bytes:
    return encode_papr(PaprDocument(
        header=PaprHeader(version=PAPR_VERSION, payload_bytes=0,
                          entry_count=len(entries), record_count=0),
        entries=tuple(entries),
    ))


def _braid() -> bytes:
    """An undriven anchor with a three-bone driven chain hanging off it."""

    return _rig_bytes(
        _entry("Bip01 Head", "Bip01 Neck"),
        _entry("B_Jiggle_Hair_01", "Bip01 Head", kind=3, block=_block(("Bip01 Head", 50.0))),
        _entry("B_Jiggle_Hair_02", "B_Jiggle_Hair_01", kind=3, block=_block(("Bip01 Head", 30.0))),
        _entry("B_Jiggle_Hair_03", "B_Jiggle_Hair_02", kind=3, block=_block(("Bip01 Head", 10.0))),
        _entry("B_Cloth_Cape", "Bip01 Spine", kind=3, block=_block(("Bip01 Spine", 80.0))),
    )


class ChainTests(unittest.TestCase):
    def test_a_chain_walks_up_to_the_first_undriven_parent(self) -> None:
        rig = load_constraints(_braid(), "x/rig.papr")
        hair = rig.chain_named("B_Jiggle_Hair_01")
        self.assertIsNotNone(hair)
        self.assertEqual(hair.anchor, "Bip01 Head")
        self.assertEqual([m.name for m in hair.members],
                         ["B_Jiggle_Hair_01", "B_Jiggle_Hair_02", "B_Jiggle_Hair_03"])

    def test_undriven_bones_are_not_chains(self) -> None:
        rig = load_constraints(_braid(), "x/rig.papr")
        self.assertIsNone(rig.chain_named("Bip01 Head"))
        self.assertEqual(len(rig.chains), 2)

    def test_strength_is_the_mean_of_the_chain_weights(self) -> None:
        rig = load_constraints(_braid(), "x/rig.papr")
        self.assertAlmostEqual(rig.chain_named("B_Jiggle_Hair_01").strength, 30.0, places=3)

    def test_jiggle_chains_sort_above_soft_body(self) -> None:
        rig = load_constraints(_braid(), "x/rig.papr")
        self.assertEqual(rig.chains[0].category, "jiggle")
        self.assertEqual(rig.chains[1].category, "soft")

    def test_deformation_is_the_category_a_player_rig_is_full_of(self) -> None:
        """The `Jiggle` names invite the wrong guess; the classifier must not repeat it."""

        from tools.placement_studio.constraints import classify_chain

        self.assertEqual(classify_chain("Bip01 L UpperFMuscle"), "deformation")
        self.assertEqual(classify_chain("Bip01 R Knee_Sub"), "deformation")
        self.assertEqual(classify_chain("Bip01 L UpArmTwist_Bottom"), "deformation")
        self.assertEqual(classify_chain("ExposeTransform_Bip01 L Hand"), "expose")
        self.assertEqual(classify_chain("P_Bip01 R Chest"), "pivot")
        self.assertEqual(classify_chain("B_Jiggle_M_Root"), "jiggle")
        self.assertEqual(classify_chain("B_Golem_piston_Syl_B_01"), "mechanical")

    def test_a_jiggle_name_wins_over_a_deformation_hint(self) -> None:
        """`B_Jiggle_M_Pelvis` contains no deformation word, but order still matters."""

        self.assertEqual(
            __import__("tools.placement_studio.constraints", fromlist=["x"])
            .classify_chain("B_Jiggle_Knee_Sub"),
            "jiggle",
        )

    def test_a_parent_cycle_terminates_and_places_every_bone_once(self) -> None:
        """A rig that names itself as its own ancestor must not spin, and must not
        drop a bone or list one twice."""

        data = _rig_bytes(
            _entry("A", "B", kind=3, block=_block(("X", 50.0))),
            _entry("B", "A", kind=3, block=_block(("X", 50.0))),
        )
        chains = build_chains(load_constraints(data, "x").document)
        placed = [m.name for chain in chains for m in chain.members]
        self.assertCountEqual(placed, ["A", "B"])

    def test_every_driven_bone_lands_in_exactly_one_chain(self) -> None:
        rig = load_constraints(_braid(), "x/rig.papr")
        placed = [m.name for chain in rig.chains for m in chain.members]
        driven = [e.name for e in rig.document.entries if e.driven]
        self.assertCountEqual(placed, driven)


class EditTests(unittest.TestCase):
    def test_setting_a_strength_scales_the_whole_chain(self) -> None:
        rig = load_constraints(_braid(), "x/rig.papr")
        edited = set_chain_strength(rig, "B_Jiggle_Hair_01", 15.0)
        self.assertAlmostEqual(edited.chain_named("B_Jiggle_Hair_01").strength, 15.0, delta=1.0)
        # The other chain is untouched.
        self.assertEqual(edited.chain_named("B_Cloth_Cape").strength, 80.0)

    def test_freezing_a_chain_zeroes_it(self) -> None:
        rig = load_constraints(_braid(), "x/rig.papr")
        self.assertEqual(freeze_chain(rig, "B_Cloth_Cape").chain_named("B_Cloth_Cape").strength, 0.0)

    def test_an_unknown_chain_is_reported_not_applied(self) -> None:
        rig = load_constraints(_braid(), "x/rig.papr")
        _edited, missing = apply_chain_edits(rig, [ChainEdit("nope", 0.5)])
        self.assertEqual(missing, ("nope",))

    def test_repeated_edits_stay_findable(self) -> None:
        """Rounding to whole percent is what keeps a second edit possible."""

        rig = load_constraints(_braid(), "x/rig.papr")
        once, _ = apply_chain_edits(rig, [ChainEdit("B_Cloth_Cape", 0.5)])
        twice, _ = apply_chain_edits(once, [ChainEdit("B_Cloth_Cape", 0.5)])
        self.assertEqual(twice.chain_named("B_Cloth_Cape").strength, 20.0)

    def test_an_unchanged_rig_exports_nothing(self) -> None:
        data = _braid()
        self.assertEqual(changed_files(data, load_constraints(data, "x/rig.papr")), {})

    def test_a_changed_rig_exports_its_game_path(self) -> None:
        data = _braid()
        rig = load_constraints(data, "character/model/x/rig.papr")
        files = changed_files(data, freeze_chain(rig, "B_Cloth_Cape"))
        self.assertEqual(list(files), ["character/model/x/rig.papr"])
        self.assertNotEqual(files["character/model/x/rig.papr"], data)

    def test_changes_are_described_in_plain_english(self) -> None:
        rig = load_constraints(_braid(), "x/rig.papr")
        lines = describe_changes(rig, freeze_chain(rig, "B_Cloth_Cape"))
        self.assertEqual(len(lines), 1)
        self.assertIn("switched off", lines[0])


class PathMatchTests(unittest.TestCase):
    KNOWN = (
        "character/model/1_pc/1_phm/phm_01.papr",
        "character/model/1_pc/2_phw/phw_01.papr",
        "character/model/2_mon/cd_m0001_00_twofeet/cd_m0001_00_bear/cd_m0001_00_bear.papr",
    )

    def test_a_model_resolves_to_the_rig_in_its_own_directory(self) -> None:
        self.assertEqual(
            constraint_path_for_model("character/model/1_pc/1_phm/phm_01.pac", self.KNOWN),
            "character/model/1_pc/1_phm/phm_01.papr",
        )

    def test_a_nested_model_resolves_to_the_nearest_parent_rig(self) -> None:
        self.assertEqual(
            constraint_path_for_model(
                "character/model/1_pc/1_phm/parts/head.pac", self.KNOWN
            ),
            "character/model/1_pc/1_phm/phm_01.papr",
        )

    def test_an_unrelated_model_resolves_to_nothing(self) -> None:
        self.assertIsNone(constraint_path_for_model("object/props/barrel.pac", self.KNOWN))

    def test_an_empty_path_resolves_to_nothing(self) -> None:
        self.assertIsNone(constraint_path_for_model("", self.KNOWN))


class PanelTests(unittest.TestCase):
    """The panel drives the same model; these run offscreen."""

    @classmethod
    def setUpClass(cls) -> None:
        pytest.importorskip("PySide6")
        from PySide6.QtWidgets import QApplication

        cls.app = QApplication.instance() or QApplication([])

    def _panel(self):
        from tools.placement_studio.window_constraints import SecondaryMotionMixin

        class Panel(SecondaryMotionMixin):
            pass

        panel = Panel()
        # Hold the widget: Qt owns the children, and letting it fall out of scope
        # deletes them under the mixin.
        panel._root_widget = panel._build_secondary_motion_tab()
        return panel

    def test_loading_a_rig_fills_the_chain_table(self) -> None:
        panel = self._panel()
        self.assertIsNone(panel.load_constraint_rig(_braid(), "x/rig.papr"))
        self.assertEqual(panel._chain_table.rowCount(), 2)

    def test_a_bad_rig_reports_instead_of_raising(self) -> None:
        panel = self._panel()
        error = panel.load_constraint_rig(b"not a rig", "x/bad.papr")
        self.assertIsNotNone(error)
        self.assertEqual(panel._chain_table.rowCount(), 0)

    def test_selecting_a_chain_lists_its_weights(self) -> None:
        panel = self._panel()
        panel.load_constraint_rig(_braid(), "x/rig.papr")
        panel._chain_table.selectRow(0)
        self.assertGreater(panel._chain_detail.rowCount(), 0)
        self.assertTrue(panel._chain_slider.isEnabled())

    def test_turning_a_chain_off_shows_a_pending_change(self) -> None:
        panel = self._panel()
        panel.load_constraint_rig(_braid(), "x/rig.papr")
        panel._chain_table.selectRow(0)
        panel._on_chain_off()
        self.assertIn("switched off", panel._constraint_pending.text())
        self.assertTrue(panel.constraint_mod_files())

    def test_reset_puts_the_rig_back_and_clears_the_export(self) -> None:
        panel = self._panel()
        panel.load_constraint_rig(_braid(), "x/rig.papr")
        panel._chain_table.selectRow(0)
        panel._on_chain_off()
        panel._on_chain_reset()
        self.assertEqual(panel._constraint_pending.text(), "No changes.")
        self.assertEqual(panel.constraint_mod_files(), {})

    def test_the_panel_warns_that_the_game_may_not_read_the_file(self) -> None:
        """The most useful thing the tool knows is bad news, so it must be on screen."""

        panel = self._panel()
        text = panel._constraint_warning.text().lower()
        self.assertIn("no evidence the game reads", text)
        self.assertIn("jiggledescriptor.xml", text)

    def test_the_panel_says_it_cannot_preview(self) -> None:
        """The one thing the UI must not imply is that the viewport shows the result."""

        panel = self._panel()
        self.assertIn("cannot show this", panel._constraint_note.text())

    def test_softer_and_stiffer_move_the_strength_in_whole_steps(self) -> None:
        panel = self._panel()
        panel.load_constraint_rig(_braid(), "x/rig.papr")
        panel._chain_table.selectRow(0)
        before = panel._rig_constraints.chains[0].strength
        panel._nudge(-5)
        after = panel._rig_constraints.chain_named(panel._selected_chain_name()).strength
        self.assertLess(after, before)
        self.assertEqual(after, round(after))

    def test_export_is_disabled_until_something_changes(self) -> None:
        panel = self._panel()
        panel.load_constraint_rig(_braid(), "x/rig.papr")
        self.assertFalse(panel._constraint_export.isEnabled())
        panel._chain_table.selectRow(0)
        panel._on_chain_off()
        self.assertTrue(panel._constraint_export.isEnabled())

    def test_exporting_an_unchanged_rig_says_so_instead_of_writing(self) -> None:
        import tempfile

        panel = self._panel()
        panel.load_constraint_rig(_braid(), "x/rig.papr")
        with tempfile.TemporaryDirectory() as tmp:
            self.assertIn("Nothing to export", panel.export_constraint_mod(tmp))
            self.assertEqual(list(Path(tmp).iterdir()), [])

    def test_exporting_a_change_writes_packages(self) -> None:
        import tempfile

        panel = self._panel()
        panel.load_constraint_rig(_braid(), "character/model/x/rig.papr")
        panel._chain_table.selectRow(0)
        panel._on_chain_off()
        panel._constraint_mod_name.setText("Calmer hair")
        with tempfile.TemporaryDirectory() as tmp:
            message = panel.export_constraint_mod(tmp)
            self.assertIn("Wrote", message)
            self.assertTrue(any(Path(tmp).iterdir()))

    def test_the_chain_table_marks_how_much_is_decoded(self) -> None:
        panel = self._panel()
        panel.load_constraint_rig(_braid(), "x/rig.papr")
        marks = {
            panel._chain_table.item(row, 4).text()
            for row in range(panel._chain_table.rowCount())
        }
        self.assertTrue(marks <= {"full", "partial"})

    def test_the_chain_table_says_what_each_chain_is_for(self) -> None:
        panel = self._panel()
        panel.load_constraint_rig(_braid(), "x/rig.papr")
        kinds = {
            panel._chain_table.item(row, 1).text()
            for row in range(panel._chain_table.rowCount())
        }
        self.assertEqual(kinds, {"jiggle", "soft"})


class CapabilityTests(unittest.TestCase):
    """The panel promises exactly what the code can do, and no more."""

    def test_capabilities_cover_both_sides(self) -> None:
        from tools.placement_studio.constraints import CAPABILITIES

        self.assertTrue(any(allowed for allowed, _text in CAPABILITIES))
        self.assertTrue(any(not allowed for allowed, _text in CAPABILITIES))

    def test_the_things_marked_possible_have_a_function_behind_them(self) -> None:
        from cdmw.core import papr_format
        from tools.placement_studio import constraints

        for name in ("set_chain_strength", "freeze_chain"):
            self.assertTrue(callable(getattr(constraints, name)))
        for name in ("rename_bone", "set_transform", "set_weights"):
            self.assertTrue(callable(getattr(papr_format, name)))

    def test_adding_a_chain_is_listed_as_impossible(self) -> None:
        """There is no API for it, so the UI must not suggest one."""

        from cdmw.core import papr_format
        from tools.placement_studio.constraints import CAPABILITIES

        self.assertFalse(hasattr(papr_format, "add_entry"))
        denied = " ".join(text for allowed, text in CAPABILITIES if not allowed).lower()
        self.assertIn("add a new chain", denied)
