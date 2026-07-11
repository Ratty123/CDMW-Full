from __future__ import annotations

from tests.mesh_harness_support import (
    ArchiveEntry,
    MeshTextureSourceResolution,
    Path,
    SPARSE_SOAK_UPDATE_COUNT,
    SPARSE_SOAK_VERTEX_COUNT,
    _resolve_real_archive_mesh_textures,
    _mesh_core_source,
    build_native_benchmark_mesh,
    build_sparse_update_soak_mesh,
    build_synthetic_mesh,
    find_native_d3d11_host,
    native_mesh_core_available,
    patch,
    pytest,
    run_scenario,
    scenario_metadata,
    tempfile,
    unittest,
)
from tests.mesh_editor_source_support import mesh_editor_tab_source
from tests.native_source_text import d3d11_preview_source

class MeshHarnessD3DProtocolTests(unittest.TestCase):
    def test_d3d11_brush_selection_event_carries_screen_brush_context(self) -> None:
        source = d3d11_preview_source()
        self.assertIn("void send_mesh_edit_screen_brush_selection_event(int x, int y)", source)
        selection_event_start = source.index("void send_mesh_edit_selection_event(")
        selection_event_body = source[selection_event_start:source.index("int update_mesh_edit_vertices_from_payload", selection_event_start)]
        self.assertIn("bool include_screen_brush", selection_event_body)
        self.assertIn("bool include_screen_brush = false", source)
        self.assertIn('\\"screen_brush\\":', selection_event_body)
        screen_event_body = source[source.index("void send_mesh_edit_screen_brush_selection_event("):selection_event_start]
        self.assertIn('\\"target_mode\\":', screen_event_body)
        self.assertIn('\\"selection_depth_mode\\":', screen_event_body)
        self.assertIn("mesh_edit_screen_brush_json(mesh_edit_.last_x, mesh_edit_.last_y, mesh_edit_.radius_pixels)", selection_event_body)
        brush_json_start = source.index("std::string mesh_edit_screen_brush_json(")
        brush_json_body = source[brush_json_start:source.index("std::string mesh_edit_screen_region_json(", brush_json_start)]
        self.assertIn("mesh_edit_source_projection_overrides_json()", brush_json_body)
        brush_selection_start = source.index("void apply_mesh_edit_brush_selection(")
        brush_selection_body = source[brush_selection_start:source.index("bool mesh_edit_preview_event_due", brush_selection_start)]
        self.assertIn("send_mesh_edit_screen_brush_selection_event(x, y)", brush_selection_body)
        self.assertNotIn("mesh_edit_depth_filter_enabled()", brush_selection_body)
        self.assertNotIn("mesh_edit_face_candidates_at", brush_selection_body)
        self.assertNotIn("mesh_edit_edge_candidates_at", brush_selection_body)
        self.assertNotIn("mesh_edit_candidates_at(x, y, mesh_edit_.radius_pixels, false)", brush_selection_body)

    def test_d3d11_region_selection_event_carries_screen_region_context(self) -> None:
        source = d3d11_preview_source()
        self.assertIn("std::string mesh_edit_screen_region_json(int x, int y) const", source)
        self.assertIn("void send_mesh_edit_screen_region_selection_event(int x, int y)", source)

        region_start = source.index("std::string mesh_edit_screen_region_json(")
        region_body = source[region_start:source.index("std::string mesh_edit_payload_json(", region_start)]
        self.assertIn('\\"start_x\\":', region_body)
        self.assertIn('\\"end_x\\":', region_body)
        self.assertIn('\\"points\\":', region_body)
        self.assertIn('\\"source_submesh_indices\\":', region_body)
        self.assertIn('\\"world_view_projection\\":', region_body)
        self.assertIn("XMStoreFloat4x4(&world_view_projection, current_mvp_matrix())", region_body)
        self.assertIn("mesh_edit_source_projection_overrides_json()", region_body)
        for legacy_field in ('\\"camera_world\\":', '\\"yaw_degrees\\":', '\\"pitch_degrees\\":', '\\"distance\\":', '\\"vertical_fov_degrees\\":', '\\"pan\\":'):
            self.assertNotIn(legacy_field, region_body)

        region_event_start = source.index("void send_mesh_edit_screen_region_selection_event(")
        region_event_body = source[region_event_start:source.index("void send_mesh_edit_selection_event(", region_event_start)]
        self.assertIn('\\"target_mode\\":', region_event_body)
        self.assertIn('\\"selection_depth_mode\\":', region_event_body)
        self.assertIn('\\"screen_region\\":', region_event_body)

        selection_start = source.index("void apply_mesh_edit_region_selection")
        selection_body = source[selection_start:source.index("void finish_mesh_edit_selection_drag", selection_start)]
        self.assertIn("send_mesh_edit_screen_region_selection_event(x, y)", selection_body)
        self.assertNotIn("mesh_edit_screen_vertices_for_view", selection_body)
        self.assertNotIn("mesh_edit_depth_filter_enabled()", selection_body)
        self.assertNotIn("mesh_edit_faces_in_selection_region", selection_body)
        self.assertNotIn("apply_mesh_edit_face_selection_delta", selection_body)
        self.assertNotIn("apply_mesh_edit_edge_selection_delta", selection_body)
        self.assertNotIn("apply_mesh_edit_selection_delta", selection_body)

    def test_d3d11_source_selection_accepts_screen_payload(self) -> None:
        source = d3d11_preview_source()
        brush_command_start = source.index('if (command == "select_mesh_edit_brush")')
        brush_command_body = source[brush_command_start:source.index('if (command == "select_mesh_edit_region")', brush_command_start)]
        region_command_start = source.index('if (command == "select_mesh_edit_region")')
        region_command_body = source[region_command_start:source.index('if (command == "update_mesh_edit_vertices")', region_command_start)]
        brush_event_start = source.index("void send_mesh_edit_screen_brush_selection_event(")
        brush_event_body = source[brush_event_start:source.index("void send_mesh_edit_screen_region_selection_event(", brush_event_start)]
        part_click_start = source.index("void send_source_part_screen_selection_event(")
        part_click_body = source[part_click_start:source.index("void update_source_part_hover(", part_click_start)]
        part_context_start = source.index("void send_source_part_screen_context_event(")
        part_context_body = source[part_context_start:source.index("void update_source_part_hover(", part_context_start)]
        hover_start = source.index("void update_source_part_hover(")
        hover_body = source[hover_start:source.index("void begin_source_part_click(", hover_start)]
        begin_part_click_start = source.index("void begin_source_part_click(")
        begin_part_click_body = source[begin_part_click_start:source.index("void finish_source_part_click(", begin_part_click_start)]
        finish_part_click_start = source.index("void finish_source_part_click(")
        finish_part_click_body = source[finish_part_click_start:source.index("bool request_source_part_context(", finish_part_click_start)]
        source_context_start = source.index("bool request_source_part_context(")
        source_context_body = source[source_context_start:source.index("std::string mesh_edit_screen_drag_json(", source_context_start)]
        brush_json_start = source.index("std::string mesh_edit_screen_brush_json(")
        brush_json_body = source[brush_json_start:source.index("std::string mesh_edit_screen_region_json(", brush_json_start)]
        region_json_start = source.index("std::string mesh_edit_screen_region_json(")
        region_json_body = source[region_json_start:source.index("std::string mesh_edit_payload_json(", region_json_start)]
        overrides_start = source.index("std::string mesh_edit_source_projection_overrides_json() const")
        overrides_body = source[overrides_start:source.index("std::string mesh_edit_screen_brush_json(", overrides_start)]

        tab_source = mesh_editor_tab_source()
        handler_start = tab_source.index("def _handle_standalone_native_mesh_edit_selection_changed")
        handler_body = tab_source[handler_start:tab_source.index("def _apply_standalone_native_mesh_edit_stroke", handler_start)]

        native_source = _mesh_core_source()
        native_projection_start = native_source.index("MeshEditorScreenBrushProjection mesh_editor_screen_brush_projection")
        native_projection_body = native_source[native_projection_start:native_source.index("bool mesh_editor_screen_ray_from_projection", native_projection_start)]
        native_brush_helpers_start = native_source.index("void mesh_editor_select_brush_source(")
        native_brush_start = native_source.index("void mesh_editor_add_screen_brush_selection(")
        native_brush_body = native_source[native_brush_start:native_source.index("bool mesh_editor_screen_region_contains", native_brush_start)]
        native_brush_helpers_body = native_source[
            native_brush_helpers_start:native_source.index("bool mesh_editor_screen_region_contains", native_brush_start)
        ]
        native_select_start = native_source.index("std::string mesh_editor_select_session_report(")
        native_select_body = native_source[
            native_select_start:native_source.index("std::string run_mesh_editor_session(", native_select_start)
        ]
        native_region_helpers_start = native_source.index("void mesh_editor_select_screen_region_submesh(")
        native_region_start = native_source.index("void mesh_editor_add_screen_region_selection(")
        native_region_body = native_source[native_region_start:native_source.index("MeshEditorSelection mesh_editor_selection_from_json", native_region_start)]
        native_region_helpers_body = native_source[
            native_region_helpers_start:native_source.index("MeshEditorSelection mesh_editor_selection_from_json", native_region_start)
        ]
        harness_source = Path("tools/mesh_harness/native_smoke.py").read_text(encoding="utf-8")

        self.assertIn('target_mode == "source"', brush_command_body)
        self.assertIn('target_mode == "source"', region_command_body)
        self.assertIn('\\"target_mode\\":', brush_event_body)
        self.assertIn('\\"screen_brush\\":', brush_event_body)
        self.assertIn('\\"operation\\":\\"toggle\\"', part_click_body)
        self.assertIn('\\"target_mode\\":\\"source\\"', part_click_body)
        self.assertIn('\\"selection_depth_mode\\":\\"xray\\"', part_click_body)
        self.assertIn("mesh_edit_screen_brush_json(x, y, 28.0f, false)", part_click_body)
        self.assertIn('send_mesh_edit_event("mesh_edit_selection_changed", payload.str())', part_click_body)
        self.assertIn('\\"operation\\":\\"context\\"', part_context_body)
        self.assertIn('\\"target_mode\\":\\"source\\"', part_context_body)
        self.assertIn('\\"context_request\\":true', part_context_body)
        self.assertIn('\\"context_x\\":', part_context_body)
        self.assertIn("mesh_edit_screen_brush_json(x, y, 28.0f, false)", part_context_body)
        self.assertIn("if (mesh_edit_.enabled)", hover_body)
        self.assertLess(
            hover_body.index("if (mesh_edit_.enabled)"),
            hover_body.index("source_part_at(x, y, 28.0f)"),
        )
        self.assertIn('send_source_part_event("source_part_hovered", -1)', hover_body)
        self.assertIn("if (mesh_edit_.enabled)", source_context_body)
        self.assertLess(
            source_context_body.index("if (mesh_edit_.enabled)"),
            source_context_body.index("source_part_at(x, y, 28.0f)"),
        )
        self.assertIn("send_source_part_screen_context_event(x, y)", source_context_body)
        self.assertIn("bool include_source_filter", brush_json_body)
        self.assertIn("bool include_source_filter = true", source)
        self.assertIn("include_source_filter && !mesh_edit_.source_submesh_indices.empty()", brush_json_body)
        self.assertIn("mesh_edit_source_projection_overrides_json()", brush_json_body)
        self.assertIn("mesh_edit_source_projection_overrides_json()", region_json_body)
        self.assertIn("alignment_preview_transform_active()", overrides_body)
        self.assertIn("batch_uses_source_normalization(batch)", overrides_body)
        self.assertIn("mesh_edit_source_world_transform_for_batch(batch)", overrides_body)
        self.assertIn("mesh_edit_source_allowed(batch.source_submesh_index)", overrides_body)
        self.assertIn("source_submesh_world_transforms", overrides_body)
        self.assertIn("world_transform", overrides_body)
        self.assertNotIn("current_world_view_projection", overrides_body)
        self.assertIn("if (!mesh_edit_.enabled)", begin_part_click_body)
        self.assertIn("source_part_at(x, y, 28.0f)", begin_part_click_body)
        self.assertIn("if (mesh_edit_.enabled)", finish_part_click_body)
        self.assertIn("send_source_part_screen_selection_event(x, y)", finish_part_click_body)
        self.assertIn("send_source_part_event(\"source_part_selected\"", finish_part_click_body)
        self.assertLess(
            finish_part_click_body.index("if (mesh_edit_.enabled)"),
            finish_part_click_body.index("send_source_part_screen_selection_event(x, y)"),
        )
        self.assertIn('target_mode == "source"', native_brush_body)
        self.assertIn("mesh_editor_select_brush_source(*session, selection, context)", native_brush_body)
        self.assertIn("mesh_editor_select_brush_submesh(entry.first, entry.second, selection, context)", native_brush_body)
        self.assertIn("source_submesh_world_transforms", native_projection_body)
        self.assertIn("matrix4x4_multiply(source_world_transform, projection.world_view_projection)", native_projection_body)
        self.assertIn("mesh_editor_projection_for_submesh(", native_projection_body)
        self.assertIn("mesh_editor_projection_for_submesh(context.projection, entry.first)", native_brush_helpers_body)
        self.assertIn("mesh_editor_pick_source_with_screen_ray(&session, context.brush, context.projection)", native_brush_helpers_body)
        self.assertIn("selection.source_indices.insert(best_index)", native_brush_helpers_body)
        self.assertIn('context.target_mode == "edge" || context.target_mode == "face"', native_brush_helpers_body)
        self.assertIn("mesh_editor_screen_ray_from_projection(context.brush, projection, ray)", native_brush_helpers_body)
        self.assertIn("mesh_editor_ray_segment_distance(", native_brush_helpers_body)
        self.assertIn("mesh_editor_ray_intersects_triangle(", native_brush_helpers_body)
        self.assertIn("mesh_editor_project_screen_brush_vertex_with_projection", native_brush_helpers_body)
        self.assertIn('const bool context_operation = selection_operation == "context"', native_select_body)
        self.assertIn("source_pick_count", native_select_body)
        self.assertIn("mesh_editor_selection_empty(incoming)", native_select_body)
        self.assertIn("editor_select_source_pick_count", handler_body)
        self.assertIn("show_part_context_menu_for_part", handler_body)
        self.assertIn('payload.get("context_request")', handler_body)
        self.assertIn("mesh_editor_select_screen_region_submesh(entry.first, entry.second, selection, context)", native_region_body)
        self.assertIn('context.target_mode == "source"', native_region_helpers_body)
        self.assertIn("mesh_editor_projection_for_submesh(context.projection, index)", native_region_helpers_body)
        self.assertIn("selection.source_indices.insert(index)", native_region_helpers_body)
        self.assertRegex(harness_source, r"['\"]command['\"]:\s*['\"]select_mesh_edit_brush['\"]")
        self.assertRegex(harness_source, r"['\"]target_mode['\"]:\s*['\"]source['\"]")
        self.assertIn("source_screen_selection_ok", harness_source)
        self.assertRegex(harness_source, r"['\"]command['\"]:\s*['\"]set_alignment_transforms['\"]")
        self.assertIn("_screen_source_transform_override_ok", harness_source)
        self.assertIn("screen_payloads_with_source_transform_overrides_ok", harness_source)

    def test_d3d11_native_screen_tools_skip_overlay_candidate_hits(self) -> None:
        source = d3d11_preview_source()
        overlay_start = source.index("const bool cursor_in_view =")
        overlay_body = source[overlay_start:source.index("if (mesh_edit_.selection_drag_active &&", overlay_start)]

        self.assertIn("add_ring(", overlay_body)
        self.assertIn('const bool remove_tool = mesh_edit_.tool == "remove";', overlay_body)
        self.assertIn("draw_mesh_edit_vertex_dots_instanced(view, *dot_vertices, xray_mode);", source)
        self.assertIn("mesh_edit_source_face_selected(batch, triangle_index, base)", source)
        self.assertIn("mesh_edit_source_edge_selected(key0, key1)", source)
        self.assertNotIn("native_screen_tool", source)
        self.assertNotIn("brush_vertices", source)
        self.assertNotIn("brush_triangle", source)
        self.assertNotIn("struct EditorCandidate", source)
        self.assertNotIn("struct MeshEditEdgeCandidate", source)
        self.assertNotIn("mesh_edit_candidates_at_in_view", source)
        self.assertNotIn("mesh_edit_edge_candidates_at_in_view", source)
        self.assertNotIn("mesh_edit_face_candidates_at_in_view", source)
        self.assertNotIn("std::vector<EditorCandidate> mesh_edit_face_candidates_at_in_view", source)
        self.assertNotIn("distance_to_screen_triangle", source)
        self.assertNotIn("distance_to_screen_segment", source)

    def test_d3d11_inflate_payload_uses_screen_radius_not_host_amount(self) -> None:
        source = d3d11_preview_source()
        amount_start = source.index("} else if (amount_tool) {")
        amount_body = source[amount_start:source.index("} else {", amount_start)]

        self.assertIn('\\"screen_radius\\":', amount_body)
        self.assertIn('\\"screen_brush\\":', amount_body)
        radius_start = source.index("std::string mesh_edit_screen_radius_json(")
        radius_body = source[radius_start:source.index("std::string mesh_edit_screen_brush_json(", radius_start)]
        self.assertIn('\\"world_view_projection\\":', radius_body)
        self.assertNotIn('\\"camera_world\\":', radius_body)
        self.assertIn("XMStoreFloat4x4(&world_view_projection, current_mvp_matrix())", radius_body)
        self.assertIn("mesh_edit_source_projection_overrides_json()", radius_body)
        self.assertNotIn('\\"distance\\":', radius_body)
        self.assertNotIn('\\"vertical_fov_degrees\\":', radius_body)
        self.assertNotIn('\\"center\\":', amount_body)
        self.assertNotIn("mesh_edit_average_position(candidates)", amount_body)
        self.assertNotIn('\\"amount\\":', amount_body)
        self.assertNotIn("amount_world", amount_body)

        native_source = _mesh_core_source()
        self.assertIn("mesh_editor_source_world_view_projection_from_json", native_source)
        self.assertIn("mesh_editor_screen_radius_units_at_center(screen_radius_payload, center, result.index)", native_source)

    def test_d3d11_screen_drag_payload_uses_cursor_endpoints(self) -> None:
        source = d3d11_preview_source()
        drag_start = source.index("std::string mesh_edit_screen_drag_json(")
        drag_body = source[drag_start:source.index("std::string mesh_edit_screen_radius_json(", drag_start)]
        payload_start = source.index("std::string mesh_edit_payload_json(")
        payload_body = source[payload_start:source.index("void send_mesh_edit_event(", payload_start)]

        self.assertIn('\\"start_x\\":', drag_body)
        self.assertIn('\\"end_x\\":', drag_body)
        self.assertIn('\\"world_view_projection\\":', drag_body)
        self.assertIn("XMStoreFloat4x4(&world_view_projection, current_mvp_matrix())", drag_body)
        self.assertIn("mesh_edit_source_projection_overrides_json()", drag_body)
        self.assertNotIn("const std::string screen_drag = mesh_edit_screen_drag_json", payload_body)
        self.assertEqual(2, payload_body.count("mesh_edit_screen_drag_json(mesh_edit_.last_x, mesh_edit_.last_y, x, y)"))
        for legacy_field in ('\\"yaw_degrees\\":', '\\"pitch_degrees\\":', '\\"distance\\":', '\\"vertical_fov_degrees\\":'):
            self.assertNotIn(legacy_field, drag_body)
        self.assertNotIn('\\"camera_world\\":', drag_body)
        self.assertNotIn("delta_x_pixels", drag_body)
        self.assertNotIn("end_x - start_x", drag_body)

        native_source = _mesh_core_source()
        self.assertIn("mesh_editor_screen_drag_projection_delta", native_source)
        self.assertIn("const bool projected = mesh_editor_has_projection_payload(screen_drag, submesh_index)", native_source)
        self.assertIn("const Vec3 base_translate = projected ? Vec3{0.0, 0.0, 0.0} : transform.translate", native_source)
        self.assertIn("add_screen_drag_delta(base_translate, screen_drag, &transform.pivot, submesh_index)", native_source)
        self.assertIn("const Vec3 drag_base = screen_drag_projection_payload", native_source)
        self.assertIn("add_screen_drag_delta(\n        drag_base,", native_source)
        self.assertIn("result.index\n    );", native_source)

    def test_d3d11_smooth_payload_sends_screen_brush_context(self) -> None:
        source = d3d11_preview_source()
        brush_start = source.index("std::string mesh_edit_screen_brush_json(")
        brush_body = source[brush_start:source.index("std::string mesh_edit_screen_region_json(", brush_start)]
        payload_start = source.index("std::string mesh_edit_payload_json(")
        payload_body = source[payload_start:source.index("void send_mesh_edit_event(", payload_start)]
        smooth_start = source.index("} else if (smooth_tool) {")
        smooth_body = source[smooth_start:source.index("} else if (amount_tool) {", smooth_start)]
        begin_start = source.index("bool begin_mesh_edit_drag(")
        begin_body = source[begin_start:source.index("bool update_mesh_edit_drag(", begin_start)]
        update_start = source.index("bool update_mesh_edit_drag(")
        update_body = source[update_start:source.index("bool finish_mesh_edit_drag(", update_start)]

        self.assertIn('\\"x\\":', brush_body)
        self.assertIn('\\"radius_pixels\\":', brush_body)
        self.assertIn('\\"viewport_width\\":', brush_body)
        self.assertIn('\\"world_view_projection\\":', brush_body)
        self.assertIn("XMStoreFloat4x4(&world_view_projection, current_mvp_matrix())", brush_body)
        for legacy_field in ('\\"camera_world\\":', '\\"yaw_degrees\\":', '\\"pitch_degrees\\":', '\\"distance\\":', '\\"vertical_fov_degrees\\":', '\\"pan\\":'):
            self.assertNotIn(legacy_field, brush_body)
        self.assertIn('\\"source_submesh_indices\\":[', brush_body)
        self.assertIn('const bool grab_screen_brush_tool = grab_tool && mesh_edit_.target_mode != "selection";', payload_body)
        self.assertIn("bool include_screen_selection", payload_body)
        self.assertIn("bool include_screen_selection = false", source)
        self.assertIn("screen_brush_tool || include_screen_selection", payload_body)
        self.assertIn('const bool remove_screen_tool = tool == "remove" && mesh_edit_.delete_mode != "selection";', payload_body)
        self.assertIn("const bool screen_brush_tool = grab_screen_brush_tool || smooth_tool || amount_tool || remove_screen_tool", payload_body)
        self.assertNotIn("mesh_edit_falloff_weight", source)
        self.assertIn('\\"target_mode\\":', payload_body)
        self.assertIn('\\"selection_depth_mode\\":', payload_body)
        self.assertIn('\\"screen_brush\\":', smooth_body)
        self.assertIn("const bool has_resident_selection = !mesh_edit_.selected_vertices.empty()", begin_body)
        self.assertIn("|| !mesh_edit_.selected_edges.empty()", begin_body)
        self.assertIn("|| !mesh_edit_.selected_faces.empty()", begin_body)
        self.assertIn("|| !mesh_edit_.selected_sources.empty();", begin_body)
        self.assertIn('move_screen_selection_tool = mesh_edit_.tool == "move" && !has_resident_selection', begin_body)
        self.assertIn('grab_screen_selection_tool = mesh_edit_.tool == "grab" && mesh_edit_.target_mode == "selection" && !has_resident_selection', begin_body)
        self.assertIn("bool screen_selection_tool = move_screen_selection_tool || grab_screen_selection_tool", begin_body)
        self.assertIn("bool resident_selection_drag_tool = selection_drag_tool && has_resident_selection", begin_body)
        self.assertIn("bool native_selection_tool = screen_brush_tool || resident_selection_drag_tool", begin_body)
        self.assertIn('mesh_edit_.tool == "grab" && mesh_edit_.target_mode != "selection"', begin_body)
        self.assertIn("bool screen_brush_tool = screen_selection_tool", begin_body)
        self.assertIn("drag_uses_resident_selection = screen_selection_tool || resident_selection_drag_tool", begin_body)
        self.assertIn("if (!native_selection_tool) return true;", begin_body)
        self.assertIn('send_mesh_edit_event("mesh_edit_stroke_started", mesh_edit_payload_json(x, y, false, screen_selection_tool));', begin_body)
        self.assertNotIn("drag_candidates", begin_body)
        self.assertNotIn("mesh_edit_payload_json(candidates", begin_body)
        self.assertIn("screen_brush_update_tool", update_body)
        self.assertIn("resident_selection_drag = drag_mode && mesh_edit_.drag_uses_resident_selection", update_body)
        self.assertIn('mesh_edit_.tool == "grab" && mesh_edit_.target_mode != "selection"', update_body)
        self.assertIn("!screen_brush_update_tool && !resident_selection_drag", update_body)
        self.assertIn('send_mesh_edit_event("mesh_edit_stroke_previewed", mesh_edit_payload_json(x, y, ctrl_down));', update_body)
        self.assertNotIn("mesh_edit_payload_json(candidates", update_body)
        self.assertNotIn("mesh_edit_groups_json", source)

    def test_d3d11_remove_payload_sends_screen_brush_without_groups(self) -> None:
        source = d3d11_preview_source()
        payload_start = source.index("std::string mesh_edit_payload_json(")
        payload_body = source[payload_start:source.index("void send_mesh_edit_event(", payload_start)]
        remove_start = payload_body.index("} else if (remove_screen_tool) {")
        remove_body = payload_body[remove_start:]
        begin_start = source.index("bool begin_mesh_edit_drag(")
        begin_body = source[begin_start:source.index("bool update_mesh_edit_drag(", begin_start)]
        update_start = source.index("bool update_mesh_edit_drag(")
        update_body = source[update_start:source.index("bool finish_mesh_edit_drag(", update_start)]

        self.assertIn('remove_screen_tool = tool == "remove" && mesh_edit_.delete_mode != "selection"', payload_body)
        self.assertIn('remove_screen_tool ? "face"', payload_body)
        self.assertIn('\\"delete_mode\\":\\"', remove_body)
        self.assertIn("json_escape(mesh_edit_.delete_mode)", remove_body)
        self.assertIn('\\"screen_brush\\":', remove_body)
        self.assertIn('\\"falloff\\":', remove_body)
        self.assertNotIn("mesh_edit_average_position", remove_body)
        self.assertNotIn('\\"screen_radius\\":', remove_body)
        self.assertIn('remove_screen_tool = mesh_edit_.tool == "remove" && mesh_edit_.delete_mode != "selection"', begin_body)
        self.assertIn("|| remove_screen_tool", begin_body)
        self.assertIn("native_selection_tool", begin_body)
        self.assertIn("!native_selection_tool", begin_body)
        self.assertIn('remove_screen_tool = mesh_edit_.tool == "remove" && mesh_edit_.delete_mode != "selection"', update_body)
        self.assertIn("screen_brush_update_tool = remove_screen_tool", update_body)
        self.assertIn("!screen_brush_update_tool && !resident_selection_drag", update_body)

    def test_d3d11_grab_brush_target_payload_sends_screen_brush_without_groups(self) -> None:
        source = d3d11_preview_source()
        payload_start = source.index("std::string mesh_edit_payload_json(")
        payload_body = source[payload_start:source.index("void send_mesh_edit_event(", payload_start)]
        grab_start = payload_body.index("if (grab_tool) {")
        grab_body = payload_body[grab_start:payload_body.index("} else if (smooth_tool) {", grab_start)]
        begin_start = source.index("bool begin_mesh_edit_drag(")
        begin_body = source[begin_start:source.index("bool update_mesh_edit_drag(", begin_start)]
        update_start = source.index("bool update_mesh_edit_drag(")
        update_body = source[update_start:source.index("bool finish_mesh_edit_drag(", update_start)]

        self.assertIn('grab_screen_brush_tool = grab_tool && mesh_edit_.target_mode != "selection"', payload_body)
        self.assertIn('\\"screen_drag\\":', grab_body)
        self.assertIn('\\"screen_brush\\":', grab_body)
        self.assertIn('\\"falloff\\":', grab_body)
        self.assertIn('mesh_edit_.tool == "grab" && mesh_edit_.target_mode != "selection"', begin_body)
        self.assertIn('grab_screen_selection_tool = mesh_edit_.tool == "grab" && mesh_edit_.target_mode == "selection" && !has_resident_selection', begin_body)
        self.assertIn('send_mesh_edit_event("mesh_edit_stroke_started", mesh_edit_payload_json(x, y, false, screen_selection_tool));', begin_body)
        self.assertIn('mesh_edit_.tool == "grab" && mesh_edit_.target_mode != "selection"', update_body)
        self.assertIn('send_mesh_edit_event("mesh_edit_stroke_previewed", mesh_edit_payload_json(x, y, ctrl_down));', update_body)

    def test_d3d11_selected_drag_begin_uses_resident_selection_without_groups(self) -> None:
        source = d3d11_preview_source()
        begin_start = source.index("bool begin_mesh_edit_drag(")
        begin_body = source[begin_start:source.index("bool update_mesh_edit_drag(", begin_start)]
        update_start = source.index("bool update_mesh_edit_drag(")
        update_body = source[update_start:source.index("bool finish_mesh_edit_drag(", update_start)]

        self.assertNotIn("mesh_edit_selected_candidates()", begin_body)
        self.assertIn('selection_drag_tool = mesh_edit_.target_mode == "selection"', begin_body)
        self.assertIn("resident_selection_drag_tool = selection_drag_tool && has_resident_selection", begin_body)
        self.assertIn("native_selection_tool = screen_brush_tool || resident_selection_drag_tool", begin_body)
        self.assertIn("drag_uses_resident_selection = screen_selection_tool || resident_selection_drag_tool", begin_body)
        self.assertIn('send_mesh_edit_event("mesh_edit_stroke_started", mesh_edit_payload_json(x, y, false, screen_selection_tool));', begin_body)
        self.assertNotIn("mesh_edit_payload_json(candidates", begin_body)
        self.assertIn("resident_selection_drag = drag_mode && mesh_edit_.drag_uses_resident_selection", update_body)
        self.assertIn("!screen_brush_update_tool && !resident_selection_drag", update_body)
        self.assertNotIn("drag_candidates", update_body)

    @pytest.mark.visual
    def test_native_mesh_editor_d3d11_delta_scenario_uses_vertex_update_without_fallback(self) -> None:
        if not native_mesh_core_available():
            self.skipTest("native mesh core binary not built")
        if find_native_d3d11_host() is None:
            self.skipTest("native D3D11 preview host not built")
        with tempfile.TemporaryDirectory() as temp_dir:
            with patch("cdmw.services.mesh_service.apply_mesh_edit_geometry_action", side_effect=AssertionError("old geometry dispatcher used")):
                result = run_scenario("native-mesh-editor-d3d11-delta", Path(temp_dir), allow_synthetic_d3d11=True)

        self.assertTrue(result["ok"])
        d3d11_delta = result["native_mesh_editor_d3d11_delta"]
        self.assertTrue(d3d11_delta["native_core_available"])
        self.assertTrue(d3d11_delta["transform_delta_ok"])
        self.assertTrue(d3d11_delta["transform_screen_payload_ok"])
        self.assertTrue(d3d11_delta["transform_dispatch_target_ok"])
        self.assertTrue(d3d11_delta["dispatch_target_ok"])
        self.assertEqual(["update_mesh_edit_vertices"], d3d11_delta["transform_host_calls"])
        self.assertEqual("mesh_edit_vertices_updated", d3d11_delta["transform_update_event"]["event"])
        self.assertGreater(d3d11_delta["transform_update_event"]["changed_vertices"], 0)
        self.assertEqual(0, d3d11_delta["transform_triangle_group_count"])
        self.assertFalse(d3d11_delta["transform_replace_all_triangles"])
        self.assertGreaterEqual(d3d11_delta["transform_command"]["metrics"]["d3d11_update_ms"], 0.0)
        self.assertTrue(d3d11_delta["delta_only_ok"])
        self.assertTrue(d3d11_delta["brush_screen_payload_ok"])
        self.assertTrue(d3d11_delta["screen_payloads_without_legacy_camera_fields_ok"])
        self.assertTrue(d3d11_delta["screen_payloads_with_source_transform_overrides_ok"])
        self.assertTrue(d3d11_delta["brush_dispatch_target_ok"])
        self.assertEqual(["update_mesh_edit_vertices"], d3d11_delta["host_calls"])
        self.assertEqual("mesh_edit_vertices_updated", d3d11_delta["update_event"]["event"])
        self.assertGreater(d3d11_delta["update_event"]["changed_vertices"], 0)
        self.assertEqual(0, d3d11_delta["triangle_group_count"])
        self.assertFalse(d3d11_delta["replace_all_triangles"])
        self.assertTrue(d3d11_delta["native_fallback_ok"])
        self.assertEqual({}, d3d11_delta["native_fallback_counts"])
        self.assertTrue(d3d11_delta["native_apply_and_d3d11_metrics_ok"])
        self.assertTrue(d3d11_delta["native_history_and_d3d11_metrics_ok"])
        self.assertGreaterEqual(d3d11_delta["d3d11_update_ms"], 0.0)
        self.assertGreaterEqual(d3d11_delta["command"]["metrics"]["d3d11_update_ms"], 0.0)
        self.assertTrue(d3d11_delta["topology_delta_ok"])
        self.assertIn("replace_mesh_edit_triangles", d3d11_delta["topology_host_calls"])
        self.assertNotIn("update_mesh_edit_vertices", d3d11_delta["topology_host_calls"])
        self.assertEqual("mesh_edit_triangles_replaced", d3d11_delta["topology_update_event"]["event"])
        self.assertGreaterEqual(d3d11_delta["topology_update_event"]["replaced_batches"], 1)
        self.assertEqual([0], d3d11_delta["topology_triangle_calls"][0]["source_submesh_indices"])
        self.assertFalse(d3d11_delta["topology_replace_all_triangles"])
        self.assertGreaterEqual(d3d11_delta["topology_command"]["metrics"]["d3d11_update_ms"], 0.0)
        self.assertTrue(d3d11_delta["appended_delta_ok"])
        self.assertIn("replace_mesh_edit_triangles", d3d11_delta["appended_host_calls"])
        self.assertNotIn("update_mesh_edit_vertices", d3d11_delta["appended_host_calls"])
        self.assertEqual("mesh_edit_triangles_replaced", d3d11_delta["appended_update_event"]["event"])
        self.assertGreaterEqual(d3d11_delta["appended_update_event"]["replaced_batches"], 1)
        self.assertEqual([1], d3d11_delta["appended_triangle_calls"][0]["source_submesh_indices"])
        self.assertFalse(d3d11_delta["appended_replace_all_triangles"])
        self.assertGreater(d3d11_delta["appended_command"]["submesh_count_delta"], 0)
        self.assertGreaterEqual(d3d11_delta["appended_command"]["metrics"]["d3d11_update_ms"], 0.0)
        self.assertTrue(d3d11_delta["separated_delta_ok"])
        self.assertIn("replace_mesh_edit_triangles", d3d11_delta["separated_host_calls"])
        self.assertNotIn("update_mesh_edit_vertices", d3d11_delta["separated_host_calls"])
        self.assertEqual("mesh_edit_triangles_replaced", d3d11_delta["separated_update_event"]["event"])
        self.assertGreaterEqual(d3d11_delta["separated_update_event"]["replaced_batches"], 1)
        self.assertEqual([0, 2], d3d11_delta["separated_triangle_calls"][0]["source_submesh_indices"])
        self.assertFalse(d3d11_delta["separated_replace_all_triangles"])
        self.assertGreater(d3d11_delta["separated_command"]["submesh_count_delta"], 0)
        self.assertGreaterEqual(d3d11_delta["separated_command"]["metrics"]["d3d11_update_ms"], 0.0)

    @pytest.mark.visual
    def test_native_mesh_editor_d3d11_payload_scenario_proves_source_transform_overrides(self) -> None:
        if find_native_d3d11_host() is None:
            self.skipTest("native D3D11 preview host not built")
        with tempfile.TemporaryDirectory() as temp_dir:
            result = run_scenario("native-mesh-editor-d3d11-payloads", Path(temp_dir), allow_synthetic_d3d11=True)

        self.assertTrue(result["ok"])
        payloads = result["native_mesh_editor_d3d11_payloads"]
        self.assertTrue(payloads["screen_payloads_without_legacy_camera_fields_ok"])
        self.assertTrue(payloads["screen_payloads_with_source_transform_overrides_ok"])
        self.assertEqual("alignment_transforms", payloads["alignment_transform_status"]["event"])
        self.assertTrue(payloads["alignment_transform_status"]["ok"])

    def test_synthetic_d3d11_scenarios_are_blocked_by_default(self) -> None:
        for scenario in ("full-suite-smoke", "native-mesh-editor-d3d11-delta", "native-mesh-editor-d3d11-payloads"):
            metadata = scenario_metadata(scenario)
            self.assertFalse(metadata.headless)
            self.assertTrue(metadata.visual)

        with patch("subprocess.Popen", side_effect=AssertionError("native window launched")):
            with tempfile.TemporaryDirectory() as temp_dir:
                result = run_scenario("native-mesh-editor-d3d11-delta", Path(temp_dir))
            with tempfile.TemporaryDirectory() as temp_dir:
                full_suite = run_scenario("full-suite-smoke", Path(temp_dir))

        self.assertFalse(result["ok"])
        self.assertIn("Synthetic Mesh Editor D3D11", result["error"])
        self.assertIn("real-archive-mesh-editor-dotnet-edit-smoke", result["error"])

        self.assertFalse(full_suite["ok"])
        self.assertIn("real-archive-mesh-editor-dotnet-edit-smoke", full_suite["error"])

    def test_mesh_editor_harness_defaults_to_real_archive_visual_proof(self) -> None:
        source = "\n".join(
            Path(path).read_text(encoding="utf-8")
            for path in ("tools/mesh_harness/constants.py", "tools/mesh_harness/cli.py")
        )

        self.assertIn('_REAL_MESH_EDITOR_DOTNET_SCENARIO = "real-archive-mesh-editor-dotnet-edit-smoke"', source)
        self.assertIn("_REAL_MESH_EDITOR_VISUAL_SCENARIO = _REAL_MESH_EDITOR_DOTNET_SCENARIO", source)
        self.assertIn("default=_REAL_MESH_EDITOR_VISUAL_SCENARIO", source)

    def test_native_benchmark_mesh_meets_target_counts(self) -> None:
        mesh = build_native_benchmark_mesh()

        self.assertGreaterEqual(mesh.total_vertices, 100_000)
        self.assertGreaterEqual(mesh.total_faces, 200_000)
        self.assertEqual(mesh.total_vertices, len(mesh.submeshes[0].vertices))
        self.assertEqual(mesh.total_faces, len(mesh.submeshes[0].faces))

    def test_real_archive_visual_proof_uses_production_textures_and_truth_gates(self) -> None:
        source = Path("tools/mesh_harness/real_d3d.py").read_text(encoding="utf-8")

        self.assertNotIn("real_archive_checker.png", source)
        self.assertIn("_resolve_real_archive_mesh_textures", source)
        for gate in (
            "archive_sources_unchanged",
            "source_payload_unchanged",
            "texture_gate_ok",
            "live_stroke_frame_budget_ok",
            "read_only_ok",
            "fallback_gate_ok",
        ):
            self.assertIn(gate, source)

    def test_real_archive_texture_resolution_attaches_production_archive_source(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            source_path = Path(temp_dir) / "body.dds"
            source_path.write_bytes(b"DDS production texture")
            mesh = build_synthetic_mesh()
            entry = ArchiveEntry(
                path="character/model/body.pac",
                pamt_path=Path(temp_dir) / "0.pamt",
                paz_file=Path(temp_dir) / "0.paz",
                offset=0,
                comp_size=1,
                orig_size=1,
                flags=0,
                paz_index=0,
            )
            with patch(
                "tools.mesh_harness.archive_provenance.resolve_mesh_texture_source",
                return_value=MeshTextureSourceResolution(
                    source_path=source_path,
                    archive_entry=entry,
                    archive_path="character/texture/body.dds",
                    status="archive",
                ),
            ):
                rows = _resolve_real_archive_mesh_textures(mesh, entry, {}, {})

        self.assertEqual(1, len(rows))
        self.assertEqual("character/texture/body.dds", rows[0]["archive_path"])
        self.assertEqual(str(source_path.resolve()), mesh.submeshes[0].texture)

    def test_sparse_update_soak_is_headless_and_defaults_to_exit_gate_scale(self) -> None:
        metadata = scenario_metadata("native-mesh-editor-sparse-update-soak")
        mesh = build_sparse_update_soak_mesh(32)

        self.assertTrue(metadata.headless)
        self.assertFalse(metadata.visual)
        self.assertEqual("native-mesh-core", metadata.expected_backend)
        self.assertGreaterEqual(metadata.timeout_seconds, 600.0)
        self.assertEqual(1_000_000, SPARSE_SOAK_VERTEX_COUNT)
        self.assertEqual(1_000, SPARSE_SOAK_UPDATE_COUNT)
        self.assertEqual(32, mesh.total_vertices)
        self.assertEqual(32, len(mesh.submeshes[0].vertices))
        self.assertEqual(1, mesh.total_faces)
        source = Path("tools/mesh_harness/scenario_runner.py").read_text(encoding="utf-8")
        self.assertIn("native-mesh-editor-sparse-update-soak", source)
        self.assertIn("run_sparse_update_soak", source)
