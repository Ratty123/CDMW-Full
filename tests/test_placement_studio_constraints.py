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

    def test_soft_chains_sort_first(self) -> None:
        rig = load_constraints(_braid(), "x/rig.papr")
        self.assertTrue(rig.chains[0].soft)

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

    def test_the_panel_says_it_cannot_preview(self) -> None:
        """The one thing the UI must not imply is that the viewport shows the result."""

        panel = self._panel()
        self.assertIn("cannot show this", panel._constraint_note.text())
