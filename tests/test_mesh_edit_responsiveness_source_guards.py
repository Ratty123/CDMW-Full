from __future__ import annotations

from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


def _read(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


class MeshEditResponsivenessSourceGuardTests(unittest.TestCase):
    def test_mesh_edit_control_changes_sync_state_without_preview_reload(self) -> None:
        source = _read("cdmw/ui/main_window.py")

        self.assertIn('mesh_edit_selection_depth_combo.addItem(label, value)', source)
        self.assertIn('("Visible Only", "visible")', source)
        self.assertIn('("X-Ray", "xray")', source)
        self.assertIn("def _mesh_edit_preview_source_indices(", source)
        self.assertIn("raw_direct_source_preview_indices.update(_mesh_edit_preview_source_indices())", source)
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
        main_source = _read("cdmw/ui/main_window.py")
        bridge_source = _read("cdmw/ui/native_d3d11_preview_host.py")

        for source in (main_source, bridge_source):
            self.assertIn('"command": "update_mesh_edit_vertices"', source)
            self.assertIn('"command": "replace_mesh_edit_triangles"', source)
            self.assertIn('selection_depth_mode: str = "visible"', source)
            self.assertIn('"selection_depth_mode": str(selection_depth_mode or "visible")', source)
            self.assertIn('"smooth_iterations": int(smooth_iterations or 3)', source)
        self.assertIn("def _mesh_edit_live_vertex_update_groups(", main_source)
        self.assertIn("mesh_edit_live_update_timer.setInterval(16)", main_source)
        self.assertIn("if include_normals and len(normals) == len(vertices):", main_source)
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
        main_source = _read("cdmw/ui/main_window.py")
        native_source = _read("native/cdmw_d3d11_preview/src/main.cpp")
        bridge_source = _read("cdmw/ui/native_d3d11_preview_host.py")

        self.assertIn("_alignment_d3d11_source_indices_for_editor_id(editor_submesh_index)", main_source)
        self.assertIn("def _mesh_edit_clear_topology_selection() -> None:", main_source)
        self.assertIn("alignment_d3d11_preview_host.clear_mesh_edit_vertex_selection()", main_source)
        selection_start = main_source.index("def _mesh_edit_selection_changed(payload: object) -> None:")
        selection_body = main_source[selection_start: main_source.index("def _mesh_edit_control_tab_changed", selection_start)]
        self.assertIn("allowed_indices = set(_mesh_edit_allowed_source_indices())", selection_body)
        self.assertIn("vertex_count = len(", selection_body)
        self.assertIn("if 0 <= vertex_index < vertex_count:", selection_body)
        self.assertIn('"indices": indices', main_source)
        self.assertIn("source_vertex_indices.append(int(vertex_index))", main_source)
        self.assertIn('const std::vector<int> indices = json_int_array_field(group, "indices");', native_source)
        self.assertIn('const bool indexed_payload = group.find("\\"indices\\"") != std::string::npos;', native_source)
        self.assertIn('if (command == "replace_mesh_edit_triangles_file")', native_source)
        self.assertIn("read_text(payload_file)", native_source)
        self.assertIn('filename.rfind(L"cdmw_mesh_edit_triangles_", 0) == 0', native_source)
        self.assertIn('"command": "replace_mesh_edit_triangles_file"', bridge_source)

    def test_mesh_edit_tool_controls_are_capability_scoped(self) -> None:
        source = _read("cdmw/ui/main_window.py")

        self.assertNotIn('("Selection only", "selection")', source)
        self.assertIn("mesh_edit_field_rows: Dict[str, Tuple[QLabel, QWidget]] = {}", source)
        self.assertIn('mesh_edit_select_part_button = QPushButton("Select Whole Part")', source)
        self.assertIn('mesh_edit_invert_selection_button = QPushButton("Invert Selection")', source)
        self.assertIn('selection_actions_visible = select_tool or selected_count > 0', source)
        self.assertIn('_set_mesh_edit_row_visible("radius", sculpt_tool or remove_tool or brush_selection_tool)', source)
        self.assertIn('_set_mesh_edit_row_visible("strength", sculpt_tool)', source)
        self.assertIn('_set_mesh_edit_row_visible("falloff", sculpt_tool)', source)
        self.assertIn('_set_mesh_edit_row_visible("iterations", current_tool == "smooth")', source)
        self.assertIn('_set_mesh_edit_row_visible("selection", select_tool)', source)
        self.assertIn('_set_mesh_edit_row_visible("depth", select_tool)', source)
        self.assertIn("mesh_edit_mirror_checkbox.setVisible(sculpt_tool)", source)
        self.assertIn("mesh_edit_select_part_button.setVisible(select_tool)", source)
        self.assertIn("mesh_edit_invert_selection_button.setVisible(select_tool)", source)
        self.assertIn("mesh_edit_subdivide_selection_button.setVisible(select_tool)", source)
        self.assertIn("mesh_edit_delete_faces_button.setVisible(select_tool)", source)
        self.assertIn("def _mesh_edit_all_vertices_in_scope() -> Dict[int, set[int]]:", source)
        self.assertIn("def _mesh_edit_select_whole_part() -> None:", source)
        self.assertIn("def _mesh_edit_invert_selection() -> None:", source)
        self.assertIn("mesh_edit_select_part_button.clicked.connect", source)
        self.assertIn("mesh_edit_invert_selection_button.clicked.connect", source)

    def test_mesh_edit_sculpt_payloads_map_d3d11_editor_ids_to_source_ids(self) -> None:
        source = _read("cdmw/ui/main_window.py")
        apply_start = source.index("def _mesh_edit_apply_preview_payload(payload: object) -> None:")
        apply_body = source[apply_start: source.index("def _mesh_edit_finish_stroke", apply_start)]

        self.assertIn("allowed_indices = set(_mesh_edit_allowed_source_indices())", apply_body)
        self.assertIn("editor_submesh_index = int(group.get(\"source_submesh_index\", -1))", apply_body)
        self.assertIn("_alignment_d3d11_source_indices_for_editor_id(editor_submesh_index)", apply_body)
        self.assertIn("for source_submesh_index in source_indices:", apply_body)
        self.assertIn("if source_submesh_index not in allowed_indices:", apply_body)

    def test_mesh_edit_loading_watchdog_clears_stale_d3d11_state(self) -> None:
        source = _read("cdmw/ui/main_window.py")
        package_source = _read("cdmw/rendering/native_preview_package.py")
        native_source = _read("native/cdmw_d3d11_preview/src/main.cpp")

        self.assertIn("def _reset_alignment_d3d11_request_state(", source)
        self.assertIn("def _alignment_d3d11_request_active() -> bool:", source)
        self.assertIn('_clear_stuck_alignment_d3d11_loading("loading watchdog")', source)
        self.assertIn('message="Preview idle."', source)
        self.assertIn('"D3D11 preview loading state cleared."', source)
        self.assertIn("def _set_alignment_d3d11_progress(", source)
        self.assertIn("Preview stale/no fresh frame.", source)
        self.assertIn("D3D11 preview stale/no fresh frame", source)
        self.assertIn("progress_changed = Signal(int, int, int, str)", source)
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
        self.assertIn("on_progress=_emit_package_progress", source)
        self.assertIn('\\"percent\\":85', native_source)
        self.assertIn('\\"percent\\":90', native_source)
        self.assertIn("resources_loaded_payload", native_source)
        self.assertIn('loaded_payload_for_event(stats, "resources_loaded")', native_source)
        self.assertIn('\\"render_suppressed_reason\\"', native_source)
        self.assertIn('\\"parent_renderable\\"', native_source)

    def test_mesh_edit_raw_package_and_live_restore_paths_exist(self) -> None:
        source = _read("cdmw/ui/main_window.py")
        worker_source = source[source.index("class AlignmentD3D11PackageWorker"): source.index("class DetachedToolWindow")]

        self.assertIn("def _mesh_edit_raw_preview_active() -> bool:", source)
        self.assertIn("mesh_edit_raw_preview_state = {\"active\": False}", source)
        self.assertIn("def _mesh_edit_apply_preview_mode_transition(reason: str) -> None:", source)
        self.assertIn('"mesh_edit_preview_mode_transition"', source)
        self.assertIn('_alignment_d3d11_invalidate_package_cache("mesh_edit_mode")', source)
        self.assertIn("def _alignment_d3d11_raw_package_active_or_pending() -> bool:", source)
        self.assertIn('_alignment_d3d11_raw_package_active_or_pending()', source)
        self.assertIn('("request_package_qualities", {})', source)
        self.assertIn('("package_quality", "normal")', source)
        self.assertIn("_queue_texture_preview_refresh()", source)
        self.assertIn('_mesh_edit_apply_preview_mode_transition("left_mesh_edit_tab")', source)
        self.assertNotIn('return _alignment_d3d11_fast_render_settings(settings), False, False, "fast_geometry"', source)
        self.assertIn('return clamp_model_preview_render_settings(settings), True, True, "material_refresh"', source)
        self.assertIn('return clamp_model_preview_render_settings(settings), True, True, "mesh_edit_raw"', source)
        self.assertNotIn("fast_settings.disable_all_support_maps = True", source)
        self.assertNotIn("fast_settings.disable_normal_map = True", source)
        self.assertNotIn("fast_settings.disable_material_map = True", source)
        self.assertNotIn("fast_settings.disable_height_map = True", source)
        self.assertIn("mesh_edit_raw_package = _mesh_edit_raw_preview_active()", source)
        self.assertIn("worker_use_textures = True", source)
        self.assertIn("original_reference_material_parity=worker_original_reference_material_parity", source)
        self.assertIn('reuse_prepared_geometry=package_quality_key == "material_refresh"', source)
        self.assertIn("def _mesh_by_source_identity", source)
        poll_start = source.index("def _poll_alignment_d3d11_status() -> None:")
        loaded_start = source.index('if event == "loaded":', poll_start)
        loaded_block = source[loaded_start: source.index('elif event == "loading":', loaded_start)]
        self.assertIn("_sync_mesh_edit_preview_settings()", loaded_block)
        self.assertIn("enable_material_combiner=bool(self.enable_material_combiner and self.use_textures)", worker_source)
        self.assertIn("def _mesh_edit_full_reset_mesh() -> None:", source)
        self.assertIn('mesh_edit_full_reset_button = QPushButton("Full Reset Mesh")', source)
        self.assertIn("def _mesh_edit_part_enabled_snapshot() -> Dict[int, bool]:", source)
        self.assertIn("def _mesh_edit_restore_enabled_snapshot(snapshot: Mapping[int, bool]) -> None:", source)
        self.assertNotIn("def _mesh_edit_restore_adjustment_snapshot", source)
        self.assertIn("restore_deleted_output = (", source)
        self.assertIn("def _mesh_edit_transformed_sources_for_live_preview(source_indices: Iterable[int])", source)
        self.assertIn("def _mesh_edit_submesh_for_live_preview(source_index: int):", source)
        self.assertIn("alignment_basis_mesh=replacement_mesh_base_for_mapping or replacement_mesh_for_mapping", source)
        self.assertIn("transformed_sources_by_index = _mesh_edit_transformed_sources_for_live_preview", source)
        self.assertIn("alignment_d3d11_preview_host.clear_mesh_edit_vertex_selection()", source)
        self.assertIn("_mesh_edit_replace_live_triangles(source_indices)", source)

    def test_mesh_edit_live_preview_uses_frozen_alignment_basis(self) -> None:
        main_source = _read("cdmw/ui/main_window.py")
        replacer_source = _read("cdmw/modding/static_mesh_replacer.py")

        self.assertIn("alignment_basis_mesh: ParsedMesh | None = None", replacer_source)
        self.assertIn("basis_mesh = alignment_basis_mesh or replacement_mesh", replacer_source)
        self.assertIn("alignment_replacement_mesh = copy.copy(basis_mesh)", replacer_source)
        self.assertIn("alignment_basis_mesh=(", main_source)
        self.assertIn("replacement_mesh_base_for_mapping", main_source)

    def test_subdivide_selection_is_explicit_topology_path_not_sculpt_toggle(self) -> None:
        source = _read("cdmw/ui/main_window.py")
        deformer_source = _read("cdmw/modding/mesh_deformer.py")

        self.assertIn('mesh_edit_subdivide_selection_button = QPushButton("Subdivide Selection")', source)
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
