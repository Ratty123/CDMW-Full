"""Gates for the New Item Studio tab: headless construction, the draft, and a plan through the panels."""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "tests"))

from cdmw.core.archive_format import parse_archive_pamt  # noqa: E402
from cdmw.domain.new_item.spec import ModelSource, PlacementKind  # noqa: E402
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
from test_iteminfo_row import COPPER, DDD, build_row  # noqa: E402
from test_new_item_service import OTHER, TEMPLATE, _read, build_package, synthetic_files  # noqa: E402


class StateTests(unittest.TestCase):
    def test_grid_edits_and_spec(self) -> None:
        row = __import__("cdmw.core.iteminfo_row", fromlist=["parse_iteminfo_row"]).parse_iteminfo_row(build_row())
        grid = stat_grid_for(row, {DDD: "DDD"}, {COPPER: "Copper", 15: "Token"})
        self.assertEqual([c.label for c in grid.columns], ["DDD", "Price (Copper)", "Price (Token)"])
        self.assertEqual(grid.template_values, ((12000, 348, 17), (14000, 384, 19)))
        self.assertEqual(grid.price_items, ((COPPER, "Copper", 348), (15, "Token", 17)))
        draft = NewItemDraft(template_key=TEMPLATE, internal_name="Clone")
        draft.grid_values = {(0, 0): 20000, (1, 1): 384, (2, 0): 30000}
        stats, prices = stat_edits_from_grid(draft, grid)
        self.assertEqual([(e.level, e.status_key, e.value) for e in stats], [(0, DDD, 20000), (2, DDD, 30000)])
        self.assertEqual(prices, (), "a value equal to the template's is not an edit")
        draft.price_values = {COPPER: 348, 15: 99}
        spec = spec_from_draft(draft, grid)
        self.assertEqual([(p.item_key, p.price) for p in spec.price_edits], [(15, 99)])
        self.assertEqual(spec.stat_edits, stats)
        self.assertEqual(scaled_grid_values(grid, 2.0), {(0, 0): 24000, (1, 0): 28000})
        self.assertEqual(flat_grid_values(grid, 5), {(0, 0): 5, (1, 0): 5})
        again = with_template(draft, OTHER)
        self.assertEqual((again.template_key, again.grid_values, again.internal_name), (OTHER, {}, "Clone"))
        with self.assertRaisesRegex(ValueError, "template"):
            spec_from_draft(NewItemDraft(), None)


class TabTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        from PySide6.QtWidgets import QApplication

        cls.app = QApplication.instance() or QApplication([])

    def setUp(self) -> None:
        self._temp = tempfile.TemporaryDirectory()
        self.root = Path(self._temp.name)
        self.pamt_path = build_package(self.root, synthetic_files())
        self.entries = tuple(parse_archive_pamt(self.pamt_path))
        self._backup_patch = patch("cdmw.core.archive_patching.ARCHIVE_PATCH_BACKUP_ROOT", self.root / "backups")
        self._backup_patch.start()

    def tearDown(self) -> None:
        self._backup_patch.stop()
        from PySide6.QtWidgets import QApplication

        QApplication.processEvents()
        self._temp.cleanup()

    def _tab(self, window=None):
        from cdmw.ui.new_item.controller import NewItemStudioController
        from cdmw.ui.new_item.tab import NewItemStudioTab

        controller = NewItemStudioController(service=NewItemService(), read_entry=_read, synchronous=True)
        return NewItemStudioTab(window=window, controller=controller, get_archive_entries=lambda: self.entries)

    def test_construction_before_any_snapshot_is_cheap_and_quiet(self) -> None:
        tab = self._tab()
        self.assertFalse(tab.controller.ready)
        self.assertEqual(tab.iter_shutdown_workers(), ())
        tab.request_shutdown()
        tab.shutdown()
        tab.close()
        tab.deleteLater()

    def test_snapshot_panels_and_a_plan_through_the_panels(self) -> None:
        from PySide6.QtCore import Qt

        tab = self._tab()
        statuses: list[tuple[str, bool]] = []
        tab.status_message_requested.connect(lambda message, error: statuses.append((message, error)))
        tab.prefill_template(TEMPLATE)
        self.assertTrue(tab.controller.ready)
        self.assertEqual(tab.controller.draft.template_key, TEMPLATE)
        self.assertIn("Ziane_OneHandSword", tab.template_panel.summary.text())
        # identity
        tab.identity_panel.internal_name.setText("Ziane_Clone_OneHandSword")
        tab.identity_panel.display_name.setText("Wolf's Fang (Clone)")
        tab.identity_panel.language.setCurrentIndex([tab.identity_panel.language.itemData(i) for i in range(tab.identity_panel.language.count())].index("ger"))
        tab.identity_panel.display_name.setText("Wolfszahn (Klon)")
        self.assertEqual(tab.controller.draft.display_names, {"eng": "Wolf's Fang (Clone)", "ger": "Wolfszahn (Klon)"})
        self.assertNotIn("Blocked", tab.identity_panel.issues.text())
        # stats: edit one cell, scale, add a level
        stats = tab.stats_panel
        self.assertEqual(stats.table.rowCount(), 2)
        self.assertEqual(stats.table.item(0, 0).text(), "12000")
        stats.table.item(0, 0).setText("20000")
        stats.add_level_button.click()
        self.assertEqual(stats.table.rowCount(), 3)
        self.assertEqual(stats.table.item(2, 0).text(), "14000", "the new level copies the one below")
        stats.price_table.item(0, 1).setText("999")
        stats.max_stack.setValue(3)
        # placement: swap the Cigar out of the camp store
        placement = tab.placement_panel
        placement.swap.setChecked(True)
        placement.store.setCurrentText("Store_Camp_Equipment")
        self.assertEqual([placement.old_item.itemData(i) for i in range(placement.old_item.count())], ["Cigar_OneHandSword", "50001"])
        placement.old_item.setCurrentIndex(0)
        self.assertEqual(tab.controller.draft.placement_kind, PlacementKind.SWAP)
        self.assertEqual(tab.controller.draft.old_item_name, "Cigar_OneHandSword")
        self.assertIn("unlocked by", placement.old_item.itemText(0))
        self.assertIn("sell freely", placement.requirement_note.text())
        self.assertFalse(tab.controller.draft.keep_requirement)
        placement.keep_requirement.setChecked(True)
        self.assertTrue(tab.controller.draft.keep_requirement)
        self.assertIn("Kept", placement.requirement_note.text())
        placement.keep_requirement.setChecked(False)
        self.assertIn("2 group(s)", placement.template_groups.text())
        # perks: the template's, then two chosen ones; and an effect from the shipped stems
        perks = tab.perks_panel
        self.assertIn("1 perk(s)", perks.template_perks.text())
        self.assertIsNone(tab.controller.draft.socket_items)
        perks.own_perks.setChecked(True)
        self.assertEqual(tab.controller.draft.socket_items, [1002791], "the template's own list to start from")
        perks.perk_filter.setText("Swift")
        self.assertEqual([perks.catalogue.itemData(i) for i in range(perks.catalogue.count())], [1002812])
        perks.add_button.click()
        perks.perk_filter.setText("Gem_III")
        perks.add_button.click()
        self.assertEqual(tab.controller.draft.socket_items, [1002791, 1002812, 1002793])
        perks.chosen.setCurrentRow(0)
        perks.remove_button.click()
        self.assertEqual(tab.controller.draft.socket_items, [1002812, 1002793])
        self.assertEqual([perks.effect.itemData(i) for i in range(perks.effect.count())], ["fx_test_fire", "fx_test_ice"])
        perks.choose_effect("fx_test_fire")
        self.assertEqual(tab.controller.draft.effect_stem, "fx_test_fire")
        self.assertEqual(tab.controller.current_spec().effect, "fx_test_fire.level.effect")
        self.assertEqual(tab.controller.current_spec().socket_items, (1002812, 1002793))
        perks.use_effect.setChecked(False)
        self.assertEqual(tab.controller.draft.effect_stem, "")
        self.assertIsNone(tab.controller.current_spec().effect)
        # build the plan
        tab.output_panel.build_button.click()
        plan = tab.controller.plan
        self.assertIsNotNone(plan, tab.output_panel.summary.toPlainText())
        self.assertEqual(plan.spec.item_key, 1990000)
        self.assertEqual(plan.spec.model_source, ModelSource.TEMPLATE)
        self.assertEqual(plan.spec.socket_items, (1002812, 1002793))
        self.assertEqual(plan.manifest["socket_items"], [1002812, 1002793])
        self.assertIsNone(plan.spec.effect)
        self.assertEqual([(e.level, e.value) for e in plan.spec.stat_edits if e.status_key == DDD], [(0, 20000), (2, 14000)])
        self.assertEqual([(e.item_key, e.price) for e in plan.spec.price_edits], [(COPPER, 999)])
        self.assertEqual(plan.spec.max_stack_count, 3)
        self.assertEqual(plan.spec.placement.old_item_name, "Cigar_OneHandSword")
        self.assertIn("ItemInfo: row 1990000", tab.output_panel.summary.toPlainText())
        self.assertTrue(tab.output_panel.export_button.isEnabled())
        # export through the panel
        out = self.root / "export"
        tab.output_panel.export_root.setText(str(out))
        with patch("cdmw.ui.new_item.panels_output.QMessageBox.information", return_value=None):
            tab.output_panel.export_button.click()
        self.assertTrue((out / "files" / "gamedata" / "binary__" / "client" / "bin" / "iteminfo.pabgb").is_file())
        # a stat cell that is not a number falls back to the grid
        stats.table.item(0, 0).setText("abc")
        self.assertEqual(stats.table.item(0, 0).text(), "20000")
        # an unknown internal name collision is reported, not planned
        tab.identity_panel.internal_name.setText("Ziane_OneHandSword")
        self.assertIn("Blocked", tab.identity_panel.issues.text())
        tab.output_panel.build_button.click()
        self.assertIsNone(tab.controller.plan)
        self.assertIn("could not be built", tab.output_panel.summary.toPlainText())
        tab.close()
        tab.deleteLater()

    def test_install_goes_through_the_window_services_after_confirmation(self) -> None:
        from types import SimpleNamespace

        from cdmw.services.archive_mutation_service import ArchiveMutationService

        mutations = ArchiveMutationService()
        window = SimpleNamespace(app_context=SimpleNamespace(services=SimpleNamespace(require_archive_mutations=lambda: mutations)))
        tab = self._tab(window=window)
        tab.prefill_template(TEMPLATE)
        tab.identity_panel.internal_name.setText("Ziane_Clone_OneHandSword")
        tab.identity_panel.display_name.setText("Wolf's Fang (Clone)")
        tab.output_panel.build_button.click()
        self.assertIsNotNone(tab.controller.plan)
        from PySide6.QtWidgets import QMessageBox

        with patch("cdmw.ui.new_item.tab.QMessageBox.question", return_value=QMessageBox.No):
            tab.output_panel.install_button.click()
        before = {e.path.replace("\\", "/"): e for e in parse_archive_pamt(self.pamt_path)}
        self.assertNotIn("gamedata/binary__/client/bin/iteminfo.pabgb", [p for p in before if "1990000" in p])
        with patch("cdmw.ui.new_item.tab.QMessageBox.question", return_value=QMessageBox.Yes), \
                patch("cdmw.services.new_item_service.game_is_running", lambda: False), \
                patch("cdmw.ui.new_item.panels_output.QMessageBox.information", return_value=None):
            tab.output_panel.install_button.click()
        after = NewItemService().build_snapshot(parse_archive_pamt(self.pamt_path), read_entry=_read)
        self.assertIn(1990000, after.rows)
        self.assertEqual(after.rows[1990000].string_key, "Ziane_Clone_OneHandSword")
        tab.close()
        tab.deleteLater()

    def test_imported_model_and_missing_import_hook(self) -> None:
        from types import SimpleNamespace

        from cdmw.services.new_item_planning import ModelFiles

        tab = self._tab(window=SimpleNamespace())
        tab.prefill_template(TEMPLATE)
        with patch("cdmw.ui.new_item.tab.QMessageBox.information", return_value=None) as info:
            tab.model_panel.import_button.click()
        self.assertTrue(info.called, "without a shell hook the tab says how to reach the Builder")
        entry = tab.controller.template_entries()[0]
        tab.receive_imported_model(entry, ModelFiles(pac_data=b"PAC imported"))
        self.assertTrue(tab.model_panel.import_model.isChecked())
        self.assertEqual(tab.controller.draft.model_source, ModelSource.IMPORTED)
        tab.identity_panel.internal_name.setText("Ziane_Clone_OneHandSword")
        tab.identity_panel.display_name.setText("X")
        tab.output_panel.build_button.click()
        plan = tab.controller.plan
        self.assertIsNotNone(plan, tab.output_panel.summary.toPlainText())
        self.assertTrue(any(path.endswith("cd_phm_01_sword_9109.pac") for path in plan.new_paths))
        tab.model_panel.clear_button.click()
        self.assertEqual(tab.controller.draft.model_source, ModelSource.TEMPLATE)
        tab.close()
        tab.deleteLater()


if __name__ == "__main__":
    unittest.main()
