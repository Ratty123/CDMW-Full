import json
import tempfile
import unittest
from pathlib import Path
from types import MethodType, SimpleNamespace

from cdmw.ui.model_library_tab import (
    ModelLibraryTab,
    _external_audit_material_inventory_rows,
    _external_audit_texture_slot_text,
    model_library_texture_status_kind,
)


class ModelLibraryUiSourceGuardTests(unittest.TestCase):
    def test_model_library_texture_status_classification_is_explicit(self) -> None:
        for status in ("Found (3)", "In ZIP (2)", "Resolved (4)"):
            self.assertEqual(model_library_texture_status_kind(status), "present")

        self.assertEqual(model_library_texture_status_kind("None found"), "missing")

        for status in ("Unknown", "Download to check", "Embedded/Unknown", "In ZIP", ""):
            self.assertEqual(model_library_texture_status_kind(status), "unknown")

    def test_external_audit_inventory_keeps_texture_file_facts_for_details(self) -> None:
        audit = SimpleNamespace(
            material_inventory=(
                SimpleNamespace(
                    material_name="HeroArmor",
                    submesh_names=("body",),
                    pbr_workflow="metallic_roughness",
                    alpha_mode="opaque",
                    double_sided=False,
                    vertex_color_factor=(),
                    vertex_alpha=(),
                    material_classes=(),
                    warnings=(),
                    texture_slots=(
                        SimpleNamespace(
                            slot_kind="material",
                            parameter_name="_metallicRoughnessTexture",
                            texture_name="Hero_MRA.png",
                            texture_path="textures/Hero_MRA.png",
                            image_format="png",
                            resolution=(2048, 1024),
                            semantic_type="material",
                            semantic_subtype="metallic_roughness",
                            packed_channels=("roughness", "metallic"),
                            color_space="linear",
                            source="gltf",
                            confidence="high",
                            evidence=("image facts",),
                            channel_stats=(),
                        ),
                    ),
                ),
            ),
        )

        rows = _external_audit_material_inventory_rows(audit)

        slot_row = rows[0]["texture_slot_rows"][0]
        self.assertEqual(slot_row["slot_kind"], "material")
        self.assertEqual(slot_row["image_format"], "png")
        self.assertEqual(slot_row["resolution"], (2048, 1024))
        self.assertEqual(slot_row["color_space"], "linear")
        self.assertEqual(slot_row["semantic_subtype"], "metallic_roughness")
        self.assertEqual(slot_row["packed_channels"], ("roughness", "metallic"))
        self.assertEqual(
            _external_audit_texture_slot_text(slot_row),
            "material Hero_MRA.png png 2048x1024 linear metallic_roughness channels=roughness/metallic",
        )

    def test_model_library_details_show_texture_slot_facts(self) -> None:
        source = (
            Path("cdmw/ui/model_library/tab.py").read_text(encoding="utf-8")
            + "\n"
            + Path("cdmw/ui/model_library/selection.py").read_text(encoding="utf-8")
        )
        state_source = Path("cdmw/ui/model_library/state.py").read_text(encoding="utf-8")

        self.assertIn('"texture_slot_rows": texture_slot_rows', state_source)
        self.assertIn('texture_slot_rows = tuple(item for item in tuple(row.get("texture_slot_rows", ()) or ())', source)
        self.assertIn("_external_audit_texture_slot_text(item)", source)
        self.assertIn("Texture files: {texture_file_text}", source)

    def test_local_download_rows_group_by_metadata_even_when_catalogue_root_differs(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            asset_dir = root / "ExternalCatalogue" / "downloads" / "Escanor-Axe-Rhitta-1234567890abcdef1234567890abcdef"
            scene_dir = asset_dir / "gltf"
            scene_dir.mkdir(parents=True)
            (asset_dir / "model_metadata.json").write_text(json.dumps({"name": "Escanor Axe Rhitta"}), encoding="utf-8")
            archive_path = asset_dir / "1234567890abcdef1234567890abcdef.zip"
            archive_path.write_bytes(b"zip")
            scene_path = scene_dir / "scene.gltf"
            scene_path.write_text("{}", encoding="utf-8")

            tab = SimpleNamespace(_texture_status_cache={})
            tab.catalogue_dir = lambda: root / "ConfiguredElsewhere"
            tab._texture_status_for_payload = lambda _payload: ""
            for method_name in (
                "_download_output_root",
                "_normalize_local_model_rows",
                "_metadata_path_for_local_row",
                "_download_metadata_path_for_local_path",
                "_nearest_local_model_metadata_path",
                "_read_download_metadata",
                "_metadata_path_from_group",
                "_display_root_for_metadata_group",
                "_download_group_local_row",
                "_find_importable_file_under",
                "_preferred_download_archive_path",
            ):
                setattr(tab, method_name, MethodType(getattr(ModelLibraryTab, method_name), tab))
            rows = [
                {
                    "kind": "local",
                    "name": "Escanor Axe Rhitta",
                    "path": str(archive_path),
                    "root": str(root),
                    "relative_path": str(archive_path.relative_to(root)),
                    "extension": ".zip",
                    "size": archive_path.stat().st_size,
                    "modified_at": archive_path.stat().st_mtime,
                    "import_supported": True,
                    "source": "Local model library",
                },
                {
                    "kind": "local",
                    "name": "Escanor Axe Rhitta",
                    "path": str(scene_path),
                    "root": str(root),
                    "relative_path": str(scene_path.relative_to(root)),
                    "extension": ".gltf",
                    "size": scene_path.stat().st_size,
                    "modified_at": scene_path.stat().st_mtime,
                    "import_supported": True,
                    "source": "Local model library",
                },
            ]

            normalized = tab._normalize_local_model_rows(rows)

        self.assertEqual(len(normalized), 1)
        self.assertEqual(normalized[0]["name"], "Escanor Axe Rhitta")
        self.assertEqual(normalized[0]["source"], "Downloaded")
        self.assertEqual(normalized[0]["archive_path"], str(archive_path))
        self.assertEqual(normalized[0]["import_path"], str(scene_path))

    def test_main_window_registers_model_library_import_signal(self) -> None:
        source = (
            Path("cdmw/ui/shell/app_window.py").read_text(encoding="utf-8")
            + "\n"
            + Path("cdmw/ui/shell/tool_tabs.py").read_text(encoding="utf-8")
            + "\n"
            + Path("cdmw/ui/shell/model_library_bridge.py").read_text(encoding="utf-8")
            + "\n"
            + Path("cdmw/ui/archive_browser/preview_d3d11_process.py").read_text(encoding="utf-8")
        )

        self.assertIn("from cdmw.ui.model_library import ModelLibraryTab", source)
        self.assertIn("self.model_library_tab = ModelLibraryTab", source)
        self.assertIn("import_mesh_requested.connect", source)
        self.assertIn("preview_mesh_requested.connect", source)
        self.assertIn("item_icon_source_generated.connect", source)
        self.assertIn("self._import_local_model_to_current_archive", source)
        self.assertIn("self._preview_model_library_mesh", source)
        self.assertIn("self._handle_model_library_item_icon_generated", source)
        self.assertIn("QMessageBox.information(self, \"Import Mesh\", message)", source)
        self.assertIn("_show_archive_d3d11_hard_failure", source)
        self.assertIn("def task(_log: Callable[[str], None]) -> object:", source)
        self.assertIn('"model_library"', source)
        self.assertIn("def _augment_model_library_scene_import_result", source)
        self.assertIn("def _discover_model_library_supplemental_files", source)
        self.assertIn("self._model_library_texture_search_roots(scene_path, metadata)", source)
        self.assertIn("Model Library companion scan added", source)
        self.assertIn("scene_import_result=scene_import_result", source)
        self.assertIn("Warning: No local texture files were found for this Model Library item.", source)
        self.assertNotIn("SketchfabLibraryTab", source)
        self.assertNotIn("Connect Sketchfab", source)

    def test_mesh_import_setup_warns_when_textures_are_absent_or_unchecked(self) -> None:
        source = Path("cdmw/ui/archive_browser/mesh_import_export.py").read_text(encoding="utf-8")

        self.assertIn('QLabel#WarningLabel', source)
        self.assertIn('supplemental_warning_label.setObjectName("WarningLabel")', source)
        self.assertIn("def _refresh_supplemental_warning() -> None:", source)
        self.assertIn("No local texture files were found for this source.", source)
        self.assertIn("Texture files are available, but none are checked.", source)
        self.assertIn("supplemental_list.itemChanged.connect(lambda _item: _refresh_supplemental_warning())", source)
        self.assertIn("_refresh_supplemental_warning()", source)

    def test_inline_d3d11_status_timer_ignores_deleted_qt_object(self) -> None:
        source = (
            Path("cdmw/ui/model_library/tab.py").read_text(encoding="utf-8")
            + "\n"
            + Path("cdmw/ui/model_library/preview.py").read_text(encoding="utf-8")
        )

        self.assertIn("def _start_inline_d3d11_status_timer(self) -> None:", source)
        self.assertIn("def _stop_inline_d3d11_status_timer(self) -> None:", source)
        self.assertIn("except RuntimeError:\n            pass", source)
        self.assertIn("self._start_inline_d3d11_status_timer()", source)
        self.assertIn("self._stop_inline_d3d11_status_timer()", source)
        self.assertNotIn("self._inline_d3d11_status_timer.stop()\n        if process is None:", source)

    def test_model_library_tab_scans_searches_and_shows_manual_file_urls(self) -> None:
        source = (
            Path("cdmw/ui/model_library/tab.py").read_text(encoding="utf-8")
            + "\n"
            + Path("cdmw/ui/model_library/actions.py").read_text(encoding="utf-8")
            + "\n"
            + Path("cdmw/ui/model_library/catalogue.py").read_text(encoding="utf-8")
            + "\n"
            + Path("cdmw/ui/model_library/commands.py").read_text(encoding="utf-8")
            + "\n"
            + Path("cdmw/ui/model_library/controller.py").read_text(encoding="utf-8")
            + "\n"
            + Path("cdmw/ui/model_library/local_rows.py").read_text(encoding="utf-8")
            + "\n"
            + Path("cdmw/ui/model_library/panels.py").read_text(encoding="utf-8")
            + "\n"
            + Path("cdmw/ui/model_library/preview.py").read_text(encoding="utf-8")
            + "\n"
            + Path("cdmw/ui/model_library/selection.py").read_text(encoding="utf-8")
            + "\n"
            + Path("cdmw/ui/model_library/settings.py").read_text(encoding="utf-8")
            + "\n"
            + Path("cdmw/ui/model_library/tasks.py").read_text(encoding="utf-8")
            + "\n"
            + Path("cdmw/ui/model_library/texture_status.py").read_text(encoding="utf-8")
            + "\n"
            + Path("cdmw/ui/model_library/view_state.py").read_text(encoding="utf-8")
        )

        self.assertIn("scan_local_model_files", source)
        self.assertIn("build_mirror_catalogue_index", source)
        self.assertIn("search_catalogue_records", source)
        self.assertIn("Mirror URL", source)
        self.assertIn("Preferred files", source)
        self.assertIn("preferred_format_checks", source)
        self.assertIn("glTF ZIP", source)
        self.assertIn("Original source ZIP (OBJ/FBX/etc.)", source)
        self.assertIn("_selected_preferred_formats", source)
        self.assertIn("_download_candidates_for_selected_formats", source)
        self.assertIn("Exclude creators", source)
        self.assertIn("creator_exclude_edit", source)
        self.assertIn("creator_excludes=creator_excludes", source)
        self.assertIn("Textures", source)
        self.assertIn("result_limit_spin.setRange(1, 5000)", source)
        self.assertIn("QProgressBar", source)
        self.assertIn("task_status_label", source)
        self.assertIn("active_task_label", source)
        self.assertIn("active_task_progress", source)
        self.assertIn("worker.progress.connect(self._handle_task_progress)", source)
        self.assertIn("def _handle_task_progress(self, message: str) -> None:", source)
        self.assertNotIn("worker.progress.connect(lambda", source)
        self.assertIn("def _update_active_task_progress", source)
        self.assertIn("empty_results_label", source)
        self.assertIn("setColumnCount(10)", source)
        self.assertIn("results_tree.setSortingEnabled(False)", source)
        self.assertIn("setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)", source)
        self.assertIn("setHorizontalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)", source)
        self.assertIn("QHeaderView.ResizeMode.Interactive", source)
        self.assertIn("resizeSection(1, 260)", source)
        self.assertNotIn("setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)", source)
        self.assertIn("sectionClicked.connect(", source)
        self.assertIn("_handle_results_header_clicked", source)
        self.assertIn("def _sort_result_rows", source)
        self.assertIn("def _result_size_bytes", source)
        self.assertIn("def _use_result_source_order", source)
        self.assertIn("self._use_result_source_order()", source)
        self.assertIn("self._result_sort_column", source)
        self.assertIn("Qt.SortOrder.DescendingOrder if column == 6", source)
        self.assertIn("item = QTreeWidgetItem(", source)
        self.assertIn("def _mirror_size_bytes", source)
        self.assertNotIn("class _ModelLibraryResultItem", source)
        self.assertNotIn("setSortingEnabled(True)", source)
        self.assertIn("Hide downloaded", source)
        self.assertIn("model_library/hide_downloaded", source)
        self.assertIn("_handle_hide_downloaded_toggled", source)
        self.assertIn("_filtered_result_rows", source)
        self.assertIn("_mirror_payload_downloaded", source)
        self.assertIn("Build Search Index", source)
        self.assertIn("Build index from current search/filter only", source)
        self.assertIn("model_library/index_current_search", source)
        self.assertIn("index_query=index_query", source)
        self.assertIn("clear_existing=index_current_search", source)
        self.assertIn("Scoped to", source)
        self.assertIn("Mirror Catalogue", source)
        self.assertIn("Local Library", source)
        self.assertIn('QGroupBox("Mirror Index Source")', source)
        self.assertIn("self.mirror_group.setVisible(self._active_results_view == \"mirror\")", source)
        self.assertIn("results_search_label = QLabel(\"Mirror search\")", source)
        self.assertIn("results_filter_field_combo = QComboBox()", source)
        self.assertIn("results_filter_field_combo.addItem(\"Creator\", \"creator\")", source)
        self.assertIn("results_filter_field_combo.addItem(\"Path / URL\", \"path\")", source)
        self.assertIn("apply_results_query_button = QPushButton(\"Search\")", source)
        self.assertIn("clear_results_query_button = QPushButton(\"Clear\")", source)
        self.assertIn("def _apply_active_results_query", source)
        self.assertIn("def _clear_active_results_query", source)
        self.assertIn("def _local_payload_matches_filter", source)
        self.assertIn("model_library/local_search_query", source)
        self.assertIn("model_library/local_search_field", source)
        self.assertIn("local_texture_filter_combo", source)
        self.assertIn('addItem("Has textures", "has")', source)
        self.assertIn('addItem("No textures found", "missing")', source)
        self.assertIn("model_library/local_texture_filter", source)
        self.assertIn("MODEL_LIBRARY_FILTER_COLUMNS", source)
        self.assertIn("results_column_filter_edits", source)
        self.assertIn("_save_column_filters_for_active_view", source)
        self.assertIn("_load_column_filters_for_active_view", source)
        self.assertIn("model_library/local_column_filters_json", source)
        self.assertIn("model_library/mirror_column_filters_json", source)
        self.assertIn("_filter_result_rows_by_columns", source)
        self.assertIn("_payload_matches_column_filters", source)
        self.assertIn("Show Local Models", source)
        self.assertIn("Search Mirror", source)
        self.assertIn("Popular", source)
        self.assertIn("Refresh", source)
        self.assertIn("QButtonGroup", source)
        self.assertIn("QScrollArea", source)
        self.assertIn("_set_active_results_view", source)
        self.assertIn("QTimer.singleShot(0, self.search_mirror)", source)
        self.assertIn("self.catalogue_db_path().is_file()", source)
        self.assertIn("refresh_active_results_view", source)
        self.assertIn("download_mirror_model_candidate", source)
        self.assertIn("Download Checked", source)
        self.assertIn("Downloading...", source)
        self.assertIn("Downloaded {index:,} / {total:,}", source)
        self.assertIn("Downloaded {len(successes):,} file(s)", source)
        self.assertIn("Select at least one preferred file type", source)
        self.assertIn("Download + Import", source)
        self.assertIn("More Actions", source)
        self.assertIn("Delete Local", source)
        self.assertIn("Delete No-Texture Downloads", source)
        self.assertIn("delete_no_texture_downloads", source)
        self.assertIn("_visible_no_texture_download_payloads", source)
        self.assertIn("_no_texture_download_delete_target_for_payload", source)
        self.assertIn("_downloaded_model_folder_target_for_payload", source)
        self.assertIn("_confirm_delete_no_texture_download_targets", source)
        self.assertIn("return self._downloaded_model_folder_target_for_payload(payload)", source)
        self.assertIn("Standalone local model files are never included", source)
        self.assertIn("Delete Local Copy", source)
        self.assertIn("_local_delete_payloads", source)
        self.assertIn("_local_delete_target_for_payload", source)
        self.assertIn("_confirm_delete_local_targets", source)
        self.assertIn("QMessageBox", source)
        self.assertIn("shutil.rmtree", source)
        self.assertIn('QGroupBox("Actions")', source)
        self.assertIn('QGroupBox("Selection")', source)
        self.assertIn('QGroupBox("Model Preview")', source)
        self.assertIn('QPushButton("Preview")', source)
        self.assertIn('QCheckBox("Auto preview local selection")', source)
        self.assertIn("Automatically previews local selections in the Model Library preview panel", source)
        self.assertIn("D3D11 Preview", source)
        self.assertIn("Preview In Archive Browser", source)
        self.assertNotIn("Import Local Model", source)
        self.assertIn("Generate Icon", source)
        self.assertIn("Generate Icon From Preview", source)
        self.assertIn("item_icon_source_generated", source)
        self.assertNotIn("grabFramebuffer", source)
        self.assertIn("generated_icons", source)
        self.assertIn("_model_preview_icon_image", source)
        self.assertIn("NativePreviewPanel", source)
        self.assertNotIn("WebGlPbrPreviewHostFrame", source)
        self.assertNotIn("WEBGL_PBR_RENDERER_BACKEND", source)
        self.assertNotIn("webgl_pbr", source)
        self.assertIn("def _inline_preview_renderer_backend", source)
        self.assertIn('return "native_d3d11"', source)
        self.assertNotIn("inline_green_up", source)
        self.assertIn("self.inline_preview_stack", source)
        self.assertIn('inline_render_settings.visible_texture_mode = "sidecar_visible_first"', source)
        self.assertIn('inline_render_settings.render_diagnostic_mode = "base_direct"', source)
        self.assertIn("inline_render_settings.disable_all_support_maps = True", source)
        self.assertIn("inline_render_settings.low_quality_texture_max_dimension = 1024", source)
        self.assertIn("inline_preview_widget.set_render_settings(inline_render_settings)", source)
        self.assertIn("inline_preview_widget.set_use_textures(True)", source)
        self.assertIn("inline_preview_widget.set_high_quality_textures(True)", source)
        self.assertIn('QCheckBox("Flip V")', source)
        self.assertIn('QPushButton("Reset")', source)
        self.assertIn("inline_preview_flip_v_checkbox.toggled.connect(", source)
        self.assertIn("_handle_inline_preview_flip_v_toggled", source)
        self.assertIn("def _handle_inline_preview_flip_v_toggled", source)
        self.assertIn("settings.flip_texture_v = bool(checked)", source)
        self.assertIn("def _reload_inline_preview_for_orientation", source)
        self.assertIn("reset_orientation=False", source)
        self.assertIn('== "native_d3d11"', source)
        self.assertIn("self._inline_preview_loaded_texture_count", source)
        self.assertIn("preview_render_settings = self.inline_preview_widget.render_settings()", source)
        self.assertIn("render_settings=preview_render_settings", source)
        self.assertIn("prepare_model_library_inline_preview(", source)
        self.assertIn("prepare_model_library_inline_preview_in_subprocess", source)
        self.assertIn("high_quality_textures=False", source)
        self.assertIn("stop_event=stop_event", source)
        self.assertIn("_pending_inline_preview_request = (Path(source_path), dict(payload), bool(reset_orientation))", source)
        self.assertIn("def _after_model_library_task_finished", source)
        self.assertIn("_inline_d3d11_diagnostic_paths", source)
        self.assertIn("_check_inline_d3d11_start_timeout", source)
        self.assertIn("_cleanup_inline_d3d11_packages", source)
        self.assertNotIn("write_isolated_d3d11_preview_package", source)
        self.assertNotIn("def _inline_preview_material_channel_summary", source)
        self.assertIn("channels: {material_channel_summary}", source)
        self.assertNotIn("import_scene_mesh_with_report", source)
        self.assertNotIn("parsed_mesh_to_preview_model", source)
        self.assertNotIn("_attach_inline_preview_textures", source)
        self.assertIn("_texture_status_for_payload", source)
        self.assertIn("_count_zip_texture_members", source)
        self.assertIn("Download to check", source)
        self.assertIn("Embedded/Unknown", source)
        self.assertIn("None found", source)
        self.assertIn("All {hidden:,} mirror result(s) are hidden", source)
        self.assertIn("SCENE_TEXTURE_SOURCE_EXTENSIONS", source)
        self.assertIn("Show File URLs", source)
        self.assertIn("Open File URL", source)
        self.assertIn("Select All", source)
        self.assertIn("Select None", source)
        self.assertIn("QMenu", source)
        self.assertIn("customContextMenuRequested", source)
        self.assertIn("Qt.CheckState.Checked", source)
        self.assertIn("_checked_payloads", source)
        self.assertIn("_batch_action_payloads", source)
        self.assertIn("Local", source)
        self.assertIn("_ensure_download_root_registered", source)
        self.assertIn("resolve_importable_model_path", source)
        self.assertIn("zip_contains_importable_model", source)
        self.assertIn("_normalize_local_model_rows", source)
        self.assertIn("_download_group_local_row", source)
        self.assertIn('"source": "Downloaded"', source)
        self.assertIn("require_importable = import_after or preview_after", source)
        self.assertIn("mirror_url_ready", source)
        self.assertIn("Preview", source)
        self.assertIn("status_label.setVisible(False)", source)
        self.assertNotIn("Open Catalogue", source)
        self.assertNotIn("preferred_format_combo", source)

    def test_model_library_keeps_preview_to_the_right_without_root_three_pane_overlap(self) -> None:
        source = Path("cdmw/ui/model_library/tab.py").read_text(encoding="utf-8")

        self.assertIn("splitter = QSplitter(Qt.Orientation.Horizontal)", source)
        self.assertIn("content_splitter = QSplitter(Qt.Orientation.Horizontal)", source)
        self.assertIn("splitter.addWidget(controls_panel)", source)
        self.assertIn("splitter.addWidget(content_splitter)", source)
        self.assertIn("content_splitter.addWidget(results_panel)", source)
        self.assertIn("content_splitter.addWidget(preview_panel)", source)
        self.assertIn("preview_panel.setMinimumWidth(280)", source)
        self.assertNotIn("right_splitter = QSplitter(Qt.Orientation.Vertical)", source)
        self.assertNotIn("\n        splitter.addWidget(results_panel)\n", source)
        self.assertNotIn("\n        splitter.addWidget(preview_panel)\n", source)
        self.assertNotIn("\n        splitter.setStretchFactor(2", source)

    def test_model_library_auto_preview_uses_inline_preview_here(self) -> None:
        source = (
            Path("cdmw/ui/model_library/tab.py").read_text(encoding="utf-8")
            + "\n"
            + Path("cdmw/ui/model_library/controller.py").read_text(encoding="utf-8")
            + "\n"
            + Path("cdmw/ui/model_library/panels.py").read_text(encoding="utf-8")
            + "\n"
            + Path("cdmw/ui/model_library/view_state.py").read_text(encoding="utf-8")
        )

        self.assertIn("self._auto_preview_timer.timeout.connect(self._preview_current_model_if_auto_enabled)", source)
        self.assertIn("self._schedule_auto_inline_preview()", source)
        self.assertNotIn("_activation_preview_timer", source)
        self.assertNotIn("_schedule_auto_archive_preview", source)
        self.assertNotIn("_preview_current_model_in_archive_if_auto_enabled", source)
        self.assertNotIn("_payload_can_auto_archive_preview", source)
        self.assertNotIn("_cancel_inline_preview_for_archive_auto_preview", source)

        schedule_start = source.index("    def _schedule_auto_inline_preview")
        schedule_body = source[schedule_start: source.index("    def handle_activated", schedule_start)]
        self.assertIn("_payload_can_preview_here(payload)", schedule_body)
        self.assertNotIn("_payload_can_import(payload)", schedule_body)

        activated_start = source.index("    def handle_activated")
        activated_body = source[activated_start: source.index("    def _preview_current_model_if_auto_enabled", activated_start)]
        self.assertIn("self._auto_preview_timer.stop()", activated_body)
        self.assertNotIn("_schedule_auto_inline_preview", activated_body)
        self.assertNotIn("preview_selected_model_here", activated_body)

        finish_start = source.index("    def _finish_results_population")
        finish_body = source[finish_start: source.index("    def _flush_results_population_batch", finish_start)]
        self.assertNotIn("_schedule_auto_inline_preview()", finish_body)

        auto_start = source.index("    def _preview_current_model_if_auto_enabled")
        auto_body = source[auto_start: source.index("    def _set_active_results_view", auto_start)]
        self.assertIn("self.preview_selected_model_here()", auto_body)
        self.assertNotIn("self.preview_selected_model()", auto_body)
        self.assertNotIn("_load_inline_model_preview", auto_body)
        self.assertNotIn("_preview_model_library_mesh", auto_body)

    def test_model_library_manual_inline_preview_resolves_zip_off_ui_thread(self) -> None:
        source = (
            Path("cdmw/ui/model_library/tab.py").read_text(encoding="utf-8")
            + "\n"
            + Path("cdmw/ui/model_library/preview.py").read_text(encoding="utf-8")
        )

        preview_start = source.index("    def preview_selected_model_here")
        preview_body = source[preview_start: source.index("    def _inline_preview_renderer_backend", preview_start)]
        self.assertIn("_inline_preview_source_path_for_payload(payload)", preview_body)
        self.assertNotIn("_resolve_payload_import_path", preview_body)
        self.assertNotIn("resolve_importable_model_path", preview_body)

        load_start = source.index("    def _load_inline_model_preview")
        task_start = source.index("        def task(", load_start)
        task_body = source[task_start: source.index("        def complete(", task_start)]
        self.assertIn("extract_root = self._inline_preview_extract_root_for_source(source_path, payload)", task_body)
        self.assertIn('if renderer_backend == "native_d3d11":', task_body)
        self.assertIn("prepare_model_library_inline_preview_in_subprocess(", task_body)
        self.assertIn("return prepare_model_library_inline_preview(", task_body)
        self.assertIn("high_quality_textures=False", task_body)
        self.assertIn("stop_event=stop_event", task_body)
        self.assertNotIn("resolve_importable_model_path(", task_body)
        self.assertNotIn("import_scene_mesh_with_report(", task_body)
        self.assertNotIn("write_isolated_d3d11_preview_package(", task_body)

        complete_start = source.index("        def complete(", load_start)
        complete_body = source[complete_start: source.index("        def handle_error(", complete_start)]
        self.assertIn("self.inline_preview_widget.set_prepared_model(preview_model, prepared_preview)", complete_body)
        self.assertIn('renderer_note = " | renderer: Qt preview"', complete_body)
        self.assertIn('self._set_inline_preview_status("Qt preview data was not built."', complete_body)
        self.assertNotIn("Native D3D11 preview package was not built", complete_body)
        self.assertIn("payload[\"import_path\"] = str(resolved_import_path)", complete_body)
        self.assertIn("self._refresh_result_row_status(payload)", complete_body)
        self.assertNotIn("self._refresh_result_row_statuses()", complete_body)

        cancel_body = source[load_start:task_start]
        self.assertIn("_pending_inline_preview_request = (Path(source_path), dict(payload), bool(reset_orientation))", cancel_body)
        self.assertIn("self._stop_event.set()", cancel_body)

        finish_start = source.index("    def _after_model_library_task_finished")
        finish_body = source[finish_start: source.index("    def generate_icon_from_preview", finish_start)]
        self.assertIn("pending = self._pending_inline_preview_request", finish_body)
        self.assertIn("QTimer.singleShot(", finish_body)
        self.assertIn("self._load_inline_model_preview(", finish_body)

        tasks_source = Path("cdmw/ui/model_library/tasks.py").read_text(encoding="utf-8")
        self.assertIn('hook = getattr(self, "_after_model_library_task_finished", None)', tasks_source)
        self.assertIn("if callable(hook):", tasks_source)
        self.assertIn("hook()", tasks_source)

    def test_inline_d3d11_host_is_shown_before_hwnd_capture(self) -> None:
        source = Path("cdmw/ui/model_library/preview.py").read_text(encoding="utf-8")
        start = source.index("    def _start_inline_d3d11_process")
        body = source[start: source.index("    def _handle_inline_d3d11_stderr", start)]

        command_index = body.index("native_d3d11_renderer_command(")
        self.assertLess(
            body.index(
                "self.inline_preview_stack.setCurrentWidget(self.inline_d3d11_preview_host)",
                body.index("self._stop_inline_d3d11_process(cleanup_packages=True)"),
            ),
            command_index,
        )
        self.assertLess(body.index("self.inline_d3d11_preview_host.show()"), command_index)
        self.assertIn("crash_dir, diagnostic_log = self._inline_d3d11_diagnostic_paths()", body)
        self.assertIn("crash_dir=crash_dir", body)
        self.assertIn("diagnostic_log=diagnostic_log", body)
        self.assertIn("_check_inline_d3d11_start_timeout", body)
        self.assertIn("cleanup_packages=True", body)
        self.assertIn("QTimer.singleShot(0, process.start)", body)
        self.assertIn("QTimer.singleShot(7000", source)

    def test_d3d11_command_reads_diagnostic_env_defaults(self) -> None:
        source = Path("cdmw/ui/native_d3d11_preview_host.py").read_text(encoding="utf-8")
        start = source.index("def native_d3d11_renderer_command")
        body = source[start: source.index("__all__", start)]

        self.assertIn('os.environ.get("CDMW_CRASH_DIR"', body)
        self.assertIn('os.environ.get("CDMW_NATIVE_DIAGNOSTIC_LOG"', body)
        self.assertIn('arguments.extend(["--crash-dir", str(crash_dir)])', body)
        self.assertIn('arguments.extend(["--diagnostic-log", str(diagnostic_log)])', body)


if __name__ == "__main__":
    unittest.main()
