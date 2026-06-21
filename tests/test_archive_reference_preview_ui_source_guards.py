from pathlib import Path
import unittest


REPO_ROOT = Path(__file__).resolve().parents[1]
APP_WINDOW = REPO_ROOT / "cdmw" / "ui" / "shell" / "app_window.py"
ARCHIVE_REFERENCE_PREVIEW = REPO_ROOT / "cdmw" / "ui" / "archive_browser" / "reference_preview.py"
ARCHIVE_PREVIEW_PANEL = REPO_ROOT / "cdmw" / "ui" / "archive_browser" / "preview_panel.py"
ARCHIVE_PREVIEW_LAYOUT = REPO_ROOT / "cdmw" / "ui" / "archive_browser" / "preview_layout.py"


class ArchiveReferencePreviewUiSourceGuards(unittest.TestCase):
    def test_referenced_text_preview_has_search_wrap_and_structured_highlighting(self) -> None:
        source = "\n".join(
            (
                APP_WINDOW.read_text(encoding="utf-8"),
                ARCHIVE_REFERENCE_PREVIEW.read_text(encoding="utf-8"),
                ARCHIVE_PREVIEW_PANEL.read_text(encoding="utf-8"),
            )
        )

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
        source = ARCHIVE_REFERENCE_PREVIEW.read_text(encoding="utf-8")

        self.assertIn("def _open_hkx_editor_from_reference_preview(", source)
        self.assertIn("_checked: bool = False", source)
        self.assertIn("current_entry: ArchiveEntry = entry", source)
        self.assertIn('pending_hkx_editor_entry["entry"] = current_entry', source)

    def test_referenced_preview_can_show_asset_family_graph(self) -> None:
        source = ARCHIVE_REFERENCE_PREVIEW.read_text(encoding="utf-8")

        self.assertIn("reference_family_graph = result.asset_family_graph", source)
        self.assertIn("reference_family_graph = build_archive_asset_family_graph(entry, result.model_texture_references)", source)
        self.assertIn('preview_tabs.addTab(family_tab, "Asset Family")', source)
        self.assertIn('family_tree.setHeaderLabels(["Role", "File", "Status", "Evidence", "Why"])', source)
        self.assertIn("self._install_tree_horizontal_wheel_guard(family_tree)", source)

    def test_archive_summary_highlighter_understands_simplified_previews(self) -> None:
        source = (REPO_ROOT / "cdmw" / "ui" / "text_preview_widgets.py").read_text(encoding="utf-8")

        self.assertIn("Simplified values for .+", source)
        self.assertIn("HKX tagfile preview for .+", source)
        self.assertIn("What this appears to contain:", source)
        self.assertIn("Recognized fields:", source)
        self.assertIn("Format summary:", source)
        self.assertIn("Tag item map:", source)
        self.assertIn("Detected classes/types:", source)
        self.assertIn("_hex_value_re", source)
        self.assertIn(r"^\s*(?:[-*]\s*)?", source)

    def test_archive_browser_text_fallbacks_share_preview_highlighting(self) -> None:
        app_window_source = APP_WINDOW.read_text(encoding="utf-8")
        theme_source = (REPO_ROOT / "cdmw" / "ui" / "shell" / "theme_controller.py").read_text(encoding="utf-8")
        preview_source = ARCHIVE_PREVIEW_PANEL.read_text(encoding="utf-8")
        preview_layout_source = ARCHIVE_PREVIEW_LAYOUT.read_text(encoding="utf-8")
        source = app_window_source + "\n" + theme_source + "\n" + preview_source + "\n" + preview_layout_source

        self.assertIn("self.archive_preview_info_edit = ArchiveDetailsEditor", source)
        self.assertIn("window.archive_preview_info_edit,", theme_source)
        self.assertIn("window.archive_preview_info_edit.apply_font_preferences(log_font, preserve_size=False)", theme_source)
        self.assertIn("self.archive_preview_info_tools = self._build_archive_text_tools(self.archive_preview_info_edit)", source)
        self.assertIn("self.archive_preview_info_edit.set_theme(self.current_theme_key)", source)
        self.assertIn("current_widget is self.archive_preview_info_edit", source)

    def test_model_preview_panes_show_navigation_controls_hint(self) -> None:
        source = "\n".join(
            (
                APP_WINDOW.read_text(encoding="utf-8"),
                ARCHIVE_PREVIEW_LAYOUT.read_text(encoding="utf-8"),
                ARCHIVE_REFERENCE_PREVIEW.read_text(encoding="utf-8"),
                ARCHIVE_PREVIEW_PANEL.read_text(encoding="utf-8"),
            )
        )

        self.assertIn("self.archive_preview_controls_hint_label = QLabel", source)
        self.assertIn("preview_controls_hint_label = QLabel", source)
        self.assertIn("left-drag orbit | middle/right-drag pan", source)
        self.assertIn("These controls move the preview camera/view only", source)
        self.assertIn("self.archive_preview_controls_hint_label.setVisible(", source)
        self.assertIn("current_widget is self.archive_model_preview", source)
        self.assertIn("current_widget is self.archive_d3d11_preview_host", source)
        self.assertIn("preview_controls_hint_label.setVisible(current_widget is preview_model or current_widget is preview_d3d11_host)", source)

    def test_referenced_pac_preview_can_use_native_d3d11_package(self) -> None:
        source = ARCHIVE_REFERENCE_PREVIEW.read_text(encoding="utf-8")
        reference_start = source.index("def _open_archive_reference_preview_entry")
        reference_end = source.index("def _export_selected_archive_texture_reference", reference_start)
        reference_source = source[reference_start:reference_end]
        dialog_start = source.index("def _show_archive_reference_preview_dialog")
        dialog_end = source.index("def _update_archive_texture_reference_action_controls", dialog_start)
        dialog_source = source[dialog_start:dialog_end]

        self.assertIn("run_native_preview_core_preview_job", reference_source)
        self.assertIn("NATIVE_PREVIEW_CORE_MODEL_EXTENSIONS", reference_source)
        self.assertIn("native_preview_package_path=native_attempt.package_path", reference_source)
        self.assertIn("preview_d3d11_host = NativeD3D11PreviewHostFrame(dialog)", dialog_source)
        self.assertIn("_start_reference_d3d11_preview", dialog_source)
        self.assertIn("self._native_d3d11_renderer_command(", dialog_source)


if __name__ == "__main__":
    unittest.main()
