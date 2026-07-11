bool Renderer::handle_package_commands(const std::string& command, const std::string& payload, bool& matched) {
        matched = true;
        if (command == "load_package") {
            pending_package_dir_ = utf8_to_wide(json_string_field(payload, "package_dir"));
            pending_status_file_ = utf8_to_wide(json_string_field(payload, "status_file"));
            pending_reset_view_ = json_bool_field(payload, "reset_view", false);
            if (json_has_field(payload, "side_by_side_split_ratio")) {
                set_side_by_side_split_ratio(json_float_field(payload, "side_by_side_split_ratio", side_by_side_split_ratio_));
            }
            request_render();
            cdmw_native_diag::event("command_load_package", {{"package_dir", cdmw_native_diag::path_to_utf8(fs::path(pending_package_dir_))}, {"status_file", cdmw_native_diag::path_to_utf8(fs::path(pending_status_file_))}});
            send_json_event("{\"event\":\"command_result\",\"command\":\"load_package\",\"ok\":true,\"queued\":true}");
            return true;
        }
        if (command == "clear_preview") {
            fs::path status_file = utf8_to_wide(json_string_field(payload, "status_file"));
            cdmw_native_diag::event("command_clear_preview", {{"status_file", cdmw_native_diag::path_to_utf8(status_file)}});
            clear_preview(status_file);
            send_json_event("{\"event\":\"command_result\",\"command\":\"clear_preview\",\"ok\":true}");
            return true;
        }
        if (command == "set_display_mode") {
            std::string mode = normalize_display_mode(json_string_field(payload, "mode", display_mode_), display_mode_);
            if (json_has_field(payload, "side_by_side_split_ratio")) {
                set_side_by_side_split_ratio(json_float_field(payload, "side_by_side_split_ratio", side_by_side_split_ratio_));
            }
            display_mode_ = mode;
            request_render();
            cdmw_native_diag::event("command_set_display_mode", {{"mode", display_mode_}});
            std::ostringstream event;
            event << "{\"event\":\"display_mode\",\"mode\":\"" << json_escape(display_mode_) << "\"}";
            send_json_event(event.str());
            if (hwnd_) {
                InvalidateRect(hwnd_, nullptr, FALSE);
            }
            return true;
        }
        if (command == "set_side_by_side_split") {
            set_side_by_side_split_ratio(json_float_field(payload, "ratio", side_by_side_split_ratio_));
            request_render();
            send_side_by_side_split_event("command");
            if (hwnd_) {
                InvalidateRect(hwnd_, nullptr, FALSE);
            }
            return true;
        }
        if (command == "set_render_tuning") {
            render_tuning_ = parse_render_tuning(payload);
            view_settings_ = parse_view_settings(payload);
            cloth_state_.enabled = json_bool_field(payload, "enable_tool_pbd_cloth_preview", cloth_state_.enabled);
            cloth_state_.paused = json_bool_field(payload, "pause_tool_pbd_cloth_preview", cloth_state_.paused);
            cloth_state_.show_pins = json_bool_field(payload, "show_tool_pbd_cloth_pins", cloth_state_.show_pins);
            cloth_state_.show_colliders = json_bool_field(payload, "show_tool_pbd_cloth_colliders", cloth_state_.show_colliders);
            cloth_state_.wind_strength = std::clamp(json_float_field(payload, "tool_pbd_cloth_wind_strength", cloth_state_.wind_strength), 0.0f, 2.0f);
            cloth_state_.wind_direction_degrees = std::clamp(json_float_field(payload, "tool_pbd_cloth_wind_direction_degrees", cloth_state_.wind_direction_degrees), -180.0f, 180.0f);
            if (json_bool_field(payload, "reset_tool_pbd_cloth_preview", false)) {
                reset_cloth_runtime();
            }
            render_tuning_overridden_ = true;
            view_settings_overridden_ = true;
            const bool sampler_ok = create_sampler_state();
            request_render();
            cdmw_native_diag::event(
                "command_set_render_tuning",
                {
                    {"max_anisotropy", std::to_string(render_tuning_.max_anisotropy)},
                    {"diagnostic_mode", std::to_string(render_tuning_.diagnostic_mode)},
                    {"d3d11_mip_lod_bias", std::to_string(render_tuning_.mip_lod_bias)},
                    {"d3d11_cull_back_faces", render_tuning_.cull_back_faces ? "true" : "false"},
                    {"d3d11_texture_address_mode", render_tuning_.texture_address_mode},
                    {"ambient_strength", std::to_string(render_tuning_.ambient_strength)},
                    {"diffuse_wrap_bias", std::to_string(render_tuning_.diffuse_wrap_bias)},
                    {"diffuse_light_scale", std::to_string(render_tuning_.diffuse_light_scale)},
                    {"specular_max", std::to_string(render_tuning_.specular_max)},
                    {"sampler_ok", sampler_ok ? "true" : "false"}
                });
            std::ostringstream event;
            event << "{\"event\":\"render_tuning\",\"ok\":" << (sampler_ok ? "true" : "false")
                  << ",\"max_anisotropy\":" << render_tuning_.max_anisotropy
                  << ",\"diagnostic_mode\":" << render_tuning_.diagnostic_mode
                  << ",\"d3d11_mip_lod_bias\":" << render_tuning_.mip_lod_bias
                  << ",\"d3d11_cull_back_faces\":" << (render_tuning_.cull_back_faces ? "true" : "false")
                  << ",\"d3d11_texture_address_mode\":\"" << json_escape(render_tuning_.texture_address_mode) << "\""
                  << ",\"ambient_strength\":" << render_tuning_.ambient_strength
                  << ",\"diffuse_wrap_bias\":" << render_tuning_.diffuse_wrap_bias
                  << ",\"diffuse_light_scale\":" << render_tuning_.diffuse_light_scale
                  << ",\"specular_max\":" << render_tuning_.specular_max
                  << ",\"sampler_max_anisotropy\":" << stats_.sampler_max_anisotropy
                  << ",\"sampler_mip_lod_bias\":" << stats_.sampler_mip_lod_bias
                  << ",\"sampler_recreate_count\":" << stats_.sampler_recreate_count
                  << ",\"cloth_enabled\":" << (cloth_state_.enabled ? "true" : "false")
                  << "}";
            send_json_event(event.str());
            return true;
        }
        if (command == "reset_tool_pbd_cloth_preview") {
            reset_cloth_runtime();
            request_render();
            send_json_event("{\"event\":\"cloth_preview_reset\",\"ok\":true}");
            return true;
        }
        matched = false;
        return false;
    }

bool Renderer::handle_material_commands(const std::string& command, const std::string& payload, bool& matched) {
        matched = true;
        if (command == "set_highlights") {
            std::set<int> highlighted;
            for (int value : json_int_array_field(payload, "source_submesh_indices")) {
                highlighted.insert(value);
            }
            std::set<int> highlighted_replacement;
            for (int value : json_int_array_field(payload, "replacement_submesh_indices")) {
                highlighted_replacement.insert(value);
            }
            std::set<int> highlighted_original;
            for (int value : json_int_array_field(payload, "original_submesh_indices")) {
                highlighted_original.insert(value);
            }
            const bool role_scoped = !highlighted_replacement.empty() || !highlighted_original.empty();
            int highlighted_batches = 0;
            for (PreviewBatch& batch : batches_) {
                std::string role = lower_copy(batch.editor_role);
                bool active = false;
                if (role_scoped && role == "original_reference") {
                    active = highlighted_original.find(batch.source_submesh_index) != highlighted_original.end();
                } else if (role_scoped && role == "replacement_preview") {
                    active = highlighted_replacement.find(batch.source_submesh_index) != highlighted_replacement.end();
                } else {
                    active = highlighted.find(batch.source_submesh_index) != highlighted.end();
                }
                batch.highlight_strength = active ? (role == "original_reference" ? 0.82f : 0.74f) : 0.0f;
                if (active) ++highlighted_batches;
            }
            request_render();
            std::ostringstream event;
            event << "{\"event\":\"highlight_state\",\"highlighted_batches\":" << highlighted_batches << "}";
            send_json_event(event.str());
            return true;
        }
        if (command == "set_hidden_source_submeshes") {
            hidden_source_submeshes_.clear();
            for (int value : json_int_array_field(payload, "source_submesh_indices")) {
                if (value >= 0) hidden_source_submeshes_.insert(value);
            }
            int visible_batches = 0;
            for (const PreviewBatch& batch : batches_) {
                if (batch.source_submesh_index < 0 || hidden_source_submeshes_.find(batch.source_submesh_index) == hidden_source_submeshes_.end()) {
                    ++visible_batches;
                }
            }
            request_render();
            std::ostringstream event;
            event << "{\"event\":\"part_visibility\",\"hidden_parts\":" << hidden_source_submeshes_.size()
                  << ",\"visible_batches\":" << visible_batches << "}";
            send_json_event(event.str());
            return true;
        }
        if (command == "set_material_overrides") {
            const std::string requested_role = lower_copy(json_string_field(payload, "editor_role", "replacement_preview"));
            std::set<int> requested_sources;
            for (int value : json_int_array_field(payload, "source_submesh_indices")) {
                if (value >= 0) requested_sources.insert(value);
            }
            const bool scoped_sources = !requested_sources.empty();
            const bool has_brightness = json_has_field(payload, "texture_brightness");
            const bool has_roughness = json_has_field(payload, "roughness");
            const bool has_metalness = json_has_field(payload, "metalness");
            const bool has_specular = json_has_field(payload, "specular");
            const bool has_height_scale = json_has_field(payload, "height_scale");
            const bool has_emissive_intensity = json_has_field(payload, "emissive_intensity");
            const bool has_contrast = json_has_field(payload, "contrast");
            const bool has_saturation = json_has_field(payload, "saturation");
            const bool has_gamma = json_has_field(payload, "gamma");
            const std::vector<float> emissive_color = json_float_array_field(payload, "emissive_color");
            const std::vector<float> tint_color = json_float_array_field(payload, "tint_color");
            int updated_batches = 0;
            for (PreviewBatch& batch : batches_) {
                const std::string role = lower_copy(batch.editor_role);
                if (!requested_role.empty() && requested_role != "all" && role != requested_role) continue;
                if (scoped_sources && requested_sources.find(batch.source_submesh_index) == requested_sources.end()) continue;
                if (has_brightness) batch.texture_brightness = std::clamp(json_float_field(payload, "texture_brightness", batch.texture_brightness), 0.1f, 3.0f);
                if (has_roughness) batch.roughness_hint = std::clamp(json_float_field(payload, "roughness", batch.roughness_hint), 0.0f, 1.0f);
                if (has_metalness) batch.metalness_hint = std::clamp(json_float_field(payload, "metalness", batch.metalness_hint), 0.0f, 1.0f);
                if (has_specular) batch.specular_hint = std::clamp(json_float_field(payload, "specular", batch.specular_hint), 0.0f, 1.0f);
                if (has_height_scale) batch.height_scale_hint = std::clamp(json_float_field(payload, "height_scale", batch.height_scale_hint), 0.0f, 1.0f);
                if (has_emissive_intensity) batch.emissive_intensity = std::clamp(json_float_field(payload, "emissive_intensity", batch.emissive_intensity), 0.0f, 32.0f);
                if (has_contrast) batch.texture_contrast = std::clamp(json_float_field(payload, "contrast", batch.texture_contrast), 0.25f, 2.5f);
                if (has_saturation) batch.texture_saturation = std::clamp(json_float_field(payload, "saturation", batch.texture_saturation), 0.0f, 4.0f);
                if (has_gamma) batch.texture_gamma = std::clamp(json_float_field(payload, "gamma", batch.texture_gamma), 0.25f, 4.0f);
                if (emissive_color.size() >= 3) {
                    batch.emissive_color[0] = std::clamp(emissive_color[0], 0.0f, 2.0f);
                    batch.emissive_color[1] = std::clamp(emissive_color[1], 0.0f, 2.0f);
                    batch.emissive_color[2] = std::clamp(emissive_color[2], 0.0f, 2.0f);
                }
                if (tint_color.size() >= 3) {
                    batch.texture_tint[0] = std::clamp(tint_color[0], 0.0f, 4.0f);
                    batch.texture_tint[1] = std::clamp(tint_color[1], 0.0f, 4.0f);
                    batch.texture_tint[2] = std::clamp(tint_color[2], 0.0f, 4.0f);
                }
                ++updated_batches;
            }
            request_render();
            std::ostringstream event;
            event << "{\"event\":\"material_overrides\",\"updated_batches\":" << updated_batches << "}";
            send_json_event(event.str());
            return true;
        }
        matched = false;
        return false;
    }

bool Renderer::handle_interaction_commands(const std::string& command, const std::string& payload, bool& matched) {
        matched = true;
        if (command == "set_texture_flip_vertical") {
            const bool enabled = json_bool_field(payload, "enabled", false);
            const std::string requested_role = lower_copy(json_string_field(payload, "editor_role", "replacement_preview"));
            std::set<int> source_filter;
            for (int value : json_int_array_field(payload, "source_submesh_indices")) {
                if (value >= 0) source_filter.insert(value);
            }
            int changed_batches = 0;
            int matched_batches = 0;
            for (PreviewBatch& batch : batches_) {
                const std::string role = lower_copy(batch.editor_role);
                if (!requested_role.empty() && requested_role != "all" && role != requested_role) {
                    continue;
                }
                if (!source_filter.empty() && source_filter.find(batch.source_submesh_index) == source_filter.end()) {
                    continue;
                }
                ++matched_batches;
                if (batch.flip_v != enabled) {
                    batch.flip_v = enabled;
                    ++changed_batches;
                }
            }
            if (changed_batches > 0) {
                request_render();
                if (hwnd_) {
                    InvalidateRect(hwnd_, nullptr, FALSE);
                }
            }
            std::ostringstream event;
            event << "{\"event\":\"texture_flip_vertical\",\"enabled\":" << (enabled ? "true" : "false")
                  << ",\"matched_batches\":" << matched_batches
                  << ",\"changed_batches\":" << changed_batches
                  << "}";
            send_json_event(event.str());
            return true;
        }
        if (command == "set_icon_capture_mode") {
            icon_capture_mode_ = json_bool_field(payload, "enabled", icon_capture_mode_);
            if (icon_capture_mode_) {
                alignment_.hover_axis.clear();
                alignment_.drag_axis.clear();
            }
            request_render();
            send_json_event("{\"event\":\"icon_capture_mode\",\"ok\":true}");
            return true;
        }
        if (command == "set_source_part_picking") {
            bool previous = source_part_.picking_enabled;
            source_part_.picking_enabled = json_bool_field(payload, "enabled", source_part_.picking_enabled);
            if (!source_part_.picking_enabled) {
                source_part_.click_pending = false;
                if (source_part_.hovered_source_submesh >= 0) {
                    source_part_.hovered_source_submesh = -1;
                    send_source_part_event("source_part_hovered", -1);
                }
            } else if (!previous) {
                source_part_.hovered_source_submesh = -1;
            }
            request_render();
            send_json_event("{\"event\":\"source_part_picking\",\"ok\":true}");
            return true;
        }
        if (command == "set_skeleton_overlay") {
            skeleton_overlay_.selected_bone_index = json_int_field(payload, "selected_bone_index", skeleton_overlay_.selected_bone_index);
            stats_.skeleton_selected_bone_index = skeleton_overlay_.selected_bone_index;
            request_render();
            if (hwnd_) {
                InvalidateRect(hwnd_, nullptr, FALSE);
            }
            std::ostringstream event;
            event << "{\"event\":\"skeleton_overlay\",\"selected_bone_index\":" << skeleton_overlay_.selected_bone_index << "}";
            send_json_event(event.str());
            return true;
        }
        matched = false;
        return false;
    }

bool Renderer::handle_edit_state_commands(const std::string& command, const std::string& payload, bool& matched) {
        matched = true;
        if (command == "set_mesh_edit_state") {
            mesh_edit_.enabled = json_bool_field(payload, "enabled", mesh_edit_.enabled);
            mesh_edit_.scope_mode = lower_copy(json_string_field(payload, "scope_mode", mesh_edit_.scope_mode));
            mesh_edit_.target_mode = lower_copy(json_string_field(payload, "target_mode", mesh_edit_.target_mode));
            mesh_edit_.tool = lower_copy(json_string_field(payload, "tool", mesh_edit_.tool));
            mesh_edit_.delete_mode = lower_copy(json_string_field(payload, "delete_mode", mesh_edit_.delete_mode));
            mesh_edit_.selection_mode = lower_copy(json_string_field(payload, "selection_mode", mesh_edit_.selection_mode));
            if (mesh_edit_.selection_mode != "brush" && mesh_edit_.selection_mode != "lasso" && mesh_edit_.selection_mode != "rectangle") {
                mesh_edit_.selection_mode = "brush";
            }
            mesh_edit_.selection_depth_mode = lower_copy(json_string_field(payload, "selection_depth_mode", mesh_edit_.selection_depth_mode));
            if (mesh_edit_.selection_depth_mode != "visible" && mesh_edit_.selection_depth_mode != "xray") {
                mesh_edit_.selection_depth_mode = "visible";
            }
            mesh_edit_.falloff = lower_copy(json_string_field(payload, "falloff", mesh_edit_.falloff));
            mesh_edit_.radius_pixels = std::clamp(json_float_field(payload, "radius_pixels", mesh_edit_.radius_pixels), 2.0f, 512.0f);
            mesh_edit_.strength = std::clamp(json_float_field(payload, "strength", mesh_edit_.strength), 0.0f, 1.0f);
            mesh_edit_.smooth_iterations = std::clamp(static_cast<int>(json_float_field(payload, "smooth_iterations", static_cast<float>(mesh_edit_.smooth_iterations))), 1, 12);
            mesh_edit_.show_vertices = json_bool_field(payload, "show_vertices", mesh_edit_.show_vertices);
            mesh_edit_.source_submesh_indices.clear();
            for (int value : json_int_array_field(payload, "source_submesh_indices")) {
                if (value >= 0) mesh_edit_.source_submesh_indices.insert(value);
            }
            invalidate_mesh_edit_caches();
            if (!mesh_edit_.enabled) {
                cancel_mesh_edit_drag();
            }
            request_render();
            send_json_event("{\"event\":\"mesh_edit_state\",\"ok\":true}");
            return true;
        }
        if (command == "set_alignment_state") {
            alignment_.enabled = json_bool_field(payload, "enabled", alignment_.enabled);
            alignment_.translation_sensitivity = std::clamp(
                json_float_field(payload, "translation_sensitivity", alignment_.translation_sensitivity),
                0.05f,
                10.0f);
            alignment_.rotation_degrees_per_pixel = std::clamp(
                json_float_field(payload, "rotation_degrees_per_pixel", alignment_.rotation_degrees_per_pixel),
                0.001f,
                8.0f);
            alignment_.selected_source_submeshes.clear();
            for (int value : json_int_array_field(payload, "source_submesh_indices")) {
                if (value >= 0) alignment_.selected_source_submeshes.insert(value);
            }
            alignment_.origin_cache_valid = false;
            if (!alignment_.enabled) {
                cancel_alignment_drag();
                alignment_.hover_axis.clear();
            }
            request_render();
            send_json_event("{\"event\":\"alignment_state\",\"ok\":true}");
            return true;
        }
        if (command == "set_alignment_transform") {
            alignment_.part_transforms.clear();
            alignment_.part_translation_drag_bases.clear();
            alignment_.part_rotation_drag_bases.clear();
            alignment_.translation_total = DirectX::XMFLOAT3(
                json_float_field(payload, "translation_x", alignment_.translation_total.x),
                json_float_field(payload, "translation_y", alignment_.translation_total.y),
                json_float_field(payload, "translation_z", alignment_.translation_total.z));
            alignment_.rotation_total = DirectX::XMFLOAT3(
                json_float_field(payload, "rotation_x", alignment_.rotation_total.x),
                json_float_field(payload, "rotation_y", alignment_.rotation_total.y),
                json_float_field(payload, "rotation_z", alignment_.rotation_total.z));
            alignment_.scale_total = DirectX::XMFLOAT3(
                std::clamp(json_float_field(payload, "scale_x", alignment_.scale_total.x), 0.001f, 1000.0f),
                std::clamp(json_float_field(payload, "scale_y", alignment_.scale_total.y), 0.001f, 1000.0f),
                std::clamp(json_float_field(payload, "scale_z", alignment_.scale_total.z), 0.001f, 1000.0f));
            request_render();
            send_json_event("{\"event\":\"alignment_transform\",\"ok\":true}");
            return true;
        }
        if (command == "set_alignment_transforms") {
            auto triple = [](const std::string& object, const std::string& name, const DirectX::XMFLOAT3& fallback) {
                std::vector<float> values = json_float_array_field(object, name);
                if (values.size() < 3u) return fallback;
                return DirectX::XMFLOAT3(values[0], values[1], values[2]);
            };
            const std::string global = json_object_field(payload, "global");
            if (!global.empty()) {
                alignment_.translation_total = triple(global, "translation", DirectX::XMFLOAT3(0.0f, 0.0f, 0.0f));
                alignment_.rotation_total = triple(global, "rotation_degrees", DirectX::XMFLOAT3(0.0f, 0.0f, 0.0f));
                alignment_.scale_total = triple(global, "scale_xyz", DirectX::XMFLOAT3(1.0f, 1.0f, 1.0f));
                alignment_.scale_total.x = std::clamp(alignment_.scale_total.x, 0.001f, 1000.0f);
                alignment_.scale_total.y = std::clamp(alignment_.scale_total.y, 0.001f, 1000.0f);
                alignment_.scale_total.z = std::clamp(alignment_.scale_total.z, 0.001f, 1000.0f);
            }
            alignment_.part_transforms.clear();
            for (const std::string& item : json_object_array_field(payload, "parts")) {
                AlignmentState::PartTransform transform;
                transform.translation = triple(item, "translation", DirectX::XMFLOAT3(0.0f, 0.0f, 0.0f));
                transform.rotation = triple(item, "rotation_degrees", DirectX::XMFLOAT3(0.0f, 0.0f, 0.0f));
                transform.scale = triple(item, "scale_xyz", DirectX::XMFLOAT3(1.0f, 1.0f, 1.0f));
                transform.scale.x = std::clamp(transform.scale.x, 0.001f, 1000.0f);
                transform.scale.y = std::clamp(transform.scale.y, 0.001f, 1000.0f);
                transform.scale.z = std::clamp(transform.scale.z, 0.001f, 1000.0f);
                for (int source_index : json_int_array_field(item, "source_submesh_indices")) {
                    if (source_index >= 0) {
                        alignment_.part_transforms[source_index] = transform;
                    }
                }
            }
            alignment_.part_translation_drag_bases.clear();
            alignment_.part_rotation_drag_bases.clear();
            alignment_.origin_cache_valid = false;
            request_render();
            send_json_event("{\"event\":\"alignment_transforms\",\"ok\":true}");
            return true;
        }
        matched = false;
        return false;
    }

bool Renderer::handle_selection_commands(const std::string& command, const std::string& payload, bool& matched) {
        matched = true;
        if (command == "clear_mesh_edit_selection") {
            mesh_edit_.selected_vertices.clear();
            mesh_edit_.selected_edges.clear();
            mesh_edit_.selected_faces.clear();
            mesh_edit_.selected_sources.clear();
            send_mesh_edit_selection_event();
            request_render();
            return true;
        }
        if (command == "set_mesh_edit_selection") {
            mesh_edit_.selected_vertices.clear();
            mesh_edit_.selected_edges.clear();
            mesh_edit_.selected_faces.clear();
            mesh_edit_.selected_sources.clear();
            for (const std::string& group : json_object_array_field(payload, "groups")) {
                int source_submesh = static_cast<int>(json_float_field(group, "source_submesh_index", -1.0f));
                if (source_submesh < 0) continue;
                if (json_bool_field(group, "source_selected", false)) {
                    mesh_edit_.selected_sources.insert(source_submesh);
                    add_mesh_edit_source_vertices_to_selection(source_submesh);
                }
                for (int source_vertex : json_i32_range_or_array_or_json_field(
                         group,
                         "source_vertex_indices_binary",
                         "source_vertex_indices",
                         "source_vertex_start",
                         "source_vertex_count")) {
                    if (source_vertex >= 0) {
                        mesh_edit_.selected_vertices.insert(std::pair<int, int>(source_submesh, source_vertex));
                    }
                }
                const std::vector<int> source_edges = json_i32_array_or_json_values_field(group, "source_edges_binary", "source_edges");
                for (size_t index = 0; index + 1u < source_edges.size(); index += 2u) {
                    const int left = source_edges[index];
                    const int right = source_edges[index + 1u];
                    if (left >= 0) mesh_edit_.selected_vertices.insert(std::pair<int, int>(source_submesh, left));
                    if (right >= 0) mesh_edit_.selected_vertices.insert(std::pair<int, int>(source_submesh, right));
                    if (left >= 0 && right >= 0 && left != right) {
                        mesh_edit_.selected_edges.insert(mesh_edit_edge_key(source_submesh, left, right));
                    }
                }
                std::set<int> source_faces;
                for (int source_face : json_i32_range_or_array_or_json_field(
                         group,
                         "source_face_indices_binary",
                         "source_face_indices",
                         "source_face_start",
                         "source_face_count")) {
                    if (source_face >= 0) {
                        source_faces.insert(source_face);
                        mesh_edit_.selected_faces.insert(std::pair<int, int>(source_submesh, source_face));
                    }
                }
                add_mesh_edit_face_vertices_to_selection(source_submesh, source_faces);
            }
            send_mesh_edit_selection_event();
            request_render();
            return true;
        }
        if (command == "select_mesh_edit_brush") {
            const int brush_x = json_int_field(payload, "x", last_mouse_x_);
            const int brush_y = json_int_field(payload, "y", last_mouse_y_);
            last_mouse_x_ = brush_x;
            last_mouse_y_ = brush_y;
            const std::string target_mode = lower_copy(json_string_field(payload, "target_mode", mesh_edit_.target_mode));
            if (target_mode == "vertex" || target_mode == "edge" || target_mode == "face" || target_mode == "source") {
                mesh_edit_.target_mode = target_mode;
            }
            mesh_edit_.selection_mode = "brush";
            mesh_edit_.selection_operation = lower_copy(json_string_field(payload, "operation", "replace"));
            apply_mesh_edit_brush_selection(brush_x, brush_y);
            request_render();
            return true;
        }
        if (command == "select_mesh_edit_region") {
            const std::string target_mode = lower_copy(json_string_field(payload, "target_mode", mesh_edit_.target_mode));
            if (target_mode == "vertex" || target_mode == "edge" || target_mode == "face" || target_mode == "source") {
                mesh_edit_.target_mode = target_mode;
            }
            mesh_edit_.selection_mode = lower_copy(json_string_field(payload, "selection_mode", mesh_edit_.selection_mode));
            if (mesh_edit_.selection_mode != "rectangle" && mesh_edit_.selection_mode != "lasso") {
                mesh_edit_.selection_mode = "rectangle";
            }
            mesh_edit_.selection_operation = lower_copy(json_string_field(payload, "operation", "replace"));
            mesh_edit_.selection_depth_mode = lower_copy(json_string_field(payload, "selection_depth_mode", mesh_edit_.selection_depth_mode));
            if (mesh_edit_.selection_depth_mode != "visible" && mesh_edit_.selection_depth_mode != "xray") {
                mesh_edit_.selection_depth_mode = "visible";
            }
            mesh_edit_.start_x = json_int_field(payload, "start_x", last_mouse_x_);
            mesh_edit_.start_y = json_int_field(payload, "start_y", last_mouse_y_);
            const int end_x = json_int_field(payload, "end_x", json_int_field(payload, "x", mesh_edit_.start_x));
            const int end_y = json_int_field(payload, "end_y", json_int_field(payload, "y", mesh_edit_.start_y));
            mesh_edit_.last_x = end_x;
            mesh_edit_.last_y = end_y;
            mesh_edit_.selection_lasso_points.clear();
            const std::vector<float> points = json_float_array_field(payload, "points");
            for (size_t index = 0; index + 1u < points.size(); index += 2u) {
                mesh_edit_.selection_lasso_points.push_back(DirectX::XMFLOAT2(points[index], points[index + 1u]));
            }
            apply_mesh_edit_region_selection(end_x, end_y);
            request_render();
            return true;
        }
        matched = false;
        return false;
    }

bool Renderer::handle_edit_update_commands(const std::string& command, const std::string& payload, bool& matched) {
        matched = true;
        if (command == "update_mesh_edit_vertices") {
            queue_mesh_edit_vertices_payload(payload, mesh_edit_revision_field(payload));
            return true;
        }
        if (command == "update_mesh_edit_vertices_file") {
            const fs::path payload_file = utf8_to_wide(json_string_field(payload, "payload_file"));
            const bool delete_after = json_bool_field(payload, "delete_after", true);
            queue_mesh_edit_vertices_file(payload_file, delete_after, mesh_edit_revision_field(payload));
            return true;
        }
        if (command == "replace_mesh_edit_triangles") {
            const auto [replaced_batches, removed_batches] = replace_mesh_edit_triangles_from_payload(payload);
            request_render();
            std::ostringstream event;
            event << "{\"event\":\"mesh_edit_triangles_replaced\",\"replaced_batches\":" << replaced_batches
                  << ",\"removed_batches\":" << removed_batches << "}";
            send_json_event(event.str());
            return true;
        }
        if (command == "replace_mesh_edit_triangles_file") {
            const fs::path payload_file = utf8_to_wide(json_string_field(payload, "payload_file"));
            const bool delete_after = json_bool_field(payload, "delete_after", true);
            const std::string file_payload = payload_file.empty() ? std::string() : read_text(payload_file);
            const auto [replaced_batches, removed_batches] = file_payload.empty()
                ? std::pair<int, int>(0, 0)
                : replace_mesh_edit_triangles_from_payload(file_payload);
            if (delete_after && !payload_file.empty()) {
                const std::wstring filename = payload_file.filename().wstring();
                if (filename.rfind(L"cdmw_mesh_edit_triangles_", 0) == 0) {
                    std::error_code ec;
                    fs::remove(payload_file, ec);
                }
            }
            request_render();
            std::ostringstream event;
            event << "{\"event\":\"mesh_edit_triangles_replaced\",\"replaced_batches\":" << replaced_batches
                  << ",\"removed_batches\":" << removed_batches
                  << ",\"payload_file\":true}";
            send_json_event(event.str());
            return true;
        }
        if (command == "capture_frame") {
            const fs::path output = utf8_to_wide(json_string_field(payload, "path"));
            if (output.empty()) {
                send_json_event("{\"event\":\"frame_capture\",\"ok\":false,\"message\":\"capture path is empty\"}");
                return false;
            }
            pending_capture_path_ = output;
            request_render();
            render();
            return true;
        }
        if (command == "get_status") {
            update_runtime_stats();
            send_json_event(loaded_payload_for_event(stats_, "status"));
            return true;
        }
        if (command == "set_view") {
            std::string role_name = lower_copy(json_string_field(payload, "role", "replacement"));
            PreviewViewRole role = PreviewViewRole::Replacement;
            if (role_name == "reference") {
                role = PreviewViewRole::Reference;
            } else if (role_name == "all") {
                role = PreviewViewRole::All;
            }
            PreviewCameraState camera = camera_for_view_role(role);
            camera.yaw = json_float_field(payload, "yaw", camera.yaw);
            camera.pitch = std::clamp(json_float_field(payload, "pitch", camera.pitch), -89.0f, 89.0f);
            camera.zoom_factor = std::clamp(json_float_field(payload, "zoom_factor", camera.zoom_factor), 0.1f, kMaxZoomFactor);
            camera.fit_to_view = json_bool_field(payload, "fit_to_view", camera.fit_to_view);
            camera.distance = camera.fit_to_view ? kFitDistance : kFitDistance / std::max(camera.zoom_factor, 0.1f);
            camera.pan_x = json_float_field(payload, "pan_x", camera.pan_x);
            camera.pan_y = json_float_field(payload, "pan_y", camera.pan_y);
            camera.pan_z = json_float_field(payload, "pan_z", camera.pan_z);
            set_camera_for_role(role, camera);
            send_view_event("set_view", role);
            request_render();
            return true;
        }
        matched = false;
        return false;
    }

bool Renderer::handle_copy_data(const COPYDATASTRUCT* cds) {
        if (!cds || cds->dwData != kCdmwCommandCopyData || !cds->lpData || cds->cbData == 0) return false;
        const char* data = reinterpret_cast<const char*>(cds->lpData);
        size_t payload_size = static_cast<size_t>(cds->cbData);
        if (payload_size > 0 && data[payload_size - 1] == '\0') --payload_size;
        std::string payload(data, data + payload_size);
        std::string command = lower_copy(json_string_field(payload, "command"));
        bool matched = false;
        if (const bool result = handle_package_commands(command, payload, matched); matched) return result;
        if (const bool result = handle_material_commands(command, payload, matched); matched) return result;
        if (const bool result = handle_interaction_commands(command, payload, matched); matched) return result;
        if (const bool result = handle_edit_state_commands(command, payload, matched); matched) return result;
        if (const bool result = handle_selection_commands(command, payload, matched); matched) return result;
        if (const bool result = handle_edit_update_commands(command, payload, matched); matched) return result;
        send_json_event("{\"event\":\"warning\",\"message\":\"unknown D3D11 host command\"}");
        return false;
    }
