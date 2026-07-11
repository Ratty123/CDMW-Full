std::string Renderer::mesh_edit_selection_operation_from_modifiers(WPARAM wparam) {
        const bool shift_down = (wparam & MK_SHIFT) != 0 || (GetKeyState(VK_SHIFT) & 0x8000) != 0;
        const bool ctrl_down = (wparam & MK_CONTROL) != 0 || (GetKeyState(VK_CONTROL) & 0x8000) != 0;
        if (shift_down && ctrl_down) return "toggle";
        if (ctrl_down) return "subtract";
        if (shift_down) return "add";
        return "replace";
    }

void Renderer::apply_mesh_edit_brush_selection(int x, int y) {
        send_mesh_edit_screen_brush_selection_event(x, y);
    }

bool Renderer::mesh_edit_preview_event_due(bool force_preview) const {
        if (force_preview || mesh_edit_.last_preview_event_time.time_since_epoch().count() == 0) return true;
        const auto now = std::chrono::steady_clock::now();
        const double elapsed_ms = std::chrono::duration<double, std::milli>(
            now - mesh_edit_.last_preview_event_time).count();
        return elapsed_ms >= 16.0;
    }

void Renderer::mark_mesh_edit_preview_event() {
        mesh_edit_.last_preview_event_time = std::chrono::steady_clock::now();
    }

void Renderer::apply_mesh_edit_region_selection(int x, int y) {
        send_mesh_edit_screen_region_selection_event(x, y);
    }

void Renderer::finish_mesh_edit_selection_drag(int x, int y) {
        apply_mesh_edit_region_selection(x, y);
        mesh_edit_.selection_drag_active = false;
        mesh_edit_.selection_lasso_points.clear();
        if (GetCapture() == hwnd_) ReleaseCapture();
    }

bool Renderer::begin_mesh_edit_drag(WPARAM wparam, int x, int y) {
        if (!mesh_edit_.enabled) return false;
        bool alt_down = (GetKeyState(VK_MENU) & 0x8000) != 0;
        if (alt_down) return false;
        bool remove_selection_mode = mesh_edit_.tool == "remove" && mesh_edit_.delete_mode == "selection";
        bool selection_mode = mesh_edit_.tool == "vertex" || remove_selection_mode;
        if (selection_mode) {
            mesh_edit_.selection_drag_active = true;
            mesh_edit_.selection_operation = mesh_edit_selection_operation_from_modifiers(wparam);
            mesh_edit_.start_x = x;
            mesh_edit_.start_y = y;
            mesh_edit_.last_x = x;
            mesh_edit_.last_y = y;
            mesh_edit_.selection_lasso_points.clear();
            if (mesh_edit_.selection_mode == "lasso") {
                mesh_edit_.selection_lasso_points.push_back(DirectX::XMFLOAT2(static_cast<float>(x), static_cast<float>(y)));
            } else if (mesh_edit_.selection_mode == "brush") {
                apply_mesh_edit_brush_selection(x, y);
                if (mesh_edit_.selection_operation == "replace") {
                    mesh_edit_.selection_operation = "add";
                }
                mark_mesh_edit_preview_event();
            }
            SetCapture(hwnd_);
            return true;
        }
        const bool has_resident_selection = !mesh_edit_.selected_vertices.empty()
            || !mesh_edit_.selected_edges.empty()
            || !mesh_edit_.selected_faces.empty()
            || !mesh_edit_.selected_sources.empty();
        const bool selection_drag_tool = mesh_edit_.target_mode == "selection"
            && (mesh_edit_.tool == "move" || mesh_edit_.tool == "grab");
        bool move_screen_selection_tool = mesh_edit_.tool == "move" && !has_resident_selection;
        bool grab_screen_selection_tool = mesh_edit_.tool == "grab" && mesh_edit_.target_mode == "selection" && !has_resident_selection;
        bool screen_selection_tool = move_screen_selection_tool || grab_screen_selection_tool;
        bool resident_selection_drag_tool = selection_drag_tool && has_resident_selection;
        bool remove_screen_tool = mesh_edit_.tool == "remove" && mesh_edit_.delete_mode != "selection";
        bool screen_brush_tool = screen_selection_tool
            || remove_screen_tool
            || (mesh_edit_.tool == "grab" && mesh_edit_.target_mode != "selection")
            || mesh_edit_.tool == "smooth"
            || mesh_edit_.tool == "inflate"
            || mesh_edit_.tool == "pinch";
        bool native_selection_tool = screen_brush_tool || resident_selection_drag_tool;
        if (!native_selection_tool) return true;
        mesh_edit_.drag_active = true;
        mesh_edit_.previewed = false;
        mesh_edit_.drag_uses_resident_selection = screen_selection_tool || resident_selection_drag_tool;
        mesh_edit_.stroke_id += 1;
        mesh_edit_.start_x = x;
        mesh_edit_.start_y = y;
        mesh_edit_.last_x = x;
        mesh_edit_.last_y = y;
        mesh_edit_.last_preview_event_time = std::chrono::steady_clock::time_point{};
        SetCapture(hwnd_);
        send_mesh_edit_event("mesh_edit_stroke_started", mesh_edit_payload_json(x, y, false, screen_selection_tool));
        return true;
    }

bool Renderer::update_mesh_edit_drag(int x, int y, bool force_preview) {
        if (mesh_edit_.selection_drag_active) {
            mesh_edit_.last_x = x;
            mesh_edit_.last_y = y;
            if (mesh_edit_.selection_mode == "brush") {
                if (mesh_edit_preview_event_due(force_preview)) {
                    apply_mesh_edit_brush_selection(x, y);
                    mark_mesh_edit_preview_event();
                }
            } else if (mesh_edit_.selection_mode == "lasso") {
                if (mesh_edit_.selection_lasso_points.empty()
                    || std::hypot(
                        mesh_edit_.selection_lasso_points.back().x - static_cast<float>(x),
                        mesh_edit_.selection_lasso_points.back().y - static_cast<float>(y)) >= 2.0f) {
                    mesh_edit_.selection_lasso_points.push_back(DirectX::XMFLOAT2(static_cast<float>(x), static_cast<float>(y)));
                }
            }
            return true;
        }
        if (!mesh_edit_.drag_active) return false;
        if (!mesh_edit_preview_event_due(force_preview)) {
            return true;
        }
        bool drag_mode = mesh_edit_.tool == "move" || mesh_edit_.tool == "grab" || mesh_edit_.tool == "vertex";
        bool resident_selection_drag = drag_mode && mesh_edit_.drag_uses_resident_selection;
        bool remove_screen_tool = mesh_edit_.tool == "remove" && mesh_edit_.delete_mode != "selection";
        bool screen_brush_update_tool = remove_screen_tool
            || (mesh_edit_.tool == "grab" && mesh_edit_.target_mode != "selection")
            || mesh_edit_.tool == "smooth"
            || mesh_edit_.tool == "inflate"
            || mesh_edit_.tool == "pinch";
        if (!screen_brush_update_tool && !resident_selection_drag) return true;
        bool ctrl_down = (GetKeyState(VK_CONTROL) & 0x8000) != 0;
        send_mesh_edit_event("mesh_edit_stroke_previewed", mesh_edit_payload_json(x, y, ctrl_down));
        mesh_edit_.last_x = x;
        mesh_edit_.last_y = y;
        mesh_edit_.previewed = true;
        mark_mesh_edit_preview_event();
        return true;
    }

bool Renderer::finish_mesh_edit_drag(int x, int y) {
        if (mesh_edit_.selection_drag_active) {
            mesh_edit_.last_x = x;
            mesh_edit_.last_y = y;
            if (mesh_edit_.selection_mode == "lasso") {
                mesh_edit_.selection_lasso_points.push_back(DirectX::XMFLOAT2(static_cast<float>(x), static_cast<float>(y)));
            }
            if (mesh_edit_.selection_mode == "brush") {
                apply_mesh_edit_brush_selection(x, y);
                mark_mesh_edit_preview_event();
                mesh_edit_.selection_drag_active = false;
                mesh_edit_.selection_lasso_points.clear();
                if (GetCapture() == hwnd_) ReleaseCapture();
            } else {
                finish_mesh_edit_selection_drag(x, y);
            }
            return true;
        }
        if (!mesh_edit_.drag_active) return false;
        update_mesh_edit_drag(x, y, true);
        std::ostringstream payload;
        payload << "{\"stroke_id\":" << mesh_edit_.stroke_id
                << ",\"phase\":\"finish\",\"tool\":\"" << json_escape(mesh_edit_.tool)
                << "\",\"delete_mode\":\"" << json_escape(mesh_edit_.delete_mode)
                << "\",\"previewed\":" << (mesh_edit_.previewed ? "true" : "false") << "}";
        send_mesh_edit_event("mesh_edit_stroke_finished", payload.str());
        mesh_edit_.drag_active = false;
        mesh_edit_.drag_uses_resident_selection = false;
        mesh_edit_.previewed = false;
        if (GetCapture() == hwnd_) ReleaseCapture();
        return true;
    }

bool Renderer::cancel_mesh_edit_drag() {
        if (mesh_edit_.selection_drag_active) {
            mesh_edit_.selection_drag_active = false;
            mesh_edit_.selection_lasso_points.clear();
            if (GetCapture() == hwnd_) ReleaseCapture();
            return true;
        }
        if (!mesh_edit_.drag_active) return false;
        std::ostringstream payload;
        payload << "{\"stroke_id\":" << mesh_edit_.stroke_id
                << ",\"phase\":\"cancel\",\"tool\":\"" << json_escape(mesh_edit_.tool)
                << "\",\"delete_mode\":\"" << json_escape(mesh_edit_.delete_mode) << "\"}";
        send_mesh_edit_event("mesh_edit_stroke_cancelled", payload.str());
        mesh_edit_.drag_active = false;
        mesh_edit_.drag_uses_resident_selection = false;
        mesh_edit_.previewed = false;
        if (GetCapture() == hwnd_) ReleaseCapture();
        return true;
    }

void Renderer::send_json_event(const std::string& payload) const {
        HWND parent = reinterpret_cast<HWND>(args_.parent_hwnd);
        LRESULT delivered = 0;
        if (parent && IsWindow(parent)) {
            COPYDATASTRUCT cds{};
            cds.dwData = kCdmwEventCopyData;
            cds.cbData = static_cast<DWORD>(payload.size() + 1);
            cds.lpData = const_cast<char*>(payload.c_str());
            delivered = SendMessageW(parent, WM_COPYDATA, reinterpret_cast<WPARAM>(hwnd_), reinterpret_cast<LPARAM>(&cds));
        }
        if (!delivered) {
            write_status(args_.status_file, payload);
        }
    }

void Renderer::send_view_event(const char* reason, PreviewViewRole role) const {
        const PreviewCameraState camera = camera_for_view_role(role);
        std::ostringstream out;
        out << "{\"event\":\"view_state\",\"reason\":\"" << json_escape(reason ? reason : "") << "\""
            << ",\"role\":\"" << preview_view_role_name(role) << "\""
            << ",\"zoom_factor\":" << camera.zoom_factor
            << ",\"fit_to_view\":" << (camera.fit_to_view ? "true" : "false")
            << ",\"yaw\":" << camera.yaw
            << ",\"pitch\":" << camera.pitch
            << ",\"pan\":[" << camera.pan_x << "," << camera.pan_y << "," << camera.pan_z << "]"
            << "}";
        send_json_event(out.str());
    }

void Renderer::send_side_by_side_split_event(const char* reason) const {
        std::ostringstream out;
        out << "{\"event\":\"side_by_side_split\""
            << ",\"reason\":\"" << json_escape(reason ? reason : "") << "\""
            << ",\"ratio\":" << side_by_side_split_ratio_
            << "}";
        send_json_event(out.str());
    }
