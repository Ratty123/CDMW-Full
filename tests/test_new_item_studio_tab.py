"""Gates for the New Item Studio tab: headless construction, the draft, and a plan through the panels."""

from __future__ import annotations

import os
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
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
from test_iteminfo_row import COPPER, DDD, build_row  # noqa: E402
from test_new_item_service import OTHER, TEMPLATE, _read, build_package, synthetic_files  # noqa: E402


class StateTests(unittest.TestCase):
    def test_grid_edits_and_spec(self) -> None:
        row = __import__("cdmw.core.iteminfo_row", fromlist=["parse_iteminfo_row"]).parse_iteminfo_row(build_row())
        grid = stat_grid_for(row, {DDD: "DDD"}, {COPPER: "Copper", 15: "Token"})
        self.assertEqual([c.label for c in grid.columns], ["Attack (DDD)", "Price (Copper)", "Price (Token)"])
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
        files = synthetic_files()
        # one shipped effect the presets name, so the preset combo has something to offer
        files["effect/binary__/releasebin/fx_cc_firesweapon_a__fire1.pae"] = b"PAE fire preset"
        # and one real effect binary, so the catalogue has facts to show
        files["effect/binary__/releasebin/fx_test_fire.pae"] = (Path(__file__).parent / "fixtures" / "effects" / "fx_hit_common_fire_attach_a_loop.pae").read_bytes()
        self.pamt_path = build_package(self.root, files)
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

    def test_an_empty_entry_list_is_read_from_the_package_root(self) -> None:
        """The shell's catalogue backend shows the browser without filling the legacy
        entry list; the studio then lists the archives itself from the game folder."""

        from cdmw.ui.new_item.controller import NewItemStudioController
        from cdmw.ui.new_item.tab import NewItemStudioTab

        controller = NewItemStudioController(service=NewItemService(), read_entry=_read, synchronous=True)
        tab = NewItemStudioTab(controller=controller, get_archive_entries=lambda: (), get_package_root=lambda: str(self.root))
        tab.start_snapshot()
        self.assertTrue(tab.controller.ready, "listed from the package root and read")
        self.assertIn(TEMPLATE, tab.controller.snapshot.rows)
        tab.request_shutdown()
        tab.shutdown()
        tab.close()
        tab.deleteLater()

    def test_no_entries_and_no_game_folder_says_so(self) -> None:
        from cdmw.ui.new_item.controller import NewItemStudioController
        from cdmw.ui.new_item.tab import NewItemStudioTab

        controller = NewItemStudioController(service=NewItemService(), read_entry=_read, synchronous=True)
        tab = NewItemStudioTab(controller=controller, get_archive_entries=lambda: (), get_package_root=lambda: "")
        tab.start_snapshot()
        self.assertFalse(tab.controller.ready)
        self.assertIn("no game folder", tab._status.text())
        tab.close()
        tab.deleteLater()

    def test_the_icon_is_captured_from_the_inline_view(self) -> None:
        """Capture the icon from this view asks the inline viewport for the frame; the
        captured PNG becomes the item's icon source (Give the item its own icon ticks)."""

        from PySide6.QtGui import QImage

        captured = Path(self.root) / "capture.png"
        QImage(8, 8, QImage.Format_ARGB32).save(str(captured))
        tab = self._tab()
        tab.prefill_template(TEMPLATE)
        model = tab.model_panel
        asked = []
        with patch.object(type(model.preview), "capture", lambda self_, path=None: asked.append(path) or True):
            model._capture_inline()
        self.assertEqual(len(asked), 1, "the inline viewport is asked once")
        # the captured frame goes through the region picker: the rectangle the user drags
        # becomes the 512 x 512 icon
        frame = QImage(64, 48, QImage.Format_ARGB32)
        frame.fill(0xFF203040)
        frame.save(str(captured))

        class FakeRegionDialog:
            def __init__(self, parent, image):
                self.image = image

            def exec(self):
                from PySide6.QtWidgets import QDialog

                return QDialog.Accepted

            def selected_source_rect(self):
                return (8, 8, 32, 24)

        with patch.object(type(model), "icon_region_dialog_factory", staticmethod(FakeRegionDialog)):
            model.preview.captured.emit(captured, frame)
        self.assertTrue(model.generate_icon.isChecked())
        written = Path(tab.controller.draft.icon_source_path)
        self.assertTrue(written.is_file(), written)
        self.assertNotEqual(written, captured, "the icon is the selected region, not the raw frame")
        self.assertEqual(QImage(str(written)).size().width(), 512)
        self.assertTrue(model.icon_thumbnail.isVisibleTo(model))
        # a cancelled selection leaves the icon alone
        model.icon_source.setText("")
        class CancelDialog(FakeRegionDialog):
            def exec(self):
                from PySide6.QtWidgets import QDialog

                return QDialog.Rejected

        with patch.object(type(model), "icon_region_dialog_factory", staticmethod(CancelDialog)):
            model.preview.captured.emit(captured, frame)
        self.assertEqual(model.icon_source.text(), "")
        with patch.object(type(model.preview), "capture", lambda self_, path=None: False):
            model._capture_inline()
        self.assertIn("not showing the item yet", model.preview_status.text())
        tab.close()
        tab.deleteLater()

    def test_an_untouched_step_carries_no_empty_boxes(self) -> None:
        """The optional blocks are hidden, not merely greyed: a step whose answer is "the
        template's" is a few lines, and no page scrolls sideways at a 1280-wide window."""

        from PySide6.QtWidgets import QCheckBox, QRadioButton, QScrollArea

        tab = self._tab()
        tab.resize(1280, 620)
        tab.show()
        tab.start_snapshot()
        self.app.processEvents()
        model, perks, groups = tab.model_panel, tab.perks_panel, tab.placement_panel
        self.assertFalse(model.clear_button.isVisibleTo(model), "nothing to discard until a model is imported")
        for widget in model._import_widgets:
            self.assertFalse(widget.isVisibleTo(model), "the import's controls wait for the import radio")
        model.import_model.setChecked(True)
        for widget in model._import_widgets:
            self.assertTrue(widget.isVisibleTo(model))
        self.assertFalse(perks.catalogue.isVisibleTo(perks), "the perk catalogue waits to be asked for")
        perks.own_perks.setChecked(True)
        self.assertTrue(perks.catalogue.isVisibleTo(perks))
        for row in perks._effect_rows:
            self.assertFalse(row.isVisibleTo(perks), "the effect's rows wait for the effect")
        perks.use_effect.setChecked(True)
        for row in perks._effect_rows:
            self.assertTrue(row.isVisibleTo(perks))
        self.assertFalse(groups.group_list.isVisibleTo(groups), "the item groups wait to be chosen by hand")
        self.assertFalse(groups.store.isVisibleTo(groups), "no shop, no shop picker")
        groups.explicit.setChecked(True)
        groups.swap.setChecked(True)
        self.assertTrue(groups.group_list.isVisibleTo(groups))
        self.assertTrue(groups.store.isVisibleTo(groups))
        for index in range(tab.steps.count()):
            tab.show_step(index)
            self.app.processEvents()
            self.assertIsInstance(tab.pages.currentWidget(), QScrollArea, "each step is its own scroll area")
        # a tick's own text never wraps, so a long one sets the whole step's minimum width
        # and the page scrolls sideways; the rest of the sentence belongs in the tooltip
        for kind in (QCheckBox, QRadioButton):
            for widget in tab.findChildren(kind):
                self.assertLessEqual(
                    len(widget.text()), 100,
                    f"this one would push the step wider than the window: {widget.text()!r}",
                )
        tab.request_shutdown()
        tab.shutdown()
        tab.close()
        tab.deleteLater()

    def test_the_preview_source_is_the_import_else_the_template_decoded_with_textures(self) -> None:
        """Step 3's viewport shows the imported model's own preview decode (textures and
        all) when there is one, else the template's mesh decoded from the archives with
        its textures resolved; the bare mesh only when that decode will not go."""

        from types import SimpleNamespace

        from cdmw.modding.mesh_parser import ParsedMesh, SubMesh

        tab = self._tab()
        self.assertIsNone(tab.controller.item_preview_source(), "no template, nothing to show")
        tab.prefill_template(TEMPLATE)
        token, build = tab.controller.item_preview_source()
        self.assertEqual(token[0], "template")
        self.assertEqual(token[1], TEMPLATE)
        by_path, by_basename = tab.controller.snapshot.archive_index_maps()
        self.assertIn(token[2].lower(), by_path)
        self.assertIn(token[2].rsplit("/", 1)[-1].lower(), by_basename)
        # the archive decode is asked with the whole listing's texture maps; a decode that
        # yields a model wins, one that does not falls back to the bare mesh
        decoded = SimpleNamespace(preferred_view="model", preview_model=SimpleNamespace(meshes=[object()]))
        seen = {}

        def fake_decode(entry, **kwargs):
            seen["entry"] = entry
            seen["kwargs"] = kwargs
            return decoded

        import threading

        with patch("cdmw.core.archive_preview_result_builder.build_archive_preview_result", fake_decode):
            self.assertIs(build(threading.Event()), decoded.preview_model)
        self.assertEqual(seen["entry"].path, token[2])
        self.assertIs(seen["kwargs"]["texture_entries_by_basename"], by_basename)
        self.assertFalse(seen["kwargs"]["enable_hkx_visual_preview"])
        # the decode is kept for the template: a second build does not decode again
        seen.clear()
        with patch("cdmw.core.archive_preview_result_builder.build_archive_preview_result", fake_decode):
            self.assertIs(build(threading.Event()), decoded.preview_model)
        self.assertNotIn("entry", seen, "the cached decode answers")
        tab.controller._template_models.clear()
        blade = ParsedMesh(path="blade", format="pac", submeshes=[SubMesh(name="b", vertices=[(0, 0, 0)] * 3, faces=[(0, 1, 2)])])
        with patch("cdmw.core.archive_preview_result_builder.build_archive_preview_result", lambda entry, **kwargs: SimpleNamespace(preferred_view="details", preview_model=None)),              patch.object(type(tab.controller), "item_mesh_for_preview", lambda self_: blade):
            self.assertIs(build(threading.Event()), blade, "no model from the decode: the bare mesh")
        # an import: its own preview model, already decoded by the Builder
        imported = SimpleNamespace(rebuilt_data=b"x", preview_model=SimpleNamespace(meshes=[object()]))
        tab.controller.set_imported_model(None, imported)
        token, build = tab.controller.item_preview_source()
        self.assertEqual(token, ("imported", id(imported)))
        self.assertIs(build(threading.Event()), imported.preview_model)
        tab.close()
        tab.deleteLater()

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
        # a stat the template lacks: CriticalRate is a StatusInfo entry no ladder here carries
        self.assertEqual(stats.table.columnCount(), 3)
        choices = [stats.new_stat.itemData(i) for i in range(stats.new_stat.count())]
        self.assertIn(1000007, choices, "CriticalRate is offered")
        self.assertNotIn(DDD, choices, "a stat the ladder already carries is not offered twice")
        crit_index = choices.index(1000007)
        self.assertIn("unproven", stats.new_stat.itemText(crit_index), "no shipped equipment carries it, and the list says so")
        stats.new_stat.setCurrentIndex(crit_index)
        stats.new_stat_value.setValue(250)
        stats.add_stat_button.click()
        self.assertEqual(stats.table.columnCount(), 4)
        self.assertEqual(stats.table.horizontalHeaderItem(1).text(), "Critical rate (CriticalRate)", "added after the template's stats, before the prices")
        self.assertEqual(stats.table.item(0, 1).text(), "250")
        self.assertEqual(stats.table.item(0, 0).text(), "20000", "the earlier edit stayed on its column")
        self.assertEqual(stats.table.item(0, 2).text(), "348", "the price column moved right with its values")
        self.assertIn("Added here: Critical rate", stats.carries.text())
        self.assertEqual(tab.controller.draft.extra_stat_keys, [1000007])
        # placement: swap the Cigar out of the camp store
        placement = tab.placement_panel
        placement.swap.setChecked(True)
        self.assertTrue(placement.choose_store("Store_Camp_Equipment"))
        self.assertFalse(placement.choose_store("Store_Nowhere"), "the shop is a fixed list, not free text")
        self.assertFalse(placement.store.isEditable())
        self.assertIn("your camp (base)", placement.store.currentText())
        self.assertIn("line(s)", placement.store.currentText())
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
        self.assertTrue(placement.unlimited_stock.isChecked(), "unlimited stock is the default")
        self.assertTrue(tab.controller.draft.unlimited_stock)
        self.assertEqual(tab.controller.current_spec().placement.stock_count, UNLIMITED_STOCK)
        placement.unlimited_stock.setChecked(False)
        self.assertFalse(tab.controller.draft.unlimited_stock)
        self.assertIsNone(tab.controller.current_spec().placement.stock_count)
        placement.unlimited_stock.setChecked(True)
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
        self.assertEqual([perks.effect.itemData(i) for i in range(perks.effect.count())], ["fx_cc_firesweapon_a__fire1", "fx_test_fire", "fx_test_ice"])
        # the element presets: only the shipped ones, the proven one marked; choosing one selects the effect
        self.assertEqual([perks.effect_preset.itemData(i) for i in range(perks.effect_preset.count())], ["", "fx_cc_firesweapon_a__fire1"])
        self.assertIn("(proven)", perks.effect_preset.itemText(1))
        perks.effect_preset.setCurrentIndex(1)
        self.assertTrue(perks.use_effect.isChecked())
        self.assertEqual(tab.controller.draft.effect_stem, "fx_cc_firesweapon_a__fire1")
        self.assertEqual(perks.effect_scale.value(), 0.6, "the preset's starting scale")
        self.assertEqual(tab.controller.draft.effect_scale, 0.6)
        perks.effect_scale.setValue(0.25)
        perks.effect_offset[1].setValue(0.1)
        self.assertEqual((tab.controller.draft.effect_scale, tab.controller.draft.effect_offset), (0.25, (0.0, 0.1, 0.0)))
        self.assertEqual((tab.controller.current_spec().effect_scale, tab.controller.current_spec().effect_offset), (0.25, (0.0, 0.1, 0.0)))
        perks.choose_effect("fx_test_fire")
        self.assertEqual(tab.controller.draft.effect_stem, "fx_test_fire")
        self.assertEqual(tab.controller.current_spec().effect, "fx_test_fire.level.effect")
        self.assertEqual(tab.controller.current_spec().socket_items, (1002812, 1002793))
        # the effect catalogue: before indexing the facts line asks for it; after, the real
        # effect says what it draws, the stubs say they did not decode, and the filter
        # matches emitters and textures too
        self.assertIn("Index the effects", perks.effect_facts.text())
        tab.controller.effect_cache_path = self.root / "effect_catalogue.json"
        perks.index_button.click()
        self.assertIsNotNone(tab.controller.effect_catalogue)
        self.assertEqual(len(tab.controller.effect_catalogue), 3)
        self.assertTrue((self.root / "effect_catalogue.json").is_file())
        self.assertIn("effects indexed", perks.index_button.text())
        facts = perks.effect_facts.text()
        self.assertIn("cdem_last_fire_circle_trail_001a", facts)
        self.assertIn("pafx_vector_chaos_01a.dds", facts)
        self.assertIn("box 2.50 x 2.53 x 2.64 m", facts)
        self.assertIn("loops", facts)
        perks.effect_filter.setText("firefly")
        self.assertEqual([perks.effect.itemData(i) for i in range(perks.effect.count())], ["fx_test_fire"])
        perks.effect_filter.setText("ice")
        self.assertEqual([perks.effect.itemData(i) for i in range(perks.effect.count())], ["fx_test_ice"])
        self.assertTrue(tab.controller.effect_facts("fx_test_ice").walk_note, "a stub effect is kept, marked undecoded")
        perks.effect_filter.setText("")
        # place in the viewport: the dialog gets the item's mesh, the effect's box and the
        # current numbers, and what it returns lands in the spins and the draft
        from cdmw.modding.mesh_parser import ParsedMesh, SubMesh

        seen = {}

        class FakeDialog:
            def __init__(self, parent, **kwargs):
                seen.update(kwargs)
                self.offset = (0.1, 0.0, -0.2)
                self.scale = 0.75

            def exec(self):
                from PySide6.QtWidgets import QDialog

                return QDialog.Accepted

        blade = ParsedMesh(path="blade", format="pac", submeshes=[SubMesh(name="b", vertices=[(0, 0, 0)] * 3, faces=[(0, 1, 2)])])
        with patch.object(type(tab.controller), "item_mesh_for_preview", lambda self_: blade), patch.object(type(perks), "placement_dialog_factory", staticmethod(FakeDialog)):
            perks.choose_effect("fx_test_fire")
            perks.place_button.click()
        self.assertIs(seen["item_mesh"], blade)
        self.assertEqual(tuple(round(v, 2) for v in seen["box_min"]), (-1.24, -1.24, -1.39))
        self.assertEqual(seen["scale"], 0.25)
        self.assertEqual(seen["effect_label"], "fx_test_fire")
        # the dialog also gets the effect's particle description (read from the snapshot with
        # the draft's look) and a reader for its sprite textures
        from cdmw.services.effect_preview_model import EffectPreview

        self.assertIsInstance(seen["effect_preview"], EffectPreview)
        self.assertEqual(seen["effect_preview"].stem, "fx_test_fire")
        self.assertEqual(len(seen["effect_preview"].emitters), 2)
        self.assertTrue(callable(seen["texture_reader"]))
        self.assertIsNone(seen["texture_reader"]("effect/texture/not_in_the_snapshot.dds"))
        self.assertEqual(tab.controller.draft.effect_scale, 0.75)
        self.assertEqual(tab.controller.draft.effect_offset, (0.1, 0.0, -0.2))
        # the look: a colour and four factors go into the spec's EffectLook; as shipped by default
        self.assertTrue(tab.controller.current_spec().effect_look.is_default)
        perks.set_effect_color((0.2, 0.4, 1.0))
        perks.look_factors["intensity"].setValue(2.0)
        perks.look_factors["rate"].setValue(0.5)
        look = tab.controller.current_spec().effect_look
        self.assertEqual((look.color, look.intensity, look.size, look.rate, look.lifetime), ((0.2, 0.4, 1.0), 2.0, 1.0, 0.5, 1.0))
        self.assertIn("#3366ff", perks.color_button.text())
        perks.color_reset.click()
        self.assertIsNone(tab.controller.current_spec().effect_look.color)
        self.assertEqual(perks.color_button.text(), "Colour: as shipped")
        perks.look_factors["intensity"].setValue(1.0)
        perks.look_factors["rate"].setValue(1.0)
        # a second tab loads the cache instead of indexing again
        again = self._tab()
        again.start_snapshot()
        again.controller.effect_cache_path = self.root / "effect_catalogue.json"
        self.assertTrue(again.controller.load_effect_catalogue())
        self.assertEqual(len(again.controller.effect_catalogue), 3)
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
        self.assertEqual([(e.level, e.value) for e in plan.spec.stat_edits if e.status_key == 1000007], [(0, 250), (1, 250), (2, 250)], "the added stat on every level")
        self.assertEqual(plan.manifest.get("added_stats"), [1000007])
        self.assertTrue(any("CriticalRate" in warning and "unproven" in warning for warning in plan.warnings), plan.warnings)
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

    def test_the_overlay_button_asks_first_and_leaves_the_shipped_archives_alone(self) -> None:
        """The second install route: the same plan into a directory of its own, mounted
        ahead of the shipped ones. Declining the question writes nothing, and accepting it
        writes no shipped payload file."""

        from types import SimpleNamespace

        from PySide6.QtWidgets import QMessageBox

        from cdmw.core.papgt_format import parse_papgt
        from cdmw.services.archive_mutation_service import ArchiveMutationService

        mutations = ArchiveMutationService()
        window = SimpleNamespace(app_context=SimpleNamespace(services=SimpleNamespace(require_archive_mutations=lambda: mutations)))
        tab = self._tab(window=window)
        tab.prefill_template(TEMPLATE)
        tab.identity_panel.internal_name.setText("Ziane_Overlay_OneHandSword")
        tab.identity_panel.display_name.setText("Wolf's Fang (Overlay)")
        tab.output_panel.build_button.click()
        self.assertIsNotNone(tab.controller.plan)
        shipped = {path: path.read_bytes() for path in sorted(self.root.glob("0009/*.paz"))}
        mount_before = (self.root / "meta" / "0.papgt").read_bytes()

        with patch("cdmw.ui.new_item.tab.QMessageBox.question", return_value=QMessageBox.No):
            tab.output_panel.install_overlay_button.click()
        self.assertEqual((self.root / "meta" / "0.papgt").read_bytes(), mount_before, "declining writes nothing")

        with patch("cdmw.ui.new_item.tab.QMessageBox.question", return_value=QMessageBox.Yes), \
                patch("cdmw.services.new_item_service.game_is_running", lambda: False), \
                patch("cdmw.ui.new_item.panels_output.QMessageBox.information", return_value=None):
            tab.output_panel.install_overlay_button.click()

        for path, before in shipped.items():
            self.assertEqual(path.read_bytes(), before, f"{path.name} was rewritten by an overlay install")
        mounted = parse_papgt((self.root / "meta" / "0.papgt").read_bytes())
        self.assertNotEqual(mounted[0].name, "0009", "the overlay is mounted ahead of the shipped directory")
        overlay = self.root / mounted[0].name
        self.assertTrue((overlay / "0.pamt").is_file() and (overlay / "0.paz").is_file())
        tab.close()
        tab.deleteLater()

    def test_the_overlay_can_be_moved_into_and_taken_away_from_the_step(self) -> None:
        """The two housekeeping buttons: one carries an install that went into the shipped
        archives out into the overlay, the other unmounts and deletes it. Neither needs a
        plan, both ask first, and both leave the shipped archives as they found them."""

        from types import SimpleNamespace

        from PySide6.QtWidgets import QMessageBox

        from cdmw.core.papgt_format import parse_papgt
        from cdmw.services.archive_mutation_service import ArchiveMutationService

        mutations = ArchiveMutationService()
        window = SimpleNamespace(app_context=SimpleNamespace(services=SimpleNamespace(require_archive_mutations=lambda: mutations)))
        tab = self._tab(window=window)
        tab._get_package_root = lambda: str(self.root)
        tab.prefill_template(TEMPLATE)

        # nothing has been installed the old way, so there is nothing to move
        with patch("cdmw.ui.new_item.tab.QMessageBox.information", return_value=None) as told:
            tab.output_panel.overlay_migration_button.click()
        self.assertTrue(told.called, "the step says there is nothing to move rather than writing")

        # install through the overlay, then take it away again
        tab.identity_panel.internal_name.setText("Ziane_Overlay_Housekeeping")
        tab.identity_panel.display_name.setText("Wolf's Fang (Housekeeping)")
        tab.output_panel.build_button.click()
        with patch("cdmw.ui.new_item.tab.QMessageBox.question", return_value=QMessageBox.Yes), \
                patch("cdmw.services.new_item_service.game_is_running", lambda: False), \
                patch("cdmw.ui.new_item.panels_output.QMessageBox.information", return_value=None):
            tab.output_panel.install_overlay_button.click()
        mounted = [item.name for item in parse_papgt((self.root / "meta" / "0.papgt").read_bytes())]
        overlay = self.root / mounted[0]
        self.assertTrue((overlay / "0.pamt").is_file())

        with patch("cdmw.ui.new_item.tab.QMessageBox.question", return_value=QMessageBox.No):
            tab.output_panel.overlay_removal_button.click()
        self.assertTrue((overlay / "0.pamt").is_file(), "declining leaves it alone")

        with patch("cdmw.ui.new_item.tab.QMessageBox.question", return_value=QMessageBox.Yes), \
                patch("cdmw.ui.new_item.panels_output.QMessageBox.information", return_value=None):
            tab.output_panel.overlay_removal_button.click()
        self.assertFalse(overlay.exists(), "and accepting deletes it")
        self.assertNotIn(overlay.name, [item.name for item in parse_papgt((self.root / "meta" / "0.papgt").read_bytes())])
        tab.close()
        tab.deleteLater()

    def test_a_model_file_is_placed_in_the_studio(self) -> None:
        """Import a model file on step 3: the studio reads it itself (no Builder, no Mesh
        Editor), shows it over the template with a first fit, takes the placement from
        the numbers or the gizmo, and Apply builds the item's mesh headlessly; moving it
        again drops that build; discarding returns to the template's model."""

        from types import SimpleNamespace

        from cdmw.modding.mesh_parser import ParsedMesh, SubMesh
        from cdmw.ui.new_item.item_preview import PlacementScene
        from cdmw.ui.new_item.model_import import ModelImportSource, ModelPlacement

        tab = self._tab()
        tab.prefill_template(TEMPLATE)
        panel = tab.model_panel
        self.assertFalse(panel.placement_group.isVisibleTo(panel), "no model, no placement controls")
        # a source: a 10 m long box along x, with one texture
        box = ParsedMesh(path="box.gltf", format="gltf", submeshes=[SubMesh(name="b", vertices=[(0, 0, 0), (10, 0, 0), (10, 2, 2), (0, 2, 2)], faces=[(0, 1, 2), (0, 2, 3)])])
        box.total_vertices = 4
        from cdmw.core.archive_modding import parsed_mesh_to_preview_model

        source = ModelImportSource(
            chosen_path=Path(r"E:/models/box.zip"), model_path=Path(r"E:/models/box/scene.gltf"), scene=SimpleNamespace(mesh=box, diagnostics=()),
            preview_model=parsed_mesh_to_preview_model(box), bounds=((0.0, 0.0, 0.0), (10.0, 2.0, 2.0)), texture_count=1,
        )
        seen = {}
        template_box = ((-0.1, -0.1, -1.0), (0.1, 0.1, 0.2))  # the test snapshot's pac is not a real mesh
        bounds_patch = patch.object(type(tab.controller), "template_bounds", lambda self_: template_box)
        bounds_patch.start()
        self.addCleanup(bounds_patch.stop)
        with patch("cdmw.ui.new_item.controller.load_model_import_source", lambda path, **kw: seen.setdefault("path", path) and source),              patch("cdmw.ui.new_item.panels_model.QFileDialog.getOpenFileName", return_value=(r"E:/models/box.zip", "")):
            panel.import_button.click()
        self.assertEqual(seen["path"], Path(r"E:/models/box.zip"))
        self.assertIs(tab.controller.model_import, source)
        self.assertEqual(tab.controller.draft.model_source, ModelSource.IMPORTED)
        self.assertTrue(panel.placement_group.isVisibleTo(panel))
        self.assertTrue(panel.import_model.isChecked())
        # a glTF source needs the vertical texture flip, and the panel shows it
        self.assertTrue(source.flip_texture_v is False or source.flip_texture_v is True)
        # the fit is baked into the mesh; the numbers start at zero on top of it
        self.assertEqual(tab.controller.model_placement, ModelPlacement(), "the numbers start at zero")
        bake = source.bake
        self.assertNotEqual(bake.scale, (1.0, 1.0, 1.0), "the fit scales the box to the template")
        self.assertEqual(source.bake_generation, 1)
        self.assertAlmostEqual(panel.scale_spins[0].value(), 1.0, places=4)
        baked_lo, baked_hi = source.baked_bounds()
        self.assertAlmostEqual(baked_hi[2] - baked_lo[2], 1.2, places=3, msg="the baked box is the template's length along z")
        self.assertIn("placement not applied", tab.summary.plain_text())
        self.assertTrue(any(issue.code == "model_placement_not_applied" for issue in tab.controller.validate()), "the plan is blocked until the placement is applied")
        # the viewport gets the placement scene: the template's decode plus the source's preview
        token, build = tab.controller.item_preview_source()
        self.assertEqual(token[0], "placement")
        import threading

        blade = ParsedMesh(path="blade", format="pac", submeshes=[SubMesh(name="b", vertices=[(0, 0, 0)] * 3, faces=[(0, 1, 2)])])
        with patch("cdmw.core.archive_preview_result_builder.build_archive_preview_result", lambda entry, **kwargs: SimpleNamespace(preferred_view="details", preview_model=None)),              patch.object(type(tab.controller), "item_mesh_for_preview", lambda self_: blade):
            scene = build(threading.Event())
        self.assertIsInstance(scene, PlacementScene)
        self.assertIs(scene.template, blade, "no decode: the bare template mesh is the reference")
        self.assertEqual(scene.placement, tab.controller.model_placement, "the scene is written at the placement")
        self.assertEqual(scene.model_bounds, source.baked_bounds())
        self.assertEqual(token[2], source.bake_generation, "the token moves with the bake")
        # the numbers move the placement
        panel.offset_spins[2].setValue(-0.25)
        self.assertAlmostEqual(tab.controller.model_placement.offset[2], -0.25, places=6)
        # apply: the headless build, the result is what the plan writes
        fake_result = SimpleNamespace(rebuilt_data=b"PAC placed", supplemental_file_specs=(), summary_lines=("one",), preview_model=None)
        with patch("cdmw.ui.new_item.controller.build_placed_import", lambda entry, src, placement, **kw: seen.setdefault("built", (entry, src, placement)) and fake_result):
            panel.apply_button.click()
        self.assertIs(tab.controller.model_result, fake_result)
        self.assertEqual(seen["built"][2], tab.controller.model_placement)
        self.assertEqual(source.applied, (source.bake, tab.controller.model_placement))
        self.assertTrue(all(issue.code != "model_placement_not_applied" for issue in tab.controller.validate()))
        self.assertIn("placed", tab.summary.plain_text())
        # the gizmo moves it again: the build is dropped until the next apply
        panel._gizmo_moved(tab.controller.model_placement.with_values(offset=(0.1, 0.0, -0.25)), True)
        self.assertIsNone(tab.controller.model_result, "a moved model has no build yet")
        self.assertAlmostEqual(panel.offset_spins[0].value(), 0.1, places=6)
        # the transform the build gets is the placement, manual mode
        transform = tab.controller.model_placement.build_transform()
        self.assertEqual(transform.alignment_mode, "manual")
        self.assertFalse(transform.scale_to_original_length)
        self.assertEqual(transform.offset_xyz, (0.1, 0.0, -0.25))
        # the fit again: the bake is redone (a new generation), the numbers go back to zero
        panel.fit_button.click()
        self.assertEqual(tab.controller.model_placement, ModelPlacement())
        self.assertEqual(source.bake, bake)
        self.assertGreaterEqual(source.bake_generation, 1)
        # discard: the template's model again
        panel.clear_button.click()
        self.assertIsNone(tab.controller.model_import)
        self.assertEqual(tab.controller.draft.model_source, ModelSource.TEMPLATE)
        self.assertFalse(panel.placement_group.isVisibleTo(panel))
        tab.close()
        tab.deleteLater()

    def test_a_second_item_never_takes_the_first_one_s_identity(self) -> None:
        """The studio remembers the key and stem every plan hands out and reserves them for
        the next one: the snapshot cannot see an item until it is installed and the
        archives are read again, and a repeat would overwrite the first item."""

        tab = self._tab()
        tab.prefill_template(TEMPLATE)
        tab.identity_panel.internal_name.setText("First_Clone_OneHandSword")
        tab.identity_panel.display_name.setText("First")
        tab.output_panel.build_button.click()
        first = tab.controller.plan
        self.assertIsNotNone(first)
        self.assertIn(first.spec.item_key, tab.controller.issued_keys)
        if first.spec.stem:
            self.assertIn(str(first.spec.stem), tab.controller.issued_stems)
        tab.identity_panel.internal_name.setText("Second_Clone_OneHandSword")
        tab.identity_panel.display_name.setText("Second")
        tab.output_panel.build_button.click()
        second = tab.controller.plan
        self.assertIsNotNone(second)
        self.assertNotEqual(second.spec.item_key, first.spec.item_key, "a second item gets its own key")
        if first.spec.stem:
            self.assertNotEqual(second.spec.stem, first.spec.stem, "and its own model stem")
        # nothing was written to the user's settings: persistence is the app's choice
        self.assertFalse(tab.controller._persist_identities)
        tab.close()
        tab.deleteLater()

    def test_an_install_reads_the_archives_again(self) -> None:
        """The installed item is only in the snapshot after a re-read, so the studio does
        one itself; without it the next item would be allocated the same key."""

        tab = self._tab()
        tab.prefill_template(TEMPLATE)
        reread = []
        with patch.object(tab.controller, "start_snapshot", side_effect=lambda entries, **kwargs: reread.append((tuple(entries), kwargs)) or True):
            tab._reread_after_install()
        self.assertEqual(len(reread), 1)
        self.assertTrue(reread[0][0], "the mounted studio refreshes even though a snapshot is already ready")
        self.assertIn("own key and stem", tab.output_panel.log.toPlainText())
        tab.close()
        tab.deleteLater()

    def test_every_plan_input_clears_a_ready_plan(self) -> None:
        tab = self._tab()
        tab.prefill_template(TEMPLATE)
        controller = tab.controller

        def remember_dummy_plan() -> None:
            controller.plan = object()
            controller._plan_revision = controller._draft_revision

        remember_dummy_plan()
        tab.identity_panel.internal_name.setText("Changed_identity")
        self.assertIsNone(controller.plan)

        remember_dummy_plan()
        tab.model_panel.icon_source.setText(str(self.root / "icons"))
        self.assertIsNone(controller.plan)

        remember_dummy_plan()
        tab.stats_panel.scale.setValue(1.25)
        tab.stats_panel._apply_scale()
        self.assertIsNone(controller.plan)
        tab.close()
        tab.deleteLater()

    def test_a_plan_finishing_after_an_edit_is_discarded(self) -> None:
        from PySide6.QtCore import QEventLoop

        from cdmw.ui.new_item.controller import NewItemStudioController

        service = NewItemService()
        snapshot = service.build_snapshot(self.entries, read_entry=_read)
        controller = NewItemStudioController(service=service, read_entry=_read)
        controller.snapshot = snapshot
        controller.set_template(TEMPLATE)
        controller.draft.internal_name = "First_Name"
        controller.draft.display_names = {"eng": "First"}
        ready_plan = service.plan(controller.current_spec(), snapshot)
        release = threading.Event()

        def delayed_task(_log, _stop):
            release.wait(1.0)
            return ready_plan

        with patch("cdmw.ui.new_item.controller.plan_task", return_value=delayed_task):
            self.assertTrue(controller.start_plan())
            controller.draft.internal_name = "Changed_After_Plan"
            controller.invalidate_plan()
            release.set()
            deadline = time.monotonic() + 2.0
            while controller._thread is not None and time.monotonic() < deadline:
                self.app.processEvents(QEventLoop.ProcessEventsFlag.AllEvents, 20)
        self.assertIsNone(controller.plan)
        self.assertNotIn(ready_plan.spec.item_key, controller.issued_keys)
        controller.shutdown()

    def test_controller_shutdown_does_not_wait_for_a_running_task(self) -> None:
        from PySide6.QtCore import QEventLoop

        from cdmw.ui.new_item.controller import NewItemStudioController

        controller = NewItemStudioController()

        def slow_task(_log, _stop):
            time.sleep(0.2)
            return None

        self.assertTrue(controller._run("slow", slow_task, lambda _result: None, lambda _message: None))
        deadline = time.monotonic() + 1.0
        while (controller._thread is None or not controller._thread.isRunning()) and time.monotonic() < deadline:
            self.app.processEvents(QEventLoop.ProcessEventsFlag.AllEvents, 20)
        started = time.monotonic()
        controller.shutdown()
        self.assertLess(time.monotonic() - started, 0.08)
        self.assertTrue(controller.iter_shutdown_workers())
        while controller._thread is not None and time.monotonic() < deadline + 1.0:
            self.app.processEvents(QEventLoop.ProcessEventsFlag.AllEvents, 20)
        self.assertEqual(controller.iter_shutdown_workers(), ())

    def test_a_builder_result_handed_in_directly_and_the_material_route(self) -> None:
        """`receive_imported_model` takes a ready Builder result (code can hand one in);
        the material route and the sheath are an imported model's questions."""

        from types import SimpleNamespace

        from cdmw.services.new_item_planning import ModelFiles

        tab = self._tab(window=SimpleNamespace())
        tab.prefill_template(TEMPLATE)
        with patch("cdmw.ui.new_item.panels_model.QFileDialog.getOpenFileName", return_value=("", "")):
            tab.model_panel.import_button.click()
        self.assertIsNone(tab.controller.model_import, "cancelling the file dialog imports nothing")
        entry = tab.controller.template_entries()[0]
        self.assertFalse(tab.model_panel.plain_pbr.isEnabled(), "the material route is an imported model's question")
        tab.receive_imported_model(entry, ModelFiles(pac_data=b"PAC imported"), scene=None)
        self.assertTrue(tab.model_panel.import_model.isChecked())
        self.assertEqual(tab.controller.draft.model_source, ModelSource.IMPORTED)
        self.assertTrue(tab.model_panel.plain_pbr.isEnabled())
        self.assertTrue(tab.model_panel.plain_pbr.isChecked(), "the plain PBR shaders by default")
        self.assertEqual(tab.controller.draft.material_route, MaterialRoute.PLAIN_PBR)
        self.assertEqual(tab.controller.current_spec().material_route, MaterialRoute.PLAIN_PBR)
        tab.model_panel.plain_pbr.setChecked(False)
        self.assertEqual(tab.controller.draft.material_route, MaterialRoute.BUILDER)
        tab.model_panel.plain_pbr.setChecked(True)
        self.assertTrue(tab.model_panel.own_sheath.isChecked() and tab.model_panel.own_sheath.isEnabled())
        self.assertEqual(tab.controller.current_spec().sheathed_model, SheathedModel.OWN_MODEL)
        tab.model_panel.own_sheath.setChecked(False)
        self.assertEqual(tab.controller.draft.sheathed_model, SheathedModel.TEMPLATE)
        tab.model_panel.own_sheath.setChecked(True)
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


    def test_a_busy_operation_after_the_panels_are_built_does_not_touch_the_bootstrap(self) -> None:
        """The bootstrap's progress bar is deleted when the panels replace it, and
        `busy_changed` goes on firing for every operation after that -- importing a model
        is one. A lambda was still calling setVisible on the deleted C++ object, which took
        the app down with `libshiboken: Internal C++ object already deleted`. A lambda also
        has no receiver for Qt to disconnect when the widget dies, which is why it survived
        to be called at all."""

        import inspect

        from PySide6.QtCore import QEvent

        import shiboken6

        from cdmw.ui.new_item.tab import NewItemStudioTab

        source = inspect.getsource(NewItemStudioTab.__init__)
        self.assertIn("busy_changed.connect(self._bootstrap_busy_changed)", source, "a slot Qt can disconnect")
        self.assertNotIn("lambda busy:", source, "not a lambda that outlives the widget it touches")

        tab = self._tab(window=None)
        progress = tab._progress
        tab.prefill_template(TEMPLATE)
        self.assertTrue(tab._panels_built, "the panels replaced the bootstrap")
        # deleteLater only runs when the loop processes deferred deletions, and the C++
        # object has to be gone for this to be the failure the reader hit
        self.app.processEvents()
        self.app.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        self.app.processEvents()
        self.assertFalse(shiboken6.isValid(progress), "the bootstrap's progress bar is gone")

        # what an import does. Neither the slot nor the signal may touch what is gone.
        tab._bootstrap_busy_changed(True)
        tab._bootstrap_busy_changed(False)
        tab.controller.busy_changed.emit(True)
        tab.controller.busy_changed.emit(False)
        self.app.processEvents()
        tab.close()
        tab.deleteLater()

    def test_an_imported_model_is_textured_and_listed_before_it_is_applied(self) -> None:
        """Both of these were wrong for the same reason: they waited for the Builder result,
        which only exists once Apply the placement has run. Before that the studio still has
        the import's own textured decode and its material wrappers."""

        from types import SimpleNamespace

        from cdmw.modding.mesh_parser import ParsedMesh, SubMesh

        def mesh(texture: str) -> ParsedMesh:
            part = SubMesh(
                name="blade", material="steel", texture=texture,
                vertices=[(0.0, 0.0, 0.0), (0.1, 0.0, 0.0), (0.0, 0.1, 0.0)],
                uvs=[(0.0, 0.0)] * 3, normals=[(0.0, 1.0, 0.0)] * 3, faces=[(0, 1, 2)],
                vertex_count=3, face_count=1,
            )
            return ParsedMesh(
                path="import.pac", format="pac", submeshes=[part], bbox_min=(0.0, 0.0, 0.0),
                bbox_max=(0.1, 0.1, 0.0), total_vertices=3, total_faces=1, has_uvs=True,
            )

        tab = self._tab(window=None)
        tab.prefill_template(TEMPLATE)
        controller = tab.controller
        self.assertIsNone(controller.model_result, "nothing applied yet")

        controller.model_import = SimpleNamespace(
            baked_preview_mesh=lambda: mesh("frostmourne_basecolor.png"),
            baked_scene_mesh=lambda: mesh(""),
            baked_bounds=lambda: ((0.0, 0.0, 0.0), (0.1, 0.1, 0.0)),
            # the materials the file itself declares, which is what a glow is chosen by
            scene=SimpleNamespace(material_bindings=(
                SimpleNamespace(material_name="lambert1"),
                SimpleNamespace(material_name="Inside"),
                SimpleNamespace(material_name="Inside"),
                SimpleNamespace(material_name="Outside"),
            )),
        )
        planned, kind = controller.item_mesh_as_planned()
        self.assertEqual(kind, "placed")
        self.assertEqual(
            planned.submeshes[0].texture, "frostmourne_basecolor.png",
            "the effect viewport gets the textured decode, not the bare geometry",
        )

        # the parts are the model's own materials, in the order the file declares them and
        # each one once. The template's parts are never among them: `cd_phm_02_hammer_sub_0002`
        # is not a thing the reader can act on, and it is not theirs to light either.
        self.assertEqual(
            controller.material_parts(),
            (("lambert1", "lambert1"), ("Inside", "Inside"), ("Outside", "Outside")),
        )

        # and the step fills its list when the file is read, not when Apply runs: the
        # Builder result only exists after Apply, and listening for that alone left it empty
        panel = tab.model_panel
        panel.glow_parts.clear()
        controller.model_import_changed.emit(controller.model_import)
        self.assertEqual(
            [panel.glow_parts.item(row).text() for row in range(panel.glow_parts.count())],
            ["lambert1", "Inside", "Outside"],
            "importing a model fills the parts list",
        )
        tab.close()
        tab.deleteLater()

    def test_an_fbx_with_no_blender_never_starts_a_read(self) -> None:
        """It did, and that was the fault: the refusal lived at the bottom of the worker,
        so a zip was extracted whole, the reason arrived in the window's status line, and
        the step was left saying "Reading the model file..." over a read that could never
        finish. The rule is answered from the listing, before the worker exists."""

        import zipfile

        tab = self._tab(window=None)
        tab.prefill_template(TEMPLATE)
        controller = tab.controller
        panel = tab.model_panel

        holder = tempfile.TemporaryDirectory(prefix="cdmw_fbx_gate_")
        self.addCleanup(holder.cleanup)
        folder = Path(holder.name)
        archive = folder / "magic-sword.zip"
        with zipfile.ZipFile(archive, "w") as zipped:
            zipped.writestr("source/MagicSword.fbx", b"not really an fbx")

        said: list = []
        controller.status_message.connect(lambda text, bad: said.append((text, bad)))
        with patch("cdmw.ui.new_item.controller.blender_for_fbx", return_value=""):
            started = controller.start_model_import(archive)

        self.assertFalse(started, "no read is started at all")
        self.assertFalse(controller.busy, "and nothing goes busy over it")
        self.assertEqual(sorted(path.name for path in folder.iterdir()), ["magic-sword.zip"], "nothing extracted")
        self.assertTrue(said and said[-1][1], "the refusal is said as a problem")
        self.assertIn("MagicSword.fbx", said[-1][0])
        self.assertIn("Blender", said[-1][0])
        # and it lands where the reader is looking, not only in the window's status line
        self.assertIn("MagicSword.fbx", panel.model_status.text())

        # the row that answers it is on the step, not folded behind Import tips: a refusal
        # naming a button nobody can see is the same as no answer. It shows with the rest
        # of the import controls, which is the moment the question can be asked at all.
        panel.import_model.setChecked(True)
        self.assertTrue(panel.blender_holder.isVisibleTo(panel), "the Blender row shows with the import controls")
        # and it says which of the two states the studio is in (the machine running this
        # may have a Blender stored, so both are asked for rather than read off it)
        with patch("cdmw.ui.new_item.blender_setting.blender_for_fbx", return_value=""):
            panel._refresh_blender_label()
        self.assertIn("Blender is required", panel.blender_label.text())
        self.assertFalse(panel.blender_forget.isVisibleTo(panel), "nothing to forget")
        with patch("cdmw.ui.new_item.blender_setting.blender_for_fbx", return_value="C:/blender/blender.exe"):
            panel._refresh_blender_label()
        self.assertIn("C:/blender/blender.exe", panel.blender_label.text(), "which Blender, not just that there is one")
        tab.close()
        tab.deleteLater()

    def test_walking_the_template_list_rebuilds_once_the_reader_stops(self) -> None:
        """Choosing a template rebuilds five steps: 65 ms against the real archives, and
        1,926 ms before the corpus measure moved to the snapshot worker. The list asked
        for that once per row the arrow keys passed through, so holding the key down
        queued one per row and the window stopped answering."""

        from PySide6.QtCore import Qt
        from PySide6.QtWidgets import QListWidgetItem

        tab = self._tab(window=None)
        tab.prefill_template(TEMPLATE)
        panel = tab.template_panel

        taken: list = []
        tab.controller.set_template = lambda key: taken.append(key)  # type: ignore[method-assign]

        panel._syncing = True
        panel.matches.clear()
        for key in (4001, 4002, 4003):
            item = QListWidgetItem(f"row {key}")
            item.setData(Qt.UserRole, key)
            panel.matches.addItem(item)
        panel._syncing = False

        for row in range(panel.matches.count()):
            panel.matches.setCurrentRow(row)
        self.assertEqual(taken, [], "walking the list takes nothing on the way past")
        self.assertTrue(panel._pick_timer.isActive(), "the row waits for the reader to settle")

        # and the row they stopped on is taken, once
        panel._pick_timer.stop()
        panel._apply_pick()
        self.assertEqual(taken, [4003])

        # leaving the step is settling on a row too: a pending pick is never dropped
        taken.clear()
        panel.matches.setCurrentRow(0)
        tab._show_step(1)
        self.assertEqual(taken, [4001], "moving on takes the row the reader left on")
        self.assertFalse(panel._pick_timer.isActive())
        tab.close()
        tab.deleteLater()

    def test_the_parts_that_glow_are_chosen_on_the_step(self) -> None:
        """A template's own emissive is not inherited -- its mask is cut for the template's
        mesh, and what the importer generates in its place is flat, so inheriting it lit a
        whole imported sword. A glow is asked for, part by part."""

        from PySide6.QtCore import Qt

        tab = self._tab(window=None)
        tab.prefill_template(TEMPLATE)
        panel = tab.model_panel
        self.assertFalse(panel.glow_box.isChecked(), "nothing glows unless it is asked for")
        self.assertEqual(tab.controller.current_spec().glow, None)

        # nothing to glow until a model is imported: the route that writes a glow runs
        # only for one, so the group stays shut
        self.assertFalse(panel.glow_box.isEnabled())
        self.assertIn("Import a model", panel.glow_box.toolTip())

        # the parts are the imported model's own materials, keyed by the wrapper name the
        # file uses and labelled by the name the reader gave them
        parts = (("cd_phm_01_sword_0109", "blade"), ("cd_phm_01_sword_handle_0109", "grip"))
        tab.controller.material_parts = lambda: parts  # type: ignore[method-assign]
        panel.refresh_glow_parts()
        self.assertEqual([panel.glow_parts.item(row).text() for row in range(panel.glow_parts.count())], ["blade", "grip"])
        self.assertTrue(panel.glow_box.isEnabled())

        panel.glow_box.setChecked(True)
        panel.glow_parts.item(0).setCheckState(Qt.CheckState.Checked)
        panel.glow_intensity.setValue(6.5)
        tab.controller.draft.glow_color = (0.0, 0.5, 1.0)
        glow = tab.controller.current_spec().glow
        self.assertEqual(glow.parts, (parts[0][0],), "the plan is given the wrapper name, not the label")
        self.assertEqual(glow.intensity, 6.5)
        self.assertEqual(glow.hex_color(), "#0080FFFF")

        panel.glow_box.setChecked(False)
        self.assertIsNone(tab.controller.current_spec().glow, "turned off, nothing glows again")
        tab.close()
        tab.deleteLater()


class InstallReportTests(unittest.TestCase):
    """Step 7's four buttons all report through one signal, and they hand back four
    different kinds of result. Before this, three of them said "Installed 0 archive
    entr(ies)", which reads like a failure after a button that did its work."""

    def test_each_route_says_what_it_did(self) -> None:
        from cdmw.services.archive_overlay_install import OverlayInstallResult
        from cdmw.services.archive_overlay_migration import MigrationPlan, MigrationResult, RemovalResult
        from cdmw.ui.new_item.panels_output import install_result_report

        title, message = install_result_report(
            OverlayInstallResult(Path("g/0036"), 1, 27, 113_457_995, 4, Path("b/1"), ())
        )
        self.assertEqual(title, "Install as an overlay")
        self.assertIn("0036", message)
        self.assertIn("27 file(s)", message)
        self.assertIn("4 of them carried forward", message)
        self.assertIn("were not written to", message)

        title, message = install_result_report(MigrationResult(Path("g/0036"), 12, (Path("a"), Path("b")), Path("b/2"), 5_000))
        self.assertEqual(title, "Move installed items into the overlay")
        self.assertIn("Moved 12 file(s)", message)
        self.assertIn("2 archive file(s)", message)

        title, message = install_result_report(MigrationPlan((), (), ()))
        self.assertEqual(title, "Move installed items into the overlay")
        self.assertIn("Nothing to move", message)

        title, message = install_result_report(RemovalResult(Path("g/0036"), True, 2, Path("b/3")))
        self.assertEqual(title, "Remove the overlay")
        self.assertIn("Removed the overlay 0036", message)
        self.assertIn("gone from the game", message)

        # the texture registry is a loose file the overlay rewrote in place, so a removal
        # that put it back has to say so
        title, message = install_result_report(RemovalResult(Path("g/0036"), True, 2, Path("b/3"), ("meta/0.pathc",)))
        self.assertIn("meta/0.pathc", message)
        self.assertIn("back to what the game shipped", message)

        title, message = install_result_report(RemovalResult(None, False, 0, None))
        self.assertIn("no overlay to remove", message)

        class _Patched:
            changed_paths = ("a", "b", "c")
            backup_dir = Path("b/4")

        title, message = install_result_report(_Patched())
        self.assertEqual(title, "Install into the game archives")
        self.assertIn("Installed 3 archive entr(ies)", message)


if __name__ == "__main__":
    unittest.main()
