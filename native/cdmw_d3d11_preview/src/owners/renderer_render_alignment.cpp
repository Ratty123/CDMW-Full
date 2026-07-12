bool Renderer::reference_material_tint_allowed() const {
        const std::string mode = lower_copy(stats_.reference_tint_mode);
        const std::string policy = lower_copy(stats_.reference_material_policy);
        return mode != "overlay_only" && mode != "none" && policy != "preserve";
    }

void Renderer::draw_render_view(const PreviewRenderView& view) {
        context_->RSSetViewports(1, &view.viewport);
        context_->RSSetState(view.wireframe && wireframe_rasterizer_ ? wireframe_rasterizer_.Get() : (render_tuning_.cull_back_faces && cull_rasterizer_ ? cull_rasterizer_.Get() : rasterizer_.Get()));
        context_->OMSetDepthStencilState(view.no_depth && overlay_depth_state_ ? overlay_depth_state_.Get() : depth_state_.Get(), 0);
        const DirectX::XMMATRIX camera_world = world_matrix_for_view_role(view.role);
        const DirectX::XMMATRIX view_projection = view_projection_matrix_for_viewport(view.viewport, distance_for_view_role(view.role));
        const DirectX::XMMATRIX world_view_projection = camera_world * view_projection;
        if (!view.wireframe && !icon_capture_mode_ && !(display_mode_ == "overlay" && view.role == PreviewViewRole::Reference)) {
            draw_workspace_grid(view, world_view_projection);
        }
        context_->RSSetViewports(1, &view.viewport);
        context_->RSSetState(view.wireframe && wireframe_rasterizer_ ? wireframe_rasterizer_.Get() : (render_tuning_.cull_back_faces && cull_rasterizer_ ? cull_rasterizer_.Get() : rasterizer_.Get()));
        context_->OMSetDepthStencilState(view.no_depth && overlay_depth_state_ ? overlay_depth_state_.Get() : depth_state_.Get(), 0);
        for (PreviewBatch& batch : batches_) {
            if (!batch_visible_in_view(batch, view.role)) continue;
            context_->RSSetState(view.wireframe && wireframe_rasterizer_ ? wireframe_rasterizer_.Get() : (render_tuning_.cull_back_faces && !batch.two_sided && cull_rasterizer_ ? cull_rasterizer_.Get() : rasterizer_.Get()));
            const bool reference = batch_is_reference(batch);
            const float selection_tint_alpha = icon_capture_mode_
                ? 0.0f
                : std::clamp(batch.highlight_strength * 0.18f, 0.0f, 0.14f);
            DirectX::XMFLOAT4 tint(
                1.0f,
                0.72f,
                0.18f,
                selection_tint_alpha);
            if (reference) {
                const float reference_tint_alpha = reference_material_tint_allowed()
                    ? std::max(view.reference_tint_alpha, selection_tint_alpha)
                    : 0.0f;
                tint = DirectX::XMFLOAT4(
                    batch.highlight_strength > 0.0f ? 1.0f : 0.36f,
                    batch.highlight_strength > 0.0f ? 0.82f : 0.58f,
                    batch.highlight_strength > 0.0f ? 0.04f : 1.0f,
                    icon_capture_mode_ ? 0.0f : reference_tint_alpha);
            }
            const DirectX::XMMATRIX alignment_transform =
                view.role == PreviewViewRole::Reference ? DirectX::XMMatrixIdentity() : alignment_preview_transform_for_batch(batch);
            const DirectX::XMMATRIX batch_world = alignment_transform * camera_world;
            const bool mesh_edit_active = mesh_edit_batch_editable_in_view(batch, view);
            const bool mesh_edit_flat = mesh_edit_active && !mesh_edit_preserve_materials_for_batch(batch);
            draw_preview_batch(batch, batch_world * view_projection, batch_world, tint, mesh_edit_flat);
        }
        draw_highlight_bounds_overlay(view);
        draw_cloth_debug_overlays(view, world_view_projection);
        draw_skeleton_overlay(view, world_view_projection);
        draw_mesh_edit_overlay(view);
        if (!icon_capture_mode_) {
            draw_alignment_axes(view, world_view_projection);
        }
    }

void Renderer::draw_side_by_side_splitter_overlay() {
        if (icon_capture_mode_ || !side_by_side_workspace_active()) return;
        D3D11_VIEWPORT viewport = full_viewport();
        context_->RSSetViewports(1, &viewport);
        std::vector<float> vertices;
        vertices.reserve(23u * 18u);
        const float split_x = side_by_side_reference_width();
        const float view_width = static_cast<float>(std::max<LONG>(1, width_));
        const float view_height = static_cast<float>(std::max<LONG>(1, height_));
        auto append_screen_vertex = [&](float x, float y, float r, float g, float b) {
            const float clip_x = (x / view_width) * 2.0f - 1.0f;
            const float clip_y = 1.0f - (y / view_height) * 2.0f;
            append_line_vertex(vertices, clip_x, clip_y, 0.0f, r, g, b);
        };
        auto add_rect = [&](float left, float top, float right, float bottom, float r, float g, float b) {
            append_screen_vertex(left, top, r, g, b);
            append_screen_vertex(right, top, r, g, b);
            append_screen_vertex(right, bottom, r, g, b);
            append_screen_vertex(left, top, r, g, b);
            append_screen_vertex(right, bottom, r, g, b);
            append_screen_vertex(left, bottom, r, g, b);
        };
        add_rect(split_x - 3.0f, 0.0f, split_x + 3.0f, view_height, 0.06f, 0.08f, 0.10f);
        const bool active = side_by_side_split_drag_active_ || side_by_side_split_hover_;
        add_rect(
            split_x - 1.0f,
            0.0f,
            split_x + 1.0f,
            view_height,
            active ? 1.0f : 0.38f,
            active ? 0.48f : 0.52f,
            active ? 0.16f : 0.64f);
        const float handle_top = std::max(14.0f, view_height * 0.5f - 34.0f);
        const float handle_bottom = std::min(view_height - 14.0f, view_height * 0.5f + 34.0f);
        add_rect(
            split_x - 5.0f,
            handle_top,
            split_x + 5.0f,
            handle_bottom,
            active ? 0.95f : 0.22f,
            active ? 0.48f : 0.30f,
            active ? 0.16f : 0.38f);
        draw_colored_triangles(vertices, DirectX::XMMatrixIdentity(), true);
    }

void Renderer::update_runtime_stats(RendererStats& stats) {
        stats.texture_cache_entries = static_cast<int>(srv_cache_.size());
        stats.texture_cache_releases = texture_cache_releases_;
        active_texture_bytes_ = active_bound_texture_bytes();
        stats.texture_cache_bytes = estimated_texture_bytes_;
        stats.live_texture_bytes = active_texture_bytes_;
        stats.estimated_texture_bytes = estimated_texture_bytes_ + active_texture_bytes_;
        stats.frame_count = frame_count_;
        stats.render_request_count = render_request_count_;
        stats.render_suppressed_count = render_suppressed_count_;
        stats.parent_unresponsive_count = parent_unresponsive_count_;
        stats.parent_health = parent_health_;
        const cdmw_native_diag::ProcessMemorySnapshot memory = cdmw_native_diag::current_process_memory();
        if (memory.ok) {
            stats.process_working_set_bytes = memory.working_set_bytes;
            stats.process_private_bytes = memory.private_bytes;
        }
    }

void Renderer::update_runtime_stats() {
        update_runtime_stats(stats_);
    }

std::uint64_t Renderer::active_bound_texture_bytes() const {
        std::uint64_t total = 0;
        for (const PreviewBatch& batch : batches_) {
            total += batch.live_texture_bytes;
        }
        return total;
    }

std::wstring Renderer::texture_file_identity(const std::wstring& path, bool* stable_file_id) {
        if (stable_file_id) *stable_file_id = false;
        std::error_code ec;
        const fs::path file_path(path);
        const std::uintmax_t size = fs::file_size(file_path, ec);
        const std::wstring size_text = ec ? L"size:unknown" : (L"size:" + std::to_wstring(static_cast<unsigned long long>(size)));
        ec.clear();
        const auto mtime = fs::last_write_time(file_path, ec);
        const std::wstring mtime_text = ec ? L"mtime:unknown" : (L"mtime:" + std::to_wstring(mtime.time_since_epoch().count()));
        std::wstring file_id_text;
        HANDLE handle = CreateFileW(
            path.c_str(),
            0,
            FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE,
            nullptr,
            OPEN_EXISTING,
            FILE_ATTRIBUTE_NORMAL,
            nullptr);
        if (handle != INVALID_HANDLE_VALUE) {
            BY_HANDLE_FILE_INFORMATION info{};
            if (GetFileInformationByHandle(handle, &info)) {
                file_id_text = L"|volume:" + std::to_wstring(info.dwVolumeSerialNumber)
                    + L"|file:" + std::to_wstring(info.nFileIndexHigh)
                    + L":" + std::to_wstring(info.nFileIndexLow);
                if (stable_file_id) *stable_file_id = true;
            }
            CloseHandle(handle);
        }
        return size_text + L"|" + mtime_text + file_id_text;
    }

std::wstring Renderer::texture_cache_key(
        const std::wstring& path,
        bool dds,
        DirectX::CREATETEX_FLAGS create_flags) {
        bool stable_file_id = false;
        const std::wstring identity = texture_file_identity(path, &stable_file_id);
        return (dds ? L"dds|" : L"wic|")
            + std::to_wstring(static_cast<uint32_t>(create_flags))
            + L"|"
            + identity
            + (stable_file_id ? L"" : (L"|" + path));
    }

float Renderer::current_display_scale(float distance) {
        return std::max(0.1f, kFitDistance / std::max(distance, 0.01f));
    }

float Renderer::world_units_per_pixel() const {
        return world_units_per_pixel_for_role(PreviewViewRole::Replacement);
    }

float Renderer::world_units_per_pixel_for_role(PreviewViewRole role) const {
        D3D11_VIEWPORT viewport = replacement_editor_viewport();
        if (role == PreviewViewRole::Reference && side_by_side_workspace_active()) {
            viewport = viewport_rect(0.0f, 0.0f, std::floor(static_cast<float>(width_) * 0.5f), static_cast<float>(height_));
        }
        float viewport_height = std::max(1.0f, viewport.Height);
        float visible_height = 2.0f * std::max(distance_for_view_role(role), 0.1f) * std::tan(DirectX::XMConvertToRadians(kVerticalFovDegrees) * 0.5f);
        return visible_height / viewport_height;
    }

DirectX::XMMATRIX Renderer::current_world_matrix() const {
        return DirectX::XMMatrixRotationRollPitchYaw(
                DirectX::XMConvertToRadians(pitch_),
                DirectX::XMConvertToRadians(yaw_),
                0.0f)
            * DirectX::XMMatrixTranslation(pan_x_, pan_y_, pan_z_);
    }

DirectX::XMMATRIX Renderer::current_view_projection_matrix() const {
        return view_projection_matrix_for_viewport(replacement_editor_viewport(), distance_);
    }

DirectX::XMMATRIX Renderer::current_mvp_matrix() const {
        return current_world_matrix() * current_view_projection_matrix();
    }

bool Renderer::project_position(const DirectX::XMFLOAT3& position, float& screen_x, float& screen_y) const {
        DirectX::XMVECTOR source = DirectX::XMLoadFloat3(&position);
        DirectX::XMVECTOR projected = DirectX::XMVector3TransformCoord(source, current_mvp_matrix());
        DirectX::XMFLOAT3 clip{};
        DirectX::XMStoreFloat3(&clip, projected);
        if (!std::isfinite(clip.x) || !std::isfinite(clip.y) || !std::isfinite(clip.z)) return false;
        if (clip.z < 0.0f || clip.z > 1.0f) return false;
        D3D11_VIEWPORT viewport = replacement_editor_viewport();
        screen_x = viewport.TopLeftX + (clip.x * 0.5f + 0.5f) * viewport.Width;
        screen_y = viewport.TopLeftY + (0.5f - clip.y * 0.5f) * viewport.Height;
        return std::isfinite(screen_x) && std::isfinite(screen_y);
    }

bool Renderer::project_batch_position(const PreviewBatch& batch, const DirectX::XMFLOAT3& position, float& screen_x, float& screen_y) const {
        DirectX::XMVECTOR source = DirectX::XMLoadFloat3(&position);
        DirectX::XMVECTOR projected = DirectX::XMVector3TransformCoord(
            source,
            alignment_preview_transform_for_batch(batch) * current_mvp_matrix());
        DirectX::XMFLOAT3 clip{};
        DirectX::XMStoreFloat3(&clip, projected);
        if (!std::isfinite(clip.x) || !std::isfinite(clip.y) || !std::isfinite(clip.z)) return false;
        if (clip.z < 0.0f || clip.z > 1.0f) return false;
        D3D11_VIEWPORT viewport = replacement_editor_viewport();
        screen_x = viewport.TopLeftX + (clip.x * 0.5f + 0.5f) * viewport.Width;
        screen_y = viewport.TopLeftY + (0.5f - clip.y * 0.5f) * viewport.Height;
        return std::isfinite(screen_x) && std::isfinite(screen_y);
    }

bool Renderer::alignment_handle_origin(DirectX::XMFLOAT3& origin) const {
        if (!alignment_handle_origin_base(origin)) return false;
        DirectX::XMMATRIX transform = DirectX::XMMatrixIdentity();
        if (alignment_global_transform_active()) {
            DirectX::XMFLOAT3 global_origin{};
            if (!alignment_global_origin_base(global_origin)) {
                global_origin = DirectX::XMFLOAT3(0.0f, 0.0f, 0.0f);
            }
            transform = alignment_transform_matrix(
                global_origin,
                alignment_.translation_total,
                alignment_.rotation_total,
                alignment_.scale_total);
        }
        if (alignment_.selected_source_submeshes.size() == 1u) {
            const int source_index = *alignment_.selected_source_submeshes.begin();
            auto part = alignment_.part_transforms.find(source_index);
            if (part != alignment_.part_transforms.end() && alignment_part_transform_active(part->second)) {
                DirectX::XMFLOAT3 part_origin{};
                if (!alignment_part_origin_base(source_index, part_origin)) {
                    part_origin = DirectX::XMFLOAT3(0.0f, 0.0f, 0.0f);
                }
                transform = alignment_transform_matrix(
                    part_origin,
                    part->second.translation,
                    part->second.rotation,
                    part->second.scale)
                    * transform;
            }
        }
        DirectX::XMStoreFloat3(
            &origin,
            DirectX::XMVector3TransformCoord(DirectX::XMLoadFloat3(&origin), transform));
        return true;
    }

std::map<std::string, std::pair<ScreenPoint, ScreenPoint>> Renderer::alignment_axis_points() const {
        std::map<std::string, std::pair<ScreenPoint, ScreenPoint>> points;
        if (!alignment_.enabled || batches_.empty()) return points;
        DirectX::XMFLOAT3 origin{};
        if (!alignment_handle_origin(origin)) return points;
        float origin_x = 0.0f;
        float origin_y = 0.0f;
        if (!project_position(origin, origin_x, origin_y)) return points;
        const std::pair<const char*, DirectX::XMFLOAT3> axes[] = {
            {"x", DirectX::XMFLOAT3(origin.x + kAlignmentAxisExtent, origin.y, origin.z)},
            {"y", DirectX::XMFLOAT3(origin.x, origin.y + kAlignmentAxisExtent, origin.z)},
            {"z", DirectX::XMFLOAT3(origin.x, origin.y, origin.z + kAlignmentAxisExtent)},
        };
        for (const auto& axis : axes) {
            float end_x = 0.0f;
            float end_y = 0.0f;
            if (!project_position(axis.second, end_x, end_y)) continue;
            points[axis.first] = std::pair<ScreenPoint, ScreenPoint>(
                ScreenPoint{origin_x, origin_y},
                ScreenPoint{end_x, end_y});
        }
        return points;
    }

float Renderer::distance_to_segment(float x, float y, const ScreenPoint& start, const ScreenPoint& end) {
        float vx = end.x - start.x;
        float vy = end.y - start.y;
        float length_sq = vx * vx + vy * vy;
        if (length_sq <= 1e-8f) {
            return std::hypot(x - start.x, y - start.y);
        }
        float t = std::clamp(((x - start.x) * vx + (y - start.y) * vy) / length_sq, 0.0f, 1.0f);
        float closest_x = start.x + vx * t;
        float closest_y = start.y + vy * t;
        return std::hypot(x - closest_x, y - closest_y);
    }

std::string Renderer::alignment_axis_at(int x, int y) const {
        if (!alignment_.enabled) return "";
        float center_distance = std::numeric_limits<float>::infinity();
        DirectX::XMFLOAT3 origin{};
        if (alignment_handle_origin(origin)) {
            float origin_x = 0.0f;
            float origin_y = 0.0f;
            if (project_position(origin, origin_x, origin_y)) {
                center_distance = std::hypot(static_cast<float>(x) - origin_x, static_cast<float>(y) - origin_y);
            }
        }
        std::string best_axis;
        float best_distance = 30.0f;
        for (const auto& [axis, segment] : alignment_axis_points()) {
            float distance = distance_to_segment(static_cast<float>(x), static_cast<float>(y), segment.first, segment.second);
            if (distance < best_distance) {
                best_axis = axis;
                best_distance = distance;
            }
        }
        if (!best_axis.empty() && (center_distance > 12.0f || best_distance + 4.0f < center_distance)) {
            return best_axis;
        }
        if (center_distance <= 26.0f) {
            return "screen";
        }
        return best_axis;
    }

std::string Renderer::alignment_rotation_handle_at(int x, int y) const {
        if (!alignment_.enabled) return "";
        DirectX::XMFLOAT3 origin{};
        if (!alignment_handle_origin(origin)) return "";
        float origin_x = 0.0f;
        float origin_y = 0.0f;
        if (!project_position(origin, origin_x, origin_y)) return "";
        const float distance = std::hypot(static_cast<float>(x) - origin_x, static_cast<float>(y) - origin_y);
        if (distance >= 34.0f && distance <= 58.0f) return "rotate";
        if (distance >= 62.0f && distance <= 84.0f) return "roll";
        return "";
    }

DirectX::XMFLOAT3 Renderer::alignment_screen_drag_delta(int delta_x, int delta_y, float units_per_pixel) const {
        DirectX::XMMATRIX rotation = DirectX::XMMatrixRotationRollPitchYaw(
            DirectX::XMConvertToRadians(pitch_),
            DirectX::XMConvertToRadians(yaw_),
            0.0f);
        DirectX::XMVECTOR determinant{};
        DirectX::XMMATRIX inverse_rotation = DirectX::XMMatrixInverse(&determinant, rotation);
        DirectX::XMVECTOR right = DirectX::XMVector3TransformNormal(DirectX::XMVectorSet(1.0f, 0.0f, 0.0f, 0.0f), inverse_rotation);
        DirectX::XMVECTOR up = DirectX::XMVector3TransformNormal(DirectX::XMVectorSet(0.0f, 1.0f, 0.0f, 0.0f), inverse_rotation);
        DirectX::XMVECTOR horizontal = DirectX::XMVectorScale(right, static_cast<float>(delta_x) * units_per_pixel);
        DirectX::XMVECTOR vertical = DirectX::XMVectorScale(up, static_cast<float>(delta_y) * units_per_pixel);
        DirectX::XMVECTOR delta = DirectX::XMVectorSubtract(horizontal, vertical);
        DirectX::XMFLOAT3 output{};
        DirectX::XMStoreFloat3(&output, delta);
        return output;
    }

void Renderer::send_alignment_vector_event(const char* event_name, const DirectX::XMFLOAT3& value) const {
        std::ostringstream out;
        out << "{\"event\":\"" << json_escape(event_name ? event_name : "") << "\""
            << ",\"x\":" << value.x
            << ",\"y\":" << value.y
            << ",\"z\":" << value.z
            << "}";
        send_json_event(out.str());
    }

bool Renderer::alignment_drag_change_due(std::chrono::steady_clock::time_point& last_sent) const {
        auto now = std::chrono::steady_clock::now();
        if (last_sent.time_since_epoch().count() == 0) {
            last_sent = now;
            return true;
        }
        if (std::chrono::duration<double, std::milli>(now - last_sent).count() < 50.0) {
            return false;
        }
        last_sent = now;
        return true;
    }

void Renderer::send_alignment_started_event(const char* mode, const char* axis) const {
        std::ostringstream out;
        out << "{\"event\":\"alignment_drag_started\""
            << ",\"mode\":\"" << json_escape(mode ? mode : "") << "\""
            << ",\"axis\":\"" << json_escape(axis ? axis : "") << "\""
            << "}";
        send_json_event(out.str());
    }

void Renderer::drop_pending_package_reload(const char* reason) {
        if (pending_package_dir_.empty()) return;
        cdmw_native_diag::event(
            "pending_package_reload_dropped",
            {
                {"reason", reason ? reason : ""},
                {"package_dir", cdmw_native_diag::path_to_utf8(fs::path(pending_package_dir_))}
            });
        pending_package_dir_.clear();
        pending_status_file_.clear();
        pending_reset_view_ = false;
    }

bool Renderer::begin_alignment_drag(WPARAM wparam, int x, int y) {
        if (!alignment_.enabled || mesh_edit_.enabled) return false;
        if (input_view_role_at(x, y) == PreviewViewRole::Reference && side_by_side_workspace_active()) {
            return false;
        }
        bool alt_down = (GetKeyState(VK_MENU) & 0x8000) != 0;
        bool shift_down = (wparam & MK_SHIFT) != 0 || (GetKeyState(VK_SHIFT) & 0x8000) != 0;
        if (alt_down) {
            drop_pending_package_reload("alignment_rotation_start");
            alignment_.rotation_drag_active = true;
            alignment_.rotation_drag_roll = shift_down;
            alignment_.part_rotation_drag_bases.clear();
            if (!alignment_.selected_source_submeshes.empty()) {
                for (int source_index : alignment_.selected_source_submeshes) {
                    alignment_.part_rotation_drag_bases[source_index] = alignment_.part_transforms[source_index].rotation;
                }
                alignment_.rotation_drag_base = DirectX::XMFLOAT3(0.0f, 0.0f, 0.0f);
            } else {
                alignment_.rotation_drag_base = alignment_.rotation_total;
            }
            alignment_.rotation_drag_delta = DirectX::XMFLOAT3(0.0f, 0.0f, 0.0f);
            alignment_.last_rotation_change_sent = std::chrono::steady_clock::time_point{};
            alignment_.last_x = x;
            alignment_.last_y = y;
            SetCapture(hwnd_);
            send_alignment_started_event("rotation", alignment_.rotation_drag_roll ? "roll" : "orbit");
            return true;
        }
        std::string rotation_handle = alignment_rotation_handle_at(x, y);
        if (!rotation_handle.empty()) {
            drop_pending_package_reload("alignment_rotation_start");
            alignment_.rotation_drag_active = true;
            alignment_.rotation_drag_roll = rotation_handle == "roll" || shift_down;
            alignment_.part_rotation_drag_bases.clear();
            if (!alignment_.selected_source_submeshes.empty()) {
                for (int source_index : alignment_.selected_source_submeshes) {
                    alignment_.part_rotation_drag_bases[source_index] = alignment_.part_transforms[source_index].rotation;
                }
                alignment_.rotation_drag_base = DirectX::XMFLOAT3(0.0f, 0.0f, 0.0f);
            } else {
                alignment_.rotation_drag_base = alignment_.rotation_total;
            }
            alignment_.rotation_drag_delta = DirectX::XMFLOAT3(0.0f, 0.0f, 0.0f);
            alignment_.last_rotation_change_sent = std::chrono::steady_clock::time_point{};
            alignment_.last_x = x;
            alignment_.last_y = y;
            SetCapture(hwnd_);
            send_alignment_started_event("rotation", alignment_.rotation_drag_roll ? "roll" : "orbit");
            return true;
        }
        std::string axis = alignment_axis_at(x, y);
        if (axis.empty()) return false;
        drop_pending_package_reload("alignment_translation_start");
        alignment_.drag_axis = axis;
        alignment_.hover_axis = axis;
        alignment_.drag_active = true;
        alignment_.part_translation_drag_bases.clear();
        if (!alignment_.selected_source_submeshes.empty()) {
            for (int source_index : alignment_.selected_source_submeshes) {
                alignment_.part_translation_drag_bases[source_index] = alignment_.part_transforms[source_index].translation;
            }
            alignment_.translation_drag_base = DirectX::XMFLOAT3(0.0f, 0.0f, 0.0f);
        } else {
            alignment_.translation_drag_base = alignment_.translation_total;
        }
        alignment_.translation_drag_delta = DirectX::XMFLOAT3(0.0f, 0.0f, 0.0f);
        alignment_.last_translation_change_sent = std::chrono::steady_clock::time_point{};
        alignment_.last_x = x;
        alignment_.last_y = y;
        SetCapture(hwnd_);
        send_alignment_started_event("translation", axis.c_str());
        return true;
    }
