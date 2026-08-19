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
        model.preview.captured.emit(captured, QImage(str(captured)))
        self.assertTrue(model.generate_icon.isChecked())
        self.assertEqual(tab.controller.draft.icon_source_path, str(captured))
        self.assertTrue(model.icon_thumbnail.isVisibleTo(model))
        with patch.object(type(model.preview), "capture", lambda self_, path=None: False):
            model._capture_inline()
        self.assertIn("not showing the item yet", model.preview_status.text())
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


if __name__ == "__main__":
    unittest.main()
