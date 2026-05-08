from pathlib import Path
import unittest


REPO_ROOT = Path(__file__).resolve().parents[1]


class ArchiveReferencePreviewUiSourceGuards(unittest.TestCase):
    def test_referenced_text_preview_has_search_wrap_and_structured_highlighting(self) -> None:
        source = (REPO_ROOT / "cdmw" / "ui" / "main_window.py").read_text(encoding="utf-8")

        self.assertIn("preview_summary_edit = ArchiveDetailsEditor", source)
        self.assertIn("preview_color_scheme = read_text_color_scheme", source)
        self.assertIn('"appearance/preview_color_scheme"', source)
        self.assertIn("DEFAULT_UI_PREVIEW_COLOR_SCHEME", source)
        self.assertIn("preview_text_edit.set_color_scheme(preview_color_scheme)", source)
        self.assertIn("preview_summary_edit.set_color_scheme(preview_color_scheme)", source)
        self.assertIn("preview_info_edit.set_color_scheme(preview_color_scheme)", source)
        self.assertIn("details_edit.set_color_scheme(preview_color_scheme)", source)
        self.assertIn("preview_summary_tools = self._build_archive_text_tools(preview_summary_edit)", source)
        self.assertIn("preview_info_tools = self._build_archive_text_tools(preview_info_edit)", source)
        self.assertIn("reference_preview_text_tools = {", source)
        self.assertIn("preview_stack.currentChanged.connect(_update_reference_preview_text_tools_visibility)", source)
        self.assertIn("def _preview_text_looks_like_structured_summary", source)
        self.assertIn("Recognized fields:", source)
        self.assertIn("HKX tagfile preview for ", source)
        self.assertIn("Format summary:", source)
        self.assertIn("Tag item map:", source)
        self.assertIn("Detected classes/types:", source)
        self.assertIn('search_edit.setPlaceholderText("Search preview")', source)
        self.assertIn('wrap_checkbox = QCheckBox("Wrap lines")', source)

    def test_referenced_hkx_edit_button_preserves_archive_entry(self) -> None:
        source = (REPO_ROOT / "cdmw" / "ui" / "main_window.py").read_text(encoding="utf-8")

        self.assertIn("def _open_hkx_editor_from_reference_preview(", source)
        self.assertIn("_checked: bool = False", source)
        self.assertIn("current_entry: ArchiveEntry = entry", source)
        self.assertIn('pending_hkx_editor_entry["entry"] = current_entry', source)

    def test_referenced_preview_can_show_asset_family_graph(self) -> None:
        source = (REPO_ROOT / "cdmw" / "ui" / "main_window.py").read_text(encoding="utf-8")

        self.assertIn("reference_family_graph = result.asset_family_graph", source)
        self.assertIn("reference_family_graph = build_archive_asset_family_graph(entry, result.model_texture_references)", source)
        self.assertIn('preview_tabs.addTab(family_tab, "Asset Family")', source)
        self.assertIn('family_tree.setHeaderLabels(["Role", "File", "Status", "Evidence", "Why"])', source)

    def test_archive_summary_highlighter_understands_simplified_previews(self) -> None:
        source = (REPO_ROOT / "cdmw" / "ui" / "widgets.py").read_text(encoding="utf-8")

        self.assertIn("Simplified values for .+", source)
        self.assertIn("HKX tagfile preview for .+", source)
        self.assertIn("What this appears to contain:", source)
        self.assertIn("Recognized fields:", source)
        self.assertIn("Format summary:", source)
        self.assertIn("Tag item map:", source)
        self.assertIn("Detected classes/types:", source)
        self.assertIn("_hex_value_re", source)
        self.assertIn(r"^\s*(?:[-*]\s*)?", source)


if __name__ == "__main__":
    unittest.main()
