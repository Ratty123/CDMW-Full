from __future__ import annotations

from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


def _read(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def _mesh_edit_source() -> str:
    return "\n".join(
        (
            _read("cdmw/ui/shell/app_window.py"),
            _read("cdmw/ui/archive_browser/static_replacement_dialog.py"),
            _read("cdmw/ui/archive_browser/static_replacement_dialog_prompt.py"),
            _read("cdmw/ui/archive_browser/static_replacement_dialog_prompt_shell.py"),
            _read("cdmw/ui/archive_browser/static_replacement_dialog_prompt_open.py"),
            _read("cdmw/ui/archive_browser/static_replacement_dialog_prompt_setup.py"),
            _read("cdmw/ui/archive_browser/static_replacement_dialog_prompt_state_callbacks.py"),
            _read("cdmw/ui/archive_browser/static_replacement_dialog_prompt_transform.py"),
            _read("cdmw/ui/archive_browser/static_replacement_dialog_prompt_deps.py"),
            _read("cdmw/ui/archive_browser/static_replacement_dialog_prompt_deps_base.py"),
            _read("cdmw/ui/archive_browser/static_replacement_dialog_prompt_deps_state_a.py"),
            _read("cdmw/ui/archive_browser/static_replacement_dialog_prompt_deps_state_b.py"),
            _read("cdmw/ui/archive_browser/static_replacement_dialog_prompt_deps_callbacks.py"),
            _read("cdmw/ui/archive_browser/static_replacement_dialog_preview_shell.py"),
            _read("cdmw/ui/archive_browser/static_replacement_dialog_workflow_shell.py"),
            _read("cdmw/ui/archive_browser/static_replacement_dialog_ui_sections.py"),
            _read("cdmw/ui/archive_browser/static_replacement_dialog_callback_factories.py"),
            _read("cdmw/ui/archive_browser/static_replacement_dialog_mesh_edit_callbacks.py"),
            _read("cdmw/ui/archive_browser/static_replacement_dialog_remaining_callbacks.py"),
            _read("cdmw/ui/archive_browser/static_replacement_combo_options.py"),
            _read("cdmw/ui/archive_browser/static_replacement_d3d11_state.py"),
            _read("cdmw/ui/archive_browser/static_replacement_d3d11_status_state.py"),
            _read("cdmw/ui/archive_browser/static_replacement_d3d11_presentation_state.py"),
            _read("cdmw/ui/archive_browser/static_replacement_d3d11_runtime_state.py"),
            _read("cdmw/ui/archive_browser/static_replacement_d3d11_watchdog_state.py"),
            _read("cdmw/ui/archive_browser/static_replacement_diagnostics.py"),
        )
    )


class MeshEditResponsivenessSourceGuardTests(unittest.TestCase):
    def test_mesh_edit_control_changes_sync_state_without_preview_reload(self) -> None:
        source = _mesh_edit_source()

        self.assertIn(
            "_populate_combo_options_helper(mesh_edit_selection_depth_combo, MESH_EDIT_SELECTION_DEPTH_OPTIONS)",
            source,
        )
        self.assertIn("MESH_EDIT_SELECTION_DEPTH_OPTIONS", source)
        self.assertIn('("Visible Only", "visible")', source)
        self.assertIn('("X-Ray", "xray")', source)
        self.assertIn("_mesh_edit_preview_source_indices = lambda", source)
        self.assertIn("_mesh_edit_replace_live_triangles(_mesh_edit_preview_source_indices())", source)
        self.assertIn("_mesh_edit_preview_source_indices()", source)
        self.assertIn("def _mesh_edit_enabled_toggled(_checked: bool = False) -> None:", source)
        self.assertIn("_mesh_edit_apply_preview_mode_transition(\"mesh_edit_toggle\")", source)
        self.assertIn("mesh_edit_enabled_checkbox.toggled.connect(_mesh_edit_enabled_toggled)", source)
        self.assertNotIn(
            "mesh_edit_enabled_checkbox.toggled.connect(lambda _checked=False: (_refresh_mesh_edit_controls(), _queue_static_preview_refresh()))",
            source,
        )

        sync_only_lines = (
            "mesh_edit_scope_combo.currentIndexChanged.connect(lambda _index: _refresh_mesh_edit_controls())",
            "mesh_edit_part_combo.currentIndexChanged.connect(lambda _index: _refresh_mesh_edit_controls())",
            "mesh_edit_tool_combo.currentIndexChanged.connect(lambda _index: _refresh_mesh_edit_controls())",
            "mesh_edit_falloff_combo.currentIndexChanged.connect(lambda _index: _refresh_mesh_edit_controls())",
            "mesh_edit_selection_mode_combo.currentIndexChanged.connect(lambda _index: _refresh_mesh_edit_controls())",
            "mesh_edit_selection_depth_combo.currentIndexChanged.connect(lambda _index: _refresh_mesh_edit_controls())",
            "mesh_edit_radius_spin.valueChanged.connect(lambda _value: _refresh_mesh_edit_controls())",
            "mesh_edit_strength_spin.valueChanged.connect(lambda _value: _refresh_mesh_edit_controls())",
        )
        for line in sync_only_lines:
            self.assertIn(line, source)

        self.assertNotIn(
            "mesh_edit_tool_combo.currentIndexChanged.connect(lambda _index: (_refresh_mesh_edit_controls(), _queue_static_preview_refresh()))",
            source,
        )
        self.assertNotIn(
            "mesh_edit_selection_mode_combo.currentIndexChanged.connect(lambda _index: (_refresh_mesh_edit_controls(), _queue_static_preview_refresh()))",
            source,
        )
        self.assertNotIn(
            "mesh_edit_radius_spin.valueChanged.connect(lambda _value: (_refresh_mesh_edit_controls(), _queue_static_preview_refresh()))",
            source,
        )

    def test_live_vertex_update_bridge_is_wired(self) -> None:
        main_source = _mesh_edit_source()
        bridge_source = _read("cdmw/ui/native_d3d11_preview_host.py")
        payload_source = _read("cdmw/ui/archive_browser/static_replacement_mesh_edit_payload.py")

        for source in (bridge_source,):
            self.assertIn('"command": "update_mesh_edit_vertices"', source)
            self.assertIn('"command": "replace_mesh_edit_triangles"', source)
            self.assertIn('selection_depth_mode: str = "visible"', source)
            self.assertIn('"selection_depth_mode": str(selection_depth_mode or "visible")', source)
            self.assertIn('"smooth_iterations": int(smooth_iterations or 3)', source)
        self.assertIn("def _mesh_edit_live_vertex_update_groups(", main_source)
        self.assertIn("mesh_edit_live_update_timer.setInterval(16)", main_source)
        self.assertIn("if include_normals and len(normals) == len(vertices):", payload_source)
        self.assertIn("alignment_d3d11_preview_host.update_mesh_edit_vertices(groups)", main_source)
        self.assertIn("alignment_d3d11_preview_host.replace_mesh_edit_triangles(groups)", main_source)
        self.assertIn("_mesh_edit_update_live_preview(changed_vertices_by_submesh)", main_source)
        self.assertIn("_MESH_EDIT_TRIANGLE_FILE_THRESHOLD = 512 * 1024", bridge_source)
        self.assertIn('"command": "replace_mesh_edit_triangles_file"', bridge_source)
        self.assertIn('"payload_file": str(temp_path)', bridge_source)

    def test_native_visible_selection_depth_and_double_click_guards_exist(self) -> None:
        source = _read("native/cdmw_d3d11_preview/src/main.cpp")

        self.assertIn('std::string selection_depth_mode = "visible";', source)
        self.assertIn('std::string selection_operation = "replace";', source)
        self.assertIn("struct MeshEditDepthMaskCache", source)
        self.assertIn("mesh_edit_depth_mask_for_view", source)
        self.assertIn("mesh_edit_screen_vertex_visible_in_depth_mask", source)
        self.assertIn('command == "update_mesh_edit_vertices"', source)
        self.assertIn('command == "replace_mesh_edit_triangles"', source)
        self.assertIn("update_mesh_edit_vertices_from_payload", source)
        self.assertIn("replace_mesh_edit_triangles_from_payload", source)
        self.assertIn("const bool xray_mode = !mesh_edit_depth_filter_enabled();", source)
        self.assertIn("draw_colored_triangles(vertices, identity, xray_mode);", source)
        self.assertIn("draw_colored_triangles(screen_overlay_vertices, identity, true);", source)
        self.assertIn("draw_mesh_edit_vertex_dots_instanced(view, *dot_vertices, brush_vertices, xray_mode);", source)
        self.assertIn("context_->OMSetDepthStencilState(no_depth && overlay_depth_state_", source)
        self.assertIn("cpu_source_vertex_lookup", source)
        self.assertIn("rebuild_batch_source_vertex_lookup", source)
        self.assertIn("mesh_edit_preview_event_due", source)
        self.assertIn("UpdateSubresource(\n                        batch.vertex_buffer.Get(),\n                        0,\n                        &box,", source)
        self.assertIn("return elapsed_ms >= 16.0 || (dx * dx + dy * dy) >= 9;", source)

        dbl_click_start = source.index("case WM_LBUTTONDBLCLK:")
        dbl_click_body = source[dbl_click_start: source.index("case WM_LBUTTONDOWN:", dbl_click_start)]
        self.assertIn("if (mesh_edit_.enabled)", dbl_click_body)
        self.assertIn("return true;", dbl_click_body)

    def test_rectangle_and_lasso_selection_use_visible_depth_filter(self) -> None:
        source = _read("native/cdmw_d3d11_preview/src/main.cpp")

        selection_start = source.index("void finish_mesh_edit_selection_drag")
        selection_body = source[selection_start: source.index("bool begin_mesh_edit_drag", selection_start)]
        self.assertIn("mesh_edit_depth_filter_enabled()", selection_body)
        self.assertEqual(2, selection_body.count("mesh_edit_screen_vertex_visible_in_depth_mask"))

    def test_select_vertices_is_selection_only_and_uses_modifier_combine(self) -> None:
        source = _read("native/cdmw_d3d11_preview/src/main.cpp")

        begin_start = source.index("bool begin_mesh_edit_drag")
        begin_body = source[begin_start: source.index("bool update_mesh_edit_drag", begin_start)]
        vertex_block = begin_body[
            begin_body.index("if (vertex_mode) {"):
            begin_body.index("std::vector<EditorCandidate> candidates")
        ]
        self.assertIn("mesh_edit_.selection_drag_active = true;", vertex_block)
        self.assertIn("mesh_edit_selection_operation_from_modifiers(wparam)", vertex_block)
        self.assertIn("apply_mesh_edit_brush_selection(x, y);", vertex_block)
        self.assertIn("return true;", vertex_block)
        self.assertNotIn("mesh_edit_stroke_started", vertex_block)

        self.assertIn('if (shift_down && ctrl_down) return "toggle";', source)
        self.assertIn('if (ctrl_down) return "subtract";', source)
        self.assertIn('if (shift_down) return "add";', source)

    def test_mesh_edit_selection_ids_and_topology_replacement_are_safe_for_d3d11(self) -> None:
        main_source = _mesh_edit_source()
        payload_source = _read("cdmw/ui/archive_browser/static_replacement_mesh_edit_payload.py")
        native_source = _read("native/cdmw_d3d11_preview/src/main.cpp")
        bridge_source = _read("cdmw/ui/native_d3d11_preview_host.py")

        self.assertIn("source_indices_for_editor_id=_alignment_d3d11_source_indices_for_editor_id", main_source)
        self.assertIn("source_indices_for_editor_id(editor_submesh_index)", payload_source)
        self.assertIn("def _mesh_edit_clear_topology_selection() -> None:", main_source)
        self.assertIn("alignment_d3d11_preview_host.clear_mesh_edit_vertex_selection()", main_source)
        selection_start = main_source.index("def _mesh_edit_selection_changed(payload: object) -> None:")
        selection_body = main_source[selection_start: main_source.index("def _mesh_edit_control_tab_changed", selection_start)]
        self.assertIn("_mesh_edit_vertices_from_payload(payload)", selection_body)
        self.assertIn("_mesh_edit_faces_from_payload(payload)", selection_body)
        self.assertIn("allowed_indices = set(int(index) for index in allowed_source_indices)", payload_source)
        self.assertIn("collection_count = len(", payload_source)
        self.assertIn("if 0 <= index < collection_count:", payload_source)
        self.assertIn('payload_index_key="source_face_indices"', main_source)
        self.assertIn("mesh_edit_selected_faces_by_submesh", selection_body)
        self.assertIn('"indices": indices', payload_source)
        self.assertIn("source_vertex_indices.append(int(vertex_index))", payload_source)
        self.assertIn("delete_faces_by_indices(", main_source)
        self.assertIn("std::vector<EditorCandidate> mesh_edit_face_candidates_at", native_source)
        self.assertIn("std::vector<EditorCandidate> mesh_edit_brush_candidates_at", native_source)
        self.assertIn("source_face_indices", native_source)
        self.assertIn('const std::vector<int> indices = json_int_array_field(group, "indices");', native_source)
        self.assertIn('const bool indexed_payload = group.find("\\"indices\\"") != std::string::npos;', native_source)
        self.assertIn('if (command == "replace_mesh_edit_triangles_file")', native_source)
        self.assertIn("read_text(payload_file)", native_source)
        self.assertIn('filename.rfind(L"cdmw_mesh_edit_triangles_", 0) == 0', native_source)
        self.assertIn('"command": "replace_mesh_edit_triangles_file"', bridge_source)

    def test_mesh_edit_tool_controls_are_capability_scoped(self) -> None:
        source = _mesh_edit_source()
        state_source = _read("cdmw/ui/archive_browser/static_replacement_mesh_edit_state.py")

        self.assertNotIn('("Selection only", "selection")', source)
        self.assertIn("mesh_edit_field_rows: Dict[str, Tuple[QLabel, QWidget]] = {}", source)
        self.assertIn('"select_part": "Select Whole Part"', state_source)
        self.assertIn('"invert_selection": "Invert Selection"', state_source)
        self.assertIn('mesh_edit_select_part_button = QPushButton(mesh_edit_action_control_text["select_part"])', source)
        self.assertIn('mesh_edit_invert_selection_button = QPushButton(mesh_edit_action_control_text["invert_selection"])', source)
        self.assertIn('"selection_actions_visible": bool(select_tool or int(selected_count) > 0)', state_source)
        self.assertIn('_set_mesh_edit_row_visible("radius", sculpt_tool or remove_tool or brush_selection_tool)', source)
        self.assertIn('_set_mesh_edit_row_visible("strength", sculpt_tool)', source)
        self.assertIn('_set_mesh_edit_row_visible("falloff", sculpt_tool)', source)
        self.assertIn('_set_mesh_edit_row_visible("iterations", smooth_tool)', source)
        self.assertIn('"smooth_tool": tool == "smooth"', state_source)
        self.assertIn('_set_mesh_edit_row_visible("selection", select_tool)', source)
        self.assertIn('_set_mesh_edit_row_visible("depth", select_tool)', source)
        self.assertIn("mesh_edit_mirror_checkbox.setVisible(sculpt_tool)", source)
        self.assertIn("mesh_edit_select_part_button.setVisible(select_tool)", source)
        self.assertIn("mesh_edit_invert_selection_button.setVisible(select_tool)", source)
        self.assertIn("mesh_edit_subdivide_selection_button.setVisible(select_tool)", source)
        self.assertIn("mesh_edit_delete_faces_button.setVisible(select_tool)", source)
        self.assertIn("_mesh_edit_all_vertices_in_scope = lambda", source)
        self.assertIn("def _mesh_edit_select_whole_part() -> None:", source)
        self.assertIn("def _mesh_edit_invert_selection() -> None:", source)
        self.assertIn("mesh_edit_select_part_button.clicked.connect", source)
        self.assertIn("mesh_edit_invert_selection_button.clicked.connect", source)

    def test_mesh_edit_sculpt_payloads_map_d3d11_editor_ids_to_source_ids(self) -> None:
        source = _mesh_edit_source()
        payload_source = _read("cdmw/ui/archive_browser/static_replacement_mesh_edit_payload.py")
        apply_start = source.index("def _mesh_edit_apply_preview_payload(payload: object) -> None:")
        apply_body = source[apply_start: source.index("def _mesh_edit_finish_stroke", apply_start)]

        self.assertIn("_mesh_edit_payload_vertex_groups_helper(", apply_body)
        self.assertIn("source_indices_for_editor_id=_alignment_d3d11_source_indices_for_editor_id", apply_body)
        self.assertIn("allowed_source_indices=_mesh_edit_allowed_source_indices()", apply_body)
        self.assertIn("allowed_indices = set(int(index) for index in allowed_source_indices)", payload_source)
        self.assertIn("editor_submesh_index = int(group.get(\"source_submesh_index\", -1))", payload_source)
        self.assertIn("source_indices_for_editor_id(editor_submesh_index)", payload_source)
        self.assertIn("for source_submesh_index in source_indices:", payload_source)
        self.assertIn("if source_submesh_index not in allowed_indices:", payload_source)

    def test_mesh_edit_loading_watchdog_clears_stale_d3d11_state(self) -> None:
        source = _mesh_edit_source()
        presentation_source = _read("cdmw/ui/archive_browser/static_replacement_d3d11_presentation_state.py")
        worker_source = _read("cdmw/workers/d3d11_package_workers.py")
        package_source = "\n".join(
            (
                _read("cdmw/rendering/native_preview_package.py"),
                _read("cdmw/rendering/native_preview_package_writer.py"),
            )
        )
        native_source = _read("native/cdmw_d3d11_preview/src/main.cpp")

        self.assertIn("def _reset_alignment_d3d11_request_state(", source)
        self.assertIn("def _alignment_d3d11_request_active() -> bool:", source)
        self.assertIn('_clear_stuck_alignment_d3d11_loading("loading watchdog")', source)
        self.assertIn("Preview idle.", source)
        self.assertIn("_alignment_d3d11_loading_cleared_performance_helper(", source)
        self.assertIn('"D3D11 preview loading state cleared."', presentation_source)
        self.assertIn("def _set_alignment_d3d11_progress(", source)
        self.assertIn("Preview reload restarted.", source)
        self.assertIn("_alignment_d3d11_restart_performance_helper(", source)
        self.assertIn("D3D11 preview reload restarted", presentation_source)
        self.assertIn('"stale_reload_restart_count": 0', source)
        self.assertIn("def _alignment_d3d11_live_frame_available() -> bool:", source)
        self.assertIn("active=not live_frame_available", source)
        self.assertIn("progress_changed = Signal(int, int, int, str)", worker_source)
        self.assertIn("class _AlignmentD3D11PackageWorkerReceiver(QObject):", source)
        self.assertIn("@Slot(int, int, int, str)", source)
        self.assertIn("@Slot(int, object, float, float)", source)
        self.assertIn("@Slot(int, str)", source)
        self.assertIn("alignment_d3d11_package_worker_receiver.handle_progress", source)
        self.assertIn("alignment_d3d11_package_worker_receiver.handle_completed", source)
        self.assertIn("alignment_d3d11_package_worker_receiver.handle_error", source)
        self.assertIn("Qt.QueuedConnection", source)
        self.assertIn('percent = int(round(float(payload.get("percent", 0) or 0)))', source)
        self.assertIn("on_progress: Optional[Callable[[int, int, str], None]] = None", package_source)
        self.assertIn("on_progress=_emit_package_progress", worker_source)
        self.assertIn('\\"percent\\":85', native_source)
        self.assertIn('\\"percent\\":90', native_source)
        self.assertIn("resources_loaded_payload", native_source)
        self.assertIn('loaded_payload_for_event(stats, "resources_loaded")', native_source)
        self.assertIn('\\"render_suppressed_reason\\"', native_source)
        self.assertIn('\\"parent_renderable\\"', native_source)

    def test_mesh_edit_raw_package_and_live_restore_paths_exist(self) -> None:
        source = _mesh_edit_source()
        worker_source = _read("cdmw/workers/d3d11_package_workers.py")
        d3d11_cache_source = _read("cdmw/ui/archive_browser/static_replacement_d3d11_cache.py")
        d3d11_presentation_source = _read("cdmw/ui/archive_browser/static_replacement_d3d11_presentation_state.py")
        raw_preview_state_source = _read("cdmw/ui/archive_browser/static_replacement_raw_preview_state.py")
        mesh_edit_state_source = _read("cdmw/ui/archive_browser/static_replacement_mesh_edit_state.py")

        self.assertIn("_mesh_edit_raw_preview_active = lambda", source)
        self.assertIn("def mesh_edit_raw_preview_initial_state() -> dict[str, bool]:", raw_preview_state_source)
        self.assertIn(
            "mesh_edit_raw_preview_state = _mesh_edit_raw_preview_initial_state_helper()",
            source,
        )
        self.assertIn(
            "_mesh_edit_raw_preview_record_state_helper(",
            source,
        )
        self.assertIn("def _mesh_edit_apply_preview_mode_transition(reason: str) -> None:", source)
        self.assertIn('"mesh_edit_preview_mode_transition"', source)
        self.assertIn('_alignment_d3d11_invalidate_package_cache("mesh_edit_mode")', source)
        self.assertIn("def alignment_d3d11_raw_package_active_or_pending(state: Mapping[str, object]) -> bool:", source)
        self.assertIn('_alignment_d3d11_raw_package_active_or_pending_helper(alignment_d3d11_state)', source)
        self.assertIn('"request_package_qualities": {},', source)
        self.assertIn('"package_quality": "normal",', source)
        self.assertIn('state["package_quality"] = str(package_quality or "normal")', d3d11_cache_source)
        self.assertIn('state["package_quality"] = "normal"', d3d11_cache_source)
        self.assertIn("_queue_texture_preview_refresh()", source)
        self.assertIn('_mesh_edit_apply_preview_mode_transition("left_mesh_edit_tab")', source)
        self.assertNotIn('return _alignment_d3d11_fast_render_settings(settings), False, False, "fast_geometry"', source)
        self.assertIn('return clamp_model_preview_render_settings(settings), high_quality_textures, enable_material_combiner, "material_refresh"', d3d11_presentation_source)
        self.assertIn('return clamp_model_preview_render_settings(settings), high_quality_textures, enable_material_combiner, "mesh_edit_raw"', d3d11_presentation_source)
        self.assertNotIn("fast_settings.disable_all_support_maps = True", d3d11_presentation_source)
        self.assertNotIn("fast_settings.disable_normal_map = True", d3d11_presentation_source)
        self.assertNotIn("fast_settings.disable_material_map = True", d3d11_presentation_source)
        self.assertNotIn("fast_settings.disable_height_map = True", d3d11_presentation_source)
        self.assertIn("def _mesh_edit_raw_preview_active_value() -> bool:", source)
        self.assertIn("mesh_edit_raw_package = _mesh_edit_raw_preview_active_value()", source)
        self.assertIn('worker_use_textures = bool(getattr(settings, "use_textures_by_default", True))', source)
        self.assertIn("original_reference_material_parity=worker_original_reference_material_parity", source)
        self.assertIn("reuse_prepared_geometry=bool(geometry_signature)", source)
        self.assertIn("def _mesh_by_source_identity", worker_source)
        poll_start = source.index("def _poll_alignment_d3d11_status() -> None:")
        loaded_start = source.index('if event == "loaded":', poll_start)
        loaded_block = source[loaded_start: source.index('elif event == "loading":', loaded_start)]
        self.assertIn("_sync_mesh_edit_preview_settings_if_ready()", loaded_block)
        self.assertIn("enable_material_combiner=bool(self.enable_material_combiner and self.use_textures)", worker_source)
        self.assertIn("def _mesh_edit_full_reset_mesh() -> None:", source)
        self.assertIn('"full_reset_mesh": "Full Reset Mesh"', mesh_edit_state_source)
        self.assertIn('mesh_edit_full_reset_button = QPushButton(mesh_edit_action_control_text["full_reset_mesh"])', source)
        self.assertIn("_mesh_edit_part_enabled_snapshot = lambda", source)
        self.assertIn("def _mesh_edit_restore_enabled_snapshot(snapshot: Mapping[int, bool]) -> None:", source)
        self.assertNotIn("def _mesh_edit_restore_adjustment_snapshot", source)
        self.assertIn("mesh_edit_should_restore_deleted_output(", mesh_edit_state_source)
        self.assertIn("restore_deleted_output = _mesh_edit_should_restore_deleted_output_helper(", source)
        self.assertIn("def _mesh_edit_transformed_sources_for_live_preview(source_indices: Iterable[int])", source)
        self.assertIn("def _mesh_edit_submesh_for_live_preview(source_index: int):", source)
        self.assertIn(
            "alignment_basis_mesh=_mesh_edit_state.replacement_mesh_base_for_mapping or _mesh_edit_state.replacement_mesh_for_mapping",
            source,
        )
        self.assertIn("transformed_sources_by_index = _mesh_edit_transformed_sources_for_live_preview", source)
        self.assertIn("alignment_d3d11_preview_host.clear_mesh_edit_vertex_selection()", source)
        self.assertIn("_mesh_edit_replace_live_triangles(source_indices)", source)

    def test_alignment_mesh_editor_texture_settings_and_view_mode_are_wired(self) -> None:
        source = (
            _mesh_edit_source()
            + "\n"
            + _read("cdmw/ui/archive_browser/preview_settings.py")
            + "\n"
            + _read("cdmw/ui/archive_browser/static_replacement_d3d11_cache.py")
        )

        self.assertIn("dialog.settings_changed.connect(settings_changed_handler)", source)
        self.assertIn("alignment_d3d11_view_mode_combo = QComboBox()", source)
        self.assertIn(
            "_d3d11_view_mode_options_helper(D3D11_PREVIEW_VIEW_MODES, D3D11_PREVIEW_VIEW_MODE_LABELS)",
            source,
        )
        self.assertIn("_populate_combo_options_helper(", source)
        self.assertIn("alignment_d3d11_view_mode_combo,", source)
        self.assertIn("(alignment_d3d11_view_mode_combo, settings.d3d11_view_mode)", source)
        self.assertIn("alignment_d3d11_view_mode_combo.currentIndexChanged.connect(_apply_alignment_preview_render_settings)", source)
        self.assertIn("def _alignment_preview_render_settings_from_controls(", source)
        self.assertIn("settings.d3d11_view_mode = str(", source)
        self.assertIn('package_fields = (', source)
        self.assertIn('"use_textures_by_default"', source)
        self.assertIn('"high_quality_by_default"', source)
        self.assertIn("_alignment_d3d11_invalidate_package_cache(\"material\")", source)
        self.assertIn("_mark_alignment_d3d11_rebuild_reason(\"material\")", source)
        self.assertIn('bool(getattr(settings, "use_textures_by_default", True))', source)
        self.assertIn('bool(getattr(settings, "high_quality_by_default", True))', source)

    def test_mesh_edit_live_preview_uses_frozen_alignment_basis(self) -> None:
        main_source = _mesh_edit_source()
        replacer_source = "\n".join(
            (
                _read("cdmw/modding/static_mesh_replacer.py"),
                _read("cdmw/modding/static_mesh_runtime_builder.py"),
            )
        )

        self.assertIn("alignment_basis_mesh: ParsedMesh | None = None", replacer_source)
        self.assertIn("basis_mesh = alignment_basis_mesh or replacement_mesh", replacer_source)
        self.assertIn("alignment_replacement_mesh = copy.copy(basis_mesh)", replacer_source)
        self.assertIn("alignment_basis_mesh=(", main_source)
        self.assertIn("replacement_mesh_base_for_mapping", main_source)

    def test_mesh_edit_drag_inverts_preview_delta_without_display_space_rewrite(self) -> None:
        source = _mesh_edit_source()
        native_source = _read("native/cdmw_d3d11_preview/src/main.cpp")
        prep_source = _read("cdmw/rendering/model_preview_prepare.py")
        package_source = "\n".join(
            (
                _read("cdmw/rendering/native_preview_package.py"),
                _read("cdmw/rendering/native_preview_package_writer.py"),
            )
        )

        live_start = source.index("def _mesh_edit_update_live_preview(")
        live_body = source[live_start: source.index("def _mesh_edit_begin_stroke", live_start)]
        self.assertIn("_queue_mesh_edit_live_vertex_updates(", live_body)
        self.assertIn("include_normals=include_normals", live_body)
        self.assertIn("immediate=immediate", live_body)
        self.assertIn("_mesh_edit_replace_live_triangles(_mesh_edit_preview_source_indices())", live_body)
        self.assertLess(
            live_body.index("_queue_mesh_edit_live_vertex_updates("),
            live_body.index("_mesh_edit_replace_live_triangles(_mesh_edit_preview_source_indices())"),
        )
        apply_start = source.index("def _mesh_edit_apply_preview_payload(payload: object) -> None:")
        apply_body = source[apply_start: source.index("def _mesh_edit_finish_stroke", apply_start)]
        self.assertIn("def _mesh_edit_preview_delta_to_source_delta(", source)
        self.assertIn("def _mesh_edit_preview_point_to_source_point(", source)
        self.assertIn("def _mesh_edit_preview_distance_to_source_distance(", source)
        self.assertIn("source_delta = _mesh_edit_preview_delta_to_source_delta(source_submesh_index, delta)", apply_body)
        self.assertIn("source_step_delta = _mesh_edit_preview_delta_to_source_delta(source_submesh_index, step_delta)", apply_body)
        self.assertIn("source_center = _mesh_edit_preview_point_to_source_point(source_submesh_index, center)", apply_body)
        self.assertIn("source_radius = _mesh_edit_preview_distance_to_source_distance(source_submesh_index, radius)", apply_body)
        self.assertIn("source_amount = _mesh_edit_preview_distance_to_source_distance(source_submesh_index, amount)", apply_body)
        self.assertIn("changed = apply_vertex_delta(", apply_body)
        self.assertIn("submesh,\n                    vertex_indices,", apply_body)
        self.assertIn("changed = apply_brush_deformation(", apply_body)
        self.assertIn("submesh,\n                    tool=tool,", apply_body)
        self.assertIn("center=source_center", apply_body)
        self.assertIn("radius=source_radius", apply_body)
        self.assertIn("amount=source_amount", apply_body)
        self.assertIn('drag_delta=source_delta if tool in {"grab"} else source_step_delta', apply_body)
        self.assertNotIn("def _mesh_edit_apply_display_space_vertex_result(", source)
        self.assertNotIn("display_submesh = _mesh_edit_submesh_for_live_preview(source_submesh_index)", apply_body)
        self.assertIn("bool alignment_batch_editable(const PreviewBatch& batch) const {", native_source)
        self.assertIn("return !batch_is_reference(batch) && batch.editor_editable;", native_source)
        self.assertIn("if (!alignment_.enabled || view.role == PreviewViewRole::Reference) return;", native_source)
        self.assertIn('reference_role = "reference" in editor_role_key or "original" in editor_role_key', prep_source)
        self.assertIn("editor_editable = bool((mesh_source_submesh_index >= 0 or replacement_role) and not reference_role)", prep_source)
        self.assertIn('"editable": bool(getattr(batch, "editor_editable", source_submesh_index >= 0)) and not reference_role', package_source)
        self.assertIn("batch.editor_editable = false;", native_source)

    def test_native_mesh_edit_json_float_parser_accepts_exponent_numbers(self) -> None:
        source = _read("native/cdmw_d3d11_preview/src/main.cpp")

        self.assertGreaterEqual(source.count(r"(?:[eE][+-]?\\d+)?"), 3)

    def test_modify_original_material_preview_is_not_skipped_during_mesh_edit(self) -> None:
        source = _mesh_edit_source()

        refresh_start = source.index("def _refresh_static_dialog_preview(*, live_mesh_edit: bool = False) -> None:")
        refresh_body = source[refresh_start: source.index("def _safe_refresh_static_dialog_preview", refresh_start)]
        static_preview_state = _read(
            "cdmw/ui/archive_browser/static_replacement_static_preview_state.py"
        )
        self.assertIn("needs_original_material_preview = _original_texture_preview_material_preview_enabled_helper(", refresh_body)
        self.assertIn("refresh_route.require_original_reference", refresh_body)
        self.assertIn("not mesh_edit_direct_source_preview or needs_original_material_preview", static_preview_state)
        self.assertIn("_apply_original_material_preview(", refresh_body)
        self.assertNotIn("if not mesh_edit_direct_source_preview:\n                        _apply_original_material_preview(", refresh_body)

    def test_native_mesh_edit_commands_require_host_capability(self) -> None:
        source = _mesh_edit_source()

        helper_start = source.index("def _alignment_d3d11_mesh_edit_commands_active() -> bool:")
        helper_body = source[helper_start: source.index("def _sync_mesh_edit_preview_settings", helper_start)]
        self.assertIn("_alignment_d3d11_preview_active()", helper_body)
        self.assertIn('callable(getattr(alignment_d3d11_preview_host, "set_mesh_edit_state", None))', helper_body)
        self.assertIn('callable(getattr(alignment_d3d11_preview_host, "update_mesh_edit_vertices", None))', helper_body)
        self.assertIn('callable(getattr(alignment_d3d11_preview_host, "replace_mesh_edit_triangles", None))', helper_body)

        sync_start = source.index("def _sync_mesh_edit_preview_settings() -> None:")
        sync_body = source[sync_start: source.index("def _refresh_mesh_edit_controls", sync_start)]
        self.assertIn("if _alignment_d3d11_mesh_edit_commands_active():", sync_body)
        self.assertLess(
            sync_body.index("if _alignment_d3d11_mesh_edit_commands_active():"),
            sync_body.index("alignment_d3d11_preview_host.set_mesh_edit_state("),
        )

    def test_mesh_edit_disables_native_alignment_transform(self) -> None:
        source = _mesh_edit_source()

        sync_start = source.index("def _sync_mesh_edit_preview_settings() -> None:")
        sync_body = source[sync_start: source.index("def _refresh_mesh_edit_controls", sync_start)]
        self.assertIn("_clear_alignment_d3d11_fast_transform_state()", sync_body)
        self.assertIn("alignment_d3d11_preview_host.set_alignment_state(", sync_body)
        self.assertIn("enabled=False", sync_body)
        self.assertIn("alignment_d3d11_preview_host.set_alignment_preview_transform()", sync_body)

        highlight_start = source.index("def _sync_highlight_sets() -> None:")
        highlight_body = source[highlight_start: source.index("def _preview_mode_qt_widgets", highlight_start)]
        self.assertIn("_selection_highlight_sets_state_helper(", highlight_body)
        self.assertIn("mesh_edit_raw_active=bool(_mesh_edit_raw_preview_active()) if d3d11_active else False", highlight_body)
        self.assertIn("preview_gizmo_checked=bool(preview_gizmo_checkbox.isChecked()) if d3d11_active else False", highlight_body)
        self.assertIn("enabled=bool(selection_state[\"d3d11_gizmo_enabled\"])", highlight_body)

        replay_start = source.index("def _replay_alignment_d3d11_fast_transform() -> None:")
        replay_body = source[replay_start: source.index("def _apply_global_transform_fast_preview", replay_start)]
        self.assertIn("_alignment_d3d11_fast_transform_replay_state_helper(", replay_body)
        self.assertIn("mesh_edit_raw_active=_mesh_edit_raw_preview_active()", replay_body)
        self.assertIn("_clear_alignment_d3d11_fast_transform_state()", replay_body)
        self.assertIn("alignment_d3d11_preview_host.set_alignment_preview_transform()", replay_body)

    def test_subdivide_selection_is_explicit_topology_path_not_sculpt_toggle(self) -> None:
        source = _mesh_edit_source()
        deformer_source = _read("cdmw/modding/mesh_deformer.py")
        mesh_edit_state_source = _read("cdmw/ui/archive_browser/static_replacement_mesh_edit_state.py")

        self.assertIn('"subdivide_selection": "Subdivide Selection"', mesh_edit_state_source)
        self.assertIn('mesh_edit_subdivide_selection_button = QPushButton(mesh_edit_action_control_text["subdivide_selection"])', source)
        self.assertIn("def _mesh_edit_subdivide_selection() -> None:", source)
        self.assertIn("mesh_edit_subdivide_selection_button.clicked.connect", source)
        self.assertIn("subdivide_faces_touching_vertices(", source)
        self.assertIn("_mesh_edit_replace_live_triangles(result.affected_submesh_indices)", source)
        self.assertIn("alignment_d3d11_preview_host.set_mesh_edit_vertex_selection(mesh_edit_selected_vertices_by_submesh)", source)
        self.assertNotIn("mesh_edit_detail_refine_checkbox", source)
        self.assertNotIn("def _mesh_edit_refine_detail_for_payload(", source)
        self.assertNotIn('"detail_refined_sources": set()', source)
        self.assertIn("class MeshSubdivisionResult", deformer_source)
        self.assertIn("def subdivide_faces_touching_vertices(", deformer_source)


if __name__ == "__main__":
    unittest.main()
