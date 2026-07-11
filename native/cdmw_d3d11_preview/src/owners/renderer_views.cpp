void Renderer::unbind_render_outputs_for_device_loss() {
        if (!context_) return;
        ID3D11ShaderResourceView* null_srvs[kTotalSrvCount] = {};
        context_->PSSetShaderResources(0, kTotalSrvCount, null_srvs);
        ID3D11RenderTargetView* null_target = nullptr;
        context_->OMSetRenderTargets(1, &null_target, nullptr);
        context_->Flush();
        render_target_.Reset();
        depth_view_.Reset();
    }

void Renderer::handle_device_loss(const char* stage, HRESULT hr) {
        const std::string stage_text = stage && stage[0] ? stage : "render";
        device_lost_ = true;
        render_requested_ = false;
        stats_.device_lost = true;
        stats_.device_loss_stage = stage_text;
        stats_.device_loss_hresult = hresult_hex(hr);
        HRESULT removed_reason = device_ ? device_->GetDeviceRemovedReason() : hr;
        stats_.device_removed_reason = hresult_hex(removed_reason);
        if (stage_text == "Present") {
            ++stats_.present_failure_count;
        } else if (stage_text == "ResizeBuffers") {
            if (stats_.resize_failure_hresult.empty()) {
                ++stats_.resize_failure_count;
                stats_.resize_failure_hresult = hresult_hex(hr);
            }
            stats_.resize_failure_reason = "device_lost";
        }
        update_runtime_stats();
        unbind_render_outputs_for_device_loss();
        const std::string payload = device_lost_payload(stats_, stage_text);
        write_status(args_.status_file, payload);
        send_json_event(payload);
        cdmw_native_diag::event(
            "d3d11_device_lost",
            {
                {"stage", stage_text},
                {"hresult", stats_.device_loss_hresult},
                {"device_removed_reason", stats_.device_removed_reason},
                {"frame_count", std::to_string(frame_count_)},
                {"render_request_count", std::to_string(render_request_count_)}
            });
    }

void Renderer::handle_render_failure(const char* stage, HRESULT hr) {
        const std::string stage_text = stage && stage[0] ? stage : "render";
        stats_.skipped.push_back(stage_text + " failed:" + hresult_hex(hr));
        update_runtime_stats();
        write_status(args_.status_file, error_payload("native D3D11 render failed during " + stage_text, stats_));
        cdmw_native_diag::event(
            "d3d11_render_failed",
            {{"stage", stage_text}, {"hresult", hresult_hex(hr)}, {"frame_count", std::to_string(frame_count_)}});
        render_requested_ = false;
    }

bool Renderer::process_pending_mesh_edit_vertex_update() {
        if (pending_mesh_edit_vertices_payload_.empty() && pending_mesh_edit_vertices_file_.empty()) return false;
        std::string payload;
        bool payload_file = false;
        fs::path file_path;
        bool delete_after = false;
        const std::uint64_t revision = pending_mesh_edit_vertices_revision_;
        pending_mesh_edit_vertices_revision_ = 0;
        if (!pending_mesh_edit_vertices_file_.empty()) {
            file_path = pending_mesh_edit_vertices_file_;
            delete_after = pending_mesh_edit_vertices_delete_after_;
            pending_mesh_edit_vertices_file_.clear();
            pending_mesh_edit_vertices_delete_after_ = false;
            payload_file = true;
            payload = read_text(file_path);
        } else {
            payload.swap(pending_mesh_edit_vertices_payload_);
        }
        const std::uint64_t effective_revision = revision > 0 ? revision : mesh_edit_revision_field(payload);
        if (mesh_edit_revision_is_stale(effective_revision, last_applied_mesh_edit_revision_)) {
            delete_mesh_edit_payload_descriptors(payload);
            cleanup_mesh_edit_vertices_file(file_path, delete_after);
            send_mesh_edit_vertices_ack(effective_revision, "rejected", 0, payload_file, "stale_or_out_of_order");
            return true;
        }
        const int changed_vertices = payload.empty() ? 0 : update_mesh_edit_vertices_from_payload(payload);
        cleanup_mesh_edit_vertices_file(file_path, delete_after);
        if (effective_revision > 0) {
            last_applied_mesh_edit_revision_ = effective_revision;
        }
        request_render();
        send_mesh_edit_vertices_ack(effective_revision, "applied", changed_vertices, payload_file, "");
        return true;
    }

void Renderer::cleanup_mesh_edit_vertices_file(const fs::path& file_path, bool delete_after) const {
        if (!delete_after || file_path.empty()) return;
        const std::wstring filename = file_path.filename().wstring();
        if (filename.rfind(L"cdmw_mesh_edit_vertices_", 0) != 0) return;
        std::error_code ec;
        fs::remove(file_path, ec);
    }

void Renderer::send_mesh_edit_vertices_ack(
        std::uint64_t revision,
        const char* status,
        int changed_vertices,
        bool payload_file,
        const char* reason) const {
        std::ostringstream event;
        event << "{\"event\":\"mesh_edit_vertices_updated\""
              << ",\"status\":\"" << json_escape(status ? status : "rejected") << "\""
              << ",\"changed_vertices\":" << changed_vertices
              << ",\"last_applied_revision\":" << last_applied_mesh_edit_revision_
              << ",\"capabilities\":[\"mesh_edit_revision_ack_v1\"]";
        if (revision > 0) {
            event << ",\"edit_revision\":" << revision << ",\"revision\":" << revision;
        }
        if (payload_file) event << ",\"payload_file\":true";
        if (reason && reason[0]) event << ",\"reason\":\"" << json_escape(reason) << "\"";
        event << "}";
        send_json_event(event.str());
    }

bool Renderer::accept_mesh_edit_vertices_revision(
        std::uint64_t revision,
        const std::string& payload,
        const fs::path& file_path,
        bool delete_after) {
        if (mesh_edit_revision_is_stale(revision, last_applied_mesh_edit_revision_)) {
            delete_mesh_edit_payload_descriptors(payload.empty() && !file_path.empty() ? read_text(file_path) : payload);
            cleanup_mesh_edit_vertices_file(file_path, delete_after);
            send_mesh_edit_vertices_ack(revision, "rejected", 0, !file_path.empty(), "stale_or_out_of_order");
            return false;
        }
        return true;
    }

void Renderer::queue_mesh_edit_vertices_payload(const std::string& payload, std::uint64_t revision) {
        process_pending_mesh_edit_vertex_update();
        if (!accept_mesh_edit_vertices_revision(revision, payload)) return;
        pending_mesh_edit_vertices_payload_ = payload;
        pending_mesh_edit_vertices_file_.clear();
        pending_mesh_edit_vertices_delete_after_ = false;
        pending_mesh_edit_vertices_revision_ = revision;
        request_render();
    }

void Renderer::queue_mesh_edit_vertices_file(const fs::path& payload_file, bool delete_after, std::uint64_t revision) {
        process_pending_mesh_edit_vertex_update();
        if (!accept_mesh_edit_vertices_revision(revision, {}, payload_file, delete_after)) return;
        pending_mesh_edit_vertices_payload_.clear();
        pending_mesh_edit_vertices_file_ = payload_file;
        pending_mesh_edit_vertices_delete_after_ = delete_after;
        pending_mesh_edit_vertices_revision_ = revision;
        request_render();
    }

bool Renderer::batch_is_reference(const PreviewBatch& batch) const {
        std::string role = lower_copy(batch.editor_role);
        return role.find("original") != std::string::npos
            || role.find("reference") != std::string::npos
            || (!batch.editor_editable && batch.source_submesh_index < 0 && !role.empty());
    }

bool Renderer::has_reference_batches() const {
        for (const PreviewBatch& batch : batches_) {
            if (batch_is_reference(batch)) return true;
        }
        return false;
    }

D3D11_VIEWPORT Renderer::viewport_rect(float x, float y, float width, float height) {
        D3D11_VIEWPORT viewport{};
        viewport.TopLeftX = std::max(0.0f, x);
        viewport.TopLeftY = std::max(0.0f, y);
        viewport.Width = std::max(1.0f, width);
        viewport.Height = std::max(1.0f, height);
        viewport.MinDepth = 0.0f;
        viewport.MaxDepth = 1.0f;
        return viewport;
    }

D3D11_VIEWPORT Renderer::full_viewport() const {
        return viewport_rect(0.0f, 0.0f, static_cast<float>(std::max<LONG>(1, width_)), static_cast<float>(std::max<LONG>(1, height_)));
    }

float Renderer::side_by_side_reference_width() const {
        return std::floor(static_cast<float>(width_) * std::clamp(side_by_side_split_ratio_, 0.18f, 0.82f));
    }

D3D11_VIEWPORT Renderer::replacement_editor_viewport() const {
        if (display_mode_ == "side_by_side" && has_reference_batches() && width_ > 4) {
            const float left_width = side_by_side_reference_width();
            return viewport_rect(left_width + 1.0f, 0.0f, static_cast<float>(width_) - left_width - 1.0f, static_cast<float>(height_));
        }
        return full_viewport();
    }

std::vector<PreviewRenderView> Renderer::active_render_views() const {
        std::vector<PreviewRenderView> views;
        const bool has_reference = has_reference_batches();
        if (display_mode_ == "side_by_side" && has_reference && width_ > 4) {
            const float left_width = side_by_side_reference_width();
            PreviewRenderView left;
            left.viewport = viewport_rect(0.0f, 0.0f, left_width, static_cast<float>(height_));
            left.role = PreviewViewRole::Reference;
            left.reference_tint_alpha = 0.0f;
            views.push_back(left);
            PreviewRenderView right;
            right.viewport = viewport_rect(left_width + 1.0f, 0.0f, static_cast<float>(width_) - left_width - 1.0f, static_cast<float>(height_));
            right.role = PreviewViewRole::Replacement;
            views.push_back(right);
            return views;
        }
        if (display_mode_ == "overlay" && has_reference) {
            PreviewRenderView reference_overlay;
            reference_overlay.viewport = full_viewport();
            reference_overlay.role = PreviewViewRole::Reference;
            reference_overlay.reference_tint_alpha = 0.0f;
            views.push_back(reference_overlay);
            PreviewRenderView replacement;
            replacement.viewport = full_viewport();
            replacement.role = PreviewViewRole::Replacement;
            views.push_back(replacement);
            return views;
        }
        if (display_mode_ == "original_only" && has_reference) {
            PreviewRenderView reference;
            reference.viewport = full_viewport();
            reference.role = PreviewViewRole::Reference;
            reference.reference_tint_alpha = 0.0f;
            views.push_back(reference);
            return views;
        }
        PreviewRenderView only;
        only.viewport = full_viewport();
        only.role = (display_mode_ == "replacement_only" && has_reference) ? PreviewViewRole::Replacement : PreviewViewRole::All;
        views.push_back(only);
        return views;
    }

bool Renderer::batch_visible_in_view(const PreviewBatch& batch, PreviewViewRole role) const {
        if (batch.source_submesh_index >= 0 && hidden_source_submeshes_.find(batch.source_submesh_index) != hidden_source_submeshes_.end()) {
            return false;
        }
        if (role == PreviewViewRole::All) return true;
        const bool reference = batch_is_reference(batch);
        if (role == PreviewViewRole::Reference) return reference;
        if (role == PreviewViewRole::Replacement) return !reference;
        return true;
    }

bool Renderer::side_by_side_workspace_active() const {
        return display_mode_ == "side_by_side" && has_reference_batches() && width_ > 4;
    }

bool Renderer::side_by_side_splitter_hit_test(int x, int /*y*/) const {
        return side_by_side_workspace_active()
            && std::abs(static_cast<float>(x) - side_by_side_reference_width()) <= 10.0f;
    }

void Renderer::set_side_by_side_split_from_x(int x) {
        if (width_ <= 4) return;
        side_by_side_split_ratio_ = std::clamp(static_cast<float>(x) / static_cast<float>(width_), 0.18f, 0.82f);
    }

void Renderer::set_side_by_side_split_ratio(float ratio) {
        side_by_side_split_ratio_ = std::clamp(ratio, 0.18f, 0.82f);
    }

PreviewViewRole Renderer::input_view_role_at(int x, int /*y*/) const {
        if (!side_by_side_workspace_active()) return PreviewViewRole::All;
        const float left_width = side_by_side_reference_width();
        return static_cast<float>(x) <= left_width ? PreviewViewRole::Reference : PreviewViewRole::Replacement;
    }

const PreviewCameraState& Renderer::reference_camera() const {
        return reference_camera_;
    }

PreviewCameraState& Renderer::reference_camera() {
        return reference_camera_;
    }

PreviewCameraState Renderer::replacement_camera() const {
        PreviewCameraState camera;
        camera.yaw = yaw_;
        camera.pitch = pitch_;
        camera.fit_to_view = fit_to_view_;
        camera.zoom_factor = zoom_factor_;
        camera.distance = distance_;
        camera.pan_x = pan_x_;
        camera.pan_y = pan_y_;
        camera.pan_z = pan_z_;
        return camera;
    }

void Renderer::set_replacement_camera(const PreviewCameraState& camera) {
        yaw_ = camera.yaw;
        pitch_ = camera.pitch;
        fit_to_view_ = camera.fit_to_view;
        zoom_factor_ = camera.zoom_factor;
        distance_ = camera.distance;
        pan_x_ = camera.pan_x;
        pan_y_ = camera.pan_y;
        pan_z_ = camera.pan_z;
    }

PreviewCameraState Renderer::camera_for_view_role(PreviewViewRole role) const {
        if (role == PreviewViewRole::Reference) {
            return reference_camera_;
        }
        return replacement_camera();
    }

void Renderer::set_camera_for_role(PreviewViewRole role, const PreviewCameraState& camera) {
        if (role == PreviewViewRole::Reference) {
            reference_camera_ = camera;
            return;
        }
        if (role == PreviewViewRole::All) {
            reference_camera_ = camera;
        }
        set_replacement_camera(camera);
    }

DirectX::XMMATRIX Renderer::world_matrix_for_camera(const PreviewCameraState& camera) const {
        return DirectX::XMMatrixRotationRollPitchYaw(
                DirectX::XMConvertToRadians(camera.pitch),
                DirectX::XMConvertToRadians(camera.yaw),
                0.0f)
            * DirectX::XMMatrixTranslation(camera.pan_x, camera.pan_y, camera.pan_z);
    }

DirectX::XMMATRIX Renderer::world_matrix_for_view_role(PreviewViewRole role) const {
        return world_matrix_for_camera(camera_for_view_role(role));
    }

float Renderer::distance_for_view_role(PreviewViewRole role) const {
        return camera_for_view_role(role).distance;
    }

DirectX::XMMATRIX Renderer::view_projection_matrix_for_viewport(const D3D11_VIEWPORT& viewport, float distance) const {
        DirectX::XMMATRIX view = DirectX::XMMatrixLookAtLH(
            DirectX::XMVectorSet(0.0f, 0.0f, -distance, 1.0f),
            DirectX::XMVectorSet(0.0f, 0.0f, 0.0f, 1.0f),
            DirectX::XMVectorSet(0.0f, 1.0f, 0.0f, 0.0f));
        DirectX::XMMATRIX projection = DirectX::XMMatrixPerspectiveFovLH(
            DirectX::XMConvertToRadians(kVerticalFovDegrees),
            std::max(1.0f, viewport.Width) / std::max(1.0f, viewport.Height),
            0.05f,
            100.0f);
        return view * projection;
    }

bool Renderer::alignment_transform_value_active(
        const DirectX::XMFLOAT3& translation,
        const DirectX::XMFLOAT3& rotation,
        const DirectX::XMFLOAT3& scale) {
        constexpr float kEpsilon = 1.0e-6f;
        return std::abs(translation.x) > kEpsilon
            || std::abs(translation.y) > kEpsilon
            || std::abs(translation.z) > kEpsilon
            || std::abs(rotation.x) > kEpsilon
            || std::abs(rotation.y) > kEpsilon
            || std::abs(rotation.z) > kEpsilon
            || std::abs(scale.x - 1.0f) > kEpsilon
            || std::abs(scale.y - 1.0f) > kEpsilon
            || std::abs(scale.z - 1.0f) > kEpsilon;
    }

bool Renderer::alignment_global_transform_active() const {
        return alignment_transform_value_active(
            alignment_.translation_total,
            alignment_.rotation_total,
            alignment_.scale_total);
    }

bool Renderer::alignment_part_transform_active(const AlignmentState::PartTransform& transform) const {
        return alignment_transform_value_active(transform.translation, transform.rotation, transform.scale);
    }

bool Renderer::alignment_preview_transform_active() const {
        if (alignment_global_transform_active()) return true;
        for (const auto& item : alignment_.part_transforms) {
            if (alignment_part_transform_active(item.second)) return true;
        }
        return false;
    }

bool Renderer::alignment_non_translation_transform_active() const {
        constexpr float kEpsilon = 1.0e-6f;
        return std::abs(alignment_.rotation_total.x) > kEpsilon
            || std::abs(alignment_.rotation_total.y) > kEpsilon
            || std::abs(alignment_.rotation_total.z) > kEpsilon
            || std::abs(alignment_.scale_total.x - 1.0f) > kEpsilon
            || std::abs(alignment_.scale_total.y - 1.0f) > kEpsilon
            || std::abs(alignment_.scale_total.z - 1.0f) > kEpsilon;
    }

bool Renderer::alignment_batch_editable(const PreviewBatch& batch) const {
        return !batch_is_reference(batch) && batch.editor_editable;
    }

bool Renderer::alignment_batch_active(const PreviewBatch& batch) const {
        if (!alignment_batch_editable(batch)) return false;
        return alignment_.selected_source_submeshes.empty()
            || alignment_.selected_source_submeshes.find(batch.source_submesh_index) != alignment_.selected_source_submeshes.end();
    }

bool Renderer::alignment_origin_for_batches(DirectX::XMFLOAT3& origin, const std::set<int>* source_filter) const {
        if (source_filter == nullptr && alignment_.origin_cache_valid) {
            origin = alignment_.origin_cache;
            return true;
        }
        bool found = false;
        float min_x = 0.0f;
        float min_y = 0.0f;
        float min_z = 0.0f;
        float max_x = 0.0f;
        float max_y = 0.0f;
        float max_z = 0.0f;
        for (const PreviewBatch& batch : batches_) {
            if (!alignment_batch_editable(batch)) continue;
            if (source_filter != nullptr && source_filter->find(batch.source_submesh_index) == source_filter->end()) continue;
            for (const DirectX::XMFLOAT3& position : batch.cpu_positions) {
                if (!found) {
                    min_x = max_x = position.x;
                    min_y = max_y = position.y;
                    min_z = max_z = position.z;
                    found = true;
                    continue;
                }
                min_x = std::min(min_x, position.x);
                min_y = std::min(min_y, position.y);
                min_z = std::min(min_z, position.z);
                max_x = std::max(max_x, position.x);
                max_y = std::max(max_y, position.y);
                max_z = std::max(max_z, position.z);
            }
        }
        if (!found) return false;
        origin = DirectX::XMFLOAT3(
            (min_x + max_x) * 0.5f,
            (min_y + max_y) * 0.5f,
            (min_z + max_z) * 0.5f);
        if (source_filter == nullptr) {
            alignment_.origin_cache = origin;
            alignment_.origin_cache_valid = true;
        }
        return true;
    }

bool Renderer::alignment_handle_origin_base(DirectX::XMFLOAT3& origin) const {
        if (!alignment_.selected_source_submeshes.empty()) {
            return alignment_origin_for_batches(origin, &alignment_.selected_source_submeshes);
        }
        return alignment_origin_for_batches(origin, nullptr);
    }

bool Renderer::alignment_global_origin_base(DirectX::XMFLOAT3& origin) const {
        return alignment_origin_for_batches(origin, nullptr);
    }

bool Renderer::alignment_part_origin_base(int source_submesh_index, DirectX::XMFLOAT3& origin) const {
        std::set<int> source_filter;
        source_filter.insert(source_submesh_index);
        return alignment_origin_for_batches(origin, &source_filter);
    }

DirectX::XMMATRIX Renderer::alignment_transform_matrix(
        const DirectX::XMFLOAT3& origin,
        const DirectX::XMFLOAT3& translation,
        const DirectX::XMFLOAT3& rotation,
        const DirectX::XMFLOAT3& scale) {
        return DirectX::XMMatrixTranslation(-origin.x, -origin.y, -origin.z)
            * DirectX::XMMatrixScaling(
                std::max(0.001f, scale.x),
                std::max(0.001f, scale.y),
                std::max(0.001f, scale.z))
            * DirectX::XMMatrixRotationRollPitchYaw(
                DirectX::XMConvertToRadians(rotation.x),
                DirectX::XMConvertToRadians(rotation.y),
                DirectX::XMConvertToRadians(rotation.z))
            * DirectX::XMMatrixTranslation(origin.x, origin.y, origin.z)
            * DirectX::XMMatrixTranslation(
                translation.x,
                translation.y,
                translation.z);
    }

DirectX::XMMATRIX Renderer::alignment_preview_transform_for_batch(const PreviewBatch& batch) const {
        if (!alignment_batch_editable(batch)) {
            return DirectX::XMMatrixIdentity();
        }
        DirectX::XMMATRIX transform = DirectX::XMMatrixIdentity();
        if (alignment_global_transform_active()) {
            DirectX::XMFLOAT3 origin{};
            if (!alignment_global_origin_base(origin)) {
                origin = DirectX::XMFLOAT3(0.0f, 0.0f, 0.0f);
            }
            transform = alignment_transform_matrix(
                origin,
                alignment_.translation_total,
                alignment_.rotation_total,
                alignment_.scale_total);
        }
        auto part = alignment_.part_transforms.find(batch.source_submesh_index);
        if (part != alignment_.part_transforms.end() && alignment_part_transform_active(part->second)) {
            DirectX::XMFLOAT3 origin{};
            if (!alignment_part_origin_base(batch.source_submesh_index, origin)) {
                origin = DirectX::XMFLOAT3(0.0f, 0.0f, 0.0f);
            }
            transform = alignment_transform_matrix(
                origin,
                part->second.translation,
                part->second.rotation,
                part->second.scale)
                * transform;
        }
        return transform;
    }

bool Renderer::batch_uses_source_normalization(const PreviewBatch& batch) {
        constexpr float kEpsilon = 1.0e-6f;
        return std::abs(batch.normalization_scale - 1.0f) > kEpsilon
            || std::abs(batch.normalization_center[0]) > kEpsilon
            || std::abs(batch.normalization_center[1]) > kEpsilon
            || std::abs(batch.normalization_center[2]) > kEpsilon;
    }

DirectX::XMMATRIX Renderer::source_to_preview_normalization_transform(const PreviewBatch& batch) {
        const float scale = (std::isfinite(batch.normalization_scale) && std::abs(batch.normalization_scale) > 1e-8f)
            ? batch.normalization_scale
            : 1.0f;
        return DirectX::XMMatrixScaling(scale, scale, scale)
            * DirectX::XMMatrixTranslation(
                -batch.normalization_center[0] * scale,
                -batch.normalization_center[1] * scale,
                -batch.normalization_center[2] * scale);
    }

DirectX::XMFLOAT3 Renderer::source_to_preview_position_for_batch(const PreviewBatch& batch, const DirectX::XMFLOAT3& position) {
        if (!batch_uses_source_normalization(batch)) {
            return position;
        }
        DirectX::XMVECTOR source = DirectX::XMLoadFloat3(&position);
        DirectX::XMVECTOR transformed = DirectX::XMVector3TransformCoord(source, source_to_preview_normalization_transform(batch));
        DirectX::XMFLOAT3 output{};
        DirectX::XMStoreFloat3(&output, transformed);
        return output;
    }

DirectX::XMMATRIX Renderer::mesh_edit_source_world_transform_for_batch(const PreviewBatch& batch) const {
        DirectX::XMMATRIX transform = source_to_preview_normalization_transform(batch);
        if (alignment_preview_transform_active()) {
            transform = transform * alignment_preview_transform_for_batch(batch);
        }
        return transform;
    }
