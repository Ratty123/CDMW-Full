"""Identity, stats, effects, and guided-layout cases for the New Item Studio tab."""

from __future__ import annotations

import os
import sys
import tempfile
import threading
import time
import unittest
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "tests"))

from cdmw.core.archive_format import parse_archive_pamt  # noqa: E402
from cdmw.domain.new_item.spec import UNLIMITED_STOCK, MaterialRoute, ModelSource, PlacementKind, SheathedModel  # noqa: E402
from cdmw.services.new_item_service import NewItemService  # noqa: E402
from cdmw.ui.new_item.state import (  # noqa: E402
    NewItemDraft,
    flat_grid_values,
    scaled_grid_values,
    spec_from_draft,
    stat_edits_from_grid,
    stat_grid_for,
    with_template,
)
from cdmw.ui.new_item.workflow_header import WorkflowStepState  # noqa: E402
from test_iteminfo_row import COPPER, DDD, build_row  # noqa: E402
from test_new_item_service import OTHER, TEMPLATE, _read, build_package, synthetic_files  # noqa: E402


class _TabAuthoringMixin:
    def test_the_import_brings_its_own_dependency_context(self) -> None:
        """The headless build over the template's mesh takes the archive maps the
        Builder's import wants; the studio builds them from its own listing (the whole
        listing behind the path and basename maps, the family files as the bounded member
        list), so the Archive Browser's selection plays no part in an import."""

        from cdmw.ui.archive_browser.workflow_dependencies import ArchiveWorkflowDependencyContext

        tab = self._tab()
        tab.prefill_template(TEMPLATE)
        context = tab.controller.import_dependency_context()
        self.assertIsInstance(context, ArchiveWorkflowDependencyContext)
        entries = tab.controller.template_entries()
        self.assertTrue(entries)
        self.assertEqual(context.selected_entry.path, entries[0].path)
        self.assertIsNotNone(context.entry_for_path(entries[0].path))
        self.assertFalse(context.remote)
        self.assertIn(entries[0].path.rsplit("/", 1)[-1].lower(), {k.lower() for k in context.entries_by_basename})
        by_path, by_basename = tab.controller.snapshot.archive_index_maps()
        self.assertIs(context.entries_by_normalized_path, by_path, "the whole listing, built once")
        self.assertIs(context.entries_by_basename, by_basename)
        tab.close()
        tab.deleteLater()

    def test_one_copper_and_the_folded_advanced_controls(self) -> None:
        tab = self._tab()
        tab.prefill_template(TEMPLATE)
        stats = tab.stats_panel
        self.assertFalse(stats.advanced.isVisibleTo(stats), "advanced controls start folded")
        stats.one_copper_button.click()
        spec = tab.controller.current_spec()
        self.assertTrue(spec.buy_price_edits and all(e.price == 1 for e in spec.buy_price_edits), spec.buy_price_edits)
        self.assertTrue(spec.price_edits and all(e.price == 1 for e in spec.price_edits), spec.price_edits)
        stats.advanced_toggle.setChecked(True)
        self.assertTrue(stats.advanced.isVisibleTo(stats))
        stats.reset_button.click()
        self.assertEqual(tab.controller.current_spec().price_edits, ())
        # the step navigator: one page at a time, Back/Next, the rail's "item so far" names
        # the template and tints what still wants a decision
        self.assertEqual(tab.steps.count(), 7)
        self.assertEqual(tab.pages.currentIndex(), 0)
        tab.next_button.click()
        self.assertEqual(tab.pages.currentIndex(), 1)
        tab.show_step(3)
        self.assertEqual(tab.steps.currentRow(), 3)
        self.assertIn("Step 4 of 7", tab.step_hint.text())
        self.assertIn("Ziane_OneHandSword", tab.summary.text())
        from cdmw.ui.new_item.ui_kit import OK, WARN, tone_color

        self.assertIn(tone_color(WARN), tab.summary.text(), "no name yet: an amber line")
        self.assertIn(tone_color(OK), tab.summary.text(), "the template: a green line")
        self.assertIn("Plan: not built yet", tab.summary.plain_text())
        # the step list is as tall as its lines, not a page-high blank
        self.assertLess(tab.steps.height(), 260)
        # the identity checks: nothing blocks with a name in place
        tab.identity_panel.internal_name.setText("Wolf_Fang_OneHandSword")
        tab.identity_panel.display_name.setText("Wolf's Fang")
        self.assertTrue(tab.identity_panel.issues_ok.isVisibleTo(tab.identity_panel))
        # the placement note is amber while nothing sells the item
        self.assertIn("Not sold anywhere", tab.placement_panel.requirement_note.plain_text())
        tab.close()
        tab.deleteLater()

    def test_identity_controls_expose_automatic_and_manual_values(self) -> None:
        from PySide6.QtGui import QValidator

        tab = self._tab()
        tab.prefill_template(TEMPLATE)
        identity = tab.identity_panel

        self.assertEqual(identity.internal_name.maxLength(), 64)
        self.assertEqual(identity.stem.maxLength(), 64)
        self.assertEqual(
            identity.internal_name.validator().validate("9 bad name", 0)[0],
            QValidator.State.Invalid,
        )
        self.assertEqual(
            identity.internal_name.validator().validate("My_Clone2", 0)[0],
            QValidator.State.Acceptable,
        )
        self.assertEqual(
            identity.stem.validator().validate("CD_PHM/Sword", 0)[0],
            QValidator.State.Invalid,
        )
        self.assertEqual(
            identity.stem.validator().validate("cd_phm_01_sword_9109", 0)[0],
            QValidator.State.Acceptable,
        )

        self.assertFalse(identity.item_key_manual.isChecked())
        self.assertFalse(identity.item_key.isEnabled())
        self.assertIsNone(tab.controller.draft.item_key)
        self.assertEqual(identity.item_key_state.property("identityState"), "auto")
        identity.item_key_manual.click()
        self.assertTrue(identity.item_key.isEnabled())
        self.assertEqual(identity.item_key.minimum(), 1)
        self.assertEqual(identity.item_key.value(), 1_990_000)
        self.assertEqual(tab.controller.draft.item_key, 1_990_000)
        identity.item_key.setValue(0)
        self.assertEqual(identity.item_key.value(), 1)
        self.assertEqual(tab.controller.draft.item_key, 1)
        identity.item_key.setValue(1_990_005)
        self.assertEqual(tab.controller.draft.item_key, 1_990_005)
        identity.item_key_manual.click()
        self.assertFalse(identity.item_key.isEnabled())
        self.assertEqual(identity.item_key.minimum(), 0)
        self.assertEqual(identity.item_key.value(), 0)
        self.assertIsNone(tab.controller.draft.item_key)

        tab.model_panel.import_model.setChecked(True)
        self.assertFalse(identity.stem_manual.isChecked())
        self.assertFalse(identity.stem.isEnabled())
        identity.stem_manual.click()
        self.assertTrue(identity.stem.isEnabled())
        self.assertEqual(identity.stem.text(), "cd_phm_01_sword_9109")
        self.assertEqual(tab.controller.draft.stem, "cd_phm_01_sword_9109")
        identity.stem_manual.click()
        self.assertFalse(identity.stem.isEnabled())
        self.assertEqual(identity.stem.text(), "")
        self.assertEqual(tab.controller.draft.stem, "")

        identity.display_name.setText("Test item")
        identity.internal_name.setText("Ziane_OneHandSword")
        self.assertEqual(identity.internal_name.text(), "Ziane_OneHandSword")
        self.assertEqual(tab.controller.draft.internal_name, "Ziane_OneHandSword")
        self.assertIn("internal_name.taken", {issue.code for issue in tab.controller.validate()})
        self.assertEqual(identity.internal_name_state.property("identityState"), "block")
        self.assertIn("already exists", identity.internal_name_state.toolTip())
        tab.close()
        tab.deleteLater()

    def test_stats_and_perk_resets_clear_hidden_state_and_safe_limits(self) -> None:
        tab = self._tab()
        tab.prefill_template(TEMPLATE)
        stats = tab.stats_panel
        stats.advanced_toggle.setChecked(True)
        stats.own_rows.setChecked(True)
        stats.table.setCurrentCell(0, 0)
        stats.flat.setValue(25000)
        stats.flat_button.click()
        self.assertEqual([stats.table.item(level, 0).text() for level in range(2)], ["25000", "25000"])
        self.assertTrue(tab.controller.draft.own_enhancement_rows)
        stats.reset_button.click()
        self.assertFalse(stats.own_rows.isChecked())
        self.assertFalse(tab.controller.draft.own_enhancement_rows)
        self.assertEqual(stats.summary_text(), ("Combat and prices: template values", False))

        perks = tab.perks_panel
        perks.own_perks.setChecked(True)
        while len(tab.controller.draft.socket_items) < 4:
            perks._add_selected()
        self.assertEqual(len(tab.controller.draft.socket_items), 4)
        self.assertFalse(perks.add_button.isEnabled(), "five perks require an explicit experimental opt-in")
        perks.experimental_perks.setChecked(True)
        self.assertTrue(perks.add_button.isEnabled())
        perks._add_selected()
        self.assertEqual(len(tab.controller.draft.socket_items), 5)
        self.assertIn("experimental", perks.perk_count.text().lower())
        perks.reset_button.click()
        self.assertFalse(perks.own_perks.isChecked())
        self.assertIsNone(tab.controller.draft.socket_items)
        self.assertEqual(perks.perks_summary(), ("Perks: template list (1)", False))
        tab.close()
        tab.deleteLater()

    def test_stats_edits_refresh_the_rail_once_and_a_refill_not_at_all(self) -> None:
        """The tab used to refresh the rail from the stats tables' itemChanged, which Qt
        emits once per cell a refill writes, and every refresh validated the draft twice.
        A refill now runs neither; one edit runs one of each, after the draft changed."""

        tab = self._tab()
        tab.prefill_template(TEMPLATE)
        tab.identity_panel.internal_name.setText("Wolf_Fang_OneHandSword")
        tab.identity_panel.display_name.setText("Wolf's Fang")
        stats = tab.stats_panel
        counts = {"summary": 0, "validate": 0}
        summary_text, validate = stats.summary_text, tab.controller.validate

        def counted_summary_text():
            counts["summary"] += 1
            return summary_text()

        def counted_validate():
            counts["validate"] += 1
            return validate()

        from PySide6.QtCore import Qt

        from cdmw.ui.new_item.ui_kit import EDIT, tone_color

        with patch.object(stats, "summary_text", counted_summary_text), patch.object(tab.controller, "validate", counted_validate):
            stats.rebuild()
            self.assertEqual((counts["summary"], counts["validate"]), (0, 0), "a refill is not an edit")
            stats.table.item(0, 0).setText("20000")
            self.assertEqual((counts["summary"], counts["validate"]), (1, 1))
            self.assertIn("1 stat cell(s)", tab.summary.plain_text(), "the rail read the draft after the edit")
            self.assertEqual(stats.table.item(0, 0).foreground().color().name(), tone_color(EDIT), "an edited cell turns blue at once")
            stats.table.item(0, 0).setText("12000")
            self.assertIsNone(stats.table.item(0, 0).data(Qt.ForegroundRole), "back on the template: the default look, not a null brush")
            counts.update(summary=0, validate=0)
            stats.advanced_toggle.setChecked(True)
            stats.add_level_button.click()
            self.assertEqual((counts["summary"], counts["validate"]), (1, 1), "a rebuild plus one invalidation")
            self.assertIn("1 added level(s)", tab.summary.plain_text())
            counts.update(summary=0, validate=0)
            choices = [stats.new_stat.itemData(i) for i in range(stats.new_stat.count())]
            stats.new_stat.setCurrentIndex(choices.index(1000007))
            stats.add_stat_button.click()
            self.assertEqual((counts["summary"], counts["validate"]), (1, 1))
            self.assertIn("1 added stat(s)", tab.summary.plain_text())
            self.assertNotIn("price field", tab.summary.plain_text(), "the rail read the grid after the column was inserted, not before")
        tab.close()
        tab.deleteLater()

    def test_empty_price_list_can_add_one_copper_from_stats_or_distribution(self) -> None:
        tab = self._tab()
        tab.start_snapshot()
        snapshot = tab.controller.snapshot
        snapshot.rows[TEMPLATE] = replace(snapshot.rows[TEMPLATE], price_list=())
        snapshot._contexts.clear()
        tab.prefill_template(TEMPLATE)

        stats = tab.stats_panel
        self.assertEqual(stats.price_table.rowCount(), 0)
        self.assertIn("No shop price", stats.price_state.plain_text())
        self.assertTrue(stats.one_copper_button.isEnabled())

        placement = tab.placement_panel
        placement.insert.setChecked(True)
        self.assertIn("No shop price", placement.price_note.plain_text())
        self.assertTrue(placement.set_copper_price_button.isVisibleTo(placement))
        placement.set_copper_price_button.click()

        self.assertEqual(stats.price_table.rowCount(), 1)
        self.assertEqual(stats.price_table.item(0, 0).text(), "Money_Copper")
        self.assertEqual(stats.price_table.item(0, 1).text(), "1")
        self.assertEqual([(p.item_key, p.price) for p in tab.controller.current_spec().price_edits], [(COPPER, 1)])
        self.assertEqual(placement.price_value.text(), "Money_Copper: 1")
        self.assertFalse(placement.price_note.isVisibleTo(placement))

        stats.reset_button.click()
        self.assertEqual(stats.price_table.rowCount(), 0)
        stats.one_copper_button.click()
        self.assertEqual([(p.item_key, p.price) for p in tab.controller.current_spec().price_edits], [(COPPER, 1)])
        tab.close()
        tab.deleteLater()

    def test_template_without_a_decoded_stat_block_explains_price_blocker(self) -> None:
        tab = self._tab()
        tab.start_snapshot()
        snapshot = tab.controller.snapshot
        snapshot.rows[TEMPLATE] = replace(
            snapshot.rows[TEMPLATE],
            socket_items=(),
            add_socket_materials=(),
            stat_block_offset=None,
            enchant_levels=(),
            enchant_count=None,
            price_list=(),
            stat_block_end=None,
        )
        snapshot._contexts.clear()
        tab.prefill_template(TEMPLATE)

        stats = tab.stats_panel
        self.assertFalse(stats.one_copper_button.isEnabled())
        self.assertIn("did not decode", stats.price_state.plain_text())
        placement = tab.placement_panel
        placement.insert.setChecked(True)
        self.assertIn("did not decode", placement.price_note.plain_text())
        self.assertFalse(placement.set_copper_price_button.isVisibleTo(placement))
        tab.identity_panel.internal_name.setText("Unpriced_Test_Helm")
        tab.identity_panel.display_name.setText("Unpriced Test Helm")
        issue_codes = {issue.code for issue in tab.controller.validate()}
        self.assertIn("template.no_stat_block", issue_codes)
        self.assertIn("placement.price_missing", issue_codes)
        tab.close()
        tab.deleteLater()

    def test_hidden_stats_tables_defer_layout_sizing_until_the_step_opens(self) -> None:
        from cdmw.ui.new_item import panels_stats
        from cdmw.ui.new_item.item_preview import ItemPreviewFrame

        tab = self._tab()
        tab.resize(1280, 720)
        tab.start_snapshot()
        tab.show()
        self.app.processEvents()
        original = panels_stats.compact_table_height
        with patch.object(ItemPreviewFrame, "_start_package", lambda *_args, **_kwargs: None), patch.object(
            panels_stats,
            "compact_table_height",
            wraps=original,
        ) as compact:
            tab.prefill_template(TEMPLATE)
            self.assertEqual(compact.call_count, 0, "a template choice must not lay out a hidden stats step")
            self.assertTrue(tab.stats_panel._table_resize_pending)
            tab.show_step(3)
            self.app.processEvents()
            self.assertEqual(compact.call_count, 2, "both stats tables size once when their step becomes visible")
            self.assertFalse(tab.stats_panel._table_resize_pending)
        tab.shutdown()
        tab.close()
        tab.deleteLater()

    def test_a_typo_in_a_cell_goes_back_without_a_rebuild_and_the_note_compares(self) -> None:
        tab = self._tab()
        tab.prefill_template(TEMPLATE)
        stats = tab.stats_panel
        stats.table.item(0, 0).setText("20000")
        with patch.object(stats, "rebuild", side_effect=AssertionError("a typo must not re-lay the step")):
            stats.table.item(0, 0).setText("twenty")
        self.assertEqual(stats.table.item(0, 0).text(), "20000", "the last valid value came back into that one cell")
        self.assertEqual(tab.controller.draft.grid_values[(0, 0)], 20000)
        self.assertIn("not a whole number", stats.selection_note.plain_text())
        # the selection note: the cell, the comparison, the shipped range; three short lines
        stats.table.setCurrentCell(1, 0)
        stats.table.setCurrentCell(0, 0)
        text = stats.selection_note.plain_text()
        self.assertIn("Level 0 Attack (DDD): 20,000", text)
        self.assertIn("Template: 12,000 (+8,000, +66.7%)", text)
        self.assertIn("Shipped equipment:", text)
        stats.table.setCurrentCell(1, 1)
        text = stats.selection_note.plain_text()
        self.assertIn("Level 1 Price (Money_Copper): 384", text)
        self.assertIn("Template: 384, unchanged", text)
        self.assertIn("Currency, not a combat stat", text)
        stats.price_table.item(0, 1).setText("lots")
        self.assertEqual(stats.price_table.item(0, 1).text(), "348", "a base price typo goes back the same way")
        tab.close()
        tab.deleteLater()

    def test_added_levels_can_be_removed_and_the_buttons_name_their_targets(self) -> None:
        tab = self._tab()
        tab.prefill_template(TEMPLATE)
        stats = tab.stats_panel
        stats.advanced_toggle.setChecked(True)
        self.assertFalse(stats.remove_level_button.isEnabled())
        stats.add_level_button.click()
        self.assertEqual(stats.table.rowCount(), 3)
        self.assertEqual(stats.table.verticalHeaderItem(2).text(), "Level 2 (added)")
        self.assertTrue(stats.remove_level_button.isEnabled())
        stats.table.item(2, 0).setText("15000")
        stats.remove_level_button.click()
        self.assertEqual(stats.table.rowCount(), 2)
        self.assertEqual(tab.controller.draft.extra_levels, 0)
        self.assertNotIn((2, 0), tab.controller.draft.grid_values, "the dropped level took its values with it")
        self.assertFalse(stats.remove_level_button.isEnabled())
        for _ in range(8):
            stats.add_level_button.click()
        self.assertEqual(tab.controller.draft.extra_levels, 8)
        self.assertFalse(stats.add_level_button.isEnabled(), "the cap disables the button instead of ignoring the click")
        stats.table.setCurrentCell(0, 0)
        self.assertEqual(stats.flat_button.text(), "Set Attack (DDD) at every level")
        stats.table.setCurrentCell(0, 1)
        self.assertEqual(stats.flat_button.text(), "Set Attack (DDD) at every level", "a price cell falls back to the first stat column")
        self.assertFalse(stats.remove_stat_button.isEnabled())
        self.assertEqual(stats.remove_stat_button.text(), "Remove column")
        choices = [stats.new_stat.itemData(i) for i in range(stats.new_stat.count())]
        stats.new_stat.setCurrentIndex(choices.index(1000007))
        stats.add_stat_button.click()
        self.assertTrue(stats.remove_stat_button.isEnabled())
        self.assertEqual(stats.remove_stat_button.text(), "Remove the Critical rate (CriticalRate) column")
        stats.table.setCurrentCell(0, 0)
        self.assertEqual(stats.remove_stat_button.text(), "Remove the Critical rate (CriticalRate) column", "a template column selected: the button still names the added one it drops")
        stats.remove_stat_button.click()
        self.assertEqual(tab.controller.draft.extra_stat_keys, [])
        self.assertEqual(stats.table.columnCount(), 3)
        self.assertEqual(stats.remove_stat_button.text(), "Remove column")
        tab.close()
        tab.deleteLater()

    def test_effect_support_is_structural_not_an_equipment_name_blocklist(self) -> None:
        tab = self._tab()
        tab.prefill_template(TEMPLATE)
        perks = tab.perks_panel
        self.assertTrue(perks.use_effect.isEnabled())
        with patch.object(type(tab.controller.snapshot), "equip_type_name", lambda _self, _row: "Helm"):
            perks._refresh_effect_support()
            self.assertTrue(perks.use_effect.isEnabled())
            self.assertIn("Available", perks.effect_support.plain_text())
        tab.close()
        tab.deleteLater()

    def test_perk_search_list_double_click_adds_and_remove_button_removes(self) -> None:
        from PySide6.QtCore import Qt
        from PySide6.QtTest import QTest

        tab = self._tab()
        tab.resize(1280, 720)
        tab.show()
        tab.prefill_template(TEMPLATE)
        tab.show_step(4)
        perks = tab.perks_panel
        perks.own_perks.setChecked(True)
        perks.perk_filter.setText("Swift")
        self.app.processEvents()
        item = perks.perk_results.item(0)
        self.assertIsNotNone(item)
        self.assertNotIn("experimental", item.text().casefold(), "the III suffix already identifies the perk rank")
        self.assertIn("experimental", item.toolTip().casefold(), "the evidence warning stays in the perk details")
        standalone_row = tab.controller.snapshot.rows[1002791]
        standalone_label = tab.controller._perk_label(
            1002791,
            standalone_row,
            tab.controller.snapshot.english.index(),
            {},
        )
        self.assertTrue(standalone_label.endswith(" — experimental"), "an unproven standalone perk keeps the marker")
        before = tuple(tab.controller.draft.socket_items or ())
        QTest.mouseClick(
            perks.perk_results.viewport(),
            Qt.MouseButton.LeftButton,
            pos=perks.perk_results.visualItemRect(item).center(),
        )
        QTest.mouseDClick(
            perks.perk_results.viewport(),
            Qt.MouseButton.LeftButton,
            pos=perks.perk_results.visualItemRect(item).center(),
        )
        self.assertEqual(tuple(tab.controller.draft.socket_items or ()), (*before, 1002812))
        perks.chosen.setCurrentRow(perks.chosen.count() - 1)
        perks.remove_button.click()
        self.assertEqual(tuple(tab.controller.draft.socket_items or ()), before)
        tab.close()
        tab.deleteLater()
        self.app.processEvents()
    def test_guided_effect_navigation_applies_discards_or_stays(self) -> None:
        tab = self._tab()
        tab.prefill_template(TEMPLATE)
        self.assertEqual(tab.steps.stepState(0), WorkflowStepState.COMPLETED)
        effects = tab.perks_panel.effects_workspace
        effects._confirm_unreviewed = lambda _reason: True
        tab.show_step(4)
        effects.choose_effect("fx_test_fire")
        self.assertTrue(effects.has_staged_changes())
        self.assertFalse(tab.continue_button.isEnabled())
        self.assertEqual(tab.steps.stepState(4), WorkflowStepState.PENDING)

        tab._effect_dirty_prompt = lambda: "stay"
        tab.show_step(5)
        self.assertEqual((tab.steps.currentRow(), tab.pages.currentIndex()), (4, 4))
        self.assertEqual(tab.controller.draft.effect_stem, "")

        tab._effect_dirty_prompt = lambda: "discard"
        tab.show_step(5)
        self.assertEqual((tab.steps.currentRow(), tab.pages.currentIndex()), (5, 5))
        self.assertFalse(effects.has_staged_changes())
        self.assertEqual(tab.controller.draft.effect_stem, "")

        tab.show_step(4)
        effects.choose_effect("fx_test_fire")
        tab._effect_dirty_prompt = lambda: "apply"
        tab.show_step(5)
        self.assertEqual((tab.steps.currentRow(), tab.pages.currentIndex()), (5, 5))
        self.assertEqual(tab.controller.draft.effect_stem, "fx_test_fire")
        self.assertFalse(effects.has_staged_changes())
        self.assertEqual(tab.steps.stepState(4), WorkflowStepState.COMPLETED)
        tab.request_shutdown()
        tab.close()
        tab.deleteLater()

    def test_guided_shell_geometry_matches_the_three_pane_contract(self) -> None:
        tab = self._tab()
        tab.start_snapshot()
        effects = tab.perks_panel.effects_workspace
        effects._host_factory = lambda _parent: None
        tab.prefill_template(TEMPLATE)
        tab.show_step(4)
        from cdmw.modding.mesh_parser import ParsedMesh, SubMesh

        blade = ParsedMesh(
            path="blade",
            format="pac",
            submeshes=[SubMesh(name="b", vertices=[(0, 0, 0)] * 3, faces=[(0, 1, 2)])],
        )
        with patch.object(type(tab.controller), "item_mesh_as_planned", return_value=(blade, "template")):
            effects._rebuild_preview()
        tab.show()
        for width, height in ((1280, 720), (1600, 900)):
            tab.resize(width, height)
            self.app.processEvents()
            self.assertEqual(tab.steps.height(), 46)
            self.assertEqual(tab.step_hint.text(), "Step 5 of 7")
            self.assertEqual(tab.back_button.text(), "Back")
            self.assertEqual(tab.continue_button.text(), "Continue")
            outer = effects.splitter.sizes()
            placement = effects.placement
            self.assertIsNotNone(placement)
            inner = placement.preview_splitter.sizes()
            total = float(sum(outer))
            left = outer[0] / total
            centre = outer[1] / total * inner[0] / sum(inner)
            inspector = outer[1] / total * inner[1] / sum(inner)
            self.assertAlmostEqual(left, 0.29, delta=0.035)
            self.assertAlmostEqual(centre, 0.43, delta=0.045)
            self.assertAlmostEqual(inspector, 0.28, delta=0.04)
            self.assertGreaterEqual(effects.splitter.widget(0).width(), 300)
            self.assertGreaterEqual(placement.preview_splitter.widget(0).width(), 480)
            self.assertGreaterEqual(placement.preview_splitter.widget(1).width(), 340)
            if width == 1280:
                toolbar_buttons = (
                    placement.move_button,
                    placement.rotate_button,
                    placement.scale_button,
                    *placement.view_buttons[:3],
                    placement.frame_button,
                    placement.pause_button,
                )
                for button in toolbar_buttons:
                    required = button.fontMetrics().horizontalAdvance(button.text()) + button.iconSize().width() + 6
                    self.assertGreaterEqual(button.width(), required, button.text())
                    self.assertLessEqual(button.height(), 36, button.text())
                rows = [button.y() for button in toolbar_buttons]
                self.assertEqual(len(set(rows)), 2, f"toolbar width={placement.guided_toolbar_panel.width()}")
                self.assertEqual(sorted(rows.count(row) for row in set(rows)), [4, 4])
            else:
                self.assertEqual(
                    len({button.y() for button in placement._guided_toolbar_buttons}),
                    1,
                    (
                        f"toolbar width={placement.guided_toolbar_panel.width()}, "
                        f"columns={placement._guided_toolbar_columns}, "
                        f"minimums={[button.minimumWidth() for button in placement._guided_toolbar_buttons]}"
                    ),
                )
        resident = effects.placement
        tab.show_step(5)
        tab.show_step(4)
        self.assertIs(effects.placement, resident, "returning to Step 5 reuses the resident placement workspace")
        tab.request_shutdown()
        tab.close()
        tab.deleteLater()

    def test_model_workspace_shows_model_icon_placement_and_preview_in_three_columns(self) -> None:
        from PySide6.QtGui import QPalette
        from PySide6.QtWidgets import QScrollArea, QSizePolicy, QTabWidget
        from cdmw.ui.themes import build_app_palette, build_app_stylesheet

        old_palette = QPalette(self.app.palette())
        old_stylesheet = self.app.styleSheet()
        self.addCleanup(self.app.setPalette, old_palette)
        self.addCleanup(self.app.setStyleSheet, old_stylesheet)
        self.app.setPalette(build_app_palette("graphite"))
        self.app.setStyleSheet(build_app_stylesheet("graphite"))

        tab = self._tab()
        tab.resize(1720, 720)
        tab.show()
        tab.prefill_template(TEMPLATE)
        tab.show_step(2)
        self.app.processEvents()
        panel = tab.model_panel

        self.assertIs(tab.pages.currentWidget(), panel)
        self.assertIsNone(panel.findChild(QTabWidget, "new_item_model_inspector_tabs"))
        self.assertIsInstance(panel.model_icon_scroll, QScrollArea)
        self.assertIs(panel.model_icon_scroll.widget(), panel.model_icon_content)
        self.assertEqual(panel.workspace_splitter.sizePolicy().horizontalPolicy(), QSizePolicy.Policy.Ignored)
        self.assertEqual(panel.workspace_splitter.count(), 3)
        self.assertIs(panel.workspace_splitter.widget(0), panel.model_icon_column)
        self.assertIs(panel.workspace_splitter.widget(1), panel.placement_column)
        self.assertIs(panel.workspace_splitter.widget(2), panel.preview_group)
        self.assertIs(panel.operation_banner.parentWidget(), panel.placement_column)
        self.assertIs(panel.preview_group.parentWidget(), panel.workspace_splitter)
        self.assertIs(panel.preview.parentWidget(), panel.preview_group)
        self.assertEqual(panel.title(), "")
        sizes = panel.workspace_splitter.sizes()
        self.assertGreater(sizes[2], sizes[1])
        self.assertGreaterEqual(panel.workspace_splitter.widget(0).width(), 620)
        self.assertGreaterEqual(panel.workspace_splitter.widget(1).width(), 520)
        self.assertGreaterEqual(panel.workspace_splitter.widget(2).width(), 520)
        self.assertEqual(panel.model_icon_scroll.horizontalScrollBar().maximum(), 0)

        for group in (panel.model_group, panel.placement_group, panel.icon_group):
            self.assertEqual(group.title(), "", "the three-column layout needs no repeated section name")
            self.assertTrue(group.property("titlelessSection"), "a blank caption must not reserve a dark title gutter")
        self.assertEqual(
            [panel.model_group.accessibleName(), panel.icon_group.accessibleName(), panel.placement_group.accessibleName()],
            ["Model", "Icon", "Placement"],
        )
        for control in (
            panel.keep_model,
            panel.import_model,
            panel.plain_pbr,
            panel.own_sheath,
            panel.keep_physics,
            panel.glow_box,
            panel.flip_texture_v,
        ):
            self.assertTrue(panel.model_icon_content.isAncestorOf(control), f"{control!r} belongs to the Model scroller")
        for control in (
            panel.keep_icon,
            panel.generate_icon,
            panel.icon_source,
        ):
            self.assertTrue(panel.model_icon_column.isAncestorOf(control), f"{control!r} belongs to the Model/Icon column")
            self.assertFalse(panel.model_icon_content.isAncestorOf(control), f"{control!r} stays visible below the Model scroller")
        for control in (panel.view_mode, panel.offset_spins[0], panel.apply_button):
            self.assertTrue(panel.placement_column.isAncestorOf(control), f"{control!r} belongs to the Placement column")
        self.assertTrue(panel.preview_group.isAncestorOf(panel.preview))
        self.assertFalse(panel.placement_column.isAncestorOf(panel.preview))
        panel.placement_group.setVisible(True)
        panel.model_status.setText(
            "helmet.zip: 3,393 vertices, 1 part(s), 3 texture(s) of its own\n"
            "Discovered 4 glTF texture reference(s).\n"
            "Placed over template.pac: the rebuilt mesh is 348,247 bytes, 4 side file(s)"
        )
        panel.keep_physics.setVisible(True)
        panel.flip_texture_v.setVisible(True)

        for width, height in ((1720, 720), (1920, 900)):
            tab.resize(width, height)
            self.app.processEvents()
            panel.model_icon_scroll.verticalScrollBar().setValue(0)
            first_y = panel.keep_model.mapTo(panel.model_icon_scroll.viewport(), panel.keep_model.rect().topLeft()).y()
            next_y = panel.import_model.mapTo(panel.model_icon_scroll.viewport(), panel.import_model.rect().topLeft()).y()
            self.assertLessEqual(first_y, 12, f"the Model/Icon column starts without a dead title gutter at {width}x{height}")
            self.assertLessEqual(next_y - first_y, 36, f"the model choice stays compact at {width}x{height}")
            self.assertTrue(panel.model_group.isVisibleTo(panel))
            self.assertTrue(panel.icon_group.isVisibleTo(panel))
            self.assertLessEqual(panel.icon_group.geometry().bottom(), panel.model_icon_column.rect().bottom())
            self.assertLessEqual(panel.icon_source.geometry().bottom(), panel.icon_group.rect().bottom())
            self.assertLessEqual(panel.apply_button.geometry().bottom(), panel.placement_group.rect().bottom())
            self.assertIs(panel.preview.parentWidget(), panel.preview_group)
            self.assertEqual(panel.preview_group.height(), panel.workspace_splitter.height())
            self.assertGreaterEqual(panel.preview.height(), 300)
            self.assertLessEqual(panel.preview_group.geometry().bottom(), panel.workspace_splitter.rect().bottom())
            self.assertLessEqual(panel.preview.geometry().bottom(), panel.preview_group.rect().bottom())

            panel.import_model.setChecked(True)
            self.app.processEvents()
            panel.model_icon_scroll.verticalScrollBar().setValue(0)
            self.assertEqual(
                panel.model_icon_scroll.verticalScrollBar().maximum(),
                0,
                f"the inactive-Glow imported-model form fits without scrolling at {width}x{height}",
            )
            self.assertTrue(panel.glow_parts.isHidden(), "inactive Glow details do not consume the model pane")
            self.assertTrue(panel.icon_group.isVisibleTo(panel))
            self.assertLessEqual(panel.icon_group.geometry().bottom(), panel.model_icon_column.rect().bottom())
            blender_y = panel.blender_button.mapTo(panel.model_icon_scroll.viewport(), panel.blender_button.rect().topLeft()).y()
            self.assertLessEqual(blender_y, 260, f"the complete model form stays packed at {width}x{height}")

        frames = []
        panel.operation_spinner.frame_advanced.connect(frames.append)
        preview_height = panel.preview_group.height()
        tab.controller._lane = "model_apply"
        panel._busy_changed(True)
        self.app.processEvents()
        panel.operation_spinner._advance()
        self.assertTrue(panel.operation_banner.isVisibleTo(panel))
        self.assertEqual(panel.preview_group.height(), preview_height)
        self.assertTrue(frames)
        with patch.object(tab.controller, "cancel_operation", return_value=True) as cancel:
            panel.cancel_operation_button.click()
        cancel.assert_called_once_with("model_apply")
        panel._busy_changed(False)

        panel._preview_status("Loading model textures…")
        self.app.processEvents()
        self.assertTrue(panel.operation_banner.isVisibleTo(panel))
        self.assertEqual(panel.operation_label.text(), "Loading model textures…")
        self.assertEqual(panel.preview_status.text(), "", "the pinned busy state is not repeated below the viewport")
        panel._preview_status("Preview ready.")
        self.assertFalse(panel.operation_banner.isVisibleTo(panel))
        self.assertEqual(panel.preview_status.text(), "Preview ready.")
        tab.close()
        tab.deleteLater()
        self.app.processEvents()
    def test_import_appearance_hides_template_specific_controls_when_they_cannot_apply(self) -> None:
        from types import SimpleNamespace

        from cdmw.services.new_item_planning import ModelFiles

        tab = self._tab(window=SimpleNamespace())
        tab.resize(1280, 720)
        tab.show()
        tab.prefill_template(TEMPLATE)
        tab.show_step(2)
        entry = tab.controller.template_entries()[0]
        tab.receive_imported_model(entry, ModelFiles(pac_data=b"PAC imported"), scene=None)
        panel = tab.model_panel
        self.app.processEvents()
        self.assertTrue(panel.own_sheath.isVisibleTo(panel))
        self.assertTrue(panel.keep_physics.isVisibleTo(panel))

        neutral_family = SimpleNamespace(borrowed_parts=(), files_for=lambda _role: ())
        with patch.object(type(tab.controller.snapshot), "family", return_value=neutral_family):
            panel._refresh_import_widgets()
            self.app.processEvents()
            self.assertFalse(panel.own_sheath.isVisibleTo(panel))
            self.assertFalse(panel.own_sheath.isEnabled())
            self.assertFalse(panel.keep_physics.isVisibleTo(panel))

        tab.request_shutdown()
        tab.shutdown()
        tab.close()
        tab.deleteLater()
        self.app.processEvents()
