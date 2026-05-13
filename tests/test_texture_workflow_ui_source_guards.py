from __future__ import annotations

import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
MAIN_WINDOW = REPO_ROOT / "cdmw" / "ui" / "main_window.py"
REPLACE_ASSISTANT_TAB = REPO_ROOT / "cdmw" / "ui" / "replace_assistant_tab.py"
RESEARCH_TAB = REPO_ROOT / "cdmw" / "ui" / "research_tab.py"
TEXTURE_EDITOR_TAB = REPO_ROOT / "cdmw" / "ui" / "texture_editor_tab.py"
ITEM_ICONS_TAB = REPO_ROOT / "cdmw" / "ui" / "item_icons_tab.py"
README = REPO_ROOT / "README.md"


class TextureWorkflowUiSourceGuards(unittest.TestCase):
    def test_dds_output_selectors_have_room_for_default_labels(self) -> None:
        source = MAIN_WINDOW.read_text(encoding="utf-8")

        self.assertIn("(self.dds_format_mode_combo, 28)", source)
        self.assertIn("(self.dds_size_mode_combo, 32)", source)
        self.assertIn("(self.dds_mip_mode_combo, 30)", source)
        self.assertIn("combo.setMinimumContentsLength(minimum_contents_length)", source)
        self.assertIn("combo.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)", source)
        self.assertIn("combo.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)", source)
        self.assertIn("dds_output_options_layout.setColumnMinimumWidth(0, 84)", source)
        self.assertIn("dds_output_header_widget = QWidget()", source)
        self.assertIn("dds_output_header_layout.addWidget(self.enable_dds_staging_checkbox, 1)", source)
        self.assertNotIn("dds_output_options_layout.setColumnMinimumWidth(0, 132)", source)
        self.assertNotIn("dds_output_options_layout.addWidget(self.enable_dds_staging_checkbox, 0, 0, 1, 3)", source)

    def test_user_facing_tool_names_are_current(self) -> None:
        main_source = MAIN_WINDOW.read_text(encoding="utf-8")
        replacer_source = REPLACE_ASSISTANT_TAB.read_text(encoding="utf-8")
        research_source = RESEARCH_TAB.read_text(encoding="utf-8")
        editor_source = TEXTURE_EDITOR_TAB.read_text(encoding="utf-8")
        readme = README.read_text(encoding="utf-8")

        self.assertIn('self.main_tabs.insertTab(1, self.replace_assistant_tab, "Texture Replacer")', main_source)
        self.assertIn('self._register_detachable_tool("replace_assistant", self.replace_assistant_tab, "Texture Replacer")', main_source)
        self.assertIn("text_search_index = self.main_tabs.indexOf(self.text_search_tab)", main_source)
        self.assertIn('self.main_tabs.insertTab(text_search_index + 1, self.item_icons_tab, "Icon creator")', main_source)
        self.assertIn('self._register_detachable_tool("item_icons", self.item_icons_tab, "Icon creator")', main_source)
        self.assertIn("self.item_icons_tab.open_target_in_archive_requested.connect(", main_source)
        self.assertIn('self.main_tabs.addTab(self.research_tab, "Research")', main_source)
        self.assertIn('QPushButton("Resolve In Research")', main_source)
        self.assertIn('self.setWindowTitle("Texture Replacer Review")', replacer_source)
        self.assertIn('QAction("Send To Texture Replacer", self)', editor_source)
        self.assertIn('QAction("Send To Icon creator", self)', editor_source)
        self.assertIn("send_to_item_icons_requested = Signal(str, object)", editor_source)
        self.assertIn('QPushButton("Refresh Research")', research_source)
        self.assertIn("`Texture Replacer`", readme)
        self.assertNotIn('"Replace Assistant"', main_source)

    def test_item_icons_workspace_has_library_and_generation_controls(self) -> None:
        source = ITEM_ICONS_TAB.read_text(encoding="utf-8")

        self.assertIn("class ItemIconLibraryTab(QWidget)", source)
        self.assertIn('header = QLabel("Icon creator")', source)
        self.assertIn('self.settings.value("item_icons/library_roots", "[]")', source)
        self.assertIn('self.index_path = self.library_root / "icon_index.json"', source)
        self.assertIn('QGroupBox("Library Folders")', source)
        self.assertIn('QGroupBox("Compatible Output")', source)
        self.assertIn('self.target_filter_edit.setPlaceholderText("Filter or paste an existing archive item icon path")', source)
        self.assertIn('self.use_archive_selection_button = QPushButton("Use Archive Selection")', source)
        self.assertIn('self.open_target_archive_button = QPushButton("Open In Archive Browser")', source)
        self.assertIn("open_target_in_archive_requested = Signal(str)", source)
        self.assertIn("def _matching_target_entries", source)
        self.assertIn("display_limit = 300", source)
        self.assertIn("choose_source_dialog", source)
        self.assertIn("build_item_icon_payload(", source)
        self.assertIn("target_template_path=template_path", source)


if __name__ == "__main__":
    unittest.main()
