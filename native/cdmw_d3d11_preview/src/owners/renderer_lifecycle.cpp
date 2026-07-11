Renderer::Renderer(
        HWND hwnd,
        const Args& args,
        std::vector<PreviewBatch> batches,
        std::vector<ClothCollider> cloth_colliders,
        SkeletonOverlayState skeleton_overlay,
        RendererStats& stats,
        ViewSettings view_settings,
        RenderTuning render_tuning,
        std::string display_mode)
        : hwnd_(hwnd),
          args_(args),
          batches_(std::move(batches)),
          cloth_colliders_(std::move(cloth_colliders)),
          skeleton_overlay_(std::move(skeleton_overlay)),
          stats_(stats),
          view_settings_(view_settings),
          render_tuning_(render_tuning),
          display_mode_(normalize_display_mode(std::move(display_mode), "replacement_only")) {
        stats_.sampler_max_anisotropy = std::clamp(render_tuning_.max_anisotropy, 1, 16);
        stats_.sampler_mip_lod_bias = std::clamp(render_tuning_.mip_lod_bias, -2.0f, 1.0f);
    }

Renderer::~Renderer() {
        if (!batches_.empty() || !srv_cache_.empty() || !texture_info_cache_.empty() || estimated_texture_bytes_ > 0) {
            release_model_resources("destructor");
        }
    }

bool Renderer::initialize() {
        RECT rect{};
        GetClientRect(hwnd_, &rect);
        width_ = std::max<LONG>(1, rect.right - rect.left);
        height_ = std::max<LONG>(1, rect.bottom - rect.top);

        D3D_FEATURE_LEVEL requested[] = {D3D_FEATURE_LEVEL_11_1, D3D_FEATURE_LEVEL_11_0};
        HRESULT hr = E_FAIL;
        const UINT sample_candidates[] = {4, 2, 1};
        for (UINT sample_count : sample_candidates) {
            DXGI_SWAP_CHAIN_DESC swap_desc{};
            swap_desc.BufferCount = 2;
            swap_desc.BufferDesc.Width = static_cast<UINT>(width_);
            swap_desc.BufferDesc.Height = static_cast<UINT>(height_);
            swap_desc.BufferDesc.Format = DXGI_FORMAT_R8G8B8A8_UNORM;
            swap_desc.BufferUsage = DXGI_USAGE_RENDER_TARGET_OUTPUT;
            swap_desc.OutputWindow = hwnd_;
            swap_desc.SampleDesc.Count = sample_count;
            swap_desc.SampleDesc.Quality = 0;
            swap_desc.Windowed = TRUE;
            swap_desc.SwapEffect = DXGI_SWAP_EFFECT_DISCARD;
            swap_chain_.Reset();
            device_.Reset();
            context_.Reset();
            hr = D3D11CreateDeviceAndSwapChain(
                nullptr,
                D3D_DRIVER_TYPE_HARDWARE,
                nullptr,
                0,
                requested,
                2,
                D3D11_SDK_VERSION,
                &swap_desc,
                swap_chain_.GetAddressOf(),
                device_.GetAddressOf(),
                &feature_level_,
                context_.GetAddressOf());
            if (SUCCEEDED(hr)) {
                msaa_sample_count_ = sample_count;
                break;
            }
        }
        if (FAILED(hr)) {
            stats_.skipped.push_back("D3D11CreateDeviceAndSwapChain failed");
            return false;
        }
        return create_render_targets() && create_pipeline() && upload_batches();
    }

void Renderer::request_render() {
        if (device_lost_) return;
        ++render_request_count_;
        stats_.render_request_count = render_request_count_;
        render_requested_ = true;
    }

bool Renderer::should_render() const {
        return !device_lost_ && (render_requested_ || !first_frame_reported_ || cloth_preview_active());
    }

bool Renderer::device_lost() const {
        return device_lost_;
    }

std::string Renderer::capture_back_buffer_to_png(const fs::path& output) {
        if (!device_ || !context_ || !swap_chain_) {
            return "{\"event\":\"frame_capture\",\"ok\":false,\"message\":\"D3D11 device is not ready\"}";
        }
        if (output.empty()) {
            return "{\"event\":\"frame_capture\",\"ok\":false,\"message\":\"capture path is empty\"}";
        }
        try {
            if (output.has_parent_path()) {
                fs::create_directories(output.parent_path());
            }
        } catch (const std::exception& exc) {
            std::ostringstream out;
            out << "{\"event\":\"frame_capture\",\"ok\":false,\"message\":\"create_directories failed: "
                << json_escape(exc.what()) << "\"}";
            return out.str();
        }
        ComPtr<ID3D11Texture2D> back_buffer;
        HRESULT hr = swap_chain_->GetBuffer(0, IID_PPV_ARGS(back_buffer.GetAddressOf()));
        if (FAILED(hr)) {
            std::ostringstream out;
            out << "{\"event\":\"frame_capture\",\"ok\":false,\"message\":\"GetBuffer failed\",\"hresult\":\""
                << hresult_hex(hr) << "\"}";
            return out.str();
        }
        DirectX::ScratchImage image;
        hr = DirectX::CaptureTexture(device_.Get(), context_.Get(), back_buffer.Get(), image);
        if (FAILED(hr)) {
            std::ostringstream out;
            out << "{\"event\":\"frame_capture\",\"ok\":false,\"message\":\"CaptureTexture failed\",\"hresult\":\""
                << hresult_hex(hr) << "\"}";
            return out.str();
        }
        const DirectX::Image* frame = image.GetImage(0, 0, 0);
        if (frame == nullptr) {
            return "{\"event\":\"frame_capture\",\"ok\":false,\"message\":\"CaptureTexture returned no image\"}";
        }
        hr = DirectX::SaveToWICFile(*frame, DirectX::WIC_FLAGS_NONE, GUID_ContainerFormatPng, output.c_str());
        if (FAILED(hr)) {
            std::ostringstream out;
            out << "{\"event\":\"frame_capture\",\"ok\":false,\"message\":\"SaveToWICFile failed\",\"hresult\":\""
                << hresult_hex(hr) << "\"}";
            return out.str();
        }
        std::ostringstream out;
        out << "{\"event\":\"frame_capture\",\"ok\":true,\"path\":\"" << json_escape(cdmw_native_diag::path_to_utf8(output)) << "\"}";
        return out.str();
    }

void Renderer::note_render_suppressed(const char* reason) {
        ++render_suppressed_count_;
        stats_.render_suppressed_count = render_suppressed_count_;
        if (reason && reason[0]) {
            stats_.parent_health = reason;
            stats_.render_suppressed_reason = reason;
            stats_.parent_renderable = std::string(reason) != "parent_not_renderable";
        }
        if (render_suppressed_count_ == 1 || render_suppressed_count_ % 120 == 0) {
            cdmw_native_diag::event(
                "render_suppressed",
                {
                    {"reason", reason && reason[0] ? reason : "not_visible"},
                    {"render_suppressed_count", std::to_string(render_suppressed_count_)},
                    {"render_request_count", std::to_string(render_request_count_)},
                    {"frame_count", std::to_string(frame_count_)}
                });
        }
    }

void Renderer::set_parent_health(const std::string& health, std::uint64_t unresponsive_count) {
        parent_health_ = health.empty() ? "ok" : health;
        parent_unresponsive_count_ = unresponsive_count;
        stats_.parent_health = parent_health_;
        stats_.parent_unresponsive_count = parent_unresponsive_count_;
    }

void Renderer::prune_srv_cache_if_needed(const char* reason) {
        if (srv_cache_.size() <= kSrvCacheSoftMaxEntries && estimated_texture_bytes_ <= kSrvCacheSoftMaxBytes) return;
        const size_t released_srv_entries = srv_cache_.size();
        const size_t released_texture_info_entries = texture_info_cache_.size();
        const std::uint64_t released_texture_bytes = estimated_texture_bytes_;
        srv_cache_.clear();
        texture_info_cache_.clear();
        estimated_texture_bytes_ = 0;
        active_texture_bytes_ = active_bound_texture_bytes();
        ++texture_cache_releases_;
        cdmw_native_diag::event(
            "texture_cache_pruned",
            {
                {"reason", reason && reason[0] ? reason : "soft_cap"},
                {"released_texture_cache_entries", std::to_string(released_srv_entries)},
                {"released_texture_info_entries", std::to_string(released_texture_info_entries)},
                {"released_estimated_texture_bytes", std::to_string(released_texture_bytes)},
                {"live_texture_bytes", std::to_string(active_texture_bytes_)},
                {"texture_cache_releases", std::to_string(texture_cache_releases_)}
            });
    }

void Renderer::release_model_resources(const char* reason) {
        const std::string reason_text = reason && reason[0] ? reason : "release";
        const size_t released_batches = batches_.size();
        const bool release_texture_cache =
            reason_text == "shutdown"
            || reason_text == "destructor"
            || reason_text == "clear"
            || reason_text == "load-missing-package"
            || reason_text == "parent_unresponsive"
            || reason_text == "parent_window_gone";
        const size_t released_srv_entries = release_texture_cache ? srv_cache_.size() : 0;
        const size_t released_texture_info_entries = release_texture_cache ? texture_info_cache_.size() : 0;
        const std::uint64_t released_texture_bytes = release_texture_cache ? estimated_texture_bytes_ : 0;
        const std::uint64_t released_live_texture_bytes = active_bound_texture_bytes();

        if (context_) {
            ID3D11ShaderResourceView* null_srvs[kTotalSrvCount] = {};
            context_->PSSetShaderResources(0, kTotalSrvCount, null_srvs);
            ID3D11Buffer* null_vertex_buffer = nullptr;
            UINT stride = 0;
            UINT offset = 0;
            context_->IASetVertexBuffers(0, 1, &null_vertex_buffer, &stride, &offset);
            context_->Flush();
        }
        batches_.clear();
        ++model_generation_;
        invalidate_mesh_edit_caches();
        cloth_colliders_.clear();
        active_texture_bytes_ = 0;
        if (release_texture_cache) {
            srv_cache_.clear();
            texture_info_cache_.clear();
            estimated_texture_bytes_ = 0;
        }
        if (released_batches || released_srv_entries || released_texture_info_entries || released_texture_bytes) {
            ++texture_cache_releases_;
        }
        const RendererStats previous_stats = stats_;
        stats_ = RendererStats{};
        if (reason_text == "device_lost") {
            stats_.device_lost = previous_stats.device_lost;
            stats_.device_loss_stage = previous_stats.device_loss_stage;
            stats_.device_loss_hresult = previous_stats.device_loss_hresult;
            stats_.device_removed_reason = previous_stats.device_removed_reason;
            stats_.present_failure_count = previous_stats.present_failure_count;
            stats_.resize_failure_count = previous_stats.resize_failure_count;
            stats_.resize_failure_hresult = previous_stats.resize_failure_hresult;
            stats_.resize_failure_reason = previous_stats.resize_failure_reason;
        }
        update_runtime_stats();
        cdmw_native_diag::event(
            "model_resources_released",
            {
                {"reason", reason_text},
                {"released_batches", std::to_string(released_batches)},
                {"released_texture_cache_entries", std::to_string(released_srv_entries)},
                {"released_texture_info_entries", std::to_string(released_texture_info_entries)},
                {"released_estimated_texture_bytes", std::to_string(released_texture_bytes)},
                {"released_live_texture_bytes", std::to_string(released_live_texture_bytes)},
                {"texture_cache_releases", std::to_string(texture_cache_releases_)}
            });
    }

void Renderer::reset_mesh_edit_revision_state() {
        if (!pending_mesh_edit_vertices_payload_.empty()) {
            delete_mesh_edit_payload_descriptors(pending_mesh_edit_vertices_payload_);
        }
        if (!pending_mesh_edit_vertices_file_.empty()) {
            cleanup_mesh_edit_vertices_file(
                pending_mesh_edit_vertices_file_,
                pending_mesh_edit_vertices_delete_after_);
        }
        pending_mesh_edit_vertices_payload_.clear();
        pending_mesh_edit_vertices_file_.clear();
        pending_mesh_edit_vertices_delete_after_ = false;
        pending_mesh_edit_vertices_revision_ = 0;
        last_applied_mesh_edit_revision_ = 0;
    }

std::vector<std::string> Renderer::missing_package_paths(const std::vector<PreviewBatch>& batches) const {
        std::vector<std::string> missing_paths;
        auto require_path = [&](const std::wstring& path, const char* label) {
            if (path.empty()) return;
            if (!fs::is_regular_file(fs::path(path)) && missing_paths.size() < 12) {
                missing_paths.push_back(std::string(label) + ":" + wide_to_utf8(path));
            }
        };
        for (const PreviewBatch& batch : batches) {
            require_path(batch.vertex_file, "vertex");
            require_path(batch.base_dds, "base_dds");
            require_path(batch.normal_dds, "normal_dds");
            require_path(batch.material_dds, "material_dds");
            require_path(batch.specular_dds, "specular_dds");
            require_path(batch.detail_dds, "detail_dds");
            require_path(batch.height_dds, "height_dds");
            require_path(batch.emissive_dds, "emissive_dds");
            require_path(batch.base_png, "base_png");
            require_path(batch.height_png, "height_png");
            require_path(batch.emissive_png, "emissive_png");
            if (batch.cloth.available) {
                require_path(batch.cloth.particle_file, "cloth_particles");
                require_path(batch.cloth.pin_file, "cloth_pins");
                require_path(batch.cloth.constraint_file, "cloth_constraints");
            }
            for (int layer_index = 0; layer_index < batch.material_layer_count; ++layer_index) {
                const PreviewMaterialLayer& layer = batch.material_layers[static_cast<size_t>(layer_index)];
                require_path(layer.diffuse_dds, "layer_diffuse");
                require_path(layer.mask_dds, "layer_mask");
                require_path(layer.material_dds, "layer_material");
                require_path(layer.normal_dds, "layer_normal");
                require_path(layer.height_dds, "layer_height");
            }
        }
        return missing_paths;
}

bool Renderer::load_package(const fs::path& package_dir, const fs::path& status_file, bool reset_view_state) {
        reset_mesh_edit_revision_state();
        if (package_dir.empty() || !fs::is_directory(package_dir)) {
            release_model_resources("load-missing-package");
            request_render();
            if (hwnd_) InvalidateRect(hwnd_, nullptr, FALSE);
            write_status(status_file, "{\"event\":\"error\",\"backend\":\"D3D11\",\"message\":\"preview package directory is missing\"}");
            cdmw_native_diag::event("package_load_error", {{"reason", "package directory missing"}, {"package_dir", cdmw_native_diag::path_to_utf8(package_dir)}});
            return false;
        }
        device_lost_ = false;
        args_.preview_package = package_dir;
        if (!status_file.empty()) {
            args_.status_file = status_file;
        }
        cdmw_native_diag::event("package_load_start", {{"package_dir", cdmw_native_diag::path_to_utf8(args_.preview_package)}, {"status_file", cdmw_native_diag::path_to_utf8(args_.status_file)}});
        write_status(args_.status_file, "{\"event\":\"loading\",\"backend\":\"D3D11\",\"stage\":\"manifest\",\"percent\":85,\"current\":85,\"total\":100,\"message\":\"Loading native D3D11 preview package...\"}");
        auto start = std::chrono::steady_clock::now();
        std::string manifest;
        RendererStats next_stats;
        std::vector<PreviewBatch> next_batches;
        std::vector<ClothCollider> next_cloth_colliders;
        SkeletonOverlayState next_skeleton_overlay;
        ViewSettings next_view_settings;
        RenderTuning next_render_tuning;
        std::string next_display_mode;
        try {
            manifest = read_text(args_.preview_package / L"manifest.json");
            next_batches = parse_manifest_batches(args_.preview_package, manifest, next_stats);
            next_skeleton_overlay = parse_skeleton_overlay_state(manifest, next_stats);
            next_cloth_colliders = parse_cloth_colliders(args_.preview_package, manifest);
            next_stats.cloth_collider_count = static_cast<int>(next_cloth_colliders.size());
            next_view_settings = parse_view_settings(manifest);
            next_render_tuning = parse_render_tuning(manifest);
            next_display_mode = parse_display_mode(manifest, display_mode_);
        } catch (const std::exception& exc) {
            request_render();
            if (hwnd_) InvalidateRect(hwnd_, nullptr, FALSE);
            write_status(args_.status_file, "{\"event\":\"error\",\"backend\":\"D3D11\",\"message\":\"native D3D11 manifest read/parse failed\"}");
            cdmw_native_diag::event("package_load_error", {{"reason", std::string("manifest read/parse failed: ") + exc.what()}, {"package_dir", cdmw_native_diag::path_to_utf8(args_.preview_package)}});
            return false;
        }
        const std::vector<std::string> missing_paths = missing_package_paths(next_batches);
        if (next_batches.empty() || !missing_paths.empty()) {
            request_render();
            if (hwnd_) InvalidateRect(hwnd_, nullptr, FALSE);
            std::ostringstream message;
            message << (next_batches.empty() ? "native D3D11 manifest had no renderable batches" : "native D3D11 manifest referenced missing files");
            write_status(args_.status_file, "{\"event\":\"error\",\"backend\":\"D3D11\",\"message\":\"native D3D11 package validation failed\"}");
            cdmw_native_diag::event(
                "package_load_error",
                {
                    {"reason", message.str()},
                    {"missing_count", std::to_string(missing_paths.size())},
                    {"missing_examples", missing_paths.empty() ? "" : missing_paths.front()},
                    {"package_dir", cdmw_native_diag::path_to_utf8(args_.preview_package)}
                });
            return false;
        }
        next_stats.manifest_ms = std::chrono::duration<double, std::milli>(std::chrono::steady_clock::now() - start).count();
        write_status(args_.status_file, "{\"event\":\"loading\",\"backend\":\"D3D11\",\"stage\":\"upload\",\"percent\":90,\"current\":90,\"total\":100,\"message\":\"Uploading D3D11 geometry and DDS textures...\"}");
        if (!upload_batches(next_batches, next_stats)) {
            write_status(args_.status_file, error_payload("native D3D11 package reload failed", next_stats));
            cdmw_native_diag::event(
                "package_load_error",
                {
                    {"reason", "upload failed"},
                    {"package_dir", cdmw_native_diag::path_to_utf8(args_.preview_package)},
                    {"texture_failures", std::to_string(next_stats.texture_failures)},
                    {"skipped", std::to_string(next_stats.skipped.size())}
                });
            return false;
        }
        release_model_resources("reload");
        batches_ = std::move(next_batches);
        cloth_colliders_ = std::move(next_cloth_colliders);
        skeleton_overlay_ = std::move(next_skeleton_overlay);
        hidden_source_submeshes_.clear();
        stats_ = next_stats;
        if (!view_settings_overridden_) {
            view_settings_ = next_view_settings;
        }
        if (!render_tuning_overridden_) {
            render_tuning_ = next_render_tuning;
        }
        display_mode_ = normalize_display_mode(next_display_mode, display_mode_);
        first_frame_started_ = false;
        first_frame_reported_ = false;
        mesh_edit_.drag_active = false;
        mesh_edit_.selection_drag_active = false;
        mesh_edit_.drag_uses_resident_selection = false;
        mesh_edit_.selection_lasso_points.clear();
        mesh_edit_.selected_vertices.clear();
        mesh_edit_.selected_edges.clear();
        mesh_edit_.selected_faces.clear();
        mesh_edit_.selected_sources.clear();
        hidden_source_submeshes_.clear();
        alignment_.drag_active = false;
        alignment_.rotation_drag_active = false;
        alignment_.hover_axis.clear();
        alignment_.drag_axis.clear();
        alignment_.translation_drag_base = DirectX::XMFLOAT3(0.0f, 0.0f, 0.0f);
        alignment_.translation_drag_delta = DirectX::XMFLOAT3(0.0f, 0.0f, 0.0f);
        alignment_.rotation_drag_base = DirectX::XMFLOAT3(0.0f, 0.0f, 0.0f);
        alignment_.rotation_drag_delta = DirectX::XMFLOAT3(0.0f, 0.0f, 0.0f);
        alignment_.part_translation_drag_bases.clear();
        alignment_.part_rotation_drag_bases.clear();
        alignment_.origin_cache_valid = false;
        source_part_.hovered_source_submesh = -1;
        source_part_.click_pending = false;
        source_part_.click_source_submesh = -1;
        if (reset_view_state) {
            reset_view();
        }
        update_runtime_stats();
        write_status(args_.status_file, resources_loaded_payload(stats_));
        request_render();
        cdmw_native_diag::event(
            "package_loaded",
            {
                {"package_dir", cdmw_native_diag::path_to_utf8(args_.preview_package)},
                {"batches", std::to_string(stats_.batch_count)},
                {"vertices", std::to_string(stats_.vertex_count)},
                {"display_mode", display_mode_},
                {"dds_uploaded_base", std::to_string(stats_.dds_uploaded.base)},
                {"png_fallback", std::to_string(stats_.png_fallback)},
                {"texture_cache_entries", std::to_string(stats_.texture_cache_entries)},
                {"estimated_texture_bytes", std::to_string(stats_.estimated_texture_bytes)},
                {"texture_cache_bytes", std::to_string(stats_.texture_cache_bytes)},
                {"live_texture_bytes", std::to_string(stats_.live_texture_bytes)}
            });
        return true;
    }

bool Renderer::clear_preview(const fs::path& status_file) {
        if (!status_file.empty()) {
            args_.status_file = status_file;
        }
        release_model_resources("clear");
        skeleton_overlay_ = SkeletonOverlayState{};
        pending_package_dir_.clear();
        pending_status_file_.clear();
        pending_reset_view_ = false;
        first_frame_started_ = true;
        first_frame_reported_ = true;
        mesh_edit_.drag_active = false;
        mesh_edit_.selection_drag_active = false;
        mesh_edit_.drag_uses_resident_selection = false;
        mesh_edit_.selection_lasso_points.clear();
        mesh_edit_.selected_vertices.clear();
        mesh_edit_.selected_edges.clear();
        mesh_edit_.selected_faces.clear();
        mesh_edit_.selected_sources.clear();
        alignment_.drag_active = false;
        alignment_.rotation_drag_active = false;
        alignment_.hover_axis.clear();
        alignment_.drag_axis.clear();
        alignment_.selected_source_submeshes.clear();
        alignment_.part_transforms.clear();
        alignment_.part_translation_drag_bases.clear();
        alignment_.part_rotation_drag_bases.clear();
        alignment_.translation_total = DirectX::XMFLOAT3(0.0f, 0.0f, 0.0f);
        alignment_.rotation_total = DirectX::XMFLOAT3(0.0f, 0.0f, 0.0f);
        alignment_.scale_total = DirectX::XMFLOAT3(1.0f, 1.0f, 1.0f);
        alignment_.translation_drag_base = DirectX::XMFLOAT3(0.0f, 0.0f, 0.0f);
        alignment_.translation_drag_delta = DirectX::XMFLOAT3(0.0f, 0.0f, 0.0f);
        alignment_.rotation_drag_base = DirectX::XMFLOAT3(0.0f, 0.0f, 0.0f);
        alignment_.rotation_drag_delta = DirectX::XMFLOAT3(0.0f, 0.0f, 0.0f);
        alignment_.origin_cache_valid = false;
        source_part_.hovered_source_submesh = -1;
        source_part_.click_pending = false;
        source_part_.click_source_submesh = -1;
        if (hwnd_) {
            InvalidateRect(hwnd_, nullptr, FALSE);
        }
        request_render();
        update_runtime_stats();
        write_status(args_.status_file, cleared_payload(stats_));
        cdmw_native_diag::event(
            "preview_cleared",
            {
                {"status_file", cdmw_native_diag::path_to_utf8(args_.status_file)},
                {"texture_cache_entries", std::to_string(stats_.texture_cache_entries)},
                {"estimated_texture_bytes", std::to_string(stats_.estimated_texture_bytes)},
                {"texture_cache_bytes", std::to_string(stats_.texture_cache_bytes)},
                {"live_texture_bytes", std::to_string(stats_.live_texture_bytes)}
            });
        return true;
    }

bool Renderer::handle_pointer_down_or_move(UINT msg, WPARAM wparam, LPARAM lparam, LRESULT& result) {
        switch (msg) {
        case WM_LBUTTONDOWN:
            cursor_x_ = GET_X_LPARAM(lparam);
            cursor_y_ = GET_Y_LPARAM(lparam);
            if (begin_side_by_side_split_drag(GET_X_LPARAM(lparam), GET_Y_LPARAM(lparam))) {
                request_render();
                result = 0;
                return true;
            }
            if (begin_alignment_drag(wparam, GET_X_LPARAM(lparam), GET_Y_LPARAM(lparam))) {
                request_render();
                result = 0;
                return true;
            }
            begin_source_part_click(wparam, GET_X_LPARAM(lparam), GET_Y_LPARAM(lparam));
            if (source_part_.click_pending) {
                request_render();
                result = 0;
                return true;
            }
            if (begin_mesh_edit_drag(wparam, GET_X_LPARAM(lparam), GET_Y_LPARAM(lparam))) {
                request_render();
                result = 0;
                return true;
            }
            [[fallthrough]];
        case WM_MBUTTONDOWN:
            begin_mouse_drag(msg, wparam, GET_X_LPARAM(lparam), GET_Y_LPARAM(lparam));
            request_render();
            result = 0;
            return true;
        case WM_RBUTTONDOWN:
            cursor_x_ = GET_X_LPARAM(lparam);
            cursor_y_ = GET_Y_LPARAM(lparam);
            if (request_source_part_context(wparam, GET_X_LPARAM(lparam), GET_Y_LPARAM(lparam))) {
                request_render();
                result = 0;
                return true;
            }
            begin_mouse_drag(msg, wparam, GET_X_LPARAM(lparam), GET_Y_LPARAM(lparam));
            request_render();
            result = 0;
            return true;
        case WM_MOUSEMOVE:
            cursor_x_ = GET_X_LPARAM(lparam);
            cursor_y_ = GET_Y_LPARAM(lparam);
            if (update_side_by_side_split_drag(GET_X_LPARAM(lparam), GET_Y_LPARAM(lparam))) {
                request_render();
                result = 0;
                return true;
            }
            if (update_mesh_edit_drag(GET_X_LPARAM(lparam), GET_Y_LPARAM(lparam))) {
                request_render();
                result = 0;
                return true;
            }
            if (update_alignment_drag(GET_X_LPARAM(lparam), GET_Y_LPARAM(lparam), wparam)) {
                request_render();
                result = 0;
                return true;
            }
            update_alignment_hover(GET_X_LPARAM(lparam), GET_Y_LPARAM(lparam));
            update_source_part_hover(GET_X_LPARAM(lparam), GET_Y_LPARAM(lparam));
            update_mouse_drag(GET_X_LPARAM(lparam), GET_Y_LPARAM(lparam));
            request_render();
            result = 0;
            return drag_mode_ != 0;
        default:
            return false;
        }
}

bool Renderer::handle_window_message(UINT msg, WPARAM wparam, LPARAM lparam, LRESULT& result) {
        if (msg == WM_LBUTTONDOWN || msg == WM_MBUTTONDOWN || msg == WM_RBUTTONDOWN || msg == WM_MOUSEMOVE) {
            return handle_pointer_down_or_move(msg, wparam, lparam, result);
        }
        switch (msg) {
        case WM_COPYDATA:
            result = handle_copy_data(reinterpret_cast<COPYDATASTRUCT*>(lparam)) ? 1 : 0;
            request_render();
            return true;
        case WM_SIZE:
            request_render();
            return false;
        case WM_PAINT:
        {
            PAINTSTRUCT ps{};
            BeginPaint(hwnd_, &ps);
            EndPaint(hwnd_, &ps);
            request_render();
            result = 0;
            return true;
        }
        case kCdmwSetZoomMessage:
            set_zoom_factor(static_cast<float>(wparam) / 1000.0f);
            request_render();
            result = 0;
            return true;
        case kCdmwSetFitMessage:
            set_fit_to_view(wparam != 0);
            request_render();
            result = 0;
            return true;
        case kCdmwResetViewMessage:
            reset_view();
            request_render();
            result = 0;
            return true;
        case WM_LBUTTONDBLCLK:
        {
            if (mesh_edit_.enabled || source_part_.picking_enabled) {
                source_part_.click_pending = false;
                result = 0;
                return true;
            }
            const PreviewViewRole reset_role = input_view_role_at(GET_X_LPARAM(lparam), GET_Y_LPARAM(lparam));
            reset_camera_for_role(reset_role);
            send_view_event("reset_role", reset_role);
            request_render();
            result = 0;
            return true;
        }
        case WM_LBUTTONUP:
            if (finish_side_by_side_split_drag(GET_X_LPARAM(lparam), GET_Y_LPARAM(lparam))) {
                request_render();
                result = 0;
                return true;
            }
            if (finish_mesh_edit_drag(GET_X_LPARAM(lparam), GET_Y_LPARAM(lparam))) {
                request_render();
                result = 0;
                return true;
            }
            if (finish_alignment_drag(GET_X_LPARAM(lparam), GET_Y_LPARAM(lparam), wparam)) {
                request_render();
                result = 0;
                return true;
            }
            finish_source_part_click(GET_X_LPARAM(lparam), GET_Y_LPARAM(lparam));
            [[fallthrough]];
        case WM_MBUTTONUP:
        case WM_RBUTTONUP:
            end_mouse_drag(msg);
            request_render();
            result = 0;
            return true;
        case WM_CONTEXTMENU:
            result = 0;
            return true;
        case WM_CANCELMODE:
        case WM_KILLFOCUS:
            cancel_mouse_interaction();
            request_render();
            result = 0;
            return false;
        case WM_CAPTURECHANGED:
            cancel_mouse_interaction(false);
            request_render();
            return false;
        case WM_MOUSEWHEEL:
        {
            POINT point{GET_X_LPARAM(lparam), GET_Y_LPARAM(lparam)};
            ScreenToClient(hwnd_, &point);
            apply_wheel_delta(GET_WHEEL_DELTA_WPARAM(wparam), point.x, point.y);
            request_render();
            result = 0;
            return true;
        }
        default:
            return false;
        }
    }

void Renderer::render() {
        if (!context_ || !swap_chain_ || device_lost_) return;
        if (!resize_if_needed()) {
            render_requested_ = !device_lost_;
            if (render_requested_ && hwnd_) InvalidateRect(hwnd_, nullptr, FALSE);
            return;
        }
        step_cloth_simulation();
        flush_pending_mesh_edit_vertex_uploads();
        if (!first_frame_started_) {
            first_frame_timer_ = std::chrono::steady_clock::now();
            first_frame_started_ = true;
        }
        float clear[4] = {clear_color_.x, clear_color_.y, clear_color_.z, 1.0f};
        context_->OMSetRenderTargets(1, render_target_.GetAddressOf(), depth_view_.Get());
        context_->ClearRenderTargetView(render_target_.Get(), clear);
        context_->ClearDepthStencilView(depth_view_.Get(), D3D11_CLEAR_DEPTH, 1.0f, 0);
        context_->IASetInputLayout(input_layout_.Get());
        context_->IASetPrimitiveTopology(D3D11_PRIMITIVE_TOPOLOGY_TRIANGLELIST);
        context_->VSSetShader(vertex_shader_.Get(), nullptr, 0);
        context_->PSSetShader(pixel_shader_.Get(), nullptr, 0);
        context_->PSSetSamplers(0, 1, sampler_.GetAddressOf());
        for (const PreviewRenderView& view : active_render_views()) {
            draw_render_view(view);
        }
        draw_side_by_side_splitter_overlay();
        std::string capture_event;
        if (!pending_capture_path_.empty()) {
            fs::path capture_path = pending_capture_path_;
            pending_capture_path_.clear();
            capture_event = capture_back_buffer_to_png(capture_path);
        }
        HRESULT present_hr = env_flag_enabled("CDMW_D3D11_PREVIEW_FORCE_PRESENT_FAILURE")
            ? DXGI_ERROR_DEVICE_REMOVED
            : swap_chain_->Present(1, 0);
        if (FAILED(present_hr)) {
            if (is_device_loss_hresult(present_hr)) {
                handle_device_loss("Present", present_hr);
            } else {
                handle_render_failure("Present", present_hr);
            }
            if (!capture_event.empty()) {
                send_json_event(capture_event);
            }
            return;
        }
        ValidateRect(hwnd_, nullptr);
        if (!icon_capture_mode_) {
            draw_alignment_overlay_gdi();
        }
        if (!capture_event.empty()) {
            send_json_event(capture_event);
        }
        ++frame_count_;
        stats_.frame_count = frame_count_;
        render_requested_ = false;
        if (!first_frame_reported_) {
            stats_.first_frame_ms = std::chrono::duration<double, std::milli>(
                std::chrono::steady_clock::now() - first_frame_timer_).count();
            update_runtime_stats();
            write_status(args_.status_file, loaded_payload(stats_));
            first_frame_reported_ = true;
            cdmw_native_diag::event(
                "first_frame",
                {
                    {"first_frame_ms", std::to_string(stats_.first_frame_ms)},
                    {"batches", std::to_string(stats_.batch_count)},
                    {"vertices", std::to_string(stats_.vertex_count)},
                    {"texture_cache_entries", std::to_string(stats_.texture_cache_entries)},
                    {"estimated_texture_bytes", std::to_string(stats_.estimated_texture_bytes)},
                    {"texture_cache_bytes", std::to_string(stats_.texture_cache_bytes)},
                    {"live_texture_bytes", std::to_string(stats_.live_texture_bytes)}
                });
        }
    }

bool Renderer::process_pending_commands() {
        bool processed = process_pending_mesh_edit_vertex_update();
        if (pending_package_dir_.empty()) return processed;
        if (alignment_.drag_active || alignment_.rotation_drag_active) {
            drop_pending_package_reload("alignment_drag_active");
            request_render();
            return processed;
        }
        fs::path package_dir = pending_package_dir_;
        fs::path status_file = pending_status_file_;
        bool reset_view_state = pending_reset_view_;
        pending_package_dir_.clear();
        pending_status_file_.clear();
        pending_reset_view_ = false;
        const bool loaded = load_package(package_dir, status_file, reset_view_state);
        request_render();
        return processed || loaded;
    }
