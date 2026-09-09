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
    def test_template_preview_composes_every_prefab_model_and_enables_native_components(self) -> None:
        from cdmw.modding.mesh_parser import ParsedMesh, SubMesh

        tab = self._tab()
        tab.prefill_template(TEMPLATE)
        primary = tab.controller.template_entries()[0]
        component = replace(
            primary,
            path=primary.path.replace(".pac", "_lower.pac"),
            offset=primary.offset + primary.comp_size,
        )
        prefab = replace(
            primary,
            path=primary.path.replace(".pac", ".prefab"),
            offset=component.offset + component.comp_size,
        )
        upper = ParsedMesh(
            path=primary.path,
            format="pac",
            submeshes=[SubMesh(name="upper", vertices=[(0.0, 0.0, 0.0)] * 3, faces=[(0, 1, 2)])],
        )
        lower = ParsedMesh(
            path=component.path,
            format="pac",
            submeshes=[SubMesh(name="lower", vertices=[(0.0, 1.0, 0.0)] * 3, faces=[(0, 1, 2)])],
        )
        output = self.root / "composite-native-output"
        native_package = output / "native-package"
        attempt = SimpleNamespace(succeeded=True, package_path=str(native_package))
        package = SimpleNamespace(package_dir=native_package)

        with patch.object(
            tab.controller,
            "template_entries",
            return_value=(primary, component),
        ), patch.object(
            tab.controller,
            "template_prefab_entries",
            return_value=(prefab,),
            create=True,
        ), patch(
            "cdmw.services.new_item_snapshot.NewItemSnapshot.payload",
            autospec=True,
            side_effect=lambda _snapshot, path: path.encode("utf-8"),
        ), patch(
            "cdmw.services.mesh_workflow_service.parse_pac",
            side_effect=(upper, lower),
        ):
            _token, source = tab.controller.item_preview_source()
            geometry = source.geometry(threading.Event())

        self.assertEqual([mesh.name for mesh in geometry.submeshes], ["upper", "lower"])

        with patch.object(
            tab.controller,
            "template_entries",
            return_value=(primary, component),
        ), patch.object(
            tab.controller,
            "template_prefab_entries",
            return_value=(prefab,),
            create=True,
        ), patch(
            "cdmw.workers.archive_preview_native.native_preview_model_property_indices",
            return_value={primary.path.casefold(): 1},
        ) as model_property_indices, patch(
            "cdmw.services.preview_rendering_service.run_native_preview_core_preview_job",
            return_value=attempt,
        ) as run_native, patch(
            "cdmw.services.mesh_rust_preview_cache.build_or_lookup_rust_preview_package",
            return_value=package,
        ) as build_package:
            _token, source = tab.controller.item_preview_source()
            result = source.materials(
                threading.Event(),
                output_root=output,
                native_preview_core_cache_root=self.root / "native-cache",
            )

        self.assertEqual(result, native_package)
        native_kwargs = run_native.call_args.kwargs
        self.assertEqual(native_kwargs["enabled_prefab_component_paths"], (component.path,))
        self.assertEqual(native_kwargs["dependency_entries"], (primary, component, prefab))
        self.assertEqual(native_kwargs["model_property_indices"], {primary.path.casefold(): 1})
        model_property_indices.assert_called_once()
        archive_identity = build_package.call_args.kwargs["archive_identity"]
        self.assertTrue(archive_identity.startswith("new_item_native:"))
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

    def test_model_apply_reads_captured_archive_maps_on_its_worker(self) -> None:
        import threading
        from contextlib import nullcontext
        from unittest.mock import Mock
        from cdmw.domain.cancellation import RunCancelled
        from cdmw.ui.new_item.controller import NewItemStudioController

        main_thread = threading.get_ident()
        readers, pending, results, prefab_reads = [], [], [], []
        by_path, by_basename = {}, {}

        def archive_maps():
            readers.append(threading.get_ident())
            return by_path, by_basename

        def prefab_payload(path):
            prefab_reads.append((path, threading.get_ident()))
            return b"selected prefab"

        def defer(_lane, task, _done, _failed, **_kwargs):
            pending.append(task)
            return True

        controller = SimpleNamespace(
            model_import=SimpleNamespace(usage=nullcontext, label="Sword", bake=object()),
            template_entries=lambda: (SimpleNamespace(basename="sword.pac"),),
            template_primary_entry=lambda: SimpleNamespace(basename="sword.pac"), _active_variant=("selected.prefab", "sword.pac"),
            model_placement=object(), snapshot=SimpleNamespace(archive_index_maps=archive_maps, payload=prefab_payload),
            _run=defer, import_dependency_context=Mock(side_effect=AssertionError("The unused family scan must not run")),
        )
        with patch("cdmw.ui.new_item.controller.build_placed_import", return_value="built") as build:
            self.assertTrue(NewItemStudioController.start_model_apply(controller))
            self.assertEqual([], readers)
            self.assertEqual([], prefab_reads)
            controller.snapshot = SimpleNamespace(archive_index_maps=Mock(side_effect=AssertionError("Snapshot changed")))

            def run():
                try:
                    results.append(pending[0](lambda _message: None, lambda *_args: None, threading.Event()))
                except Exception as error:
                    results.append(error)

            worker = threading.Thread(target=run)
            worker.start()
            worker.join(3)
            self.assertFalse(worker.is_alive())
            self.assertEqual(["built"], results)
            self.assertEqual(1, len(readers))
            self.assertNotEqual(main_thread, readers[0])
            self.assertIs(by_path, build.call_args.kwargs["entries_by_normalized_path"])
            self.assertIs(by_basename, build.call_args.kwargs["entries_by_basename"])
            self.assertEqual([("selected.prefab", readers[0])], prefab_reads)
            self.assertEqual(b"selected prefab", build.call_args.kwargs["attachment_prefab_data"])
            cancelled = threading.Event()
            cancelled.set()
            with self.assertRaises(RunCancelled):
                pending[0](lambda _message: None, lambda *_args: None, cancelled)
            self.assertEqual(1, len(readers))
            self.assertEqual(1, build.call_count)
            self.assertEqual(1, len(prefab_reads))

    def test_one_copper_and_the_folded_advanced_controls(self) -> None:
        tab = self._tab()
        tab.prefill_template(TEMPLATE)
        stats = tab.stats_panel
        self.assertFalse(stats.advanced.isVisibleTo(stats), "advanced controls start folded")
        stats.one_copper_button.click()
        spec = tab.controller.current_spec()
        self.assertTrue(spec.buy_price_edits and all(e.price == 1 for e in spec.buy_price_edits), spec.buy_price_edits)
        self.assertTrue(spec.price_edits and all(e.price == 1 for e in spec.price_edits), spec.price_edits)
        self.assertFalse(spec.include_perk_prices)
        stats.advanced_toggle.setChecked(True)
        self.assertTrue(stats.advanced.isVisibleTo(stats))
        stats.reset_button.click()
        self.assertEqual(tab.controller.current_spec().price_edits, ())
        self.assertTrue(tab.controller.current_spec().include_perk_prices)
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
        self.assertIn("No current shop placement", tab.placement_panel.requirement_note.plain_text())
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

        with patch.object(stats, "summary_text", counted_summary_text), patch.object(tab.controller, "validate", counted_validate):
            stats.rebuild()
            self.assertEqual((counts["summary"], counts["validate"]), (0, 0), "a refill is not an edit")
            stats.table.item(0, 0).setText("20000")
            self.assertEqual((counts["summary"], counts["validate"]), (1, 1))
            self.assertIn("1 stat cell(s)", tab.summary.plain_text(), "the rail read the draft after the edit")
            self.assertTrue(stats.table.item(0, 0).font().bold(), "an edited cell is emphasised at once")
            self.assertIsNone(stats.table.item(0, 0).data(Qt.ForegroundRole))
            stats.table.item(0, 0).setText("12000")
            self.assertIsNone(stats.table.item(0, 0).data(Qt.FontRole), "back on the template: the default look")
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

    def test_one_copper_adds_copper_to_a_template_priced_only_in_another_currency(self) -> None:
        from cdmw.core.iteminfo_row import parse_iteminfo_row, rebuild_stat_block
        from cdmw.core.structured_binary_editor import parse_pabgh_table, replace_table_row
        from tests.test_new_item_provenance import current_files

        files = current_files()
        body_path = 'gamedata/binarystaticinfo__/bin/iteminfo.staticinfobody'
        head_path = body_path.replace('body', 'header')
        body, head = files[body_path], files[head_path]
        row = next(parse_iteminfo_row(body[start:end]) for entry, start, end in
            parse_pabgh_table(head, payload=body).row_spans(len(body)) if entry.row_id == TEMPLATE)
        raw = rebuild_stat_block(row, price_list=tuple(p for p in row.price_list if p.item_key != COPPER))
        files[body_path], files[head_path] = replace_table_row(body, head, TEMPLATE, raw)
        self.entries = tuple(parse_archive_pamt(build_package(self.root, files)))
        tab = self._tab()
        tab.start_snapshot()
        tab.prefill_template(TEMPLATE)
        tab.controller.draft.display_names['eng'] = 'Copper test'
        for label, action in (('quick', tab.stats_panel.one_copper_button.click), ('shortcut', tab.stats_panel.set_copper_price)):
            with self.subTest(action=label):
                tab.stats_panel.reset_button.click()
                action()
                self.assertEqual(tab.controller.draft.price_values[COPPER], 1)
                plan = tab.controller.service.plan(tab.controller.current_spec(), tab.controller.snapshot)
                body, head = plan.loose_files[body_path], plan.loose_files[head_path]
                item = next(parse_iteminfo_row(body[start:end]) for entry, start, end in
                    parse_pabgh_table(head, payload=body).row_spans(len(body)) if entry.row_id == plan.spec.item_key)
                self.assertEqual(next(p.price for p in item.price_list if p.item_key == COPPER), 1)
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
        tab.show_step(3)
        self.assertEqual(tab.steps.stepState(3), WorkflowStepState.WARNING)
        self.assertTrue(tab.steps.stepButton(3).property("workflowAttention"))
        self.assertEqual(tab.steps.stepButton(3).property("workflowMarker"), "warning")
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

    def test_perk_text_index_is_reused_and_tracks_the_current_localization_table(self) -> None:
        from cdmw.core.paloc_format import LocalizationEntry, LocalizationTable
        from cdmw.ui.new_item.controller import NewItemStudioController

        controller = NewItemStudioController(read_entry=_read, synchronous=True)
        self.addCleanup(controller.shutdown)
        controller.start_snapshot(self.entries)
        snapshot = controller.snapshot
        key = next(iter(snapshot.perk_item_keys))
        row = snapshot.rows[key]

        def with_text(label: str, description: str):
            return replace(snapshot, english=LocalizationTable((
                LocalizationEntry(0, row.name_key, label),
                LocalizationEntry(0, row.desc_key, description),
            )))

        controller.snapshot = with_text("First perk", "First description")
        with patch.object(LocalizationTable, "index", autospec=True, side_effect=LocalizationTable.index) as index:
            self.assertIn(key, dict(controller.perk_catalogue("First perk")))
            self.assertIn("First perk", controller.perk_label(key))
            for _ in range(10):
                self.assertIn("First description", controller.perk_details(key))
            self.assertEqual(index.call_count, 1, "all perk tooltips share one table lookup")

            controller.snapshot = with_text("Second perk", "Second description")
            self.assertIn("Second perk", controller.perk_label(key))
            self.assertIn("Second description", controller.perk_details(key))
            self.assertEqual(index.call_count, 2, "a replacement table cannot reuse stale text")

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
        self.assertEqual(tab.steps.stepState(0), WorkflowStepState.ACTIVE)
        effects = tab.perks_panel.effects_workspace
        effects._confirm_unreviewed = lambda _reason: True
        tab.show_step(4)
        effects.choose_effect("fx_test_fire")
        self.assertTrue(effects.has_staged_changes())
        self.assertFalse(tab.continue_button.isEnabled())
        self.assertEqual(tab.steps.stepState(4), WorkflowStepState.WARNING)

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

    def test_guided_header_separates_current_completed_future_and_attention(self) -> None:
        tab = self._tab()
        tab.start_snapshot()
        self.assertEqual(tab.steps.currentRow(), 0)
        self.assertEqual(tab.steps.stepState(0), WorkflowStepState.BLOCKED)
        self.assertEqual(
            [tab.steps.stepState(index) for index in range(1, tab.steps.count())],
            [WorkflowStepState.PENDING] * 6,
        )
        self.assertEqual(
            [index for index in range(tab.steps.count()) if tab.steps.stepButton(index).property("workflowActive")],
            [0],
        )
        self.assertFalse(any(tab.steps.stepButton(index).property("workflowCompleted") for index in range(1, 7)))
        self.assertTrue(tab.steps.stepButton(0).property("workflowAttention"))

        tab.show_step(1)
        self.assertEqual(tab.steps.stepState(0), WorkflowStepState.BLOCKED)
        self.assertEqual(tab.steps.stepState(1), WorkflowStepState.BLOCKED)
        tab.prefill_template(TEMPLATE)
        tab.identity_panel.internal_name.clear()
        tab.identity_panel.display_name.clear()
        self.app.processEvents()
        self.assertEqual(tab.steps.stepState(0), WorkflowStepState.COMPLETED)
        self.assertEqual(tab.steps.stepState(1), WorkflowStepState.BLOCKED)

        tab.identity_panel.internal_name.setText("Workflow_Test_Item")
        tab.identity_panel.display_name.setText("Workflow Test Item")
        tab.show_step(2)
        self.assertEqual(tab.steps.stepState(1), WorkflowStepState.COMPLETED)
        self.assertEqual(tab.steps.stepState(2), WorkflowStepState.ACTIVE)
        self.assertEqual(tab.steps.stepState(3), WorkflowStepState.PENDING)
        self.assertEqual(tab.steps.stepState(4), WorkflowStepState.PENDING)

        tab.show_step(5)
        self.assertEqual(tab.steps.stepState(5), WorkflowStepState.WARNING)
        self.assertTrue(tab.steps.stepButton(5).property("workflowAttention"))
        self.assertEqual(tab.steps.stepButton(5).property("workflowMarker"), "warning")
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
        tab.show()
        with patch.object(type(tab.controller), "item_mesh_as_planned", return_value=(blade, "template")):
            effects._rebuild_preview()
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
            self.assertAlmostEqual(left, 0.29, delta=0.035)
            self.assertAlmostEqual(centre, 0.43, delta=0.045)
            # The inspector retains its natural width; the viewport receives
            # extra width on larger windows instead of scaling every pane.
            self.assertEqual(placement.preview_splitter.widget(1).sizePolicy().horizontalStretch(), 0)
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

    def test_model_workspace_keeps_two_inspectors_around_the_resident_preview(self) -> None:
        from PySide6.QtGui import QFont, QFontDatabase, QPalette
        from PySide6.QtWidgets import QAbstractButton
        from cdmw.ui.themes import build_app_palette, build_app_stylesheet

        old_palette = QPalette(self.app.palette())
        old_stylesheet = self.app.styleSheet()
        old_font = QFont(self.app.font())
        self.addCleanup(self.app.setFont, old_font)
        # The Windows offscreen plugin has no system fonts unless explicitly loaded.
        font_path = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts/segoeui.ttf"
        if font_path.is_file():
            QFontDatabase.addApplicationFont(str(font_path))
            self.app.setFont(QFont("Segoe UI", 10))
        self.addCleanup(self.app.setPalette, old_palette)
        self.addCleanup(self.app.setStyleSheet, old_stylesheet)
        self.app.setPalette(build_app_palette("graphite"))
        self.app.setStyleSheet(build_app_stylesheet("graphite"))
        tab = self._tab()
        package_start = patch("cdmw.ui.new_item.item_preview.ItemPreviewFrame._start_package", lambda *_args, **_kwargs: None)
        package_start.start()
        self.addCleanup(package_start.stop)
        tab.show()
        tab.prefill_template(TEMPLATE)
        tab.show_step(2)
        panel = tab.model_panel
        panel.import_model.setChecked(True)
        panel._set_placement_visible(True)
        panel.import_summary.setText("wolf_gravestone_sword_free (1).zip\n14,709 vertices · 3 parts · 3 textures")
        panel.model_status.set_note("Full import notes and material warnings stay available.")
        panel.keep_physics.show()
        panel.flip_texture_v.show()
        self.assertEqual(panel.workspace_splitter.count(), 3)
        self.assertIs(panel.workspace_splitter.widget(0), panel.model_icon_column)
        self.assertIs(panel.workspace_splitter.widget(1), panel.preview_column)
        self.assertIs(panel.workspace_splitter.widget(2), panel.placement_column)
        self.assertIs(panel.preview.parentWidget(), panel.preview_group)
        self.assertIs(panel.icon_thumbnail.parentWidget(), panel.icon_group)
        self.assertTrue(panel.quick_turn_section.contents.isHidden())
        self.assertLess(panel.preview_layout.indexOf(panel.view_toolbar), panel.preview_layout.indexOf(panel.preview))
        self.assertFalse(panel.model_status.isVisibleTo(panel))
        panel.import_details.toggle.click()
        self.assertTrue(panel.model_status.isVisibleTo(panel))
        panel.import_details.toggle.click()
        panel.blender_details.toggle.click()
        self.assertTrue(panel.blender_button.isVisibleTo(panel))
        panel.blender_details.toggle.click()

        resident = panel.preview
        for width, height in ((1280, 720), (1440, 900), (1140, 720), (1920, 1080)):
            tab.resize(width, height)
            self.app.processEvents()
            self.assertEqual(tab.size().width(), width, "the page must not force the window wider")
            self.assertEqual(tab.size().height(), height, "the page must not force the window taller")
            self.assertIs(panel.preview, resident)
            self.assertIs(panel.preview.parentWidget(), panel.preview_group)
            self.assertGreaterEqual(panel.preview.height(), 300)
            if width >= 1280:
                self.assertTrue(panel.placement_column.isVisibleTo(panel))
                self.assertEqual(panel.inspector_tabs.indexOf(panel.placement_group), -1)
                self.assertGreater(panel.preview_column.width(), panel.model_icon_column.width())
                self.assertGreater(panel.preview_column.width(), panel.placement_column.width())
                self.assertEqual(panel.placement_column.horizontalScrollBar().maximum(), 0)
                self.assertLessEqual(panel.placement_group.geometry().bottom(), panel.placement_column.height())
            for index, page in enumerate((panel.appearance_page, panel.dyes, panel.icon_group)):
                panel.inspector_tabs.setCurrentIndex(index)
                self.app.processEvents()
                self.assertTrue(page.isVisibleTo(panel))
                self.assertEqual(panel.model_icon_scroll.horizontalScrollBar().maximum(), 0)
                if width >= 1280:
                    self.assertEqual(panel.model_icon_scroll.verticalScrollBar().maximum(), 0,
                                     f"inspector tab {index} should fit at {width}x{height}")
                for button in page.findChildren(QAbstractButton):
                    if button.isVisibleTo(panel):
                        self.assertLessEqual(button.height(), 36, button.text())
            panel.inspector_tabs.setCurrentIndex(0)
            self.assertTrue(panel.glow_parts.isHidden())
            self.assertLessEqual(panel.import_button.height(), 36)
            self.assertLessEqual(panel.apply_button.height(), 36)
            if width >= 1280:
                panel.quick_turn_section.toggle.setChecked(True)
                self.app.processEvents()
                for button in (panel.apply_button, *panel.quick_turn_buttons.values()):
                    bounds = button.rect().translated(button.mapTo(panel, button.rect().topLeft()))
                    self.assertTrue(panel.rect().contains(bounds), button.text())
                panel.quick_turn_section.toggle.setChecked(False)

        frames = []
        panel.operation_spinner.frame_advanced.connect(frames.append)
        tab.controller._lane = "model_apply"
        panel._busy_changed(True)
        self.app.processEvents()
        self.assertTrue(panel.operation_banner.isVisibleTo(panel))
        self.assertFalse(panel.placement_group.isEnabled())
        self.assertTrue(all(not button.isEnabled() for button in panel.quick_turn_buttons.values()))
        panel.operation_spinner._advance()
        self.assertTrue(frames)
        with patch.object(tab.controller, "cancel_operation", return_value=True) as cancel:
            panel.cancel_operation_button.click()
        cancel.assert_called_once_with("model_apply")
        panel._busy_changed(False)
        panel._preview_status("Fast textures are visible; loading full textures…")
        self.assertTrue(panel.operation_banner.isVisibleTo(panel))
        self.assertEqual(panel.preview_status.text(), "")
        panel._preview_status("Full textures loaded.")
        self.assertFalse(panel.operation_banner.isVisibleTo(panel))
        self.assertEqual(panel.preview_status.text(), "Full textures loaded.")

        # Other workflow pages set the complete tab's 1140 px minimum. Exercise the
        # Model page alone below that width, retaining its controls and viewport.
        panel.setParent(None)
        self.addCleanup(panel.deleteLater)
        self.addCleanup(panel.close)
        panel.setStyleSheet(tab.styleSheet())
        panel._set_placement_visible(True)
        panel.show()
        for width, height, point_size in ((960, 640, 10), (780, 900, 10), (1140, 720, 14), (1600, 900, 10)):
            panel.setFont(QFont("Segoe UI", point_size))
            panel.resize(width, height)
            self.app.processEvents()
            self.assertEqual(panel.size().toTuple(), (width, height))
            self.assertIs(panel.preview, resident)
            self.assertIs(panel.preview.parentWidget(), panel.preview_group)
            if width < 1280:
                self.assertFalse(panel.placement_column.isVisibleTo(panel))
                panel.inspector_tabs.setCurrentWidget(panel.placement_group)
                panel.quick_turn_section.toggle.setChecked(True)
                self.app.processEvents()
                self.assertTrue(panel.apply_button.isVisibleTo(panel))
                self.assertEqual(panel.model_icon_scroll.horizontalScrollBar().maximum(), 0)
                panel.model_icon_scroll.ensureWidgetVisible(panel.apply_button)
                self.app.processEvents()
                panel.model_icon_scroll.verticalScrollBar().setValue(panel.model_icon_scroll.verticalScrollBar().maximum())
                bounds = panel.apply_button.rect().translated(panel.apply_button.mapTo(panel.model_icon_scroll.viewport(), panel.apply_button.rect().topLeft()))
                self.assertTrue(panel.model_icon_scroll.viewport().rect().contains(bounds),
                                f"{width}x{height} {point_size}pt: button={bounds}, viewport={panel.model_icon_scroll.viewport().rect()}, scroll={panel.model_icon_scroll.verticalScrollBar().value()}/{panel.model_icon_scroll.verticalScrollBar().maximum()}")
            else:
                self.assertTrue(panel.placement_column.isVisibleTo(panel))
                self.assertEqual(panel.inspector_tabs.indexOf(panel.placement_group), -1)
            panel.quick_turn_section.toggle.setChecked(False)

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
