from __future__ import annotations

import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QLabel,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from cdmw.services.settings_service import create_settings
from cdmw.ui.shell.compact.presentations import (
    COMPACT_PRESENTATION_SPECS,
    apply_compact_presentation,
)


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
        self.assertEqual((8, 8, 8, 8), (margins.left(), margins.top(), margins.right(), margins.bottom()))
        self.assertEqual(6, layout.spacing())
        self.assertEqual(1, splitter.handleWidth())
        self.assertTrue(bool(widget.property("compactPresentation")))
        self.assertEqual("text_search", widget.property("compactToolKey"))
        self.assertEqual(3, len(splitter.sizes()))
        self.assertGreater(splitter.sizes()[2], splitter.sizes()[0])
        widget.close()

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

    def test_real_format_explorer_retains_source_authoritative_detail_orientation(self) -> None:
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

        self.assertGreater(tab.table.height(), tab.detail.height())
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
        tab.close()
        tab.deleteLater()


if __name__ == "__main__":
    unittest.main()
