from __future__ import annotations

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from cdmw.domain.mesh.body_region_atlas import (
    BODY_REGION_ATLAS_COLOURS,
    UNCLAIMED_COLOUR,
    BodyRegionAtlas,
    build_body_region_atlas,
)
from cdmw.domain.mesh.body_region_falloff import smooth_body_region_weights
from cdmw.domain.mesh.body_regions import build_body_region_map
from cdmw.ui.mesh_editor.body_region_atlas_panel import REGION_ID_ROLE, BodyRegionAtlasPanel

from tests.test_mesh_body_region_sliders import _limb_mesh, _limb_skeleton


def _atlas() -> BodyRegionAtlas:
    mesh = _limb_mesh()
    region_map = smooth_body_region_weights(
        mesh, build_body_region_map(mesh, _limb_skeleton()), band=0.15
    )
    return build_body_region_atlas(region_map)


class AtlasModelTests(unittest.TestCase):
    def test_rows_are_grouped_by_body_part(self) -> None:
        atlas = _atlas()
        self.assertFalse(atlas.empty)
        self.assertTrue(all(group.rows for group in atlas.groups))
        for group in atlas.groups:
            self.assertTrue(all(row.group == group.name for row in group.rows))

    def test_colours_are_stable_and_distinct(self) -> None:
        """A region must keep its colour across list, overlay, and export.

        Assigning by sorted id rather than map order means adding a region
        cannot recolour the others.
        """

        atlas = _atlas()
        first = {row.region_id: row.colour for row in atlas.rows}
        again = {row.region_id: row.colour for row in _atlas().rows}
        self.assertEqual(first, again)
        expected = min(len(first), len(BODY_REGION_ATLAS_COLOURS))
        self.assertGreaterEqual(len({tuple(colour) for colour in first.values()}), expected)

    def test_unknown_region_falls_back_to_the_unclaimed_colour(self) -> None:
        self.assertEqual(_atlas().colour_for("not_a_region"), UNCLAIMED_COLOUR)

    def test_summary_reports_coverage(self) -> None:
        atlas = _atlas()
        self.assertIn("regions", atlas.summary)
        self.assertIn("skin weight claimed", atlas.summary)

    def test_missing_skeleton_becomes_an_explained_warning(self) -> None:
        mesh = _limb_mesh()
        atlas = build_body_region_atlas(build_body_region_map(mesh, None))
        self.assertTrue(atlas.empty)
        self.assertTrue(any("skeleton" in message for message in atlas.warnings))
        self.assertEqual(atlas.summary, "No body regions were resolved.")

    def test_unclaimed_skin_weight_is_warned_about(self) -> None:
        mesh = _limb_mesh()
        # A bone no rule claims, so its surface cannot be reached by sliders.
        skeleton = _limb_skeleton()
        skeleton.bones[1].name = "Prop_Attach_07"
        atlas = build_body_region_atlas(build_body_region_map(mesh, skeleton))
        self.assertTrue(any("no region rule claims" in message for message in atlas.warnings))


class AtlasPanelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self) -> None:
        self.panel = BodyRegionAtlasPanel()
        self.atlas = _atlas()
        self.panel.set_atlas(self.atlas)

    def tearDown(self) -> None:
        self.panel.deleteLater()

    def test_panel_lists_every_region_under_its_group(self) -> None:
        groups = self.panel.tree.topLevelItemCount()
        self.assertEqual(groups, len(self.atlas.groups))
        listed = sum(
            self.panel.tree.topLevelItem(index).childCount() for index in range(groups)
        )
        self.assertEqual(listed, len(self.atlas.rows))

    def test_ticking_a_region_emits_the_selection(self) -> None:
        received: list[tuple[str, ...]] = []
        self.panel.regions_selected.connect(received.append)
        item = self.panel.tree.topLevelItem(0).child(0)
        item.setCheckState(0, Qt.Checked)

        self.assertTrue(received)
        self.assertEqual(received[-1], (str(item.data(0, REGION_ID_ROLE)),))
        self.assertEqual(self.panel.selected_region_ids(), received[-1])

    def test_rebuilding_does_not_emit_once_per_row(self) -> None:
        """The guard matters: a rebuild sets every row's check state."""

        received: list[tuple[str, ...]] = []
        self.panel.regions_selected.connect(received.append)
        self.panel.set_atlas(self.atlas)
        self.assertEqual(len(received), 1)
        self.assertEqual(received[-1], ())

    def test_select_all_then_clear(self) -> None:
        self.panel.select_all_button.click()
        self.assertEqual(len(self.panel.selected_region_ids()), len(self.atlas.rows))
        self.panel.clear_button.click()
        self.assertEqual(self.panel.selected_region_ids(), ())

    def test_generate_requests_the_ticked_regions(self) -> None:
        requested: list[tuple[str, ...]] = []
        self.panel.sliders_requested.connect(requested.append)
        target = self.atlas.rows[0].region_id
        self.panel.set_selected_region_ids([target])
        self.panel.build_button.click()
        self.assertEqual(requested, [(target,)])

    def test_generate_with_nothing_ticked_means_the_whole_body(self) -> None:
        requested: list[tuple[str, ...]] = []
        self.panel.sliders_requested.connect(requested.append)
        self.panel.build_button.click()
        self.assertEqual(requested, [()])

    def test_an_empty_atlas_disables_the_actions(self) -> None:
        """Nothing to build, so the panel must not offer it."""

        self.panel.set_atlas(BodyRegionAtlas(summary="No body regions were resolved."))
        self.assertFalse(self.panel.build_button.isEnabled())
        self.assertFalse(self.panel.tree.isEnabled())
        self.assertEqual(self.panel.selected_region_ids(), ())

    def test_warnings_only_show_when_present(self) -> None:
        self.assertFalse(self.panel.warning_label.isVisible() and not self.atlas.warnings)
        noisy = BodyRegionAtlas(summary="x", warnings=("something is off",))
        self.panel.set_atlas(noisy)
        self.assertEqual(self.panel.warning_label.text(), "something is off")
