from pathlib import Path
import unittest


REPO_ROOT = Path(__file__).resolve().parents[1]
MAIN_WINDOW = REPO_ROOT / "cdmw" / "ui" / "shell" / "app_window.py"
SHELL_MENUS = REPO_ROOT / "cdmw" / "ui" / "shell" / "menus.py"
SHELL_WINDOW_RUNTIME_STATE = REPO_ROOT / "cdmw" / "ui" / "shell" / "window_runtime_state.py"
SIGNAL_WIRING = REPO_ROOT / "cdmw" / "ui" / "shell" / "signal_wiring.py"
SETTINGS_PERSISTENCE = REPO_ROOT / "cdmw" / "ui" / "shell" / "settings_persistence.py"
DASHBOARD_CONTROLLER = REPO_ROOT / "cdmw" / "ui" / "shell" / "dashboard_controller.py"
STARTUP_CONTROLLER = REPO_ROOT / "cdmw" / "ui" / "shell" / "startup_controller.py"
UTILITY_CONTROLLER = REPO_ROOT / "cdmw" / "ui" / "shell" / "utility_controller.py"
ARCHIVE_PROGRESS = REPO_ROOT / "cdmw" / "ui" / "archive_browser" / "progress.py"
ARCHIVE_ACTIONS = REPO_ROOT / "cdmw" / "ui" / "archive_browser" / "actions.py"
ARCHIVE_ASSET_CATALOG = REPO_ROOT / "cdmw" / "ui" / "archive_browser" / "asset_catalog.py"
ARCHIVE_ASSET_CATALOG_DIALOG = REPO_ROOT / "cdmw" / "ui" / "archive_browser" / "asset_catalog_dialog.py"
ARCHIVE_ASSET_CATALOG_SCOPE = REPO_ROOT / "cdmw" / "ui" / "archive_browser" / "asset_catalog_scope.py"
ARCHIVE_FILTER_CONTROLS = REPO_ROOT / "cdmw" / "ui" / "archive_browser" / "filter_controls.py"
ARCHIVE_FILES_PANEL = REPO_ROOT / "cdmw" / "ui" / "archive_browser" / "files_panel.py"
ARCHIVE_ICON_PIPELINE = REPO_ROOT / "cdmw" / "ui" / "archive_browser" / "icon_pipeline.py"
ARCHIVE_INDEX_WORKERS_UI = REPO_ROOT / "cdmw" / "ui" / "archive_browser" / "index_workers.py"
ARCHIVE_ATTACHMENT_DONOR_PICKER_DIALOG = REPO_ROOT / "cdmw" / "ui" / "archive_browser" / "attachment_donor_picker_dialog.py"
ARCHIVE_ATTACHMENT_PLACEMENT_DIFF_DIALOG = REPO_ROOT / "cdmw" / "ui" / "archive_browser" / "attachment_placement_diff_dialog.py"
ARCHIVE_ATTACHMENT_SAFE_PLACEMENT_DIALOG = REPO_ROOT / "cdmw" / "ui" / "archive_browser" / "attachment_safe_placement_dialog.py"
ARCHIVE_APPEARANCE_COMMON = REPO_ROOT / "cdmw" / "ui" / "archive_browser" / "appearance_common.py"
ARCHIVE_APPEARANCE_COMPOSITE = REPO_ROOT / "cdmw" / "ui" / "archive_browser" / "appearance_composite.py"
ARCHIVE_APPEARANCE_SWAP = REPO_ROOT / "cdmw" / "ui" / "archive_browser" / "appearance_swap.py"
ARCHIVE_HKX_DOCUMENT_ACTIONS = REPO_ROOT / "cdmw" / "ui" / "archive_browser" / "hkx_document_actions.py"
ARCHIVE_HKX_EDITOR_DIALOG = REPO_ROOT / "cdmw" / "ui" / "archive_browser" / "hkx_editor_dialog.py"
ARCHIVE_MESH_MODIFY_ORIGINAL = REPO_ROOT / "cdmw" / "ui" / "archive_browser" / "mesh_modify_original.py"
ARCHIVE_MESH_PATCH_FLOW = REPO_ROOT / "cdmw" / "ui" / "archive_browser" / "mesh_patch_flow.py"
ARCHIVE_MESH_SETUP_HELPERS = REPO_ROOT / "cdmw" / "ui" / "archive_browser" / "mesh_setup_helpers.py"
ARCHIVE_MATERIAL_SIDECAR_ACTIONS = REPO_ROOT / "cdmw" / "ui" / "archive_browser" / "material_sidecar_actions.py"
ARCHIVE_MATERIAL_SIDECAR_EDITOR_DIALOG = REPO_ROOT / "cdmw" / "ui" / "archive_browser" / "material_sidecar_editor_dialog.py"
ARCHIVE_MATERIAL_SIDECAR_EDITOR_HELPERS = REPO_ROOT / "cdmw" / "ui" / "archive_browser" / "material_sidecar_editor_helpers.py"
ARCHIVE_MOD_READY_EXPORT = REPO_ROOT / "cdmw" / "ui" / "archive_browser" / "mod_ready_export.py"
ARCHIVE_RENDER_LIFECYCLE = REPO_ROOT / "cdmw" / "ui" / "archive_browser" / "render_lifecycle.py"
ARCHIVE_SCAN_LIFECYCLE = REPO_ROOT / "cdmw" / "ui" / "archive_browser" / "scan_lifecycle.py"
ARCHIVE_UI_FORMATTING = REPO_ROOT / "cdmw" / "ui" / "archive_browser" / "ui_formatting.py"
ARCHIVE_VIRTUAL_PATH_LOOKUP = REPO_ROOT / "cdmw" / "ui" / "archive_browser" / "virtual_path_lookup.py"
ARCHIVE_ATTACHMENT_ICONS = REPO_ROOT / "cdmw" / "ui" / "archive_browser" / "attachment_icons.py"
ARCHIVE_ATTACHMENT_LOOSE_FILES = REPO_ROOT / "cdmw" / "ui" / "archive_browser" / "attachment_loose_files.py"
ARCHIVE_ATTACHMENT_BATCH = REPO_ROOT / "cdmw" / "ui" / "archive_browser" / "attachment_batch.py"
ARCHIVE_ATTACHMENT_PACKAGE = REPO_ROOT / "cdmw" / "ui" / "archive_browser" / "attachment_package.py"
ARCHIVE_ATTACHMENT_PLAN = REPO_ROOT / "cdmw" / "ui" / "archive_browser" / "attachment_plan.py"
ARCHIVE_ATTACHMENT_SOCKET_EDITOR = REPO_ROOT / "cdmw" / "ui" / "archive_browser" / "attachment_socket_editor.py"
ARCHIVE_ATTACHMENT_VISUAL_CONTEXT = REPO_ROOT / "cdmw" / "ui" / "archive_browser" / "attachment_visual_context.py"
ARCHIVE_ATTACHMENT_VISUAL_CORE = REPO_ROOT / "cdmw" / "ui" / "archive_browser" / "attachment_visual_core.py"
ARCHIVE_ATTACHMENT_VISUAL_DIALOG = REPO_ROOT / "cdmw" / "ui" / "archive_browser" / "attachment_visual_dialog.py"
ARCHIVE_ATTACHMENT_VISUAL_GEOMETRY = REPO_ROOT / "cdmw" / "ui" / "archive_browser" / "attachment_visual_geometry.py"
ARCHIVE_ATTACHMENT_VISUAL_PREVIEW = REPO_ROOT / "cdmw" / "ui" / "archive_browser" / "attachment_visual_preview.py"
ARCHIVE_CONTROLS_PANEL = REPO_ROOT / "cdmw" / "ui" / "archive_browser" / "controls_panel.py"
ARCHIVE_ASSET_FAMILY_DIALOG = REPO_ROOT / "cdmw" / "ui" / "archive_browser" / "asset_family_dialog.py"
ARCHIVE_ASSET_FAMILY_LAYOUT = REPO_ROOT / "cdmw" / "ui" / "archive_browser" / "asset_family_layout.py"
ARCHIVE_ASSET_FAMILY_PANEL = REPO_ROOT / "cdmw" / "ui" / "archive_browser" / "asset_family_panel.py"
ARCHIVE_ASSET_FAMILY_REFERENCES = REPO_ROOT / "cdmw" / "ui" / "archive_browser" / "asset_family_references.py"
ARCHIVE_HEADER = REPO_ROOT / "cdmw" / "ui" / "archive_browser" / "header.py"
ARCHIVE_CHARACTER_DEPENDENCY_EXPORT = REPO_ROOT / "cdmw" / "ui" / "archive_browser" / "character_dependency_export.py"
ARCHIVE_PREVIEW_PANEL = REPO_ROOT / "cdmw" / "ui" / "archive_browser" / "preview_panel.py"
ARCHIVE_PREVIEW_LAYOUT = REPO_ROOT / "cdmw" / "ui" / "archive_browser" / "preview_layout.py"
ARCHIVE_REFERENCE_PREVIEW = REPO_ROOT / "cdmw" / "ui" / "archive_browser" / "reference_preview.py"
ARCHIVE_SOURCE_MIX_ACTIONS = REPO_ROOT / "cdmw" / "ui" / "archive_browser" / "source_mix_actions.py"
ARCHIVE_SOURCE_MIX_OVERLAY = REPO_ROOT / "cdmw" / "ui" / "archive_browser" / "source_mix_overlay.py"
ARCHIVE_WEAPON_PLACEMENT_MAP = REPO_ROOT / "cdmw" / "ui" / "archive_browser" / "weapon_placement_map.py"
ARCHIVE_WEAPON_PLACEMENT_STUDIO = REPO_ROOT / "cdmw" / "ui" / "archive_browser" / "weapon_placement_studio.py"
ARCHIVE_WORKERS = REPO_ROOT / "cdmw" / "workers" / "archive_workers.py"
ARCHIVE_SCAN_WORKERS = REPO_ROOT / "cdmw" / "workers" / "archive_scan_workers.py"
ARCHIVE_PREVIEW_NATIVE = REPO_ROOT / "cdmw" / "workers" / "archive_preview_native.py"
MESH_DOMAIN_SESSION = REPO_ROOT / "cdmw" / "domain" / "mesh" / "session.py"
MESH_EDITOR_SHELL_BRIDGE = REPO_ROOT / "cdmw" / "ui" / "mesh_editor" / "shell_bridge.py"
TEXTURE_WORKFLOW_UPSCALE_BACKEND_PANEL = REPO_ROOT / "cdmw" / "ui" / "texture_workflow" / "upscale_backend_panel.py"


class ArchiveBrowserAssetUnderstandingUiSourceGuards(unittest.TestCase):
    def test_item_finder_uses_persistent_icon_cache_and_visible_warmup(self) -> None:
        source = "\n".join(
            (
                MAIN_WINDOW.read_text(encoding="utf-8"),
                ARCHIVE_ASSET_CATALOG_DIALOG.read_text(encoding="utf-8"),
                ARCHIVE_ASSET_CATALOG_SCOPE.read_text(encoding="utf-8"),
                ARCHIVE_ATTACHMENT_DONOR_PICKER_DIALOG.read_text(encoding="utf-8"),
                ARCHIVE_ICON_PIPELINE.read_text(encoding="utf-8"),
            )
        )
        worker_source = ARCHIVE_WORKERS.read_text(encoding="utf-8")

        self.assertIn("load_archive_item_icon_thumbnail_cache(", worker_source)
        self.assertIn("save_archive_item_icon_thumbnail_cache(", worker_source)
        self.assertIn("ensure_directxtex_dds_preview_pngs(", worker_source)
        self.assertNotIn("def _warm_item_finder_icon_rows_before_exec(", source)
        self.assertNotIn("QApplication.instance()\n            deadline = time.monotonic() + min(0.5", source)
        self.assertIn("batch = self.archive_item_icon_priority_queue[:16]", source)
        self.assertIn("QTimer.singleShot(140, _queue_catalog_row_icons_for_visible_rows)", source)
        self.assertIn("finder_icon_visible_timer.setInterval(80)", source)
        self.assertIn("display_limit = 600 if not query_tokens and not selected_category and not selected_group else 2500", source)
        self.assertIn("allow_sync_prepare=False", source)

    def test_item_icon_worker_prefers_persistent_and_batch_conversion(self) -> None:
        source = ARCHIVE_WORKERS.read_text(encoding="utf-8")
        worker_start = source.index("class ArchiveItemIconWarmupWorker")
        worker_end = source.index("__all__", worker_start)
        worker_source = source[worker_start:worker_end]
        cache_hit = worker_source.index("cached = load_archive_item_icon_thumbnail_cache(")
        extract = worker_source.index("source_path, _note = ensure_archive_preview_source(")
        batch_convert = worker_source.index("batch_results = ensure_directxtex_dds_preview_pngs(")
        fallback_convert = worker_source.index("preview_path = ensure_dds_display_preview_png(")

        self.assertLess(cache_hit, extract)
        self.assertLess(batch_convert, fallback_convert)
        self.assertIn("pending_dds_keys.add(prepared_key)", worker_source)
        self.assertIn("failed_dds_notes.setdefault(", worker_source)
        self.assertIn("save_archive_item_icon_thumbnail_cache(", worker_source)
        self.assertIn("emit_prepared(prepared_key, cached_path, note)", worker_source)

    def test_asset_map_tabs_and_preview_health_are_present(self) -> None:
        source = "\n".join(
            (
                MAIN_WINDOW.read_text(encoding="utf-8"),
                SIGNAL_WIRING.read_text(encoding="utf-8"),
                ARCHIVE_ASSET_FAMILY_LAYOUT.read_text(encoding="utf-8"),
                ARCHIVE_PREVIEW_LAYOUT.read_text(encoding="utf-8"),
                ARCHIVE_PREVIEW_PANEL.read_text(encoding="utf-8"),
            )
        )
        preview_worker_source = ARCHIVE_PREVIEW_NATIVE.read_text(encoding="utf-8")

        self.assertIn("self.archive_asset_map_tabs = QTabWidget()", source)
        self.assertIn('self.archive_asset_family_button = QPushButton("Asset Family")', source)
        self.assertIn("self.archive_asset_family_button.clicked.connect(self._open_archive_asset_family_workspace_dialog)", source)
        self.assertIn("self.archive_asset_family_summary_label = QLabel", source)
        self.assertIn('self.archive_asset_map_tabs.addTab(self.archive_asset_map_tree, "Asset Family")', source)
        self.assertIn('self.archive_asset_map_tabs.addTab(self.archive_asset_uses_tree, "Uses")', source)
        self.assertIn('self.archive_asset_map_tabs.addTab(self.archive_asset_used_by_tree, "Used By")', source)
        self.assertIn('self.archive_asset_map_tabs.addTab(self.archive_asset_placement_tree, "Placement")', source)
        self.assertIn('self.archive_asset_map_tabs.addTab(self.archive_texture_refs_tree, "Raw Table")', source)
        self.assertIn("self.archive_preview_role_badge = QLabel", source)
        self.assertIn("self.archive_preview_health_label = QLabel", source)
        self.assertIn("def _archive_preview_health_text(", source)
        self.assertIn('"Preview OK"', source)
        self.assertIn('"Physics Metadata"', source)
        self.assertNotIn('"Physics Linked"', source)
        self.assertIn('"Name Inferred"', source)
        self.assertIn("Native Asset Family: schema=v", preview_worker_source)
        self.assertIn("python_graph = build_archive_asset_family_graph(source_entry, tuple(references))", preview_worker_source)
        self.assertIn('graph.attachment_evidence = tuple(getattr(python_graph, "attachment_evidence", ()) or ())', preview_worker_source)

    def test_asset_relationship_actions_use_direct_scope_and_no_live_scan(self) -> None:
        source = (
            MAIN_WINDOW.read_text(encoding="utf-8")
            + "\n"
            + SHELL_WINDOW_RUNTIME_STATE.read_text(encoding="utf-8")
            + "\n"
            + ARCHIVE_ASSET_FAMILY_LAYOUT.read_text(encoding="utf-8")
            + "\n"
            + MESH_EDITOR_SHELL_BRIDGE.read_text(encoding="utf-8")
            + "\n"
            + ARCHIVE_ACTIONS.read_text(encoding="utf-8")
            + "\n"
            + ARCHIVE_ASSET_FAMILY_DIALOG.read_text(encoding="utf-8")
            + "\n"
            + ARCHIVE_ASSET_FAMILY_REFERENCES.read_text(encoding="utf-8")
            + "\n"
            + ARCHIVE_ASSET_FAMILY_PANEL.read_text(encoding="utf-8")
        )

        self.assertIn("def _scope_current_archive_entry_only(self) -> None:", source)
        self.assertIn("def _current_archive_asset_set_entries(self, *, include_used_by: bool = False, include_hints: bool = False)", source)
        self.assertIn("def _scope_current_archive_asset_set(self, *, include_used_by: bool = False, include_hints: bool = False)", source)
        self.assertIn("def _scope_archive_asset_family_for_entry(self, entry: ArchiveEntry, *, include_hints: bool = False) -> None:", source)
        self.assertIn("def _export_archive_asset_family_for_entry(self, entry: ArchiveEntry, *, include_hints: bool = False) -> None:", source)
        self.assertIn("def _export_current_archive_asset_set(self) -> None:", source)
        self.assertIn("build_archive_item_icon_references_from_catalog(", source)
        self.assertIn('"Item Icons"', source)
        self.assertIn('reference_kind == "item_icon"', source)
        self.assertIn("def _show_archive_smart_actions_menu(self) -> None:", source)
        self.assertIn("self._apply_archive_direct_scope(", source)
        self.assertIn("Single-file scoped Archive Browser to:", source)
        self.assertIn("no full archive scan", source)
        self.assertIn('self.archive_texture_smart_actions_button = QPushButton("Family Actions")', source)
        self.assertNotIn('self.archive_open_mesh_editor_button = QPushButton("Open in Mesh Editor...")', source)
        self.assertNotIn('self.archive_open_mesh_editor_button.setObjectName("ArchiveOpenMeshEditorButton")', source)
        self.assertNotIn("self.archive_open_mesh_editor_button.clicked.connect", source)
        self.assertNotIn("self._set_action_button_state(\n                self.archive_open_mesh_editor_button", source)
        self.assertIn("def _prepare_mesh_editor_archive_launch(self, entry: ArchiveEntry) -> bool:", source)
        self.assertIn("def _launch_archive_mesh_editor_for_entry(self, entry: ArchiveEntry) -> None:", source)
        self.assertIn('self.archive_texture_scope_all_button = QPushButton("Filter to Family")', source)
        self.assertIn('self.archive_texture_export_asset_set_button = QPushButton("Export Family...")', source)
        self.assertIn("def _set_action_button_state(", source)
        self.assertIn("Unavailable:", source)
        self.assertIn("setToolTipsVisible", source)
        self.assertIn('"Export every resolved raw referenced-file row. Use Export Family for the curated Asset Family package."', source)
        self.assertIn('show_asset_set_hints_action = menu.addAction("Show Family + Hints")', source)

    def test_archive_file_context_menu_exposes_role_aware_actions(self) -> None:
        source = (
            MAIN_WINDOW.read_text(encoding="utf-8")
            + "\n"
            + ARCHIVE_HKX_DOCUMENT_ACTIONS.read_text(encoding="utf-8")
            + "\n"
            + ARCHIVE_ACTIONS.read_text(encoding="utf-8")
            + "\n"
            + ARCHIVE_MATERIAL_SIDECAR_ACTIONS.read_text(encoding="utf-8")
            + "\n"
            + ARCHIVE_VIRTUAL_PATH_LOOKUP.read_text(encoding="utf-8")
        )
        source += "\n" + MESH_EDITOR_SHELL_BRIDGE.read_text(encoding="utf-8")

        self.assertIn("def _show_archive_tree_context_menu(self, position) -> None:", source)
        self.assertIn('preview_action = menu.addAction(menu_icons["view"], "Preview")', source)
        self.assertIn('preview_window_action = menu.addAction(menu_icons["view"], "Open Preview Window...")', source)
        self.assertNotIn('composite_action = menu.addAction("Preview Composite Appearance...")', source)
        self.assertNotIn('appearance_swap_action = menu.addAction("Appearance Armor Swap...")', source)
        self.assertIn('export_file_action = menu.addAction(menu_icons["file"], "Export File...")', source)
        self.assertIn('extract_file_action = menu.addAction(menu_icons["file"], "Extract File...")', source)
        self.assertIn('family_action = menu.addAction(menu_icons["family"], "Asset Family...")', source)
        self.assertIn('weapon_placement_studio_action = menu.addAction(menu_icons["workflow"], "Weapon Placement Studio (Disabled - WIP)")', source)
        self.assertIn("weapon_placement_studio_action.setEnabled(False)", source)
        self.assertNotIn('placement_action = menu.addAction(menu_icons["family"], "Weapon Placement Studio...")', source)
        self.assertNotIn('placement_action = menu.addAction(menu_icons["family"], "Open Placement Workspace...")', source)
        self.assertIn('hkx_placement_action = menu.addAction(menu_icons["family"], "Edit HKX...")', source)
        self.assertNotIn('hkx_placement_action = menu.addAction("Open HKX Placement...")', source)
        self.assertIn("self._archive_hkx_placement_candidates_for_entry(entry)", source)
        self.assertIn("self._open_archive_hkx_placement_for_entry(current_entry)", source)
        self.assertIn('import_loose_mod_action = menu.addAction(menu_icons["workflow"], "Import Loose Mod Folder...")', source)
        self.assertNotIn('open_mesh_editor_action = menu.addAction(menu_icons["mesh"], "Open in Mesh Editor...")', source)
        self.assertNotIn('open_mesh_editor_action = menu.addAction("Open in Mesh Editor...")', source)
        self.assertIn('modify_original_action = menu.addAction(menu_icons["mesh"], "Modify Original...")', source)
        self.assertIn("self._mesh_editor_modify_original_requested(current_entry)", source)
        self.assertIn('texture_editor_action = menu.addAction(menu_icons["texture"], "Open In Texture Editor...")', source)
        self.assertIn('edit_hkx_action = menu.addAction(menu_icons["physics"], "Edit HKX...")', source)
        self.assertIn('inspect_sidecar_action = menu.addAction(menu_icons["data"], "Inspect Structured Data...")', source)
        self.assertIn('edit_material_action = menu.addAction(menu_icons["texture"], "Edit Material Values...")', source)
        self.assertIn("material_sidecar_entry = self._related_material_sidecar_entry_for_archive_entry(entry)", source)
        self.assertIn("if material_sidecar_entry is not None:", source)
        self.assertIn("current_material_entry=material_sidecar_entry", source)
        self.assertIn("self._open_material_sidecar_editor(current_material_entry)", source)
        self.assertIn("candidate_path = (source_virtual_path.parent / basename).as_posix()", source)
        self.assertIn("candidate = self._find_archive_entry_by_virtual_path(candidate_path)", source)

    def test_archive_action_dropdowns_mirror_pac_context_actions(self) -> None:
        source = MAIN_WINDOW.read_text(encoding="utf-8") + "\n" + ARCHIVE_PREVIEW_LAYOUT.read_text(encoding="utf-8")

        for token in (
            'self.archive_action_preview_button = QPushButton("Preview")',
            'self.archive_action_open_preview_window_button = QPushButton("Open Preview Window...")',
            'self.archive_action_copy_filename_button = QPushButton("Copy Filename")',
            'self.archive_action_export_file_button = QPushButton("Export File...")',
            'self.archive_action_extract_file_button = QPushButton("Extract File...")',
            'self.archive_action_show_only_file_button = QPushButton("Show Only This File")',
            'self.archive_action_asset_family_button = QPushButton("Asset Family...")',
            'self.archive_action_filter_to_family_button = QPushButton("Filter to Family")',
            'self.archive_action_export_family_button = QPushButton("Export Family...")',
            'self.archive_action_source_mix_button = QPushButton("Build Loose Package From Sources...")',
            'self.archive_action_character_dependency_button = QPushButton("Export Character Dependency Package...")',
            'self.archive_weapon_placement_studio_button = QPushButton("Weapon Placement Studio")',
        ):
            self.assertIn(token, source)

        for token in (
            '("Export File", self.archive_action_export_file_button)',
            '("Extract File", self.archive_action_extract_file_button)',
            '("Export Family", self.archive_action_export_family_button)',
            '("Export Character Dependency Package", self.archive_action_character_dependency_button)',
            '("Import Loose Mod Folder", self.archive_import_loose_mod_button)',
            '("Preview", self.archive_action_preview_button)',
            '("Open Preview Window", self.archive_action_open_preview_window_button)',
            '("Copy Filename", self.archive_action_copy_filename_button)',
            '("Show Only This File", self.archive_action_show_only_file_button)',
            '("Asset Family", self.archive_action_asset_family_button)',
            '("Filter to Family", self.archive_action_filter_to_family_button)',
            '("Build Loose Package From Sources", self.archive_action_source_mix_button)',
            '(None, self.archive_weapon_placement_studio_button)',
            '("Edit Material Values", self.archive_material_values_button)',
        ):
            self.assertIn(token, source)

    def test_material_values_preview_uses_embedded_d3d11_renderer(self) -> None:
        source = (
            MAIN_WINDOW.read_text(encoding="utf-8")
            + "\n"
            + ARCHIVE_MATERIAL_SIDECAR_EDITOR_DIALOG.read_text(encoding="utf-8")
            + "\n"
            + ARCHIVE_MATERIAL_SIDECAR_EDITOR_HELPERS.read_text(encoding="utf-8")
        )

        self.assertIn('material_preview_host = NativeD3D11PreviewHostFrame(dialog)', source)
        self.assertIn('material_preview_host.setObjectName("MaterialValuesNativeD3D11PreviewHost")', source)
        self.assertIn("preview_accuracy_warning = QLabel", source)
        self.assertIn("Material Values uses an approximate CDMW preview shader", source)
        self.assertIn("test the exported mod in game", source.lower())
        self.assertIn("write_isolated_d3d11_preview_package(", source)
        self.assertIn("material_preview_host.load_package(package_dir, status_file", source)
        self.assertIn("material_preview_base_result_state", source)
        self.assertIn("reused active Archive Preview D3D11 package; no material values changed.", source)
        self.assertIn("cleanup_owned_package=False", source)
        self.assertIn("def _current_archive_material_preview_result()", source)
        self.assertIn("def _active_archive_material_preview_package(model_entry: ArchiveEntry)", source)
        self.assertIn("archive_isolated_renderer_active_package", source)
        self.assertIn("material_preview_package_matches_entry", source)
        self.assertIn("def fast_material_preview_package_from_manifest(", source)
        self.assertIn("manifest-only material update", source)
        self.assertIn("manifest updated in", source)
        self.assertIn("cache_root=self._native_preview_package_cache_root()", source)
        self.assertIn("create_native_preview_package_staging_dir(cache_root)", source)
        self.assertIn("texture_edits_active = bool(_edited_values({\"texture\"}))", source)
        self.assertIn("edited material colors shown as solid preview overlay", source)
        self.assertIn("selected_value_edit.textChanged.connect(_sync_tree_from_selected_value)", source)
        self.assertNotIn("selected_value_edit.textEdited.connect(_sync_tree_from_selected_value)", source)
        self.assertIn("selected_value_sync_timer = QTimer(dialog)", source)
        self.assertIn("_poll_selected_value_edit", source)
        self.assertIn("selected_value_pending_edits", source)
        self.assertIn("def material_editor_color_from_value", source)
        self.assertIn("def material_value_swatch_icon", source)
        self.assertIn("blocker = QSignalBlocker(tree)", source)
        self.assertIn("item.setIcon(3, material_value_swatch_icon(color, material_value_swatch_icons))", source)
        self.assertIn('selected_value_swatch.setObjectName("SelectedMaterialValueColorSwatch")', source)
        self.assertIn("def _update_selected_value_swatch", source)
        self.assertIn("selected_value_live_refresh_timer = QTimer(dialog)", source)
        self.assertIn("def selected_value_ready_for_live_refresh", source)
        self.assertIn("_start_material_preview_refresh(include_texture_edits=False, live=True)", source)
        self.assertIn("selected_value_edit.textChanged.connect(_queue_selected_value_live_refresh)", source)
        self.assertIn("Live material preview refresh scheduled...", source)
        self.assertIn("QTimer.singleShot(", source)
        self.assertIn("def material_sidecar_selected_value_live_refresh_interval_ms", source)
        self.assertIn("material_sidecar_selected_value_live_refresh_interval_ms()", source)
        self.assertIn("current_item_for_sync = _current_item()", source)
        self.assertNotIn('NativePreviewPanel("Click Show Preview to build an approximate model preview."', source)

    def test_composite_appearance_preview_action_is_present(self) -> None:
        source = "\n".join(
            (
                MAIN_WINDOW.read_text(encoding="utf-8"),
                SIGNAL_WIRING.read_text(encoding="utf-8"),
                ARCHIVE_PREVIEW_LAYOUT.read_text(encoding="utf-8"),
                ARCHIVE_APPEARANCE_COMMON.read_text(encoding="utf-8"),
                ARCHIVE_APPEARANCE_COMPOSITE.read_text(encoding="utf-8"),
            )
        )

        self.assertIn("from cdmw.core.appearance_composite import", source)
        self.assertIn("AppearanceCompositeModelOverride", source)
        self.assertIn('self.archive_appearance_composite_button = QPushButton("Composite Preview...")', source)
        self.assertNotIn('("Preview Composite Appearance", self.archive_appearance_composite_button)', source)
        self.assertIn(
            "self.archive_appearance_composite_button.clicked.connect(self._open_current_archive_appearance_composite_preview)",
            source,
        )
        self.assertIn("def _prompt_appearance_composite_component_selection", source)
        self.assertIn("def _appearance_composite_selected_context", source)
        self.assertIn("def _prompt_appearance_composite_override_component", source)
        self.assertIn("def _open_archive_appearance_composite_preview_for_entry", source)
        self.assertIn("build_appearance_composite_preview_plan", source)
        self.assertIn("build_appearance_composite_model", source)
        self.assertIn("find_appearance_composite_candidates", source)
        self.assertIn("model_overrides=model_overrides", source)
        self.assertIn("Preparing composite appearance preview for D3D11", source)
        self.assertIn("prepared_preview_model=prepared_preview_model", source)
        self.assertIn("What-if model override", source)
        self.assertIn("Display-only preview: no archive or game files are modified.", source)
        self.assertIn("Socket-only weapons/helmets use raw-origin fallback", source)
        self.assertIn("No archive or game files were modified.", source)

    def test_appearance_armor_swap_action_and_review_are_present(self) -> None:
        swap_source = ARCHIVE_APPEARANCE_SWAP.read_text(encoding="utf-8")
        source = "\n".join(
            (
                MAIN_WINDOW.read_text(encoding="utf-8"),
                SIGNAL_WIRING.read_text(encoding="utf-8"),
                ARCHIVE_PREVIEW_LAYOUT.read_text(encoding="utf-8"),
                ARCHIVE_APPEARANCE_COMMON.read_text(encoding="utf-8"),
                swap_source,
            )
        )

        self.assertIn("AppearanceSinglePacSwapPlan", source)
        self.assertIn("build_appearance_single_pac_swap_plan", source)
        self.assertIn("build_appearance_single_pac_swap_package_plan", source)
        self.assertIn('self.archive_appearance_swap_button = QPushButton("Armor Swap...")', source)
        self.assertNotIn('("Appearance Armor Swap", self.archive_appearance_swap_button)', source)
        self.assertIn("self.archive_appearance_swap_button.clicked.connect(self._open_current_archive_appearance_swap)", source)
        self.assertIn("def _appearance_swap_selected_context", source)
        self.assertIn("def _open_current_archive_appearance_swap", source)
        self.assertIn("def _open_archive_appearance_swap_review_dialog", source)
        self.assertIn("def _start_archive_appearance_swap_package_build", source)
        self.assertIn("Target body appearance context:", source)
        self.assertIn("Target component:", source)
        self.assertIn("Target model path:", source)
        self.assertIn("Donor model path:", source)
        self.assertIn("Included donor texture count:", source)
        self.assertIn("Allow experimental mismatched body/slot package", source)
        self.assertIn("Build Loose Package", source)
        self.assertIn("No exact app XML match was found", source)
        self.assertIn("Target app XML, prefabdata, skeleton, ragdoll, and part-hide files are unchanged.", source)
        self.assertIn("export_archive_payloads_to_mod_ready_loose(", source)

        start = swap_source.index("def _open_archive_appearance_swap_for_entry(")
        end = swap_source.index("def _begin_archive_appearance_swap_review", start)
        body = swap_source[start:end]
        self.assertIn("self._begin_archive_appearance_swap_review(target_app_entry, donor_model_entry)", body)
        self.assertNotIn("find_appearance_composite_candidates", body)

    def test_character_dependency_export_plans_off_ui_thread(self) -> None:
        source = MAIN_WINDOW.read_text(encoding="utf-8") + "\n" + ARCHIVE_CHARACTER_DEPENDENCY_EXPORT.read_text(encoding="utf-8")
        start = source.index("def _export_character_dependency_package_for_entry(")
        end = source.index("__all__", start)
        body = source[start:end]

        self.assertIn("archive_entries = tuple(self.archive_entries)", body)
        self.assertIn("def task(on_log: Callable[[str], None]) -> object:", body)
        self.assertIn("return build_character_dependency_plan(", body)
        self.assertIn("self._run_utility_task(", body)
        self.assertIn("show_archive_progress=True", body)
        self.assertIn("QTimer.singleShot(", body)
        self.assertIn("def _handle_character_dependency_package_plan", body)
        self.assertNotIn("plan = build_character_dependency_plan(entry, self.archive_entries)", body)

    def test_modify_original_workspace_uses_safe_roundtrip_clone_path(self) -> None:
        source = "\n".join(
            (
                MAIN_WINDOW.read_text(encoding="utf-8"),
                SIGNAL_WIRING.read_text(encoding="utf-8"),
                ARCHIVE_PREVIEW_LAYOUT.read_text(encoding="utf-8"),
                MESH_EDITOR_SHELL_BRIDGE.read_text(encoding="utf-8"),
                ARCHIVE_MESH_MODIFY_ORIGINAL.read_text(encoding="utf-8"),
                ARCHIVE_MESH_SETUP_HELPERS.read_text(encoding="utf-8"),
                ARCHIVE_SCAN_LIFECYCLE.read_text(encoding="utf-8"),
                ARCHIVE_INDEX_WORKERS_UI.read_text(encoding="utf-8"),
                ARCHIVE_RENDER_LIFECYCLE.read_text(encoding="utf-8"),
            )
        )
        mesh_session_source = MESH_DOMAIN_SESSION.read_text(encoding="utf-8")

        self.assertIn('self.archive_model_modify_original_button = QPushButton("Modify Original...")', source)
        self.assertIn("self.archive_model_modify_original_button.clicked.connect(self._modify_current_archive_original_mesh)", source)
        self.assertIn('("Modify Original Mesh", self.archive_model_modify_original_button)', source)
        self.assertIn("def _start_archive_modify_original_workspace(self, entry: ArchiveEntry) -> None:", source)
        self.assertIn('export_archive_mesh(', source)
        self.assertIn("class ModifyOriginalWorkflowSelection:", mesh_session_source)
        self.assertIn('QRadioButton("Edit inside Mesh Replacement (no workspace export)")', source)
        self.assertIn('QRadioButton("Create editable workspace folder")', source)
        self.assertIn('"format": "cdmw_modify_original_workspace_v1"', source)
        self.assertIn('"workspace_mode": "user_workspace" if create_workspace else "internal_app_session"', source)
        self.assertIn('"create_workspace": create_workspace', source)
        self.assertIn('"policy": "safe_clone_workspace_imports_through_mesh_replacement_geometry_path"', source)
        self.assertIn("def _open_modify_original_mesh_setup(", source)
        self.assertIn("selection = self._prompt_archive_modify_original_workspace_options(entry)", source)
        self.assertIn("create_workspace = bool(selection.create_workspace)", source)
        self.assertIn("resolve_skeleton_for_obj=create_workspace", source)
        self.assertIn("session_root = workspace_paths(self.settings_file_path.parent)[\"modify_original_sessions_root\"]", source)
        self.assertIn("def _cleanup_stale_modify_original_sessions(", source)
        self.assertNotIn("modify_original_auto", source)
        self.assertIn("force_static_replacement=True", source)
        self.assertIn("MeshImportSetupSelection(", source)
        self.assertIn('placement_review_title="Modify Original Geometry"', source)
        self.assertIn("self._start_archive_mesh_patch(", source)
        self.assertIn("MODIFY_ORIGINAL_README.txt", source)
        self.assertIn("find_available_output_path(parent_root / workspace_name)", source)

    def test_modify_original_in_app_clone_skips_obj_skeleton_resolution(self) -> None:
        archive_modding_source = (
            (REPO_ROOT / "cdmw" / "core" / "archive_modding.py").read_text(encoding="utf-8")
            + "\n"
            + (REPO_ROOT / "cdmw" / "core" / "archive_mesh_export.py").read_text(encoding="utf-8")
        )
        main_window_source = MAIN_WINDOW.read_text(encoding="utf-8") + "\n" + ARCHIVE_MESH_MODIFY_ORIGINAL.read_text(encoding="utf-8")

        self.assertIn("resolve_skeleton_for_obj: bool = True", archive_modding_source)
        self.assertIn('export_kind == "fbx" or bool(resolve_skeleton_for_obj)', archive_modding_source)
        self.assertIn("resolve_skeleton_for_obj=create_workspace", main_window_source)

    def test_modify_original_preserves_selected_archive_entry_as_export_target(self) -> None:
        source = (
            MAIN_WINDOW.read_text(encoding="utf-8")
            + "\n"
            + ARCHIVE_MESH_MODIFY_ORIGINAL.read_text(encoding="utf-8")
            + "\n"
            + ARCHIVE_MESH_PATCH_FLOW.read_text(encoding="utf-8")
        )

        self.assertIn("def _modify_original_runtime_candidate_note", source)
        self.assertIn("Modify Original keeps the selected PAC as the export target", source)
        self.assertIn("build_entry = entry", source)
        self.assertNotIn("runtime_target_entry=runtime_target_entry", source)
        self.assertNotIn("setup.runtime_target_entry = runtime_target_entry", source)
        self.assertNotIn("Modify Original runtime target override", source)

    def test_roles_name_evidence_and_grouping_are_user_facing(self) -> None:
        source = (
            MAIN_WINDOW.read_text(encoding="utf-8")
            + "\n"
            + SETTINGS_PERSISTENCE.read_text(encoding="utf-8")
            + "\n"
            + ARCHIVE_SCAN_LIFECYCLE.read_text(encoding="utf-8")
            + "\n"
            + ARCHIVE_RENDER_LIFECYCLE.read_text(encoding="utf-8")
            + "\n"
            + ARCHIVE_FILES_PANEL.read_text(encoding="utf-8")
            + "\n"
            + (REPO_ROOT / "cdmw" / "ui" / "archive_browser" / "controller.py").read_text(encoding="utf-8")
            + "\n"
            + ARCHIVE_ASSET_CATALOG.read_text(encoding="utf-8")
            + "\n"
            + ARCHIVE_ASSET_CATALOG_DIALOG.read_text(encoding="utf-8")
            + "\n"
            + ARCHIVE_ASSET_CATALOG_SCOPE.read_text(encoding="utf-8")
            + "\n"
            + ARCHIVE_UI_FORMATTING.read_text(encoding="utf-8")
            + "\n"
            + ARCHIVE_ASSET_FAMILY_PANEL.read_text(encoding="utf-8")
            + "\n"
            + ARCHIVE_ASSET_FAMILY_REFERENCES.read_text(encoding="utf-8")
            + "\n"
            + ARCHIVE_HEADER.read_text(encoding="utf-8")
        )

        self.assertIn('self.archive_tree.setHeaderLabels(["Name", "Exact Name", "Name Evidence", "Role / Type"', source)
        self.assertIn('"Package", "State", "Path"', source)
        self.assertIn('self.archive_tree.setProperty("cdmw_disable_auto_column_fill", True)', source)
        self.assertIn('"ui/archive_tree_v4_column_widths"', source)
        self.assertIn('"ui/archive_tree_v4_column_order"', source)
        self.assertIn('"ui/archive_tree_v4_hidden_columns"', source)
        self.assertIn('"ui/archive_tree_v4_sort_column"', source)
        self.assertIn('"ui/archive_tree_v4_sort_order"', source)
        self.assertIn("archive_header.sectionClicked.connect(self._handle_archive_tree_header_clicked)", source)
        self.assertIn("def _handle_archive_tree_header_clicked(self, column: int) -> None:", source)
        self.assertIn("sort_archive_entries_for_browser(", source)
        self.assertIn("preserve_direct_file_order=self._archive_tree_sort_active()", source)
        self.assertNotIn("self.archive_tree.setSortingEnabled", source)
        self.assertNotIn("self.archive_tree.sortItems", source)
        self.assertNotIn('"ui/archive_tree_v2_column_widths"', source)
        self.assertIn("def _archive_entry_role_label(", source)
        self.assertIn("def _archive_asset_map_group_label(", source)
        self.assertIn("def _archive_known_used_by_references(", source)
        self.assertIn("def _archive_entry_override_state(", source)
        self.assertIn("active_archive_entry_for_virtual_path", source)
        self.assertIn('"Active mod"', source)
        self.assertIn('"Shadowed original"', source)
        self.assertIn('"Selected Model"', source)
        self.assertIn('"Attachment / Placement"', source)
        self.assertIn('"Physics / HKX"', source)
        self.assertIn('"MeshInfo"', source)
        self.assertIn('"Prefab / Metadata"', source)
        self.assertIn('"Exact localization"', source)
        self.assertIn('"Name hint: {first_related_name}"', source)
        self.assertIn("variant_count", source)

    def test_large_category_view_population_is_batched(self) -> None:
        source = (
            MAIN_WINDOW.read_text(encoding="utf-8")
            + "\n"
            + ARCHIVE_SCAN_LIFECYCLE.read_text(encoding="utf-8")
            + "\n"
            + ARCHIVE_RENDER_LIFECYCLE.read_text(encoding="utf-8")
            + "\n"
            + (REPO_ROOT / "cdmw" / "ui" / "archive_browser" / "controller.py").read_text(encoding="utf-8")
            + "\n"
            + ARCHIVE_ASSET_CATALOG.read_text(encoding="utf-8")
            + "\n"
            + ARCHIVE_ASSET_CATALOG_DIALOG.read_text(encoding="utf-8")
            + "\n"
            + ARCHIVE_ASSET_CATALOG_SCOPE.read_text(encoding="utf-8")
            + "\n"
            + UTILITY_CONTROLLER.read_text(encoding="utf-8")
        )
        scan_worker_source = ARCHIVE_SCAN_WORKERS.read_text(encoding="utf-8")

        self.assertIn("browser_state[\"category_entry_indexes\"] = build_archive_category_entry_index", scan_worker_source)
        self.assertIn("build_browser_category_index = bool(", source)
        self.assertIn("startup_deferred_archive_load = bool(", source)
        self.assertIn("build_category_index=build_browser_category_index", source)
        self.assertIn("build_category_index=rebuild_category_index", source)
        self.assertIn("elif refresh_archive_browser:", source)
        self.assertIn("self.archive_tree.set_archive_state(", source)
        self.assertNotIn("self.archive_tree_category_population_timer", source)
        self.assertNotIn("def _begin_archive_category_population(", source)
        self.assertNotIn("def _continue_archive_category_population(self) -> None:", source)
        self.assertIn("category = str(value or \"\")", source)
        self.assertIn("collected_indexes.update(self._archive_category_entry_indexes().get(category, []))", source)
        self.assertIn("and not self._archive_category_index_ready()", source)
        self.assertIn('("category_index_s", "category_index")', scan_worker_source)
        self.assertNotIn("else build_archive_category_entry_index(self.archive_filtered_entries)", source)
        self.assertNotIn("self.archive_tree_category_entry_indexes = build_archive_category_entry_index(self.archive_filtered_entries)\n            return self.archive_tree_category_entry_indexes", source)
        self.assertNotIn("if kind == \"category\":\n                self._ensure_archive_category_item_populated(item)", source)
        self.assertIn("category_evidence", source)
        self.assertIn("Category evidence:", source)
        self.assertIn("Generated thumbnail from asset texture", source)

    def test_archive_startup_progress_is_coalesced_for_smooth_splash(self) -> None:
        source = (
            MAIN_WINDOW.read_text(encoding="utf-8")
            + "\n"
            + SHELL_WINDOW_RUNTIME_STATE.read_text(encoding="utf-8")
            + "\n"
            + (REPO_ROOT / "cdmw" / "ui" / "archive_browser" / "controller.py").read_text(encoding="utf-8")
            + "\n"
            + SHELL_MENUS.read_text(encoding="utf-8")
            + "\n"
            + DASHBOARD_CONTROLLER.read_text(encoding="utf-8")
            + "\n"
            + STARTUP_CONTROLLER.read_text(encoding="utf-8")
            + "\n"
            + ARCHIVE_PROGRESS.read_text(encoding="utf-8")
            + "\n"
            + ARCHIVE_CONTROLS_PANEL.read_text(encoding="utf-8")
        )

        self.assertIn("self._archive_scan_progress_timer = QTimer(self)", source)
        self.assertIn("self._archive_scan_progress_min_interval_s = 1.0 / 30.0", source)
        self.assertIn("def _flush_archive_scan_progress(self) -> None:", source)
        self.assertIn("def _apply_archive_scan_progress(self, current: int, total: int, detail: str) -> None:", source)
        self.assertIn("def _archive_progress_phase_for_detail(self, detail: str) -> Tuple[str, int, int]:", source)
        self.assertIn("def _set_archive_load_progress(", source)
        self.assertIn("self._startup_splash_progress_detail(str(detail or \"Working...\"))", source)
        self.assertIn("self._archive_scan_progress_timer.start(delay_ms)", source)
        self.assertIn("self._flush_archive_scan_progress()", source)
        self.assertIn("self.archive_scan_progress_bar.setRange(0, 100)", source)
        self.assertIn("self.archive_scan_progress_bar.setFormat(f\"{percent_value}%\")", source)
        self.assertIn("self.archive_scan_progress_label.setText(phase_text)", source)
        self.assertIn("self._dashboard_set_archive_progress(phase_text, detail_text, percent_value)", source)
        self.assertIn('self.archive_scan_progress_label = QLabel("Ready")', source)
        controls_source = ARCHIVE_CONTROLS_PANEL.read_text(encoding="utf-8")
        menus_source = SHELL_MENUS.read_text(encoding="utf-8")
        self.assertNotIn('QGroupBox("Status")', controls_source)
        self.assertNotIn("archive_status_group_layout", controls_source)
        self.assertNotIn("Scan packages, filter rows, preview files, and extract archive entries.", controls_source)
        self.assertNotIn("Set game/package and extraction paths in Settings > Archive Locations.", controls_source)
        self.assertNotIn("archive_filters_layout.addWidget(self.archive_package_filter_hint_label)", controls_source)
        self.assertIn("archive_log_panel = QWidget()", controls_source)
        self.assertLess(
            menus_source.index("menu_corner_layout.addWidget(self.archive_scan_progress_label)"),
            menus_source.index("menu_corner_layout.addWidget(self.archive_scan_progress_bar)"),
        )
        self.assertLess(
            menus_source.index("menu_corner_layout.addWidget(self.archive_scan_progress_bar)"),
            menus_source.index("menu_corner_layout.addWidget(self.archive_cache_status_chip)"),
        )
        self.assertIn("menu_corner_layout.setSpacing(8)", menus_source)
        self.assertIn("self.archive_scan_progress_bar.setFixedSize(118, 18)", menus_source)
        self.assertIn("self.archive_cache_status_chip.setFixedWidth(132)", menus_source)
        self.assertIn("self.archive_cache_status_chip.setAlignment(Qt.AlignCenter)", menus_source)
        self.assertIn("self.archive_cache_status_chip.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)", menus_source)
        self.assertIn("def _set_archive_cache_status_chip(", source)
        self.assertIn('"building": "Cache: Building"', source)
        self.assertNotIn("percent_text =", source)
        self.assertIn('or "name search" in lowered', source)
        self.assertIn("phase_percent = int(round(100.0 * completed_value / max(total, 1)))", source)
        self.assertIn("detail_with_progress = f\"{progress_detail} ({phase_percent}%)\"", source)
        self.assertIn("self._set_archive_load_progress(progress_detail, completed_value, total, percent=percent)", source)
        self.assertIn("new_work_after_ready = (", source)
        self.assertIn("previous >= 100", source)
        self.assertIn('phase_text not in {"Ready", "Failed"}', source)
        self.assertIn("if not allow_decrease and not new_work_after_ready:", source)
        self.assertIn("def _archive_virtual_fetch_batch_size(self) -> int:", source)
        self.assertNotIn("self.archive_tree_population_time_budget_ms = 6.0", source)
        self.assertNotIn("self.archive_tree_population_timer.setInterval(12)", source)
        self.assertNotIn("self.archive_tree_category_population_timer.setInterval(12)", source)
        self.assertNotIn("return 420, 130", source)
        self.assertIn("current_item is not None and not defer_default_selection", source)

    def test_archive_startup_defers_enhanced_and_basic_indexes_until_after_ready(self) -> None:
        source = "\n".join(
            (
                MAIN_WINDOW.read_text(encoding="utf-8"),
                ARCHIVE_SCAN_LIFECYCLE.read_text(encoding="utf-8"),
                ARCHIVE_INDEX_WORKERS_UI.read_text(encoding="utf-8"),
                ARCHIVE_RENDER_LIFECYCLE.read_text(encoding="utf-8"),
            )
        )
        worker_source = ARCHIVE_WORKERS.read_text(encoding="utf-8")
        scan_body = ARCHIVE_SCAN_WORKERS.read_text(encoding="utf-8")
        self.assertIn(
            "Item-name search cache is missing or stale; archive list will open and search will build on demand.",
            scan_body,
        )
        self.assertIn("class ArchiveBasicIndexWorker", worker_source)
        self.assertIn("class ArchiveEnhancedIndexWorker", worker_source)
        self.assertIn('"enhanced_index_needs_build"', source)
        self.assertIn('"basic_index_needs_build"', source)
        self.assertIn("prewarm_basic_index = bool(", source)
        self.assertIn("prewarm_enhanced_index = bool(", source)
        self.assertIn("self.archive_deferred_basic_index_start_pending = bool(prewarm_basic_index)", source)
        self.assertIn("self.archive_deferred_enhanced_index_start_pending = bool(prewarm_enhanced_index)", source)
        self.assertIn("Path lookup cache deferred; it will build when filters", source)
        self.assertIn("Item-name search cache will warm after the archive list opens", source)
        self.assertIn("archive_enhanced_index_auto_prewarm_pending", source)
        self.assertIn("def _schedule_archive_enhanced_index_auto_prewarm", source)
        self.assertIn("self._start_archive_basic_index_worker()", source)
        self.assertIn("self._start_archive_enhanced_index_worker()", source)
        self.assertIn("self._schedule_archive_post_ready_background_work()", source)
        self.assertIn("Checking archive path lookup cache in background...", worker_source)
        self.assertIn('"cache_loaded": bool(basic_cache.get("cache_loaded", True))', worker_source)
        run_start = scan_body.index("    @Slot()\n    def run")
        run_body = scan_body[run_start:]
        self.assertIn("enhanced_index_needs_build = bool(entries and name_search_index is None)", run_body)
        self.assertIn("enhanced_index_needs_build = bool(entries)", run_body)
        self.assertIn("load_name_search_index_cache: bool = False", scan_body)
        self.assertIn("load_name_search_index=self.load_name_search_index_cache", run_body)
        self.assertIn("Item-name search cache will load on demand after the archive list opens.", run_body)
        self.assertIn("build_enhanced_indexes_before_ready = bool(", run_body)
        self.assertIn("or source != \"cache\"", run_body)
        self.assertIn("self._build_enhanced_archive_indexes_inline(entries)", run_body)
        self.assertIn("Preparing archive search cache as part of archive cache build.", run_body)
        self.assertIn("basic_indexes_needed_before_ready", run_body)
        self.assertIn("Path lookup cache is deferred until filters", run_body)
        self.assertIn("load_or_update_archive_basic_index_shards(", run_body)
        self.assertIn("save_archive_basic_index_cache(", run_body)
        self.assertIn('"enhanced_index_needs_build": enhanced_index_needs_build', run_body)
        self.assertIn('"basic_index_needs_build": bool(', run_body)
        self.assertIn("role_index", run_body)
        enhanced_start = worker_source.index("class ArchiveEnhancedIndexWorker")
        enhanced_end = worker_source.index("class ArchiveStructureFilterWorker", enhanced_start)
        enhanced_body = worker_source[enhanced_start:enhanced_end]
        self.assertIn("Preparing archive search cache (2/3): path/name index...", enhanced_body)
        self.assertIn("load_or_update_archive_name_search_shards(", enhanced_body)
        archive_name_search_source = Path("cdmw/core/archive_name_search.py").read_text(encoding="utf-8")
        self.assertIn("def load_or_update_archive_name_search_shards", archive_name_search_source)
        self.assertIn("Preparing archive search cache (2/3): path/name index", archive_name_search_source)

    def test_placement_workspace_and_loose_overlay_review_are_present(self) -> None:
        source = "\n".join(
            (
                MAIN_WINDOW.read_text(encoding="utf-8"),
                ARCHIVE_ATTACHMENT_DONOR_PICKER_DIALOG.read_text(encoding="utf-8"),
                ARCHIVE_ATTACHMENT_PLACEMENT_DIFF_DIALOG.read_text(encoding="utf-8"),
                ARCHIVE_ATTACHMENT_PLAN.read_text(encoding="utf-8"),
                ARCHIVE_ATTACHMENT_SOCKET_EDITOR.read_text(encoding="utf-8"),
            )
        )

        self.assertIn("def _open_archive_attachment_placement_workspace_dialog", source)
        self.assertIn("Weapon Placement", source)
        self.assertIn("Move the target weapon between 1H/2H body placements.", source)
        self.assertIn("Choose Placement Source", source)
        self.assertIn("Target to change", source)
        self.assertIn("Choose a 1H/2H source weapon, then build.", source)
        self.assertNotIn('self.archive_bulk_placement_swap_button = QPushButton("Bulk Placement Swap...")', source)
        self.assertNotIn("Bulk Placement Swap From Selection", source)
        self.assertIn("def _open_archive_attachment_donor_picker_dialog", source)
        self.assertIn("Search uses the already-built Archive Browser indexes", source)
        self.assertIn("Item Finder cache", source)
        self.assertIn("Basename index", source)
        self.assertIn("Current Archive Browser results", source)
        responsiveness_source = (REPO_ROOT / "cdmw" / "ui" / "shell" / "responsiveness_controller.py").read_text(encoding="utf-8")
        self.assertIn("class AutoTreeColumnWidthEventFilter(QObject)", responsiveness_source)
        self.assertIn("expand_tree_columns_to_available_width(tree)", responsiveness_source)
        self.assertIn('globals()["_cdmw_tree_column_width_filter_ref"]', source)
        self.assertIn("Add Loose Donor Folder", source)
        self.assertIn("Open Target Socket XML", source)
        self.assertIn("Write Loose Socket XML", source)
        self.assertIn("def _open_archive_socket_xml_editor_dialog", source)
        self.assertIn("Numbered XML preview", source)
        self.assertIn("PreviewSyntaxHighlighter", source)
        self.assertIn("splitter = QSplitter(Qt.Vertical)", source)
        self.assertIn("QPlainTextEdit.LineWrapMode.WidgetWidth", source)
        self.assertIn('editor_tabs.addTab(compare_page, "Compare Socket XML")', source)
        self.assertIn('compare_archive_button = QPushButton("Load Archive Socket XML...")', source)
        self.assertIn('compare_copy_selected_button = QPushButton("Copy To Selected Socket")', source)
        self.assertIn("Search uses the cached Archive Browser basename index", source)
        self.assertIn('compare_group = QGroupBox("Socket Value Compare")', source)
        self.assertIn("Compare the actual recovered socket/prefab values", source)
        self.assertIn('target_socket_button = QPushButton("Open Target Socket XML")', source)
        self.assertIn('donor_socket_button = QPushButton("Open Source Socket XML")', source)
        self.assertIn('visual_group = QGroupBox("Simple Placement")', source)
        self.assertIn("Current Placement State", source)
        self.assertIn('source_copy_button = QPushButton("Choose 1H/2H Source Weapon...")', source)
        self.assertIn("New Placement State", source)
        self.assertIn("Swap type", source)
        self.assertIn('swap_type_combo.addItem("Placement only (hip/back)", "placement_only")', source)
        self.assertIn('swap_type_combo.addItem("Full 1H/2H behavior (experimental)", "full_behavior")', source)
        self.assertIn("Target visuals", source)
        self.assertIn("WeaponBehaviorSwapAnalysis", source)
        self.assertIn("Target Context", source)
        self.assertIn("Target Context Source", source)
        self.assertIn("simple_ready_status", source)
        self.assertIn("Pick a 1H/2H source weapon or manual body location to build.", source)
        self.assertIn("visual_plan_section.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)", source)
        self.assertIn("left_scroll_layout.addStretch(1)", source)
        self.assertIn("No buildable placement patch yet", source)
        self.assertIn("def _descriptor_socket_pair", source)
        self.assertIn("descriptor_socket, descriptor_child, _descriptor_part = _descriptor_socket_pair", source)
        self.assertIn("Target slot metadata (.pac_xml)", source)
        self.assertIn("StackEquipDataContainer _equipType", source)
        self.assertIn("Patch target .pac_xml slot metadata", source)
        self.assertIn("Target prefab placement + role metadata", source)

    def test_hkx_editor_placement_workflow_is_disabled_wip(self) -> None:
        source = ARCHIVE_HKX_EDITOR_DIALOG.read_text(encoding="utf-8")
        start = source.index("placement_page = QWidget()")
        end = source.index("hkx_preview_panel = QWidget()", start)
        placement_source = source[start:end]

        self.assertIn('"Disabled - WIP. Prefab/socket placement workflow is paused here', placement_source)
        self.assertIn('placement_swap_title = QLabel("Placement Swap (Disabled - WIP)")', placement_source)
        self.assertIn('placement_swap_copy_button = QPushButton("Choose Placement Source (Disabled - WIP)")', placement_source)
        self.assertIn("placement_swap_copy_button.setEnabled(False)", placement_source)
        self.assertIn('placement_tab_index = tab_widget.addTab(placement_page, "Placement (Disabled - WIP)")', placement_source)
        self.assertIn("tab_widget.setTabEnabled(placement_tab_index, False)", placement_source)
        self.assertIn("placement_page.setEnabled(False)", placement_source)
        self.assertIn("Choose Placement Source is disabled - WIP.", placement_source)
        self.assertNotIn("placement_swap_copy_button.clicked.connect", placement_source)

        nav_start = source.index("for section_index in range(tab_widget.count()):")
        nav_end = source.index("syncing_tree = {\"active\": False}", nav_start)
        nav_source = source[nav_start:nav_end]
        self.assertIn("section_index == placement_tab_index", nav_source)
        self.assertIn("combo_item.setEnabled(False)", nav_source)
        self.assertIn("~Qt.ItemFlag.ItemIsEnabled", nav_source)
        self.assertIn("Placement view is disabled - WIP.", source)

    def test_weapon_placement_studio_ui_and_guardrails_are_present(self) -> None:
        source = "\n".join(
            (
                MAIN_WINDOW.read_text(encoding="utf-8"),
                ARCHIVE_WEAPON_PLACEMENT_STUDIO.read_text(encoding="utf-8"),
                ARCHIVE_ACTIONS.read_text(encoding="utf-8"),
                ARCHIVE_ATTACHMENT_BATCH.read_text(encoding="utf-8"),
                ARCHIVE_ASSET_FAMILY_DIALOG.read_text(encoding="utf-8"),
            )
        )
        self.assertIn('weapon_placement_studio_action = menu.addAction(menu_icons["workflow"], "Weapon Placement Studio (Disabled - WIP)")', source)
        self.assertIn('placement_button = QPushButton("Weapon Placement Studio (Disabled - WIP)")', source)
        self.assertIn("placement_button.setEnabled(False)", source)
        self.assertIn("weapon_placement_studio_action.setEnabled(False)", source)
        self.assertNotIn("weapon_placement_studio_action.triggered.connect", source)
        self.assertNotIn('"Weapon Swap Studio..."', source)
        self.assertNotIn('"Open Placement Workspace..."', source)

        start = source.index("    def _open_archive_weapon_placement_studio_dialog(")
        end = source.index("__all__", start)
        studio_source = source[start:end]
        placement_map_source = ARCHIVE_WEAPON_PLACEMENT_MAP.read_text(encoding="utf-8")

        self.assertIn("Weapon Placement Studio is disabled - WIP.", studio_source)
        self.assertIn("return", studio_source)
        self.assertLessEqual(len(studio_source.splitlines()), 8)
        self.assertNotIn('dialog.setWindowTitle("Weapon Placement Studio")', studio_source)
        self.assertNotIn("self._deactivate_archive_model_renderers_for_non_model_preview()", studio_source)
        self.assertNotIn("Build Placement Package", studio_source)
        self.assertNotIn("Native PAC view is disabled by default for Weapon Placement Studio", studio_source)
        self.assertNotIn("CDMW_ENABLE_WEAPON_STUDIO_NATIVE_D3D11", studio_source)
        self.assertNotIn("from cdmw.core.weapon_swap_templates import (", source)
        self.assertIn("Weapon Placement Batch", source)
        self.assertIn("class WeaponPlacementStudioPlacementMap(QFrame)", placement_map_source)
        self.assertIn("self._show_shield = False", placement_map_source)
        self.assertIn("Human skeleton schematic: bones and sockets, not a blob/body proxy.", placement_map_source)
        self.assertIn("draw_socket_anchor(\"Spine2\"", placement_map_source)
        self.assertIn("draw_label(\"human skeleton back\"", placement_map_source)

    def test_weapon_placement_ctf_smoke_script_is_present(self) -> None:
        source = Path("tools/weapon_placement_studio_ctf_smoke.py").read_text(encoding="utf-8")
        self.assertIn("cd_phm_02_sword_0015.pac", source)
        self.assertIn("CDMW_CTF_ROOT", source)
        self.assertIn('Path.home() / "Desktop" / "CTF"', source)
        self.assertIn("build_archive_preview_result", source)
        self.assertIn("ballish_bounds", source)
        self.assertIn("decode timing threshold", source)

    def test_mod_generation_ui_uses_target_manager_checklists(self) -> None:
        app_window_source = MAIN_WINDOW.read_text(encoding="utf-8")
        safe_placement_dialog_source = ARCHIVE_ATTACHMENT_SAFE_PLACEMENT_DIALOG.read_text(encoding="utf-8")
        visual_dialog_source = ARCHIVE_ATTACHMENT_VISUAL_DIALOG.read_text(encoding="utf-8")
        source = "\n".join(
            (
                app_window_source,
                ARCHIVE_ATTACHMENT_BATCH.read_text(encoding="utf-8"),
                ARCHIVE_ATTACHMENT_DONOR_PICKER_DIALOG.read_text(encoding="utf-8"),
                ARCHIVE_ATTACHMENT_PLACEMENT_DIFF_DIALOG.read_text(encoding="utf-8"),
                safe_placement_dialog_source,
                ARCHIVE_ATTACHMENT_VISUAL_CONTEXT.read_text(encoding="utf-8"),
                ARCHIVE_ATTACHMENT_VISUAL_CORE.read_text(encoding="utf-8"),
                visual_dialog_source,
                ARCHIVE_ATTACHMENT_VISUAL_GEOMETRY.read_text(encoding="utf-8"),
                ARCHIVE_ATTACHMENT_VISUAL_PREVIEW.read_text(encoding="utf-8"),
                ARCHIVE_MOD_READY_EXPORT.read_text(encoding="utf-8"),
                TEXTURE_WORKFLOW_UPSCALE_BACKEND_PANEL.read_text(encoding="utf-8"),
            )
        )
        replace_source = Path("cdmw/ui/replace_assistant_tab.py").read_text(encoding="utf-8")

        self.assertIn("mod_package_export_options_for_profiles", source)
        self.assertIn('QLabel("Target Mod Managers")', source)
        self.assertIn('QLabel("Package output")', source)
        self.assertIn("Choose target mod managers. The app will write the right folders and metadata", source)
        self.assertNotIn("Universal / minimal metadata", source)
        self.assertNotIn("Universal / minimal metadata", replace_source)
        self.assertNotIn("Universal / game-relative", source)
        self.assertIn("Definitive Mod Manager", source)
        self.assertIn("JMM JSON", source)
        self.assertIn("CDUMM", source)
        self.assertIn("Crimson Sharp / Crimson Browser", source)
        self.assertIn("Field-JSON v3.1", source)
        self.assertNotIn('form_layout.addWidget(QLabel("Manager profile"), 5, 0)', source)
        self.assertNotIn('form_layout.addWidget(QLabel("Folder structure"), 7, 0)', source)
        self.assertNotIn('form_layout.addWidget(QLabel("Generate"), 10, 0)', source)

        self.assertIn("mod_package_export_options_for_profiles", replace_source)
        self.assertIn("self.package_profile_checkboxes", replace_source)
        self.assertIn('package_layout.addWidget(QLabel("Target Mod Managers"), 4, 0)', replace_source)
        self.assertNotIn('package_layout.addWidget(QLabel("Manager profile"), 5, 0)', replace_source)
        self.assertNotIn('package_layout.addWidget(QLabel("Structure"), 6, 0)', replace_source)
        self.assertNotIn('package_layout.addWidget(QLabel("Generate"), 7, 0)', replace_source)
        self.assertIn("Full behavior blocked", source)
        self.assertIn("source role/socket metadata would resize target prefab", source)
        self.assertIn("Advanced: class-wide descriptor fallback", source)
        self.assertIn("normal build targets only this weapon prefab/metadata", source)
        self.assertIn("Class stowed placement descriptor", source)
        self.assertIn("character/phm_description_player_kliff.xml", source)
        self.assertIn("character/phm_01.pab.sockets.xml", source)
        self.assertIn("placement_descriptor_alias", source)
        self.assertIn("placement_socket_alias", source)
        self.assertIn("Blocked donor file row outside explicit advanced mode", source)
        self.assertNotIn('QGroupBox("Target Files")', source)
        self.assertIn('advanced_features_toggle = QCheckBox("Enable Advanced Features")', source)
        self.assertIn("advanced_features_widget.setVisible(False)", source)
        self.assertIn("advanced_features_toggle.toggled.connect", source)
        self.assertIn("def _effective_package_plan_rows", source)
        self.assertIn("if not _advanced_features_enabled():", source)
        self.assertIn("effective_package_plan_rows = _effective_package_plan_rows()", source)
        self.assertIn("advanced_features_layout.addWidget(package_details_section)", source)
        self.assertIn('class_wide_section = CollapsibleSection("Advanced: Class-Wide Tools", expanded=False)', source)
        self.assertIn("Affects all PHM 2H swords", source)
        self.assertIn("package_details_section.body_layout.addWidget(use_source_icon_checkbox)", source)
        self.assertNotIn("Preview Placement...", source)
        self.assertIn("Import Placement Profile XML", source)
        self.assertIn("ArchiveAttachmentSafePlacementDialogMixin", app_window_source)
        self.assertNotIn("def _open_archive_attachment_safe_placement_dialog", app_window_source)
        self.assertIn("class ArchiveAttachmentSafePlacementDialogMixin", safe_placement_dialog_source)
        self.assertIn("def _open_archive_attachment_safe_placement_dialog", safe_placement_dialog_source)
        self.assertIn("D3D11-only placement editor", source)
        self.assertIn("return self._open_archive_attachment_safe_placement_dialog(", source)
        self.assertIn("placement_d3d11_available", source)
        self.assertIn("Native D3D11 Required", source)
        self.assertIn("No fallback preview renderer is available.", source)
        self.assertIn("NativeD3D11PreviewHostFrame", source)
        self.assertIn('preview_style_combo.addItem("Socket schematic (recommended)", "schematic")', source)
        self.assertIn('preview_style_combo.addItem("Decoded mesh overlay (diagnostic)", "mesh")', source)
        self.assertIn("def _build_attachment_placement_schematic_preview_model", source)
        self.assertIn("Socket schematic uses stable weapon proxies", source)
        self.assertIn("if _placement_preview_style() == \"schematic\":", source)
        self.assertIn("target_evidence=target_evidence", source)
        self.assertIn("editable_source_id = 9001", source)
        self.assertIn('placement_d3d11_host.set_display_mode("overlay")', source)
        self.assertIn('display_mode="overlay"', source)
        self.assertIn('editor_workspace="placement_visual"', source)
        self.assertIn("placement_d3d11_host.alignment_drag_finished.connect", source)
        self.assertIn("preview_style_combo.currentIndexChanged.connect", source)
        self.assertNotIn("software " + "socket map", source)
        self.assertNotIn("software_" + "map_button", source)
        self.assertIn("Build Placement Package", source)
        preview_worker_source = (REPO_ROOT / "cdmw" / "workers" / "preview_workers.py").read_text(encoding="utf-8")
        self.assertIn("class VisualPlacementPreviewWorker(QObject)", preview_worker_source)
        self.assertNotIn("Loading placement preview", visual_dialog_source)
        self.assertIn("texconv_text_snapshot = self.texconv_path_edit.text().strip()", source)
        self.assertNotIn("Placement body context resolved, lazy preview disabled for startup stability", visual_dialog_source)
        self.assertNotIn("Building placement body context model:", visual_dialog_source)
        self.assertIn("body_vertex_budget = 80_000", source)
        self.assertIn("max_vertices=model_vertex_budget", source)
        self.assertIn("sample_step = max(2", source)
        self.assertIn("return 0.10", source)
        self.assertIn("target_uses_raw_space = False", source)
        self.assertIn("donor_uses_raw_space = False", source)
        self.assertIn("model_scale=0.24", source)
        self.assertIn('mesh.preview_role = "replacement_preview" if show_candidate', source)
        self.assertIn("mesh.source_submesh_index = int(mesh_index)", source)
        self.assertIn("decoded PAC bounds cannot turn placement preview into a blob", source)
        self.assertIn("Large target model was triangle-sampled", source)
        self.assertIn("Large candidate model was triangle-sampled", source)
        self.assertNotIn("Large target model was shown as bounds", source)
        self.assertNotIn("Large candidate model was shown as bounds", source)
        self.assertNotIn("return [bounds_mesh]", source)
        self.assertNotIn("simplified bounds", source)
        self.assertNotIn('controls_layout.addWidget(QLabel("Body context"))', visual_dialog_source)
        self.assertNotIn('body_context_combo.addItem("Auto body model", "auto")', visual_dialog_source)
        self.assertNotIn('body_context_combo.addItem("Skeleton only", "skeleton")', visual_dialog_source)
        self.assertNotIn('body_context_combo.addItem("Proxy fallback", "proxy")', visual_dialog_source)
        self.assertNotIn("preview_widget.set_prepared_model", visual_dialog_source)
        self.assertNotIn("refresh_timer.timeout.connect(_start_preview_refresh)", visual_dialog_source)
        self.assertIn("force_visual_proxy_anchor", source)
        self.assertIn("def _attachment_visual_body_context_model_entry", source)
        self.assertIn("cd_phm_00_nude_10_0001.pac", source)
        self.assertIn("cd_phw_00_nude_00_0001.pac", source)
        self.assertIn('evidence_section = QGroupBox("Target / Source Evidence")', source)
        self.assertIn('visual_plan_section = QGroupBox("Move Weapon On Body")', source)
        self.assertIn("main_splitter = QSplitter(Qt.Horizontal)", source)
        self.assertIn("dialog.setWindowFlags(", source)
        self.assertIn("Qt.WindowMaximizeButtonHint", source)
        self.assertIn("dialog.setSizeGripEnabled(True)", source)
        self.assertIn("main_splitter.setChildrenCollapsible(False)", source)
        self.assertIn("left_scroll = QScrollArea(dialog)", source)
        self.assertIn("right_scroll = QScrollArea(dialog)", source)
        self.assertIn("left_scroll.setWidgetResizable(True)", source)
        self.assertIn("right_scroll.setWidgetResizable(True)", source)
        self.assertIn("advanced_features_layout.addWidget(advanced_evidence_section)", source)
        self.assertNotIn("layout.addWidget(advanced_evidence_section, 1)", source)
        self.assertIn("def _apply_placement_dialog_responsive_layout", source)
        self.assertIn("main_splitter.setOrientation(Qt.Vertical)", source)
        placement_diff_source = ARCHIVE_ATTACHMENT_PLACEMENT_DIFF_DIALOG.read_text(encoding="utf-8")
        placement_diff_start = placement_diff_source.index("def _open_archive_attachment_placement_diff_dialog")
        placement_diff_body = placement_diff_source[
            placement_diff_start : placement_diff_source.index("__all__", placement_diff_start)
        ]
        self.assertNotIn("dialog.setMaximumSize(max_width, max_height)", placement_diff_body)
        self.assertIn("def _fit_placement_dialog_to_screen", source)
        self.assertIn("available = screen.availableGeometry()", source)
        self.assertIn("QTimer.singleShot(0, _fit_placement_dialog_to_screen)", source)
        self.assertIn("def _fit_picker_to_screen", source)
        self.assertIn("placement_source_splitter.setCollapsible(0, False)", source)
        self.assertIn("section_splitter = QSplitter(Qt.Vertical)", source)
        self.assertIn("main_splitter.setSizes([520, 760])", source)
        self.assertIn("section_splitter.setChildrenCollapsible(False)", source)
        self.assertIn("section_splitter.setSizes([360, 360])", source)
        self.assertIn("section_splitter.setStretchFactor(0, 1)", source)
        self.assertIn("section_splitter.setStretchFactor(1, 1)", source)
        self.assertIn("Patch PartInOut placement XML", source)
        self.assertIn("Patch character socket XML", source)
        self.assertIn('iteminfo_entry = _placement_entry_by_virtual_path("gamedata/binary__/client/bin/iteminfo.pabgb"', source)
        self.assertIn('equiptype_entry = _placement_entry_by_virtual_path("gamedata/binary__/client/bin/equiptypeinfo.pabgb"', source)
        self.assertIn("def _visual_iteminfo_behavior_patch", source)
        self.assertIn("build_iteminfo_behavior_equip_type_patch", source)
        self.assertIn("build_prefab_attachment_profile_patch", source)
        self.assertIn("Full behavior needs a source prefab CD_* part role.", source)
        self.assertIn("Build Universal 2H Swords As 1H", source)
        self.assertIn("Build Universal 2H Swords As True 1H", source)
        self.assertNotIn("close_row.addWidget(universal_twohand_button)", source)
        self.assertIn("def _build_universal_twohand_sword_package", source)
        self.assertIn("include_true_onehand_iteminfo", source)
        self.assertIn("build_universal_twohand_sword_true_onehand_iteminfo_patch", source)
        self.assertIn("def _placement_original_entry_by_virtual_path", source)
        self.assertIn('actionchart/bin__/upperaction/1_pc/1_phm/twohandsword_upper.paac', source)
        self.assertIn('actionchart/bin__/upperaction/1_pc/1_phm/longsword_upper.paac', source)
        self.assertIn('actionchart/bin__/upperaction/1_pc/1_phm/basic_upper_weaponin.paac', source)
        self.assertIn("build_universal_twohand_sword_animation_alias_plan", source)
        self.assertIn("def _read_original_archive_bytes", source)
        self.assertIn("No actionchart .paac graph copy", source)
        self.assertNotIn("twohandsword_upper.paac receives sword_upper.paac payload", source)
        self.assertIn("No ItemInfo table export", source)
        self.assertIn("9-byte one-hand sword-family and _itemType patch", source)
        self.assertIn("Combat/guard PAA aliases are skipped by default", source)
        self.assertIn("True 1H/offhand export is disabled", source)
        self.assertIn("WeaponCasePart is left unchanged", source)
        self.assertIn("Include 2H sword hip placement XML", source)
        self.assertIn("ItemInfo behavior", source)
        self.assertIn("Patch ItemInfo behavior", source)
        self.assertIn("Include unchanged ItemInfo header companion", source)
        self.assertIn("build_part_in_out_socket_profile_patch", source)
        self.assertIn("build_socket_bone_data_profile_patch", source)
        self.assertIn("def _placement_part_in_out_patch_blocking_reason", source)
        self.assertIn("def _placement_behavior_patch_blocking_reason", source)
        self.assertIn("patched_part_names", source)
        self.assertIn("patch_scope_blocked", source)
        self.assertIn("build_ready = bool(effective_package_plan_rows or visual_rows) and not bool(patch_scope_blocked or behavior_blocked)", source)
        self.assertIn("Placement patch touches unrelated descriptor rows", source)
        self.assertIn("Build Placement Package", source)
        self.assertIn("Target that changes", source)
        self.assertIn("Placement source", source)
        icon_source = ARCHIVE_ATTACHMENT_ICONS.read_text(encoding="utf-8")
        loose_source = ARCHIVE_ATTACHMENT_LOOSE_FILES.read_text(encoding="utf-8")
        package_source = ARCHIVE_ATTACHMENT_PACKAGE.read_text(encoding="utf-8")
        plan_source = ARCHIVE_ATTACHMENT_PLAN.read_text(encoding="utf-8")
        source_mix_source = ARCHIVE_SOURCE_MIX_ACTIONS.read_text(encoding="utf-8")
        source_mix_overlay_source = ARCHIVE_SOURCE_MIX_OVERLAY.read_text(encoding="utf-8")
        combined_source = (
            source
            + "\n"
            + icon_source
            + "\n"
            + loose_source
            + "\n"
            + package_source
            + "\n"
            + plan_source
            + "\n"
            + source_mix_source
            + "\n"
            + source_mix_overlay_source
        )

        self.assertIn("def _build_attachment_donor_package_plan", plan_source)
        self.assertIn("def _attachment_package_loose_target_specs", loose_source)
        self.assertIn("def _attachment_package_target_support_entries", package_source)
        self.assertIn("def _attachment_package_item_icon_entries", icon_source)
        self.assertIn("def _attachment_package_source_icon_override_rows", icon_source)
        self.assertIn("def _attachment_package_target_prefab_entries_for_donor", package_source)
        self.assertIn("Target uses side-specific prefab variants", plan_source)
        self.assertIn("Covers target side-specific prefab", combined_source)
        self.assertIn("Copy source prefab bytes", plan_source)
        self.assertIn("Include source socket XML dependency", plan_source)
        self.assertIn("Copy source item icon bytes", plan_source)
        self.assertIn("Use placement source icon", source)
        self.assertIn("Target-only mode", source)
        self.assertIn("Preserve target PAC/model bytes", combined_source)
        self.assertIn("Preserve target material sidecar bytes", combined_source)
        self.assertIn("Preserve target item icon bytes", combined_source)
        self.assertIn("Preserve target prefab bytes", combined_source)
        self.assertIn("Preserve target PAA/motion bytes", combined_source)
        self.assertIn("Preserve target socket context XML", combined_source)
        self.assertIn("Preserve target HKX/HKT physics bytes", combined_source)
        self.assertIn("Modded target files preserved", source)
        self.assertIn("Vanilla target files stay in game. Package writes placement metadata only.", source)
        self.assertIn("Cross weapon-class placement source detected", plan_source)
        self.assertIn("Source HKX/physics not copied by default.", combined_source)
        self.assertIn("Copy source HKX/HKT physics bytes", plan_source)
        self.assertIn("Copy source PAA/motion bytes", plan_source)
        self.assertIn("No original archives will be modified.", source)
        self.assertIn("Legacy raw prefab copy (risky)", source)
        self.assertIn("Legacy raw prefab copy for batch (risky)", source)
        self.assertIn("legacy_raw_prefab_copy=experimental_model_checkbox.isChecked()", source)
        self.assertNotIn("legacy_raw_prefab_copy=True,", source)
        self.assertNotIn("proven same-length prefab socket-name rewrites", visual_dialog_source)
        self.assertIn("build_prefab_socket_name_patch", source)
        self.assertIn("def _open_archive_loose_mod_overlay_dialog", source_mix_overlay_source)
        self.assertIn("Loose Mod Overlay Review", source_mix_overlay_source)
        self.assertIn("Select Exact Family", source_mix_overlay_source)
        self.assertIn("Select All Families", source_mix_overlay_source)
        self.assertIn("Select All Exact Matches", source_mix_overlay_source)
        self.assertIn("Use as Mesh Replacement Source", source_mix_overlay_source)
        self.assertIn("group_source_mix_candidates_by_family(candidates)", source_mix_overlay_source)
        self.assertIn("def _resolve_source_mix_candidate_targets", source_mix_source)
        self.assertIn("self.archive_entries_by_normalized_path.get(normalized", source_mix_source)
        self.assertIn("self.archive_entries_by_basename.get(candidate_name", source_mix_source)
        self.assertIn("candidates = scan_loose_folder_source(scan_root)", source_mix_overlay_source)
        self.assertIn("candidates = self._resolve_source_mix_candidate_targets(candidates)", source_mix_overlay_source)

        loose_roots_start = loose_source.index("def _attachment_package_loose_target_roots_for_entry")
        loose_roots_body = loose_source[
            loose_roots_start : loose_source.index("def _attachment_package_loose_target_specs", loose_roots_start)
        ]
        self.assertIn("_attachment_package_output_loose_roots()", loose_roots_body)
        self.assertIn("_attachment_package_raw_extract_root()", loose_roots_body)
        self.assertNotIn("_collect_archive_preview_loose_roots()", loose_roots_body)
        self.assertNotIn("archive_extract_root_edit", loose_roots_body)

        loose_specs_start = loose_source.index("def _attachment_package_loose_target_specs")
        loose_specs_body = loose_source[loose_specs_start:]
        for token in (".prefab", ".hkx", ".hkt", ".paa", ".paa_metabin", ".motionblending", ".sockets.xml"):
            self.assertIn(token, loose_specs_body)
        self.assertNotIn("donor_entry", loose_specs_body)
        self.assertNotIn("donor_graph", loose_specs_body)
        self.assertNotIn("Copy source", loose_specs_body)

    def test_relation_selection_covers_asset_map_uses_and_used_by(self) -> None:
        source = (
            MAIN_WINDOW.read_text(encoding="utf-8")
            + "\n"
            + SIGNAL_WIRING.read_text(encoding="utf-8")
            + "\n"
            + ARCHIVE_ASSET_FAMILY_REFERENCES.read_text(encoding="utf-8")
            + "\n"
            + ARCHIVE_REFERENCE_PREVIEW.read_text(encoding="utf-8")
        )

        self.assertIn("def _archive_reference_from_item(", source)
        self.assertIn('if source == "uses"', source)
        self.assertIn('if source == "used_by"', source)
        self.assertIn('if source == "family"', source)
        self.assertIn("self.current_archive_used_by_references", source)
        self.assertIn("self.current_archive_family_member_rows", source)
        self.assertIn("relation_tree.customContextMenuRequested.connect", source)
        self.assertIn("sender = self.sender()", source)
        self.assertIn("tree = sender if isinstance(sender, QTreeWidget) else self.archive_texture_refs_tree", source)

    def test_dds_asset_family_promotes_used_by_materials_and_models(self) -> None:
        source = (
            MAIN_WINDOW.read_text(encoding="utf-8")
            + "\n"
            + ARCHIVE_ASSET_FAMILY_DIALOG.read_text(encoding="utf-8")
            + "\n"
            + ARCHIVE_ASSET_FAMILY_REFERENCES.read_text(encoding="utf-8")
            + "\n"
            + ARCHIVE_ASSET_FAMILY_PANEL.read_text(encoding="utf-8")
        )

        self.assertIn("texture_sidecars: List[ArchiveEntry] = []", source)
        self.assertIn("texture_stem_candidates: List[str] = []", source)
        self.assertIn("def add_texture_sidecar(candidate: ArchiveEntry, *, reason: str, confidence: str) -> None:", source)
        self.assertIn("def add_material_sidecar_candidates_for_stem(stem: str) -> None:", source)
        self.assertIn("def add_model_candidates_for_stem(stem: str, *, reason: str, confidence: str) -> None:", source)
        self.assertIn("Material sidecar references this exact texture path.", source)
        self.assertIn("Material sidecar shares the selected texture stem", source)
        self.assertIn("Model shares the selected texture stem in the current archive index", source)
        self.assertIn("Model candidate shares the basename with a material sidecar that references this texture", source)
        self.assertIn('if isinstance(current_entry, ArchiveEntry) and str(current_entry.extension or "").lower() == ".dds":', source)
        self.assertIn("family_references.extend(self.current_archive_used_by_references)", source)
        self.assertIn("asset_family_graph_for_view = build_archive_asset_family_graph(current_entry, tuple(family_references))", source)
        self.assertIn("raw_table_references = list(self.current_archive_model_texture_references)", source)
        self.assertIn('raw_table_sources.extend(("used_by", index) for index in range(len(self.current_archive_used_by_references)))', source)
        self.assertIn('if str(entry.extension or "").lower() == ".dds":', source)
        self.assertIn("combined_references.extend(self._archive_known_used_by_references(entry))", source)

    def test_asset_family_splitter_width_is_stable_across_preview_refresh(self) -> None:
        source = (
            MAIN_WINDOW.read_text(encoding="utf-8")
            + "\n"
            + SHELL_WINDOW_RUNTIME_STATE.read_text(encoding="utf-8")
            + "\n"
            + ARCHIVE_ASSET_FAMILY_LAYOUT.read_text(encoding="utf-8")
            + "\n"
            + ARCHIVE_ASSET_FAMILY_PANEL.read_text(encoding="utf-8")
        )

        self.assertIn("self.archive_asset_family_preferred_width = 420", source)
        self.assertIn("Preserve the user's Asset Family splitter width while loading or when a file", source)
        self.assertIn('getattr(self, "archive_asset_family_preferred_width", 420)', source)
        self.assertIn('not getattr(self, "_archive_preview_splitter_clamping", False)', source)
        self.assertIn("self.archive_asset_family_preferred_width = sizes[1]", source)
        self.assertIn("def _refresh_archive_asset_family_panel_layout(self, *, prefer_default: bool = False) -> None:", source)
        self.assertIn("def _schedule_archive_asset_family_panel_layout(self, *, prefer_default: bool = False) -> None:", source)
        self.assertIn("self._schedule_archive_asset_family_panel_layout(prefer_default=True)", source)
        self.assertIn("Keep Asset Family visible even in compact or freshly reflowed layouts.", source)
        self.assertIn("target_sizes = [preview_width, max(1, refs_width)]", source)
        self.assertNotIn("target_sizes = [total, 0]", source)

    def test_asset_family_trees_do_not_auto_scroll_horizontally_from_wheel(self) -> None:
        source = MAIN_WINDOW.read_text(encoding="utf-8") + "\n" + ARCHIVE_ASSET_FAMILY_LAYOUT.read_text(encoding="utf-8")
        responsiveness_source = (REPO_ROOT / "cdmw" / "ui" / "shell" / "responsiveness_controller.py").read_text(encoding="utf-8")

        self.assertIn("class TreeHorizontalWheelGuard(QObject):", responsiveness_source)
        self.assertIn("event.type() != QEvent.Type.Wheel", responsiveness_source)
        self.assertIn("has_horizontal_delta", responsiveness_source)
        self.assertIn("modifiers & Qt.ShiftModifier", responsiveness_source)
        self.assertIn("horizontal_bar.setValue(max(horizontal_bar.minimum(), min(previous_value, horizontal_bar.maximum())))", responsiveness_source)
        self.assertIn("def _install_tree_horizontal_wheel_guard(self, tree: QTreeWidget) -> None:", source)
        self.assertIn('tree.setProperty("cdmw_disable_auto_column_fill", True)', source)
        self.assertIn("tree.viewport().installEventFilter(guard)", source)
        self.assertIn("self._tree_horizontal_wheel_guards.append(guard)", source)
        self.assertIn("self._install_tree_horizontal_wheel_guard(self.archive_texture_refs_tree)", source)
        self.assertIn("self._install_tree_horizontal_wheel_guard(tree)", source)
        self.assertIn("horizontal_scroll_positions = [", source)

    def test_scope_banner_is_visible_for_direct_asset_scopes(self) -> None:
        source = (
            MAIN_WINDOW.read_text(encoding="utf-8")
            + "\n"
            + ARCHIVE_FILES_PANEL.read_text(encoding="utf-8")
            + "\n"
            + ARCHIVE_FILTER_CONTROLS.read_text(encoding="utf-8")
        )

        self.assertIn("self.archive_scope_banner_label = QLabel", source)
        self.assertIn("Scope active: {scope_text}. Clear Scope returns to normal archive filtering.", source)
        self.assertIn("self.archive_scope_banner_label.setVisible(True)", source)
        self.assertIn("self.archive_scope_banner_label.setVisible(False)", source)


if __name__ == "__main__":
    unittest.main()
