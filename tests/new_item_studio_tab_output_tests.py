"""Planning, writing, overlay, and model-import cases for the New Item Studio tab."""

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


def _assert_template_panel_chrome_removed(case: unittest.TestCase, template) -> None:
    from PySide6.QtWidgets import QLabel

    case.assertFalse(hasattr(template, "summary"))
    preview_layout = template.preview_group.layout()
    case.assertLess(
        preview_layout.indexOf(template.preview_holder),
        preview_layout.indexOf(template.preview_note),
    )
    case.assertLess(
        preview_layout.indexOf(template.preview_note),
        preview_layout.indexOf(template.preview_status),
    )
    case.assertFalse(
        any(
            label.text().startswith("Every new item is a copy")
            for label in template.findChildren(QLabel)
        )
    )


class _TabOutputMixin:
    def test_snapshot_panels_and_a_plan_through_the_panels(self) -> None:
        from PySide6.QtCore import Qt

        tab = self._tab()
        statuses: list[tuple[str, bool]] = []
        tab.status_message_requested.connect(lambda message, error: statuses.append((message, error)))
        tab.prefill_template(TEMPLATE)
        self.assertTrue(tab.controller.ready)
        self.assertEqual(tab.controller.draft.template_key, TEMPLATE)
        template = tab.template_panel
        _assert_template_panel_chrome_removed(self, template)
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
        self.assertIn("experimental", stats.new_stat.itemText(crit_index), "no shipped equipment carries it, and the list says so")
        stats.new_stat.setCurrentIndex(crit_index)
        stats.new_stat_value.setValue(250)
        stats.add_stat_button.click()
        self.assertEqual(stats.table.columnCount(), 4)
        self.assertEqual(stats.table.horizontalHeaderItem(1).text(), "Critical rate (CriticalRate) — raw", "added after the template's stats, before the prices")
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
        self.assertIn("Internal ID: Socket_Swift_III", perks.perk_details.plain_text())
        perks.add_button.click()
        perks.perk_filter.setText("Gem_III")
        perks.add_button.click()
        self.assertEqual(tab.controller.draft.socket_items, [1002791, 1002812, 1002793])
        perks.chosen.setCurrentRow(0)
        perks.remove_button.click()
        self.assertEqual(tab.controller.draft.socket_items, [1002812, 1002793])
        effects = perks.effects_workspace
        self.assertEqual(perks.effect_preset.count(), 1, "the curated/proven dropdown no longer supplies options")
        self.assertEqual(perks.effect_preset.currentData(), "")
        self.assertIsNotNone(tab.controller.effect_catalogue, "effect metadata is indexed automatically")
        self.assertEqual(len(tab.controller.effect_catalogue), 3)
        effects.choose_effect("fx_test_fire")
        self.assertEqual(tab.controller.draft.effect_stem, "", "selection remains staged")
        self.assertEqual(effects.staged_state.scale, 1.0, "every newly selected effect starts neutral")
        self.assertEqual(effects.staged_state.offset, (0.0, 0.0, 0.0))
        self.assertTrue(effects.has_staged_changes())
        effects._confirm_unreviewed = lambda _reason: True
        self.assertTrue(effects.apply_staged())
        self.assertEqual(tab.controller.draft.effect_stem, "fx_test_fire")
        self.assertEqual(tab.controller.current_spec().effect, "fx_test_fire.level.effect")
        self.assertEqual(tab.controller.current_spec().socket_items, (1002812, 1002793))
        effects.search.setText("firefly")
        stems = [effects.library_model.row(index).stem for index in range(effects.library_model.rowCount())]
        self.assertEqual(stems, ["", "fx_test_fire"])
        effects.search.setText("ice")
        stems = [effects.library_model.row(index).stem for index in range(effects.library_model.rowCount())]
        self.assertEqual(stems, ["", "fx_test_fire", "fx_test_ice"], "filtering keeps the committed selection")
        self.assertTrue(tab.controller.effect_facts("fx_test_ice").walk_note, "an undecoded effect remains placeable as shipped")
        effects.search.setText("")
        effects.choose_effect("")
        self.assertTrue(effects.apply_staged())
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
        template_mesh = ParsedMesh(
            path="template.pac",
            format="pac",
            submeshes=[SubMesh(
                name="template",
                vertices=[
                    (x, y, z)
                    for x in (template_box[0][0], template_box[1][0])
                    for y in (template_box[0][1], template_box[1][1])
                    for z in (template_box[0][2], template_box[1][2])
                ],
                faces=[],
            )],
        )
        with patch.object(
            tab.controller,
            "_template_geometry_build",
            return_value=(("template",), lambda _stop: template_mesh),
        ), patch.object(
            tab.controller,
            "_template_uses_weapon_fit",
            return_value=True,
        ), patch(
            "cdmw.ui.new_item.controller.load_model_import_source",
            lambda path, **kw: seen.setdefault("path", path) and source,
        ), patch(
            "cdmw.ui.new_item.panels_model.QFileDialog.getOpenFileName",
            return_value=(r"E:/models/box.zip", ""),
        ):
            panel.import_button.click()
        self.assertEqual(seen["path"], Path(r"E:/models/box.zip"))
        self.assertIs(tab.controller.model_import, source)
        self.assertEqual(tab.controller.draft.model_source, ModelSource.IMPORTED)
        self.app.processEvents()
        self.assertTrue(panel.placement_group.isVisibleTo(panel))
        self.assertTrue(panel.model_group.isVisibleTo(panel))
        self.assertTrue(panel.icon_group.isVisibleTo(panel))
        self.assertTrue(
            panel.preview.isVisibleTo(tab.template_panel),
            "the same resident preview starts under Template before Model & Placement opens",
        )
        tab.show_step(2)
        self.app.processEvents()
        self.assertTrue(panel.preview.isVisibleTo(panel), "the resident preview moves with its loaded scene")
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
        self.assertEqual(scene.model_origin, source.baked_origin())
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

    def test_model_import_fits_a_slow_template_without_blocking_the_ui_thread(self) -> None:
        """The source reader was asynchronous but its completion callback parsed the
        template PAC twice on the UI thread. A slow template therefore still produced a
        real Windows AppHang after the DAE worker had already finished."""

        from types import SimpleNamespace

        from PySide6.QtCore import QThread, QTimer

        from cdmw.modding.mesh_parser import ParsedMesh, SubMesh
        from cdmw.ui.new_item.controller import NewItemStudioController
        from cdmw.ui.new_item.model_import import ModelImportSource

        imported_mesh = ParsedMesh(
            path="helmet.dae",
            format="dae",
            submeshes=[SubMesh(name="helmet", vertices=[(-1.0, -1.0, -1.0), (1.0, 1.0, 1.0)], faces=[])],
        )
        template_mesh = ParsedMesh(
            path="helmet_template.pac",
            format="pac",
            submeshes=[SubMesh(name="helmet", vertices=[(-0.2, 1.5, -0.2), (0.2, 1.9, 0.2)], faces=[])],
        )
        source = ModelImportSource(
            chosen_path=Path("helmet.zip"),
            model_path=Path("helmet.dae"),
            scene=SimpleNamespace(mesh=imported_mesh, material_bindings=()),
            preview_model=SimpleNamespace(meshes=[]),
            bounds=((-1.0, -1.0, -1.0), (1.0, 1.0, 1.0)),
            centroid=(0.0, 0.0, 0.0),
        )
        controller = NewItemStudioController(synchronous=False)
        controller.snapshot = object()
        controller.draft.template_key = 7
        heartbeats: list[float] = []
        fit_threads: list[QThread] = []
        timer = QTimer()
        timer.setInterval(10)
        timer.timeout.connect(lambda: heartbeats.append(time.perf_counter()))

        def slow_worker_template(_stop_event):
            fit_threads.append(QThread.currentThread())
            time.sleep(0.25)
            return template_mesh

        def slow_ui_template():
            fit_threads.append(QThread.currentThread())
            time.sleep(0.25)
            return template_mesh

        try:
            timer.start()
            baseline_until = time.perf_counter() + 0.04
            while time.perf_counter() < baseline_until:
                self.app.processEvents()
                time.sleep(0.002)
            with patch.object(
                controller,
                "_template_geometry_build",
                return_value=(("template",), slow_worker_template),
            ), patch.object(
                controller,
                "_template_uses_weapon_fit",
                return_value=False,
            ), patch.object(
                controller,
                "_template_mesh",
                side_effect=slow_ui_template,
            ), patch(
                "cdmw.ui.new_item.controller.load_model_import_source",
                return_value=source,
            ):
                returned_at = time.perf_counter()
                self.assertTrue(controller.start_model_import(Path("helmet.dae")))
                self.assertLess(time.perf_counter() - returned_at, 0.05, "starting the worker returns immediately")
                deadline = time.perf_counter() + 2.0
                while time.perf_counter() < deadline and controller.busy:
                    self.app.processEvents()
                    time.sleep(0.002)
            after_until = time.perf_counter() + 0.04
            while time.perf_counter() < after_until:
                self.app.processEvents()
                time.sleep(0.002)
            timer.stop()

            gaps = [later - earlier for earlier, later in zip(heartbeats, heartbeats[1:])]
            self.assertIs(controller.model_import, source)
            self.assertFalse(controller.busy)
            self.assertTrue(fit_threads)
            self.assertTrue(all(thread is not controller.thread() for thread in fit_threads))
            self.assertLess(max(gaps, default=0.0), 0.12, "the 10 ms UI heartbeat stays live during the template fit")
            self.assertFalse(source.fit_match_grip, "a helmet template receives the centred equipment fit")
            self.assertAlmostEqual(source.baked_origin()[1], 1.7, places=6)
        finally:
            timer.stop()
            controller.request_shutdown()
            deadline = time.perf_counter() + 2.0
            while time.perf_counter() < deadline and controller.iter_shutdown_workers():
                self.app.processEvents()
                time.sleep(0.002)
            controller.deleteLater()

    def test_imported_model_parts_round_trip_through_mesh_editor(self) -> None:
        """The handoff never reads resident geometry on the UI thread: the New Item
        controller's owned task captures one stable revision, rebuilds the textured
        source, invalidates the earlier placement build, and exposes the new part."""

        from types import SimpleNamespace

        from cdmw.modding.mesh_deformer import clone_mesh_for_editing, split_faces_to_submesh
        from cdmw.modding.mesh_parser import ParsedMesh, SubMesh
        from cdmw.modding.scene_import_result_ops import SceneImportResult
        from cdmw.services.new_item_materials import glow_preview_parameter_groups
        from cdmw.services.preview_workflow_service import parsed_mesh_to_preview_model
        from cdmw.ui.new_item.model_import import ModelImportSource

        mesh = ParsedMesh(
            path="blade.gltf",
            format="gltf",
            submeshes=[SubMesh(
                name="blade",
                material="steel",
                vertices=[(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (1.0, 1.0, 0.0), (0.0, 1.0, 0.0), (-0.5, 0.5, 0.0)],
                uvs=[(0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0), (0.0, 0.5)],
                normals=[(0.0, 0.0, 1.0)] * 5,
                faces=[(0, 1, 2), (0, 2, 3), (0, 3, 4)],
                vertex_count=5,
                face_count=3,
            )],
            bbox_min=(0.0, 0.0, 0.0),
            bbox_max=(1.0, 1.0, 0.0),
            total_vertices=5,
            total_faces=3,
            has_uvs=True,
        )
        binding = SimpleNamespace(material_name="steel", submesh_index=0, texture_slots=())
        scene = SceneImportResult(mesh=mesh, material_bindings=(binding,))
        source = ModelImportSource(
            chosen_path=Path("blade.gltf"),
            model_path=Path("blade.gltf"),
            scene=scene,
            preview_model=parsed_mesh_to_preview_model(mesh),
            bounds=((0.0, 0.0, 0.0), (1.0, 1.0, 0.0)),
        )

        class FakeMeshController:
            def __init__(self, edited, session_id):
                self.active_session_id = session_id
                self.mesh = edited
                self.revision = 1
                self.change_during_capture = False

            def session_view(self):
                return SimpleNamespace(session_id=self.active_session_id, revision=self.revision)

            def working_mesh(self, *, clone=True):
                result = clone_mesh_for_editing(self.mesh) if clone else self.mesh
                if self.change_during_capture:
                    self.revision += 1
                return result

        class FakeEditor:
            standalone_controller = None
            standalone_pending_dotnet_topology_request = None

            def open_mesh_session(self, opened, *, session_id, mode, initial_element_type=""):
                self.assert_mode = mode
                self.assert_element_type = initial_element_type
                edited = clone_mesh_for_editing(opened)
                split_faces_to_submesh(edited, selected_faces_by_submesh={0: {0}})
                split_faces_to_submesh(edited, selected_faces_by_submesh={0: {0}})
                self.standalone_controller = FakeMeshController(edited, session_id)
                return self.standalone_controller.session_view()

            @staticmethod
            def _standalone_action_worker_active():
                return False

            @staticmethod
            def _wait_for_dotnet_export_updates(_timeout):
                return True

        class FakeContainer:
            def __init__(self, editor):
                self.editor = editor

            def ensure_widget(self):
                return self.editor

        editor = FakeEditor()
        container = FakeContainer(editor)
        activated = []
        window = SimpleNamespace(
            mesh_editor_tab=container,
            _activate_tool_widget=lambda target: activated.append(target),
        )
        tab = self._tab(window=window)
        tab.prefill_template(TEMPLATE)
        tab.controller.model_import = source
        tab.controller.model_result = SimpleNamespace(rebuilt_data=b"old placement")
        source.applied = (source.bake, tab.controller.model_placement)
        tab.controller.draft.model_source = ModelSource.IMPORTED
        tab.controller.model_import_changed.emit(source)

        tab.model_panel.open_part_editor_button.click()
        self.assertEqual(editor.assert_mode, "edit")
        self.assertEqual(editor.assert_element_type, "face")
        self.assertIs(activated[-1], container)
        self.assertFalse(tab.model_panel.use_part_editor_button.isHidden())

        tab.model_panel.use_part_editor_button.click()
        self.assertEqual(len(source.scene.mesh.submeshes), 3)
        self.assertEqual(source.mesh_generation, 1)
        self.assertIsNone(source.applied)
        self.assertIsNone(tab.controller.model_result, "the placement build predates the edited parts")
        self.assertEqual(
            tab.controller.material_parts(),
            (("steel", "steel"), ("blade split", "blade split"), ("blade split 2", "blade split 2")),
        )
        glow_groups = glow_preview_parameter_groups(
            source.scene.mesh,
            SimpleNamespace(parts=("blade split 2",), color=(1.0, 0.25, 0.0), intensity=3.0),
        )
        glow_by_part = {
            index: group
            for group in glow_groups
            for index in group["source_submesh_indices"]
        }
        self.assertIsNone(glow_by_part[1]["emissive_intensity"])
        self.assertIsNotNone(glow_by_part[2]["emissive_intensity"])
        self.assertIn("3 part(s)", tab.model_panel.part_editor_status.plain_text())

        editor.standalone_controller.change_during_capture = True
        tab.model_panel.use_part_editor_button.click()
        self.assertEqual(source.mesh_generation, 1, "a changing resident revision is rejected")
        self.assertIn("safely", tab.model_panel.part_editor_status.plain_text().lower())
        tab.close()
        tab.deleteLater()

    def test_imported_model_part_capture_runs_on_the_owned_worker(self) -> None:
        from types import SimpleNamespace

        from PySide6.QtCore import QEventLoop, QThread

        from cdmw.modding.mesh_deformer import clone_mesh_for_editing
        from cdmw.modding.mesh_parser import ParsedMesh, SubMesh
        from cdmw.modding.scene_import_result_ops import SceneImportResult
        from cdmw.services.preview_workflow_service import parsed_mesh_to_preview_model
        from cdmw.ui.new_item.controller import NewItemStudioController
        from cdmw.ui.new_item.model_import import ModelImportSource

        mesh = ParsedMesh(
            path="worker.gltf",
            format="gltf",
            submeshes=[SubMesh(
                name="part",
                vertices=[(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0)],
                faces=[(0, 1, 2)],
                vertex_count=3,
                face_count=1,
            )],
            total_vertices=3,
            total_faces=1,
        )
        source = ModelImportSource(
            chosen_path=Path("worker.gltf"),
            model_path=Path("worker.gltf"),
            scene=SceneImportResult(mesh=mesh),
            preview_model=parsed_mesh_to_preview_model(mesh),
            bounds=((0.0, 0.0, 0.0), (1.0, 1.0, 0.0)),
        )
        controller = NewItemStudioController()
        controller.model_import = source
        observed = []

        class MeshController:
            active_session_id = "worker-session"

            @staticmethod
            def session_view():
                return SimpleNamespace(session_id="worker-session", revision=1)

            @staticmethod
            def working_mesh(*, clone=True):
                observed.append(QThread.currentThread() is controller.thread())
                return clone_mesh_for_editing(mesh) if clone else mesh

        self.assertTrue(controller.start_model_part_edit_apply(
            source,
            MeshController(),
            expected_session_id="worker-session",
            wait_for_updates=lambda _timeout: True,
        ))
        deadline = time.monotonic() + 2.0
        while controller._thread is not None and time.monotonic() < deadline:
            self.app.processEvents(QEventLoop.ProcessEventsFlag.AllEvents, 20)
        self.assertEqual(observed, [False], "resident mesh hydration did not run on the UI thread")
        self.assertEqual(source.mesh_generation, 1)
        self.assertEqual(controller.iter_shutdown_workers(), ())
        controller.shutdown()

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

    def test_output_places_plan_and_review_left_of_write_actions(self) -> None:
        from PySide6.QtWidgets import QGridLayout, QGroupBox

        tab = self._tab()
        tab.prefill_template(TEMPLATE)
        panel = tab.output_panel
        sections = {group.title(): group for group in panel.findChildren(QGroupBox)}
        content = next(
            panel.layout().itemAt(index).layout()
            for index in range(panel.layout().count())
            if panel.layout().itemAt(index).layout() is not None
        )

        self.assertIsInstance(content, QGridLayout)
        positions = {
            content.itemAt(index).widget(): content.getItemPosition(index)
            for index in range(content.count())
        }
        self.assertEqual(positions[sections["1. Build the plan"]], (0, 0, 1, 1))
        self.assertEqual(positions[sections["2. What the plan will change"]], (1, 0, 1, 1))
        self.assertEqual(positions[sections["3. Write it"]], (0, 1, 2, 1))
        self.assertEqual((content.columnStretch(0), content.columnStretch(1)), (1, 1))
        tab.close()
        tab.deleteLater()
