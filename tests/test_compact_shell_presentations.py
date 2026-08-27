from __future__ import annotations

import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QSettings, Qt
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSplitter,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from cdmw.services.settings_service import create_settings
from cdmw.ui.shell.compact.presentations import (
    COMPACT_PRESENTATION_SPECS,
    apply_compact_presentation,
    compact_surface_contract,
)
from cdmw.ui.widgets import FlatSectionPanel


EXPECTED_TOOL_KEYS = (
    "archive_browser",
    "model_library",
    "item_icons",
    "new_item_studio",
    "mesh_editor",
    "placement_studio",
    "texture_workflow",
    "replace_assistant",
    "recolor_variants",
    "texture_editor",
    "mod_package_retrofit",
    "format_explorer",
    "translation_studio",
    "research",
    "text_search",
)


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


class CompactShellPresentationTests(unittest.TestCase):
    def setUp(self) -> None:
        _app()
        self._temporary = tempfile.TemporaryDirectory(prefix="cdmw-compact-presentation-test-")
        self.settings = create_settings(
            settings_file_path=Path(self._temporary.name) / "settings.ini"
        )

    def tearDown(self) -> None:
        _app().processEvents()
        self._temporary.cleanup()

    def _window(self, variant: str) -> SimpleNamespace:
        self.settings.setValue("ui/shell_variant", variant)
        return SimpleNamespace(settings=self.settings, shell_variant=variant)

    def test_specs_cover_all_fifteen_reference_files_once(self) -> None:
        self.assertEqual(EXPECTED_TOOL_KEYS, tuple(COMPACT_PRESENTATION_SPECS))
        filenames = [spec.reference_filename for spec in COMPACT_PRESENTATION_SPECS.values()]
        self.assertEqual(15, len(filenames))
        self.assertEqual(15, len(set(filenames)))
        self.assertEqual(
            [f"{index:02d}" for index in range(1, 16)],
            [filename[:2] for filename in filenames],
        )

    def test_classic_workspace_is_an_exact_noop(self) -> None:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(17, 18, 19, 20)
        layout.setSpacing(14)
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setHandleWidth(8)
        splitter.addWidget(QWidget())
        splitter.addWidget(QWidget())
        splitter.addWidget(QWidget())
        layout.addWidget(splitter)

        changed = apply_compact_presentation(
            self._window("legacy"), "text_search", widget
        )

        margins = layout.contentsMargins()
        self.assertFalse(changed)
        self.assertEqual((17, 18, 19, 20), (margins.left(), margins.top(), margins.right(), margins.bottom()))
        self.assertEqual(14, layout.spacing())
        self.assertEqual(8, splitter.handleWidth())
        self.assertFalse(bool(widget.property("compactPresentation")))

    def test_compact_adapter_is_idempotent_and_uses_one_pixel_dividers(self) -> None:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(14)
        splitter = QSplitter(Qt.Orientation.Horizontal)
        for _index in range(3):
            splitter.addWidget(QWidget())
        layout.addWidget(splitter)
        widget.resize(1120, 720)
        widget.show()

        window = self._window("compact_rail")
        self.assertTrue(apply_compact_presentation(window, "text_search", widget))
        first_filter = widget._cdmw_compact_presentation_filter
        self.assertTrue(apply_compact_presentation(window, "text_search", widget))
        _app().processEvents()

        self.assertIs(first_filter, widget._cdmw_compact_presentation_filter)
        margins = layout.contentsMargins()
        self.assertEqual((6, 6, 6, 6), (margins.left(), margins.top(), margins.right(), margins.bottom()))
        self.assertEqual(4, layout.spacing())
        self.assertEqual(1, splitter.handleWidth())
        self.assertTrue(bool(widget.property("compactPresentation")))
        self.assertEqual("text_search", widget.property("compactToolKey"))
        self.assertEqual(3, len(splitter.sizes()))
        self.assertGreater(splitter.sizes()[2], splitter.sizes()[0])
        widget.close()

    def test_compact_tool_root_paints_over_the_previous_stacked_page(self) -> None:
        widget = QWidget()
        widget.setLayout(QVBoxLayout())

        self.assertFalse(widget.autoFillBackground())
        self.assertTrue(
            apply_compact_presentation(
                self._window("compact_rail"),
                "text_search",
                widget,
            )
        )

        self.assertTrue(
            widget.autoFillBackground(),
            "a transparent Compact root can preserve pixels from the previously visible tool",
        )
        widget.close()

    def test_compact_flat_contract_overrides_tool_cards_and_preserves_real_separators(self) -> None:
        widget = QWidget()
        widget.setStyleSheet(
            "QGroupBox { border: 1px solid red; border-radius: 10px; }"
            "QFrame#EditorActionPane { border: 1px solid red; border-radius: 12px; }"
        )
        layout = QVBoxLayout(widget)
        semantic_group = QGroupBox("Semantic section")
        semantic_group.setLayout(QVBoxLayout())
        semantic_group.layout().addWidget(QLabel("Content"))
        action_pane = QFrame()
        action_pane.setObjectName("EditorActionPane")
        action_pane.setFrameShape(QFrame.Shape.StyledPanel)
        separator = QFrame()
        separator.setFrameShape(QFrame.Shape.HLine)
        nested_panel = FlatSectionPanel("Nested section")
        for child in (semantic_group, action_pane, separator, nested_panel):
            layout.addWidget(child)

        window = self._window("compact_rail")
        widget.resize(640, 480)
        widget.show()
        self.assertTrue(apply_compact_presentation(window, "text_search", widget))
        self.assertTrue(apply_compact_presentation(window, "text_search", widget))
        late_section = QGroupBox("Late-built tab content")
        late_section.setLayout(QVBoxLayout())
        layout.addWidget(late_section)
        widget.resize(641, 480)
        _app().processEvents()

        contract = compact_surface_contract(widget)
        self.assertGreaterEqual(contract["compact_surface_count"], 5)
        self.assertEqual(0, contract["unflattened_compact_surface_count"])
        self.assertEqual([], contract["unflattened_compact_surfaces"])
        self.assertEqual("flat_square_v1", contract["flat_style_contract"])
        self.assertTrue(bool(semantic_group.property("compactFlatSurface")))
        self.assertTrue(bool(late_section.property("compactFlatSurface")))
        self.assertEqual("Semantic section", semantic_group.title())
        self.assertEqual(QFrame.Shape.NoFrame, action_pane.frameShape())
        self.assertEqual(QFrame.Shape.HLine, separator.frameShape())
        self.assertFalse(bool(separator.property("compactFlatSurface")))
        self.assertEqual(1, widget.styleSheet().count("CDMW_COMPACT_FLAT_STYLE_BEGIN"))
        self.assertGreater(
            widget.styleSheet().rfind("border-radius: 0px"),
            widget.styleSheet().find("border-radius: 12px"),
        )
        widget.close()

    def test_archive_compact_strip_replaces_empty_controls_column_with_menus(self) -> None:
        widget = QWidget()
        root = QVBoxLayout(widget)
        splitter = QSplitter(Qt.Orientation.Horizontal)
        controls_scroll = QScrollArea()
        controls = FlatSectionPanel("Controls")
        controls_scroll.setWidget(controls)
        files = FlatSectionPanel("Files")
        preview = FlatSectionPanel("Preview")
        splitter.addWidget(controls_scroll)
        splitter.addWidget(files)
        splitter.addWidget(preview)
        root.addWidget(splitter)

        search_group = QGroupBox()
        search_layout = QHBoxLayout(search_group)
        scan = QPushButton("Scan")
        refresh = QPushButton("Refresh")
        finder = QPushButton("Item Finder")
        search_edit = QLineEdit()
        search_button = QPushButton("Search")
        extension = QComboBox()
        extension.addItem("All files")
        extension_picker = QToolButton()
        extension_picker.setText("Select")
        for control in (scan, refresh, finder, search_edit, search_button, extension, extension_picker):
            search_layout.addWidget(control)
        controls.body_layout.addWidget(search_group)

        actions_group = QGroupBox("Actions")
        actions_layout = QVBoxLayout(actions_group)
        extract_selected = QPushButton("Extract Selected")
        extract_filtered = QPushButton("Extract Filtered")
        resolve = QPushButton("Resolve In Research")
        for button in (extract_selected, extract_filtered, resolve):
            actions_layout.addWidget(button)
        controls.body_layout.addWidget(actions_group)
        filters_group = QGroupBox("Filters")
        filters_group.setLayout(QVBoxLayout())
        filters_group.layout().addWidget(QLineEdit())
        controls.body_layout.addWidget(filters_group)

        window = self._window("compact_rail")
        window.archive_controls_group = controls
        window.archive_controls_scroll = controls_scroll
        window.archive_scan_button = scan
        window.archive_refresh_scan_button = refresh
        window.archive_asset_catalog_button = finder
        window.archive_filter_edit = search_edit
        window.archive_path_search_button = search_button
        window.archive_extension_filter_combo = extension
        window.archive_extension_picker_button = extension_picker
        window.archive_extract_selected_button = extract_selected
        window.archive_extract_filtered_button = extract_filtered
        window.archive_resolve_in_research_button = resolve
        clicked: list[str] = []
        extension_picker.clicked.connect(lambda: clicked.append("select"))
        extract_selected.clicked.connect(lambda: clicked.append("selected"))

        self.assertTrue(apply_compact_presentation(window, "archive_browser", widget))
        _app().processEvents()

        self.assertTrue(controls_scroll.isHidden())
        self.assertEqual(0, controls_scroll.maximumWidth())
        self.assertTrue(files.header_widget.isHidden())
        self.assertTrue(preview.header_widget.isHidden())
        self.assertEqual("CompactArchiveSelectButton", extension_picker.objectName())
        extension_picker.click()
        self.assertEqual(["select"], clicked)
        actions_button = widget._cdmw_compact_archive_actions_button
        self.assertEqual(3, len(actions_button.menu().actions()))
        actions_button.menu().actions()[0].trigger()
        self.assertEqual(["select", "selected"], clicked)
        filters_button = widget._cdmw_compact_archive_more_filters_button
        self.assertIsNotNone(filters_button.menu())
        self.assertEqual("", filters_group.title())
        for button in (extension_picker, actions_button, filters_button):
            self.assertFalse(button.autoRaise())
            self.assertEqual(Qt.FocusPolicy.StrongFocus, button.focusPolicy())
        widget.close()

    def test_real_item_icons_keeps_both_empty_previews_visible_without_scrollbars(self) -> None:
        from cdmw.ui.item_icons.tab import ItemIconLibraryTab

        root = Path(self._temporary.name)
        tab = ItemIconLibraryTab(
            settings=QSettings(str(root / "item-icons.ini"), QSettings.IniFormat),
            base_dir=root,
            get_archive_entries=lambda: (),
            resolve_target_template_path=lambda _entry: root / "target.png",
        )
        try:
            self.assertTrue(
                apply_compact_presentation(
                    self._window("compact_rail"), "item_icons", tab
                )
            )
            for width, height in ((1444, 895), (1132, 794), (892, 674)):
                tab.resize(width, height)
                tab.show()
                _app().processEvents()

                self.assertEqual(0, tab.source_preview_scroll.verticalScrollBar().maximum())
                self.assertEqual(0, tab.final_preview_scroll.verticalScrollBar().maximum())
                self.assertGreaterEqual(tab.source_preview_scroll.viewport().height(), 72)
                self.assertGreaterEqual(tab.final_preview_scroll.viewport().height(), 72)
        finally:
            tab.shutdown()
            tab.close()
            tab.deleteLater()

    def test_compact_label_changes_do_not_change_internal_tool_key(self) -> None:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        label = QLabel("Use in New Item Studio")
        label.setToolTip("Open New Item Studio with this model.")
        layout.addWidget(label)

        self.assertTrue(
            apply_compact_presentation(
                self._window("compact_rail"), "model_library", widget
            )
        )

        self.assertEqual("Use in Create New Item", label.text())
        self.assertEqual("Open Create New Item with this model.", label.toolTip())
        self.assertEqual("model_library", widget.property("compactToolKey"))

        placement = QWidget()
        placement_layout = QVBoxLayout(placement)
        turn_button = QPushButton("Rotate")
        placement_layout.addWidget(turn_button)
        self.assertTrue(
            apply_compact_presentation(
                self._window("compact_rail"), "placement_studio", placement
            )
        )
        self.assertEqual("Rotate", turn_button.text())
        self.assertEqual("Rotate", turn_button.toolTip())
        self.assertEqual("Rotate", turn_button.accessibleName())
        self.assertEqual("placement_studio", placement.property("compactToolKey"))

    def test_new_item_uses_compact_theme_accent_without_changing_classic(self) -> None:
        from cdmw.ui.new_item.workflow_header import WorkflowHeader

        widget = QWidget()
        layout = QVBoxLayout(widget)
        steps = WorkflowHeader()
        widget.steps = steps
        layout.addWidget(steps)
        palette = widget.palette()
        accent = QColor("#c56f3d")
        palette.setColor(QPalette.ColorRole.Highlight, accent)
        widget.setPalette(palette)
        steps.setPalette(palette)
        widget.setStyleSheet("QWidget { border-bottom: 2px solid #078de5; }")

        classic_widget = QWidget()
        classic_widget.setStyleSheet("QWidget { color: #078de5; }")
        self.assertFalse(
            apply_compact_presentation(
                self._window("legacy"), "new_item_studio", classic_widget
            )
        )
        self.assertIn("#078de5", classic_widget.styleSheet())

        self.assertTrue(
            apply_compact_presentation(
                self._window("compact_rail"), "new_item_studio", widget
            )
        )

        self.assertEqual(accent.name(), steps._active_color.name())
        self.assertIn(accent.name(), widget.styleSheet())
        self.assertNotIn("#078de5", widget.styleSheet().lower())
        classic_widget.deleteLater()
        widget.deleteLater()

    def test_texture_workflow_reuses_paths_and_moves_existing_actions_to_top(self) -> None:
        widget = QWidget()
        root = QVBoxLayout(widget)
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(QWidget())
        splitter.addWidget(QWidget())
        root.addWidget(splitter)
        actions = QHBoxLayout()
        actions.addWidget(QLabel("Actions"))
        root.addLayout(actions)
        left_panel = QWidget()
        left_layout = QVBoxLayout(left_panel)
        paths_section = QWidget()
        left_layout.addStretch(1)
        window = self._window("compact_rail")
        window.left_panel = left_panel
        window.paths_section = paths_section

        self.assertTrue(apply_compact_presentation(window, "texture_workflow", widget))

        self.assertIs(actions, root.itemAt(0).layout())
        self.assertEqual(0, left_layout.indexOf(paths_section))
        self.assertEqual(1, splitter.handleWidth())

    def test_real_format_explorer_retains_source_authoritative_side_by_side_layout(self) -> None:
        from tools.format_explorer.tab import FormatExplorerTab

        tab = FormatExplorerTab()
        tab.resize(1120, 720)
        tab.show()
        self.assertTrue(
            apply_compact_presentation(
                self._window("compact_rail"), "format_explorer", tab
            )
        )
        _app().processEvents()

        self.assertEqual(Qt.Orientation.Horizontal, tab.main_splitter.orientation())
        self.assertGreater(tab.table.width(), tab.detail.width())
        self.assertLess(tab.table.geometry().right(), tab.detail.geometry().left())
        self.assertEqual(tab.table.height(), tab.detail.height())
        self.assertTrue(tab.table.isVisibleTo(tab))
        self.assertTrue(tab.detail.isVisibleTo(tab))
        self.assertEqual(1, tab.table.selectionMode().value)
        tab.close()

    def test_real_texture_editor_prioritizes_canvas_at_minimum_size(self) -> None:
        from cdmw.ui.texture_editor_tab import TextureEditorTab

        tab = TextureEditorTab(
            settings=self.settings,
            base_dir=Path(self._temporary.name),
            get_png_root=lambda: "",
            get_original_dds_root=lambda: "",
            get_archive_entries=lambda: (),
            get_current_config=lambda: None,
        )
        tab.resize(1120, 720)
        tab.show()
        self.assertTrue(
            apply_compact_presentation(
                self._window("compact_rail"), "texture_editor", tab
            )
        )
        _app().processEvents()

        sizes = tab.main_splitter.sizes()
        self.assertEqual(3, len(sizes))
        self.assertGreater(sizes[1], sizes[0])
        self.assertGreater(sizes[1], sizes[2])
        self.assertEqual(1, tab.main_splitter.handleWidth())
        self.assertTrue(tab.canvas_panel.isVisibleTo(tab))
        contract = compact_surface_contract(tab)
        self.assertGreater(contract["compact_surface_count"], 10)
        self.assertEqual(0, contract["unflattened_compact_surface_count"])
        tab.close()
        tab.deleteLater()


if __name__ == "__main__":
    unittest.main()
