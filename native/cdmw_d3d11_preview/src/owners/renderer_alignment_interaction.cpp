bool Renderer::update_alignment_translation_drag(int x, int y, WPARAM wparam) {
        if (!alignment_.drag_active || alignment_.drag_axis.empty()) return false;
        int delta_x = x - alignment_.last_x;
        int delta_y = y - alignment_.last_y;
        alignment_.last_x = x;
        alignment_.last_y = y;
        if (delta_x == 0 && delta_y == 0) return true;
        bool shift_down = (wparam & MK_SHIFT) != 0 || (GetKeyState(VK_SHIFT) & 0x8000) != 0;
        bool ctrl_down = (wparam & MK_CONTROL) != 0 || (GetKeyState(VK_CONTROL) & 0x8000) != 0;
        float movement_scale = shift_down ? 0.10f : (ctrl_down ? 4.0f : 1.0f);
        float units_per_pixel = world_units_per_pixel() * std::max(0.01f, alignment_.translation_sensitivity) * movement_scale;
        DirectX::XMFLOAT3 delta(0.0f, 0.0f, 0.0f);
        if (alignment_.drag_axis == "screen") {
            delta = alignment_screen_drag_delta(delta_x, delta_y, units_per_pixel);
        } else {
            auto points = alignment_axis_points();
            auto found = points.find(alignment_.drag_axis);
            if (found == points.end()) return true;
            float axis_dx = found->second.second.x - found->second.first.x;
            float axis_dy = found->second.second.y - found->second.first.y;
            float axis_length = std::max(std::hypot(axis_dx, axis_dy), 1.0f);
            float projected_pixels = (static_cast<float>(delta_x) * axis_dx + static_cast<float>(delta_y) * axis_dy) / axis_length;
            float movement = projected_pixels * units_per_pixel;
            if (alignment_.drag_axis == "x") delta.x = movement;
            else if (alignment_.drag_axis == "y") delta.y = movement;
            else if (alignment_.drag_axis == "z") delta.z = movement;
        }
        alignment_.translation_drag_delta.x += delta.x;
        alignment_.translation_drag_delta.y += delta.y;
        alignment_.translation_drag_delta.z += delta.z;
        if (!alignment_.selected_source_submeshes.empty()) {
            for (int source_index : alignment_.selected_source_submeshes) {
                DirectX::XMFLOAT3 base = alignment_.part_translation_drag_bases[source_index];
                alignment_.part_transforms[source_index].translation = DirectX::XMFLOAT3(
                    base.x + alignment_.translation_drag_delta.x,
                    base.y + alignment_.translation_drag_delta.y,
                    base.z + alignment_.translation_drag_delta.z);
            }
        } else {
            alignment_.translation_total = DirectX::XMFLOAT3(
                alignment_.translation_drag_base.x + alignment_.translation_drag_delta.x,
                alignment_.translation_drag_base.y + alignment_.translation_drag_delta.y,
                alignment_.translation_drag_base.z + alignment_.translation_drag_delta.z);
        }
        alignment_.origin_cache_valid = false;
        if (alignment_drag_change_due(alignment_.last_translation_change_sent)) {
            send_alignment_vector_event("alignment_drag_changed", alignment_.translation_drag_delta);
        }
        return true;
    }

bool Renderer::update_alignment_rotation_drag(int x, int y, WPARAM wparam) {
        if (!alignment_.rotation_drag_active) return false;
        int delta_x = x - alignment_.last_x;
        int delta_y = y - alignment_.last_y;
        alignment_.last_x = x;
        alignment_.last_y = y;
        if (delta_x == 0 && delta_y == 0) return true;
        bool shift_down = (wparam & MK_SHIFT) != 0 || (GetKeyState(VK_SHIFT) & 0x8000) != 0;
        bool ctrl_down = (wparam & MK_CONTROL) != 0 || (GetKeyState(VK_CONTROL) & 0x8000) != 0;
        float degrees_per_pixel = std::max(0.001f, alignment_.rotation_degrees_per_pixel);
        if (ctrl_down) degrees_per_pixel *= 4.0f;
        else if (shift_down && !alignment_.rotation_drag_roll) degrees_per_pixel *= 0.25f;
        DirectX::XMFLOAT3 delta(0.0f, 0.0f, 0.0f);
        if (alignment_.rotation_drag_roll) {
            delta.z = static_cast<float>(delta_x) * degrees_per_pixel;
        } else {
            delta.x = static_cast<float>(delta_y) * degrees_per_pixel;
            delta.y = static_cast<float>(delta_x) * degrees_per_pixel;
        }
        alignment_.rotation_drag_delta.x += delta.x;
        alignment_.rotation_drag_delta.y += delta.y;
        alignment_.rotation_drag_delta.z += delta.z;
        if (!alignment_.selected_source_submeshes.empty()) {
            for (int source_index : alignment_.selected_source_submeshes) {
                DirectX::XMFLOAT3 base = alignment_.part_rotation_drag_bases[source_index];
                alignment_.part_transforms[source_index].rotation = DirectX::XMFLOAT3(
                    base.x + alignment_.rotation_drag_delta.x,
                    base.y + alignment_.rotation_drag_delta.y,
                    base.z + alignment_.rotation_drag_delta.z);
            }
        } else {
            alignment_.rotation_total = DirectX::XMFLOAT3(
                alignment_.rotation_drag_base.x + alignment_.rotation_drag_delta.x,
                alignment_.rotation_drag_base.y + alignment_.rotation_drag_delta.y,
                alignment_.rotation_drag_base.z + alignment_.rotation_drag_delta.z);
        }
        alignment_.origin_cache_valid = false;
        if (alignment_drag_change_due(alignment_.last_rotation_change_sent)) {
            send_alignment_vector_event("alignment_rotation_changed", alignment_.rotation_drag_delta);
        }
        return true;
    }

bool Renderer::update_alignment_drag(int x, int y, WPARAM wparam) {
        if (alignment_.rotation_drag_active) return update_alignment_rotation_drag(x, y, wparam);
        if (alignment_.drag_active) return update_alignment_translation_drag(x, y, wparam);
        return false;
    }

void Renderer::update_alignment_hover(int x, int y) {
        if (!alignment_.enabled || mesh_edit_.enabled || alignment_.drag_active || alignment_.rotation_drag_active) {
            return;
        }
        std::string next_axis = alignment_rotation_handle_at(x, y);
        if (next_axis.empty()) {
            next_axis = alignment_axis_at(x, y);
        }
        if (next_axis != alignment_.hover_axis) {
            alignment_.hover_axis = next_axis;
            request_render();
        }
    }

bool Renderer::finish_alignment_drag(int x, int y, WPARAM wparam) {
        if (alignment_.rotation_drag_active) {
            update_alignment_rotation_drag(x, y, wparam);
            send_alignment_vector_event("alignment_rotation_finished", alignment_.rotation_drag_delta);
            alignment_.rotation_drag_active = false;
            alignment_.rotation_drag_roll = false;
            alignment_.part_rotation_drag_bases.clear();
            if (GetCapture() == hwnd_) ReleaseCapture();
            return true;
        }
        if (alignment_.drag_active) {
            update_alignment_translation_drag(x, y, wparam);
            send_alignment_vector_event("alignment_drag_finished", alignment_.translation_drag_delta);
            alignment_.drag_active = false;
            alignment_.drag_axis.clear();
            alignment_.part_translation_drag_bases.clear();
            if (GetCapture() == hwnd_) ReleaseCapture();
            return true;
        }
        return false;
    }

bool Renderer::cancel_alignment_drag() {
        bool was_active = alignment_.drag_active || alignment_.rotation_drag_active;
        if (alignment_.drag_active) {
            if (!alignment_.part_translation_drag_bases.empty()) {
                for (const auto& item : alignment_.part_translation_drag_bases) {
                    alignment_.part_transforms[item.first].translation = item.second;
                }
            } else {
                alignment_.translation_total = alignment_.translation_drag_base;
            }
        }
        if (alignment_.rotation_drag_active) {
            if (!alignment_.part_rotation_drag_bases.empty()) {
                for (const auto& item : alignment_.part_rotation_drag_bases) {
                    alignment_.part_transforms[item.first].rotation = item.second;
                }
            } else {
                alignment_.rotation_total = alignment_.rotation_drag_base;
            }
        }
        alignment_.drag_active = false;
        alignment_.rotation_drag_active = false;
        alignment_.rotation_drag_roll = false;
        alignment_.drag_axis.clear();
        alignment_.translation_drag_delta = DirectX::XMFLOAT3(0.0f, 0.0f, 0.0f);
        alignment_.rotation_drag_delta = DirectX::XMFLOAT3(0.0f, 0.0f, 0.0f);
        alignment_.part_translation_drag_bases.clear();
        alignment_.part_rotation_drag_bases.clear();
        alignment_.origin_cache_valid = false;
        return was_active;
    }

void Renderer::draw_alignment_overlay_gdi() const {
        // Text labels stay in the D3D frame so interaction remains stable.
        // The visible handles are rendered before Present.
    }

int Renderer::source_part_at(int x, int y, float radius_pixels) const {
        int best_source_submesh = -1;
        float best_distance = radius_pixels;
        for (const PreviewBatch& batch : batches_) {
            if (batch.source_submesh_index < 0 || batch.cpu_positions.empty()) continue;
            for (const DirectX::XMFLOAT3& position : batch.cpu_positions) {
                float screen_x = 0.0f;
                float screen_y = 0.0f;
                if (!project_batch_position(batch, position, screen_x, screen_y)) continue;
                float distance = std::hypot(static_cast<float>(x) - screen_x, static_cast<float>(y) - screen_y);
                if (distance < best_distance) {
                    best_distance = distance;
                    best_source_submesh = batch.source_submesh_index;
                }
            }
        }
        return best_source_submesh;
    }

void Renderer::send_source_part_event(const char* event_name, int source_submesh_index) const {
        std::ostringstream out;
        out << "{\"event\":\"" << json_escape(event_name ? event_name : "") << "\""
            << ",\"source_submesh_index\":" << source_submesh_index
            << "}";
        send_json_event(out.str());
    }

void Renderer::send_source_part_context_event(int source_submesh_index, int x, int y) const {
        std::ostringstream out;
        out << "{\"event\":\"source_part_context_requested\""
            << ",\"source_submesh_index\":" << source_submesh_index
            << ",\"x\":" << x
            << ",\"y\":" << y
            << "}";
        send_json_event(out.str());
    }

void Renderer::send_source_part_screen_selection_event(int x, int y) {
        ++stats_.mesh_edit_selection_event_count;
        std::ostringstream payload;
        payload << "{\"operation\":\"toggle\""
            << ",\"target_mode\":\"source\""
            << ",\"selection_depth_mode\":\"xray\""
            << ",\"screen_brush\":" << mesh_edit_screen_brush_json(x, y, 28.0f, false)
            << ",\"falloff\":\"smooth\"}";
        send_mesh_edit_event("mesh_edit_selection_changed", payload.str());
    }

void Renderer::send_source_part_screen_context_event(int x, int y) {
        ++stats_.mesh_edit_selection_event_count;
        std::ostringstream payload;
        payload << "{\"operation\":\"context\""
            << ",\"target_mode\":\"source\""
            << ",\"selection_depth_mode\":\"xray\""
            << ",\"screen_brush\":" << mesh_edit_screen_brush_json(x, y, 28.0f, false)
            << ",\"falloff\":\"smooth\""
            << ",\"context_request\":true"
            << ",\"context_x\":" << x
            << ",\"context_y\":" << y
            << "}";
        send_mesh_edit_event("mesh_edit_selection_changed", payload.str());
    }

void Renderer::update_source_part_hover(int x, int y) {
        if (!source_part_.picking_enabled) {
            if (source_part_.hovered_source_submesh >= 0) {
                source_part_.hovered_source_submesh = -1;
                send_source_part_event("source_part_hovered", -1);
            }
            return;
        }
        if (mesh_edit_.enabled) {
            if (source_part_.hovered_source_submesh >= 0) {
                source_part_.hovered_source_submesh = -1;
                send_source_part_event("source_part_hovered", -1);
            }
            return;
        }
        int source_submesh = source_part_at(x, y, 28.0f);
        if (source_submesh == source_part_.hovered_source_submesh) return;
        source_part_.hovered_source_submesh = source_submesh;
        send_source_part_event("source_part_hovered", source_submesh);
    }

void Renderer::begin_source_part_click(WPARAM wparam, int x, int y) {
        source_part_.click_pending = false;
        source_part_.click_source_submesh = -1;
        bool alt_down = (GetKeyState(VK_MENU) & 0x8000) != 0;
        bool shift_down = (wparam & MK_SHIFT) != 0 || (GetKeyState(VK_SHIFT) & 0x8000) != 0;
        bool ctrl_down = (wparam & MK_CONTROL) != 0 || (GetKeyState(VK_CONTROL) & 0x8000) != 0;
        if (!source_part_.picking_enabled || alt_down || shift_down || ctrl_down) return;
        if (!mesh_edit_.enabled) {
            int source_submesh = source_part_at(x, y, 28.0f);
            if (source_submesh < 0) return;
            source_part_.click_source_submesh = source_submesh;
        }
        source_part_.click_pending = true;
        source_part_.start_x = x;
        source_part_.start_y = y;
    }

void Renderer::finish_source_part_click(int x, int y) {
        if (!source_part_.click_pending) return;
        int source_submesh = source_part_.click_source_submesh;
        source_part_.click_pending = false;
        source_part_.click_source_submesh = -1;
        if (std::hypot(static_cast<float>(x - source_part_.start_x), static_cast<float>(y - source_part_.start_y)) > 6.0f) {
            return;
        }
        if (mesh_edit_.enabled) {
            send_source_part_screen_selection_event(x, y);
            return;
        }
        if (source_submesh >= 0) {
            send_source_part_event("source_part_selected", source_submesh);
        }
    }

bool Renderer::request_source_part_context(WPARAM wparam, int x, int y) {
        bool alt_down = (GetKeyState(VK_MENU) & 0x8000) != 0;
        bool shift_down = (wparam & MK_SHIFT) != 0 || (GetKeyState(VK_SHIFT) & 0x8000) != 0;
        bool ctrl_down = (wparam & MK_CONTROL) != 0 || (GetKeyState(VK_CONTROL) & 0x8000) != 0;
        if (!source_part_.picking_enabled || alt_down || shift_down || ctrl_down) return false;
        if (mesh_edit_.enabled) {
            send_source_part_screen_context_event(x, y);
            return true;
        }
        int source_submesh = source_part_at(x, y, 28.0f);
        if (source_submesh < 0) return false;
        send_source_part_context_event(source_submesh, x, y);
        return true;
    }
