from __future__ import annotations

import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
MAIN_WINDOW = REPO_ROOT / "cdmw" / "ui" / "shell" / "app_window.py"
SETTINGS_AUTOSAVE = REPO_ROOT / "cdmw" / "ui" / "shell" / "settings_autosave.py"
SETTINGS_PERSISTENCE = REPO_ROOT / "cdmw" / "ui" / "shell" / "settings_persistence.py"
TEXTURE_PANEL_PERSISTENCE = REPO_ROOT / "cdmw" / "ui" / "shell" / "texture_panel_persistence.py"
SHELL_MENUS = REPO_ROOT / "cdmw" / "ui" / "shell" / "menus.py"
SHELL_TOOL_TABS = REPO_ROOT / "cdmw" / "ui" / "shell" / "tool_tabs.py"
TEXTURE_WORKFLOW_ASSET_AUTHORING_PANEL = REPO_ROOT / "cdmw" / "ui" / "texture_workflow" / "asset_authoring_panel.py"
TEXTURE_WORKFLOW_DDS_OUTPUT_PANEL = REPO_ROOT / "cdmw" / "ui" / "texture_workflow" / "dds_output_panel.py"
TEXTURE_WORKFLOW_SETTINGS_PANEL = REPO_ROOT / "cdmw" / "ui" / "texture_workflow" / "settings_panel.py"
TEXTURE_WORKFLOW_SHELL_CONTROLS = REPO_ROOT / "cdmw" / "ui" / "texture_workflow" / "shell_controls.py"
ARCHIVE_CONTROLS_PANEL = REPO_ROOT / "cdmw" / "ui" / "archive_browser" / "controls_panel.py"
DASHBOARD_CONTROLLER = REPO_ROOT / "cdmw" / "ui" / "shell" / "dashboard_controller.py"
SHELL_ROOT_LAYOUT = REPO_ROOT / "cdmw" / "ui" / "shell" / "root_layout.py"
SHELL_WORKSPACE_LAYOUT = REPO_ROOT / "cdmw" / "ui" / "shell" / "workspace_layout.py"
TEXTURE_WORKSPACE_LAYOUT = REPO_ROOT / "cdmw" / "ui" / "shell" / "texture_workspace_layout.py"
REPLACE_ASSISTANT_TAB = REPO_ROOT / "cdmw" / "ui" / "replace_assistant_tab.py"
REPLACE_ASSISTANT_REVIEW_DIALOG = REPO_ROOT / "cdmw" / "ui" / "replace_assistant" / "review_dialog.py"
RESEARCH_TAB = REPO_ROOT / "cdmw" / "ui" / "research" / "tab.py"
TEXTURE_EDITOR_TAB = REPO_ROOT / "cdmw" / "ui" / "texture_editor_tab.py"
ITEM_ICONS_TAB = REPO_ROOT / "cdmw" / "ui" / "item_icons" / "tab.py"
ITEM_ICONS_PANELS = REPO_ROOT / "cdmw" / "ui" / "item_icons" / "panels.py"
THEMES = REPO_ROOT / "cdmw" / "ui" / "themes.py"
README = REPO_ROOT / "README.md"


class TextureWorkflowUiSourceGuards(unittest.TestCase):
    def test_asset_authoring_panel_uses_openimageio_worker_and_persistence(self) -> None:
        panel_source = TEXTURE_WORKFLOW_ASSET_AUTHORING_PANEL.read_text(encoding="utf-8")
        settings_panel_source = TEXTURE_WORKFLOW_SETTINGS_PANEL.read_text(encoding="utf-8")
        autosave_source = SETTINGS_AUTOSAVE.read_text(encoding="utf-8")
        persistence_source = (
            SETTINGS_PERSISTENCE.read_text(encoding="utf-8")
            + TEXTURE_PANEL_PERSISTENCE.read_text(encoding="utf-8")
        )

        self.assertIn("class TextureWorkflowAssetAuthoringPanelMixin", panel_source)
        self.assertIn("OpenImageIOTaskWorker", panel_source)
        self.assertNotIn("MaterialMakerExportWorker", panel_source)
        self.assertNotIn("Material Maker", panel_source)
        self.assertIn("QThread(self)", panel_source)
        self.assertIn("self.shell.utility_worker = worker", panel_source)
        self.assertIn("worker.completed.connect(self._handle_openimageio_task_complete)", panel_source)
        self.assertIn("thread.finished.connect(self.shell._cleanup_worker_refs)", panel_source)
        self.assertNotIn("_queue_current_compare_preview_if_visible", panel_source)
        self.assertNotIn("subprocess", panel_source)
        self.assertIn("class TextureWorkflowSettingsPanelMixin(TextureWorkflowAssetAuthoringPanelMixin)", settings_panel_source)
        self.assertNotIn("self.material_maker_project_edit", autosave_source)
        self.assertIn("self.textures.openimageio_source_path_edit", autosave_source)
        self.assertIn("self.textures.asset_authoring_section,", autosave_source)
        self.assertNotIn('"asset_authoring/material_maker_project_path"', persistence_source)
        self.assertIn('"asset_authoring/oiio_source_path"', persistence_source)
        self.assertIn('"sections/asset_authoring_expanded"', persistence_source)

    def test_dds_output_selectors_have_room_for_default_labels(self) -> None:
        source = TEXTURE_WORKFLOW_DDS_OUTPUT_PANEL.read_text(encoding="utf-8")

        self.assertIn("(self.dds_format_mode_combo, 18)", source)
        self.assertIn("(self.dds_size_mode_combo, 18)", source)
        self.assertIn("(self.dds_mip_mode_combo, 18)", source)
        self.assertIn("combo.setMinimumContentsLength(minimum_contents_length)", source)
        self.assertIn("combo.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)", source)
        self.assertIn("combo.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)", source)
        self.assertIn("dds_output_options_layout.setRowWrapPolicy(QFormLayout.WrapAllRows)", source)
        self.assertIn("dds_output_header_widget = QWidget()", source)
        self.assertIn("dds_output_header_layout.addWidget(self.enable_dds_staging_checkbox, 1)", source)
        self.assertNotIn("dds_output_options_layout.setColumnMinimumWidth(0, 132)", source)
        self.assertNotIn("dds_output_options_layout.addWidget(self.enable_dds_staging_checkbox, 0, 0, 1, 3)", source)


    def test_item_icons_workspace_has_library_and_generation_controls(self) -> None:
        tab_source = ITEM_ICONS_TAB.read_text(encoding="utf-8")
        panels_source = ITEM_ICONS_PANELS.read_text(encoding="utf-8")
        controller_source = Path("cdmw/ui/item_icons/controller.py").read_text(encoding="utf-8")
        output_worker_source = Path("cdmw/workers/item_icon_workers.py").read_text(encoding="utf-8")
        source = tab_source + "\n" + panels_source + "\n" + controller_source

        self.assertIn(
            "class ItemIconLibraryTab(ItemIconRecordListMixin, ItemIconWorkerMixin, QWidget)",
            tab_source,
        )
        self.assertIn("class ItemIconRecordListMixin:", controller_source)
        self.assertNotIn('header = QLabel("Icon Creator")', source)
        self.assertIn('self.settings.value("item_icons/library_roots", "[]")', source)
        self.assertIn('self.index_path = self.library_root / "icon_index.json"', source)
        self.assertIn('QGroupBox("Library Folders")', source)
        self.assertIn('QGroupBox("Compatible Output")', source)
        self.assertIn('target_filter_edit.setPlaceholderText("Filter or paste an existing archive item icon path")', source)
        self.assertIn('use_archive_selection_button = QPushButton("Use Selection")', source)
        self.assertIn('open_target_archive_button = QPushButton("Open")', source)
        self.assertIn("open_target_in_archive_requested = Signal(str)", source)
        self.assertIn("def _matching_target_entries", source)
        self.assertIn("display_limit = 300", source)
        self.assertIn("choose_source_dialog", source)
        self.assertIn("_queue_item_icon_output(", tab_source)
        self.assertIn("build_item_icon_payload(", output_worker_source)
        self.assertIn("target_template_path=template_path", output_worker_source)
        self.assertIn('add_to_loose_mod_button = QPushButton("Add")', source)
        self.assertIn("add_to_loose_mod_button.clicked.connect(", source)
        self.assertIn("add_to_existing_loose_mod", source)
        self.assertIn("def add_to_existing_loose_mod", source)
        self.assertIn("patch_existing_loose_mod_with_item_icon(", output_worker_source)
        self.assertIn("background_mode=self._background_mode()", source)
        self.assertIn('delete_source_button = QPushButton("Delete")', source)
        self.assertIn("def delete_selected_source", source)
        self.assertNotIn("path.unlink(", source)
        self.assertIn("class ItemIconLibraryMutationWorker", output_worker_source)
        self.assertIn("path.unlink(missing_ok=True)", output_worker_source)
        self.assertIn("customContextMenuRequested", source)
        self.assertIn("def _show_records_context_menu", source)


if __name__ == "__main__":
    unittest.main()
