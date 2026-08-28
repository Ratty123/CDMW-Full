"""Gates for Create New Item: headless construction, the draft, and a plan through the panels."""

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
from tests.new_item_studio_tab_authoring_tests import _TabAuthoringMixin  # noqa: E402
from tests.new_item_studio_tab_lifecycle_tests import InstallReportTests, _TabLifecycleMixin  # noqa: E402
from tests.new_item_studio_tab_output_tests import _TabOutputMixin  # noqa: E402


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
        added_price_grid = stat_grid_for(
            row,
            {DDD: "DDD"},
            {COPPER: "Copper", 15: "Token", 99: "Other Money"},
            extra_price_keys=(99,),
        )
        self.assertEqual(added_price_grid.price_items[-1], (99, "Other Money", None))
        added_price_spec = spec_from_draft(
            NewItemDraft(template_key=TEMPLATE, internal_name="Clone", price_values={99: 1}),
            added_price_grid,
        )
        self.assertEqual([(p.item_key, p.price) for p in added_price_spec.price_edits], [(99, 1)])
        again = with_template(draft, OTHER)
        self.assertEqual((again.template_key, again.grid_values, again.internal_name), (OTHER, {}, "Clone"))
        with self.assertRaisesRegex(ValueError, "template"):
            spec_from_draft(NewItemDraft(), None)


class TabTests(_TabAuthoringMixin, _TabOutputMixin, _TabLifecycleMixin, unittest.TestCase):
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

    def test_success_records_the_current_game_build_as_new_item_compatible(self) -> None:
        recorded: list[tuple[object, ...]] = []
        window = SimpleNamespace(
            _record_game_feature_compatibility=lambda *args: recorded.append(args),
        )
        tab = self._tab(window=window, get_package_root=lambda: str(self.root))

        tab.start_snapshot()

        self.assertEqual(recorded, [(self.root, "new_item_archive_snapshot")])
        tab.close()
        tab.deleteLater()

    def test_only_layout_failures_receive_a_proven_game_update_note(self) -> None:
        requested: list[tuple[object, ...]] = []

        def evidence(*args: object) -> bool:
            requested.append(args)
            return True

        window = SimpleNamespace(_game_update_feature_error_evidence=evidence)
        tab = self._tab(window=window, get_package_root=lambda: str(self.root))

        tab._snapshot_failed("unsupported part-prefab table layout (partprefabtable.pappt)")
        self.assertIn("Game update detected via CrimsonDesert.exe hash.", tab._status.text())
        self.assertEqual(
            requested,
            [(self.root, "new_item_archive_snapshot")],
        )

        requested.clear()
        tab._snapshot_failed("permission denied while reading the archive")
        self.assertNotIn("Game update detected via CrimsonDesert.exe hash.", tab._status.text())
        self.assertEqual(requested, [])
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
        archive_cache_root = self.root / "archive-cache"
        window = SimpleNamespace(
            archive_cache_root=archive_cache_root,
            settings_tab=settings_tab,
            _current_model_preview_render_settings=lambda: initial,
            _current_archive_performance_settings=lambda: initial_performance,
        )
        tab = self._tab(window=window)
        tab._mount_panels()

        self.assertAlmostEqual(tab.model_panel.preview._render_settings.d3d11_tone_gamma, 1.17)
        self.assertAlmostEqual(tab.model_panel.preview._render_settings.d3d11_ao_strength, 0.7)
        self.assertEqual(tab.model_panel.preview._cache_mode, "aggressive")
        self.assertEqual(
            tab.model_panel.preview._native_preview_core_cache_root,
            archive_cache_root / "preview" / "native",
        )

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

    def test_template_selection_and_preview_are_wide_side_by_side_columns(self) -> None:
        from PySide6.QtWidgets import QHeaderView

        tab = self._tab()
        tab.resize(1600, 900)
        tab.start_snapshot()
        tab.show()
        self.app.processEvents()

        panel = tab.template_panel
        selection = panel.selection_column.geometry()
        preview = panel.preview_group.geometry()
        self.assertTrue(panel.selection_column.isAncestorOf(panel.matches))
        self.assertFalse(hasattr(panel, "summary"))
        self.assertTrue(panel.preview_group.isAncestorOf(panel.preview_holder))
        self.assertLess(
            panel.preview_group.layout().indexOf(panel.preview_holder),
            panel.preview_group.layout().indexOf(panel.preview_note),
        )
        self.assertEqual(panel.matches.columnCount(), 4)
        self.assertEqual(
            [panel.matches.headerItem().text(column) for column in range(panel.matches.columnCount())],
            ["Internal name:", "Item Name", "Key", "Type"],
        )
        for column in range(panel.matches.columnCount()):
            self.assertEqual(panel.matches.header().sectionResizeMode(column), QHeaderView.ResizeMode.Interactive)
        self.assertTrue(panel.matches.property("cdmw_disable_auto_column_fill"))

        def trailing_space() -> int:
            return panel.matches.viewport().width() - sum(
                panel.matches.columnWidth(column) for column in range(panel.matches.columnCount())
            )

        self.assertLessEqual(abs(trailing_space()), 2, "startup fits the complete result viewport")
        original_width = panel.matches.columnWidth(0)
        resized_width = original_width - 37
        panel.matches.header().resizeSection(0, resized_width)
        self.assertEqual(panel.matches.columnWidth(0), resized_width, "the reader can resize any result column")
        self.assertLessEqual(abs(trailing_space()), 2, "resizing transfers unused width instead of leaving a blank strip")
        panel._refresh_matches()
        self.assertEqual(panel.matches.columnWidth(0), resized_width, "refresh keeps the reader's column width")
        tab.resize(1900, 900)
        self.app.processEvents()
        self.app.processEvents()
        self.assertLessEqual(abs(trailing_space()), 2, "later panel growth also fits the result viewport")
        self.assertLess(selection.right(), preview.left(), "selection stays left of the preview")
        self.assertLessEqual(abs(selection.top() - preview.top()), 1)
        self.assertLessEqual(abs(selection.bottom() - preview.bottom()), 1)
        self.assertGreater(preview.width(), selection.width(), "the preview receives the wider column")

        tab.shutdown()
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
        from PySide6.QtWidgets import QLabel

        tab = self._tab()
        tab.prefill_template(TEMPLATE)
        self.assertFalse(
            any(
                label.text().startswith("Every new item is a copy")
                for label in tab.template_panel.findChildren(QLabel)
            )
        )
        self.assertFalse(
            any(
                details.toggle.text() == "Import tips"
                for details in tab.model_panel.findChildren(DetailsToggle)
            )
        )
        visible_copy = "\n".join(
            (
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
        self.assertIn("sheathed or holstered when the template has one", visible_copy)
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
        host.addTab(tab, "Create New Item")
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
        host.addTab(tab, "Create New Item")
        host.resize(1280, 720)
        host.show()
        tab.prefill_template(TEMPLATE)
        tab.show_step(4)
        perks = tab.perks_panel
        perks.own_perks.setChecked(True)
        self.app.processEvents()

        compact_available = perks.perk_results.height()
        compact_selected = perks.chosen.height()
        self.assertGreaterEqual(compact_available, 299, "Qt may assign the final odd layout pixel elsewhere")
        self.assertGreaterEqual(compact_selected, 299, "Qt may assign the final odd layout pixel elsewhere")
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
        from cdmw.ui.new_item.item_preview import ProgressivePreviewSource

        tab = self._tab()
        self.assertIsNone(tab.controller.item_preview_source(), "no template, nothing to show")
        tab.prefill_template(TEMPLATE)
        token, build = tab.controller.item_preview_source()
        self.assertIsInstance(build, ProgressivePreviewSource)
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
        with patch("cdmw.services.mesh_workflow_service.parse_pac", return_value=blade):
            geometry = build.geometry(threading.Event())
        self.assertIs(geometry, blade, "the first stage is the template's bare geometry")
        # an import: its own preview model, already decoded by the Builder
        imported = SimpleNamespace(rebuilt_data=b"x", preview_model=SimpleNamespace(meshes=[object()]))
        tab.controller.set_imported_model(None, imported)
        token, build = tab.controller.item_preview_source()
        self.assertEqual(token, ("imported", id(imported)))
        self.assertIs(build(threading.Event()), imported.preview_model)
        tab.close()
        tab.deleteLater()

    def test_model_preview_character_reuses_the_template_route_without_becoming_editable(self) -> None:
        """The optional body is assembled in the preview worker, kept in the template's
        item-space frame, and carried separately from the editable model."""

        from cdmw.modding.mesh_parser import ParsedMesh, SubMesh
        from cdmw.ui.new_item.item_preview import PlacementScene, ProgressivePreviewSource

        tab = self._tab()
        tab.prefill_template(TEMPLATE)
        item = ParsedMesh(
            path="item.pac",
            format="pac",
            submeshes=[SubMesh(
                name="item",
                vertices=[(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0)],
                faces=[(0, 1, 2)],
            )],
        )
        body = ParsedMesh(
            path="kliff.pac",
            format="pac",
            submeshes=[SubMesh(
                name="effect_character_0",
                material="effect_character_body",
                vertices=[(0.0, 0.0, 0.0), (0.0, 1.0, 0.0), (1.0, 0.0, 0.0)],
                faces=[(0, 1, 2)],
            )],
        )
        quarter_turn = (1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, -1.0, 0.0)
        held_calls = []

        def held(*, stop_event=None):
            held_calls.append(stop_event)
            return SimpleNamespace(mesh=body, item_rotation=quarter_turn)

        with patch.object(
            tab.controller,
            "_template_geometry_build",
            return_value=(("geometry",), lambda _stop: item),
        ), patch.object(
            tab.controller,
            "_template_preview_build",
            return_value=(("template",), lambda _stop: item),
        ), patch.object(
            tab.controller,
            "character_holding_the_item",
            side_effect=held,
        ):
            token, source = tab.controller.item_preview_source(include_character=True)
            self.assertEqual(token[0], "template-character")
            self.assertIsInstance(source, ProgressivePreviewSource)
            scene = source.geometry(threading.Event())
            material_scene = source.materials(threading.Event())

        self.assertIsInstance(scene, PlacementScene)
        self.assertIs(scene.model, item)
        self.assertIsNone(scene.template, "the character alone is the non-editable reference")
        self.assertEqual(
            tuple(round(value, 6) for value in scene.character.submeshes[0].vertices[1]),
            (0.0, 0.0, -1.0),
            "the body moves into item space while the established placement axes stay authoritative",
        )
        self.assertIs(material_scene.character, scene.character)
        self.assertEqual(len(held_calls), 1, "geometry and material stages share one assembled character")
        self.assertIsInstance(held_calls[0], threading.Event)

        imported = SimpleNamespace(
            bake_generation=2,
            mesh_generation=3,
            baked_scene_mesh=lambda: item,
            baked_preview_mesh=lambda: item,
            baked_bounds=lambda: ((0.0, 0.0, 0.0), (1.0, 1.0, 0.0)),
            baked_origin=lambda: (0.0, 0.0, 0.0),
            acquire_usage=lambda: object(),
        )
        tab.controller.model_import = imported
        with patch.object(
            tab.controller,
            "_template_geometry_build",
            return_value=(("geometry",), lambda _stop: item),
        ), patch.object(
            tab.controller,
            "_template_preview_build",
            return_value=(("template",), lambda _stop: item),
        ), patch.object(
            tab.controller,
            "character_holding_the_item",
            return_value=SimpleNamespace(mesh=body, item_rotation=None),
        ):
            imported_token, imported_source = tab.controller.item_preview_source(
                include_character=True,
            )
            imported_scene = imported_source.geometry(threading.Event())

        self.assertEqual(imported_token[0], "placement")
        self.assertTrue(imported_token[-1])
        self.assertIs(imported_scene.template, item)
        self.assertIs(imported_scene.model, item)
        self.assertIs(imported_scene.character, body)
        tab.close()
        tab.deleteLater()

    def test_model_preview_character_control_is_template_gated_and_routes_the_toggle(self) -> None:
        tab = self._tab()
        tab.prefill_template(TEMPLATE)
        panel = tab.model_panel
        self.assertTrue(panel.show_character.isEnabled())
        tab.controller.set_template(None)
        self.assertFalse(panel.show_character.isEnabled())
        tab.prefill_template(TEMPLATE)
        self.assertTrue(panel.show_character.isEnabled())
        routed = []

        with patch.object(
            tab.controller,
            "item_preview_source",
            side_effect=lambda *, include_character=False: routed.append(include_character),
        ), patch.object(panel, "isVisible", return_value=True):
            panel.show_character.setChecked(True)

        self.assertTrue(panel.show_character.isChecked())
        self.assertEqual(panel.view_mode.currentData(), "overlay")
        self.assertEqual(routed, [True])
        tab.close()
        tab.deleteLater()

    def test_template_materials_use_preview_core_when_the_shared_native_cache_is_available(self) -> None:
        from types import SimpleNamespace

        from cdmw.models import ModelPreviewRenderSettings

        tab = self._tab()
        tab.prefill_template(TEMPLATE)
        token, source = tab.controller.item_preview_source()
        entry = tab.controller.template_entries()[0]
        output = self.root / "new-item-native-output"
        native_cache = self.root / "shared-native-cache"
        native_package = output / "native-package"
        settings = ModelPreviewRenderSettings(d3d11_tone_gamma=1.17)
        attempt = SimpleNamespace(succeeded=True, package_path=str(native_package))
        package = SimpleNamespace(package_dir=native_package)

        with patch(
            "cdmw.services.preview_rendering_service.run_native_preview_core_preview_job",
            return_value=attempt,
        ) as run_native, patch(
            "cdmw.services.mesh_dotnet_preview_package.build_or_lookup_dotnet_preview_package",
            return_value=package,
        ) as adapt_package, patch(
            "cdmw.core.archive_preview_result_builder.build_archive_preview_result",
        ) as python_decode:
            result = source.materials(
                threading.Event(),
                output_root=output,
                native_preview_core_cache_root=native_cache,
                render_settings=settings,
                cache_mode="balanced",
            )

        self.assertEqual(result, native_package)
        native_kwargs = run_native.call_args.kwargs
        self.assertEqual(run_native.call_args.args[0].path, token[2])
        self.assertEqual(native_kwargs["cache_root"], native_cache)
        self.assertTrue(native_kwargs["render_settings"].use_textures_by_default)
        self.assertAlmostEqual(native_kwargs["render_settings"].d3d11_tone_gamma, 1.17)
        self.assertIn(entry, native_kwargs["dependency_entries"])
        self.assertFalse(native_kwargs["dependency_entries_complete"])
        self.assertEqual(native_kwargs["package_root"], Path(entry.pamt_path).parent.parent)
        self.assertEqual(Path(native_kwargs["output_root"]).parent, output)
        adapt_package.assert_called_once()
        python_decode.assert_not_called()
        tab.close()
        tab.deleteLater()

    def test_template_materials_keep_the_python_fallback_when_preview_core_fails(self) -> None:
        from types import SimpleNamespace

        tab = self._tab()
        tab.prefill_template(TEMPLATE)
        _token, source = tab.controller.item_preview_source()
        decoded_model = SimpleNamespace(meshes=[object()])
        decoded = SimpleNamespace(preferred_view="model", preview_model=decoded_model)
        output = self.root / "new-item-native-fallback"

        def fail_native(_entry, **kwargs):
            native_output = Path(kwargs["output_root"])
            native_output.mkdir(parents=True)
            (native_output / "partial.bin").write_bytes(b"partial")
            return SimpleNamespace(succeeded=False, package_path="")

        with patch(
            "cdmw.services.preview_rendering_service.run_native_preview_core_preview_job",
            side_effect=fail_native,
        ), patch(
            "cdmw.core.archive_preview_result_builder.build_archive_preview_result",
            return_value=decoded,
        ) as python_decode:
            result = source.materials(
                threading.Event(),
                output_root=output,
                native_preview_core_cache_root=self.root / "shared-native-cache",
                cache_mode="balanced",
            )

        self.assertIs(result, decoded_model)
        python_decode.assert_called_once()
        self.assertEqual(tuple(output.glob("package_*_native")), ())
        tab.close()
        tab.deleteLater()

    def test_template_materials_cancel_preview_core_without_running_the_python_fallback(self) -> None:
        from cdmw.domain.cancellation import RunCancelled

        tab = self._tab()
        tab.prefill_template(TEMPLATE)
        _token, source = tab.controller.item_preview_source()
        output = self.root / "new-item-native-cancel"

        def cancel_native(_entry, **kwargs):
            native_output = Path(kwargs["output_root"])
            native_output.mkdir(parents=True)
            (native_output / "partial.bin").write_bytes(b"partial")
            raise RunCancelled("cancelled in test")

        with patch(
            "cdmw.services.preview_rendering_service.run_native_preview_core_preview_job",
            side_effect=cancel_native,
        ), patch(
            "cdmw.core.archive_preview_result_builder.build_archive_preview_result",
        ) as python_decode:
            with self.assertRaisesRegex(RunCancelled, "cancelled in test"):
                source.materials(
                    threading.Event(),
                    output_root=output,
                    native_preview_core_cache_root=self.root / "shared-native-cache",
                    cache_mode="balanced",
                )

        python_decode.assert_not_called()
        self.assertEqual(tuple(output.glob("package_*_native")), ())
        tab.close()
        tab.deleteLater()





if __name__ == "__main__":  # pragma: no cover
    unittest.main()
