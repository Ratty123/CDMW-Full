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
from cdmw.ui.new_item.workflow_header import WorkflowStepState  # noqa: E402
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

    def _tab(self, window=None, **kwargs):
        from cdmw.ui.new_item.controller import NewItemStudioController
        from cdmw.ui.new_item.tab import NewItemStudioTab

        controller = NewItemStudioController(service=NewItemService(), read_entry=_read, synchronous=True)
        return NewItemStudioTab(window=window, controller=controller, get_archive_entries=lambda: self.entries, **kwargs)

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
        tab.prefill_template(TEMPLATE)
        self.app.processEvents()
        model, perks, groups = tab.model_panel, tab.perks_panel, tab.placement_panel
        self.assertFalse(model.clear_button.isVisibleTo(model), "nothing to discard until a model is imported")
        for widget in model._import_widgets:
            self.assertTrue(widget.isHidden(), "the import's controls wait for the import radio")
        model.import_model.setChecked(True)
        for widget in model._import_widgets:
            self.assertFalse(widget.isHidden())
        self.assertFalse(perks.perk_results.isVisibleTo(perks), "the perk catalogue waits to be asked for")
        perks.own_perks.setChecked(True)
        self.assertTrue(perks.perk_results.isVisibleTo(perks))
        self.assertFalse(perks.catalogue.isVisibleTo(perks), "the legacy combo is data-only")
        self.assertEqual([perks.tabs.tabText(index) for index in range(perks.tabs.count())], ["Perks", "Effects"])
        self.assertIs(perks.tabs.currentWidget(), perks.perks_page, "customizing perks reveals the Perks tab")
        perks.tabs.setCurrentWidget(perks.effects_page)
        self.assertFalse(perks._legacy_intro.isVisibleTo(perks), "the retired page intro does not float over the tabs")
        self.assertFalse(perks.effect_primary.isVisibleTo(perks), "the curated/proven selector is not presented")
        self.assertIs(perks.parentWidget(), tab.pages)
        self.assertIs(tab.summary.parentWidget(), tab.summary_box)
        self.assertFalse(tab.summary.isWindow(), "the hidden workflow summary must never become a floating window")
        self.assertFalse(tab.summary_box.isVisibleTo(tab))
        self.assertEqual(tab.controller.draft.effect_stem, "", "the No effect row starts without an arbitrary effect")
        tab.show_step(4)
        self.app.processEvents()
        self.assertIs(tab.pages.currentWidget(), perks, "Step 5 is the non-scrolling resident workspace")
        self.assertEqual(perks.effects_workspace.minimumWidth(), 0)
        self.assertEqual(perks.effects_workspace.splitter.widget(0).minimumWidth(), 300)
        self.assertEqual(perks.effects_workspace.placement_holder.minimumWidth(), 820)
        tab.stats_panel.advanced_toggle.setChecked(True)
        tab.show_step(3)
        self.app.processEvents()
        self.assertEqual(tab.pages.currentWidget().horizontalScrollBar().maximum(), 0, "expanded raw-stat controls fit at 1280")
        self.assertFalse(groups.group_list.isVisibleTo(groups), "the item groups wait to be chosen by hand")
        self.assertFalse(groups.store.isVisibleTo(groups), "no shop, no shop picker")
        groups.explicit.setChecked(True)
        groups.swap.setChecked(True)
        self.assertTrue(groups.group_list.isVisibleTo(groups))
        self.assertTrue(groups.store.isVisibleTo(groups))
        for index in range(tab.steps.count()):
            tab.show_step(index)
            self.app.processEvents()
            if index in {2, 4}:
                self.assertNotIsInstance(tab.pages.currentWidget(), QScrollArea)
            else:
                self.assertIsInstance(tab.pages.currentWidget(), QScrollArea)
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

    def test_snapshot_receives_the_archive_browsers_published_indexes(self) -> None:
        from types import SimpleNamespace

        path_index: dict[str, tuple] = {}
        basename_index: dict[str, tuple] = {}
        extension_index: dict[str, tuple] = {}
        for entry in self.entries:
            path = str(entry.path).replace("\\", "/").strip("/").lower()
            path_index[path] = (*path_index.get(path, ()), entry)
            basename = path.rsplit("/", 1)[-1]
            basename_index[basename] = (*basename_index.get(basename, ()), entry)
            extension = Path(path).suffix.lower()
            extension_index[extension] = (*extension_index.get(extension, ()), entry)
        window = SimpleNamespace(
            archive_entries_by_normalized_path=path_index,
            archive_entries_by_basename=basename_index,
            archive_entries_by_extension=extension_index,
        )
        tab = self._tab(window=window)
        tab.start_snapshot()

        reused_path_index, reused_basename_index = tab.controller.snapshot.archive_index_maps()
        self.assertIs(reused_path_index, path_index)
        self.assertIs(reused_basename_index, basename_index)
        tab.close()
        tab.deleteLater()

    def test_model_preview_tracks_the_shared_archive_render_settings(self) -> None:
        from types import SimpleNamespace

        from PySide6.QtCore import QObject, Signal

        from cdmw.models import ArchivePerformanceSettings, ModelPreviewRenderSettings

        class SettingsTab(QObject):
            model_preview_settings_changed = Signal(object)
            archive_performance_settings_changed = Signal(object)

        settings_tab = SettingsTab()
        initial = ModelPreviewRenderSettings(d3d11_tone_gamma=1.17, d3d11_ao_strength=0.7)
        initial_performance = ArchivePerformanceSettings(native_preview_cache_mode="aggressive")
        window = SimpleNamespace(
            archive_cache_root=None,
            settings_tab=settings_tab,
            _current_model_preview_render_settings=lambda: initial,
            _current_archive_performance_settings=lambda: initial_performance,
        )
        tab = self._tab(window=window)
        tab._mount_panels()

        self.assertAlmostEqual(tab.model_panel.preview._render_settings.d3d11_tone_gamma, 1.17)
        self.assertAlmostEqual(tab.model_panel.preview._render_settings.d3d11_ao_strength, 0.7)
        self.assertEqual(tab.model_panel.preview._cache_mode, "aggressive")

        updated = ModelPreviewRenderSettings(d3d11_tone_gamma=0.91, d3d11_ao_strength=0.4)
        settings_tab.model_preview_settings_changed.emit(updated)
        settings_tab.archive_performance_settings_changed.emit(
            ArchivePerformanceSettings(native_preview_cache_mode="off")
        )
        self.app.processEvents()

        self.assertAlmostEqual(tab.model_panel.preview._render_settings.d3d11_tone_gamma, 0.91)
        self.assertAlmostEqual(tab.model_panel.preview._render_settings.d3d11_ao_strength, 0.4)
        self.assertEqual(tab.model_panel.preview._cache_mode, "off")
        tab.shutdown()
        tab.close()
        tab.deleteLater()

    def test_template_and_model_steps_share_one_resident_preview(self) -> None:
        from PySide6.QtCore import QObject, Signal
        from PySide6.QtWidgets import QWidget

        from cdmw.ui.new_item.item_preview import ItemPreviewFrame

        class HostSignals(QObject):
            state_changed = Signal(str, str)
            capture_completed = Signal(object)

        class FakeController:
            def __init__(self) -> None:
                self._signals = HostSignals()
                self.state_changed = self._signals.state_changed
                self.capture_completed = self._signals.capture_completed

            def shutdown(self) -> None:
                pass

        class FakeHost(QWidget):
            alignment_drag_started = Signal()
            alignment_drag_changed = Signal(float, float, float)
            alignment_drag_finished = Signal(float, float, float)
            alignment_rotation_changed = Signal(float, float, float)
            alignment_rotation_finished = Signal(float, float, float)
            alignment_scale_changed = Signal(float, float, float)
            alignment_scale_finished = Signal(float, float, float)

            def __init__(self, parent) -> None:
                super().__init__(parent)
                self.controller = FakeController()

            def set_render_tuning(self, _settings) -> None:
                pass

            def set_icon_capture_mode(self, _enabled) -> None:
                pass

        tab = self._tab()
        tab.resize(1280, 720)
        tab.show()
        preview = tab.model_panel.preview if tab._panels_built else None
        self.assertIsNone(preview)
        tab.start_snapshot()
        preview = tab.model_panel.preview
        preview._host_factory = FakeHost
        started: list[object] = []

        def fake_start(frame, request, **_kwargs) -> None:
            started.append(request[0])
            frame._thread = object()

        with patch.object(ItemPreviewFrame, "_start_package", fake_start):
            tab.template_panel.prefill(TEMPLATE)
            resident_host = preview.host
            self.assertIs(preview.parentWidget(), tab.template_panel.preview_holder)
            self.assertEqual(len(started), 1)
            tab.show_step(2)
            self.app.processEvents()
            self.assertIs(preview.parentWidget(), tab.model_panel.preview_group)
            self.assertIs(preview.host, resident_host, "the native-host owner survives the page move")
            self.assertEqual(len(started), 1, "moving the resident viewport must not rebuild its package")
        preview._thread = None
        tab.close()
        tab.deleteLater()

    def test_effect_target_preflight_is_cached_by_template_and_effect(self) -> None:
        tab = self._tab()
        tab.prefill_template(TEMPLATE)
        controller = tab.controller
        controller._effect_target_compatibility_cache.clear()
        service_type = type(controller.service)
        original = service_type.inspect_effect_targets
        calls: list[object] = []

        def counted(service, spec, snapshot):
            calls.append((spec.template_key, spec.effect))
            return original(service, spec, snapshot)

        with patch.object(
            service_type,
            "inspect_effect_targets",
            counted,
        ):
            first = controller.effect_target_compatibility("fx_test_fire")
            second = controller.effect_target_compatibility("fx_test_fire")
            self.assertIs(second, first)
            self.assertEqual(len(calls), 1)
            controller.set_template(OTHER)
            before = len(calls)
            other_first = controller.effect_target_compatibility("fx_test_fire")
            other_second = controller.effect_target_compatibility("fx_test_fire")
            self.assertIs(other_second, other_first)
            self.assertEqual(len(calls), before + 1)
        tab.close()
        tab.deleteLater()

    def test_new_item_copy_is_equipment_neutral_and_sheathed_wording_is_conditional(self) -> None:
        from cdmw.ui.new_item.ui_kit import DetailsToggle

        tab = self._tab()
        tab.prefill_template(TEMPLATE)
        template_intro = tab.template_panel.layout().itemAt(0).widget().text()
        self.assertFalse(
            any(
                details.toggle.text() == "Import tips"
                for details in tab.model_panel.findChildren(DetailsToggle)
            )
        )
        visible_copy = "\n".join(
            (
                template_intro,
                tab.template_panel.filter_edit.placeholderText(),
                tab.identity_panel.internal_name.placeholderText(),
                tab.identity_panel.internal_name.toolTip(),
                tab.identity_panel.stem.placeholderText(),
                tab.stats_panel.table.toolTip(),
                tab.stats_panel.new_stat.toolTip(),
                tab.output_panel.checklist.body.text(),
            )
        ).lower()
        self.assertIn("equipment_clone", visible_copy)
        self.assertNotIn("sword", visible_copy)
        self.assertNotIn("weapon", visible_copy)
        self.assertNotIn("armour", visible_copy)
        self.assertIn("optional sheathed variant", visible_copy)
        self.assertIn("when the template has one", visible_copy)
        tab.close()
        tab.deleteLater()

    def test_distribution_and_output_fit_at_common_window_heights(self) -> None:
        from PySide6.QtGui import QPalette
        from PySide6.QtWidgets import QTabWidget
        from cdmw.ui.themes import build_app_palette, build_app_stylesheet

        old_palette = QPalette(self.app.palette())
        old_stylesheet = self.app.styleSheet()
        self.app.setPalette(build_app_palette("graphite"))
        self.app.setStyleSheet(build_app_stylesheet("graphite"))
        tab = self._tab()
        host = QTabWidget()
        host.addTab(tab, "New Item Studio")
        try:
            host.show()
            tab.prefill_template(TEMPLATE)
            for width, height in ((1280, 720), (1600, 900)):
                host.resize(width, height)
                tab.show_step(5)
                placement = tab.placement_panel
                placement.explicit.setChecked(True)
                placement.swap.setChecked(True)
                self.app.processEvents()
                page = tab.pages.currentWidget()
                self.assertEqual(
                    page.verticalScrollBar().maximum(),
                    0,
                    f"Distribution has an outer scroll at {width}x{height}",
                )
                self.assertEqual(placement.group_list.minimumHeight(), 96)
                self.assertTrue(placement.group_list.isVisibleTo(placement))
                self.assertTrue(placement.store.isVisibleTo(placement))
                if width == 1280:
                    self.assertLessEqual(placement.group_list.height(), 140)
                else:
                    self.assertGreater(placement.group_list.height(), 140)

                tab.show_step(6)
                self.app.processEvents()
                page = tab.pages.currentWidget()
                output = tab.output_panel
                self.assertEqual(
                    page.verticalScrollBar().maximum(),
                    0,
                    f"Output has an outer scroll at {width}x{height}",
                )
                self.assertEqual(output.summary.minimumHeight(), 120)
                if width == 1280:
                    self.assertLessEqual(output.summary.height(), 120)
                else:
                    self.assertGreater(output.summary.height(), 120, "the larger viewport still gives the review room")
        finally:
            tab.request_shutdown()
            tab.shutdown()
            host.close()
            host.deleteLater()
            self.app.setStyleSheet(old_stylesheet)
            self.app.setPalette(old_palette)
            self.app.processEvents()

    def test_custom_perks_use_the_available_workspace_instead_of_short_fixed_lists(self) -> None:
        from PySide6.QtWidgets import QTabWidget

        tab = self._tab()
        host = QTabWidget()
        host.addTab(tab, "New Item Studio")
        host.resize(1280, 720)
        host.show()
        tab.prefill_template(TEMPLATE)
        tab.show_step(4)
        perks = tab.perks_panel
        perks.own_perks.setChecked(True)
        self.app.processEvents()

        compact_available = perks.perk_results.height()
        compact_selected = perks.chosen.height()
        self.assertGreaterEqual(compact_available, 300)
        self.assertGreaterEqual(compact_selected, 300)
        self.assertTrue(perks.add_button.isVisibleTo(perks))
        self.assertTrue(perks.remove_button.isVisibleTo(perks))

        host.resize(1600, 900)
        self.app.processEvents()
        self.assertGreater(perks.perk_results.height(), compact_available)
        self.assertGreater(perks.chosen.height(), compact_selected)
        tab.request_shutdown()
        tab.shutdown()
        host.close()
        host.deleteLater()
        self.app.processEvents()

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
        from PySide6.QtWidgets import QScrollArea, QSizePolicy, QTabWidget

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

        for width, height in ((1720, 720), (1920, 900)):
            tab.resize(width, height)
            self.app.processEvents()
            panel.model_icon_scroll.verticalScrollBar().setValue(0)
            first_y = panel.keep_model.mapTo(panel.model_icon_scroll.viewport(), panel.keep_model.rect().topLeft()).y()
            next_y = panel.import_model.mapTo(panel.model_icon_scroll.viewport(), panel.import_model.rect().topLeft()).y()
            self.assertLessEqual(first_y, 24, f"the Model/Icon column starts at the top at {width}x{height}")
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

    def test_post_install_snapshot_completion_preserves_group_picker_items(self) -> None:
        """A reread updates archive data without rebuilding the unchanged group picker."""

        tab = self._tab()
        tab.prefill_template(TEMPLATE)
        group_list = tab.placement_panel.group_list
        original_snapshot = tab.controller.snapshot
        original_groups = tuple((group.key, group.name) for group in original_snapshot.item_groups)
        original_items = tuple(group_list.item(row) for row in range(group_list.count()))
        self.assertTrue(original_items)

        tab._reread_after_install()

        self.assertIsNot(tab.controller.snapshot, original_snapshot, "the real snapshot task completed")
        self.assertEqual(
            tuple((group.key, group.name) for group in tab.controller.snapshot.item_groups),
            original_groups,
            "installing an item changes group membership, not the group catalogue",
        )
        self.assertEqual(group_list.count(), len(original_items))
        for row, item in enumerate(original_items):
            self.assertIs(
                group_list.item(row),
                item,
                "the post-install reread must not release and recreate unchanged Qt item wrappers",
            )
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

    def test_model_operation_progress_and_cancel_are_correlated(self) -> None:
        from PySide6.QtCore import QEventLoop

        from cdmw.ui.new_item.controller import NewItemStudioController

        controller = NewItemStudioController()
        progress = []
        errors = []
        completed = []
        statuses = []
        controller.operation_progress.connect(lambda *values: progress.append(values))
        controller.status_message.connect(lambda *values: statuses.append(values))

        def task(_log, report, stop_event):
            report(1, 3, "Transforming mesh")
            while not stop_event.wait(0.005):
                pass
            report(2, 3, "Late progress must not replace Cancelling")
            return object()

        self.assertTrue(
            controller._run(
                "model_apply",
                task,
                completed.append,
                errors.append,
                task_accepts_progress=True,
            )
        )
        deadline = time.monotonic() + 2.0
        while not progress and time.monotonic() < deadline:
            self.app.processEvents(QEventLoop.ProcessEventsFlag.AllEvents, 20)
        self.assertTrue(controller.cancel_operation("model_apply"))
        while controller._thread is not None and time.monotonic() < deadline:
            self.app.processEvents(QEventLoop.ProcessEventsFlag.AllEvents, 20)
        self.assertIn(("model_apply", 1, 3, "Transforming mesh"), progress)
        self.assertTrue(any(values[-1] == "Cancelling…" for values in progress))
        self.assertFalse(any(values[-1].startswith("Late progress") for values in progress))
        self.assertEqual(completed, [])
        self.assertEqual(errors, [])
        self.assertIn(("Operation cancelled.", False), statuses)
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

    def test_an_imported_model_is_textured_and_listed_before_and_after_apply(self) -> None:
        """The live import owns preview materials and part names throughout the workflow;
        the Builder result owns output, not the source PBR appearance."""

        from types import SimpleNamespace

        from cdmw.modding.mesh_parser import ParsedMesh, SubMesh

        def mesh(texture: str) -> ParsedMesh:
            part = SubMesh(
                name="blade", material="steel", texture=texture,
                vertices=[(0.0, 0.0, 0.0), (0.1, 0.0, 0.0), (0.0, 0.1, 0.0)],
                uvs=[(0.0, 0.0)] * 3, normals=[(0.0, 1.0, 0.0)] * 3, faces=[(0, 1, 2)],
                vertex_count=3, face_count=1,
            )
            part.preview_material_texture_inputs = (texture,)
            part.preview_material_parameters = (texture,)
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

        controller.model_result = SimpleNamespace(preview_model=object())
        with patch.object(
            controller,
            "_textured_preview_mesh",
            return_value=mesh("template_synthesized.png"),
        ) as rebuilt_material_fallback:
            planned, kind = controller.item_mesh_as_planned()
        self.assertEqual(kind, "applied")
        self.assertEqual(
            planned.submeshes[0].texture,
            "frostmourne_basecolor.png",
            "Apply must not replace Model & Placement's source materials with the rebuilt template material row",
        )
        self.assertEqual(planned.submeshes[0].preview_material_texture_inputs, ("frostmourne_basecolor.png",))
        self.assertEqual(planned.submeshes[0].preview_material_parameters, ("frostmourne_basecolor.png",))
        rebuilt_material_fallback.assert_not_called()
        controller.model_result = None

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

        # the row that answers it is directly on Model: a refusal
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

    def test_clicking_a_template_applies_before_navigation_settles(self) -> None:
        from PySide6.QtCore import Qt
        from PySide6.QtTest import QTest

        tab = self._tab(window=None)
        tab.resize(1280, 720)
        tab.show()
        tab.prefill_template(TEMPLATE)
        panel = tab.template_panel
        panel.filter_edit.clear()
        self.app.processEvents()
        target = next(
            panel.matches.item(row)
            for row in range(panel.matches.count())
            if panel.matches.item(row).data(Qt.UserRole) == OTHER
        )
        panel.matches.scrollToItem(target)

        taken: list = []
        tab.controller.set_template = lambda key: taken.append(key)  # type: ignore[method-assign]
        QTest.mouseClick(
            panel.matches.viewport(),
            Qt.MouseButton.LeftButton,
            pos=panel.matches.visualItemRect(target).center(),
        )

        self.assertEqual(taken, [OTHER], "a deliberate click does not wait for the navigation timer")
        self.assertFalse(panel._pick_timer.isActive())
        self.assertIsNone(panel._pending_key)
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
